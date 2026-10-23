"""E22: three platform processes against one coordinator process.

E13b already drives the coordinator over loopback from several client
processes, and E21 kills a coordinator that owns its ledger in the same
process.  Neither is the deployment the design describes: platform processes
that hold their own local ledgers, a shared coordinator in a process of its
own, and a crash of that process while platforms are mid-flight.

This experiment wires exactly that.  Three platform processes read the trace
for their own platform, reserve and commit over a line protocol, and append the
answers they hand back.  Halfway through, the coordinator process is killed
with SIGKILL and restarted on the same port from its write-ahead log; the
platforms reconnect and retry the transaction they were in.

It is still one host on two vCPUs over loopback.  It bounds the cost of
crossing a process boundary and it exercises restart and reconnection, but it
is not a multi-node deployment: no consensus, no replication, no network
partition.
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import signal
import socket
import socketserver
import time
from pathlib import Path
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import default_trace, write_csv, write_json
from privfuse.ledger.durable import DurableLedger
from privfuse.ledger.ledger import Coordinator, LedgerError, State
from privfuse.trace.generator import EPS_DELTA

N_REQUESTS = 900
N_SUBJECTS = 60
N_PLATFORMS = 3
CAP = 0.5
SEED = 3
TTL = 30.0
KILL_AT_ANSWERS = 300

CTX = mp.get_context("spawn")


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        coordinator: Coordinator = self.server.coordinator  # type: ignore[attr-defined]
        ledger = coordinator.ledger
        for line in self.rfile:
            parts = line.decode().split()
            if not parts:
                continue
            if parts[0] == "R":
                _, tx, tenant, platform, subject, eps_pure, rho = parts
                state = ledger.state(tx)
                if state is State.COMMITTED:
                    self.wfile.write(b"+")
                    continue
                if state is State.RESERVED:
                    self.wfile.write(b"+")
                    continue
                if state is not None:
                    self.wfile.write(b"-")
                    continue
                cost = CostVector(eps_pure=float(eps_pure), rho=float(rho), delta=0.0)
                try:
                    ok, _ = coordinator.try_reserve(
                        tx, tenant, platform, {subject: cost}, now=time.time()
                    )
                except LedgerError:
                    ok = False
                self.wfile.write(b"+" if ok else b"-")
            elif parts[0] == "C":
                try:
                    coordinator.commit(parts[1], now=time.time())
                    self.wfile.write(b"+")
                except LedgerError:
                    self.wfile.write(b"-")
            elif parts[0] == "Q":
                self.wfile.write(b"+")
                return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(port: int, wal: str, caps: dict[str, float], ready: Any) -> None:
    server = _Server(("127.0.0.1", port), _Handler)
    ledger = DurableLedger(wal, ttl=TTL, delta=EPS_DELTA)
    server.coordinator = Coordinator(  # type: ignore[attr-defined]
        caps=caps, ttl=TTL, delta=EPS_DELTA, ledger=ledger
    )
    ready.set()
    try:
        server.serve_forever(poll_interval=0.05)
    finally:
        ledger.close()


def _connect(port: int) -> socket.socket:
    sock = socket.create_connection(("127.0.0.1", port), timeout=10.0)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return sock


def _call(sock: socket.socket, message: str) -> bytes:
    sock.sendall(message.encode())
    reply = sock.recv(1)
    if not reply:
        raise ConnectionError("coordinator closed the connection")
    return reply


def _platform(
    index: int,
    port: int,
    answers_path: str,
    ready: Any,
    reconnects: Any,
) -> None:
    trace = default_trace(
        n_requests=N_REQUESTS,
        n_subjects=N_SUBJECTS,
        cap_eps=CAP,
        seed=SEED,
        n_platforms=N_PLATFORMS,
    )
    mine = [
        (f"t{i:04d}", request)
        for i, request in enumerate(trace.requests)
        if request.platform == f"p{index}" and len(request.subjects) == 1
    ]
    path = Path(answers_path)
    sock: socket.socket | None = None
    attempts = 0
    with open(path, "a", encoding="utf-8") as answers:
        for tx, request in mine:
            subject = request.subjects[0]
            while True:
                try:
                    if sock is None:
                        sock = _connect(port)
                    reply = _call(
                        sock,
                        f"R {tx} {request.tenant} {request.platform} {subject} "
                        f"{request.cost.eps_pure} {request.cost.rho}\n",
                    )
                    if reply == b"-":
                        break
                    _call(sock, f"C {tx}\n")
                    answers.write(
                        json.dumps(
                            {
                                "tx": tx,
                                "subject": subject,
                                "eps_pure": request.cost.eps_pure,
                                "rho": request.cost.rho,
                            },
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    answers.flush()
                    os.fsync(answers.fileno())
                    break
                except (ConnectionError, OSError):
                    attempts += 1
                    try:
                        if sock is not None:
                            sock.close()
                    except OSError:
                        pass
                    sock = None
                    time.sleep(0.01)
    if sock is not None:
        sock.close()
    reconnects.put(attempts)


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _run_once(mode: str, kill: bool) -> dict[str, Any]:
    caps = {f"s{i:06d}": CAP for i in range(N_SUBJECTS)}
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        wal = str(base / "coordinator.wal")
        answers = base / "answers.jsonl"
        port = _free_port()

        ready = CTX.Event()
        server = CTX.Process(target=_serve, args=(port, wal, caps, ready), daemon=True)
        server.start()
        if not ready.wait(timeout=30):
            raise TimeoutError("coordinator did not start")

        reconnects: Any = CTX.Queue()
        workers = [
            CTX.Process(
                target=_platform,
                args=(index, port, str(answers), ready, reconnects),
                daemon=True,
            )
            for index in range(N_PLATFORMS)
        ]
        started = time.perf_counter()
        for worker in workers:
            worker.start()

        downtime = 0.0
        killed_at = 0
        if kill:
            deadline = time.perf_counter() + 120.0
            while time.perf_counter() < deadline:
                if answers.exists():
                    killed_at = len(answers.read_text(encoding="utf-8").splitlines())
                    if killed_at >= KILL_AT_ANSWERS:
                        break
                time.sleep(0.005)
            killed_at_time = time.perf_counter()
            os.kill(server.pid, signal.SIGKILL)
            server.join(timeout=10)
            print(f"killed coordinator after {killed_at} answers", flush=True)

            time.sleep(0.05)
            ready2 = CTX.Event()
            restarted = CTX.Process(target=_serve, args=(port, wal, caps, ready2), daemon=True)
            restarted.start()
            if not ready2.wait(timeout=30):
                raise TimeoutError("coordinator did not restart")
            downtime = time.perf_counter() - killed_at_time

        for worker in workers:
            worker.join(timeout=180)
        elapsed = time.perf_counter() - started
        if kill:
            restarted.terminate()
            restarted.join(timeout=10)
        else:
            server.terminate()
            server.join(timeout=10)

        attempts = 0
        while not reconnects.empty():
            attempts += int(reconnects.get())

        records = [
            json.loads(line)
            for line in answers.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        ledger = DurableLedger(wal, ttl=TTL, delta=EPS_DELTA)
        spend: dict[str, CostVector] = {}
        free = 0
        for record in records:
            if ledger.state(record["tx"]) is not State.COMMITTED:
                free += 1
            cost = CostVector(eps_pure=record["eps_pure"], rho=record["rho"])
            subject = record["subject"]
            spend[subject] = spend.get(subject, CostVector.zero()) + cost
        worst = max((cost.eps(EPS_DELTA) for cost in spend.values()), default=0.0)
        row = {
            "mode": mode,
            "platforms": float(N_PLATFORMS),
            "processes": float(N_PLATFORMS + 1),
            "kills": 1.0 if kill else 0.0,
            "requests": float(N_REQUESTS),
            "answers": float(len(records)),
            "free_answers": float(free),
            "duplicate_answers": float(len(records) - len({r["tx"] for r in records})),
            "worst_client_eps": worst,
            "cap": CAP,
            "client_violations": float(worst > CAP + 1e-9),
            "reconnect_attempts": float(attempts),
            "wal_records": float(ledger.replayed),
            "torn_records": float(ledger.torn_records),
            "seconds": elapsed,
            "answers_per_second": len(records) / elapsed,
            "answers_before_kill": float(killed_at),
            "downtime_seconds": downtime,
            "steady_seconds": elapsed - downtime,
            "steady_answers_per_second": len(records) / max(elapsed - downtime, 1e-9),
        }
        ledger.close()
        print(row, flush=True)
    return row


def run() -> list[dict[str, Any]]:
    rows = [_run_once("durable+restart", kill=True), _run_once("durable", kill=False)]
    write_csv("e22_deploy", rows)
    write_json(
        "e22_deploy_meta",
        {
            "n_requests": N_REQUESTS,
            "n_subjects": N_SUBJECTS,
            "n_platforms": N_PLATFORMS,
            "cap": CAP,
            "kill_at_answers": KILL_AT_ANSWERS,
            "single_subject_only": True,
            "note": "one host, two vCPUs, loopback TCP; not a multi-node deployment",
        },
    )
    return rows


if __name__ == "__main__":
    run()
