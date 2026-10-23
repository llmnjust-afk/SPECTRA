"""E13: where does the settlement path actually serialise?

Two measurements. (a) Disjoint-subject throughput inside one CPython process:
if striping helps, four threads on four different subjects should beat four
threads on one subject. (b) Cross-process settlement: the same coordinator is
served over loopback TCP and driven by 1, 2 and 4 client processes, which is
the only way to scale the critical section past the interpreter lock.

Part (b) measures two processes on one host over loopback. It bounds the cost
of a remote settlement round trip; it is not a multi-node deployment, and it
does not include consensus, replication or a persistent ledger backend.
"""

from __future__ import annotations

import multiprocessing as mp
import socket
import socketserver
import threading
import time
from typing import Any

from privfuse.dp.cost import CostVector
from privfuse.experiments.common import write_csv, write_json
from privfuse.ledger.ledger import Coordinator

COST = CostVector(eps_pure=0.01, rho=0.0, delta=0.0)
BIG_CAP = 1e9


def _disjoint(n_threads: int, per_thread: int, striped: bool, disjoint: bool) -> dict[str, Any]:
    subjects = [f"s{i}" for i in range(n_threads)]
    caps = {s: BIG_CAP for s in subjects}
    coord = Coordinator(caps=caps, ttl=1e6, striped=striped)

    def worker(k: int) -> None:
        subject = subjects[k] if disjoint else subjects[0]
        for i in range(per_thread):
            tx = f"t{k}-{i}"
            ok, _ = coord.try_reserve(tx, "ten", f"p{k}", {subject: COST})
            if ok:
                coord.commit(tx)

    threads = [threading.Thread(target=worker, args=(k,)) for k in range(n_threads)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.perf_counter() - start
    return {
        "mode": "disjoint" if disjoint else "shared",
        "locking": "striped" if striped else "global",
        "threads": n_threads,
        "ops": n_threads * per_thread,
        "seconds": elapsed,
        "ops_per_second": n_threads * per_thread / elapsed,
    }


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        coord: Coordinator = self.server.coordinator  # type: ignore[attr-defined]
        for line in self.rfile:
            parts = line.decode().split()
            if not parts:
                continue
            if parts[0] == "R":
                _, tx, tenant, platform, subject, eps = parts
                ok, _ = coord.try_reserve(
                    tx, tenant, platform, {subject: CostVector(eps_pure=float(eps), rho=0.0, delta=0.0)}
                )
                self.wfile.write(b"+" if ok else b"-")
            elif parts[0] == "C":
                coord.commit(parts[1])
                self.wfile.write(b"+")
            elif parts[0] == "Q":
                self.wfile.write(b"+")
                return


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def _serve(port_q: Any, ready: Any, n_subjects: int) -> None:
    caps = {f"s{i}": BIG_CAP for i in range(n_subjects)}
    server = _Server(("127.0.0.1", 0), _Handler)
    server.coordinator = Coordinator(caps=caps, ttl=1e6, striped=True)  # type: ignore[attr-defined]
    port_q.put(server.server_address[1])
    ready.set()
    server.serve_forever()


def _client(port: int, n_ops: int, offset: int, out: Any) -> None:
    sock = socket.create_connection(("127.0.0.1", port))
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    latencies: list[float] = []
    buf = sock.makefile("rwb", buffering=0)
    for i in range(n_ops):
        tx = f"c{offset}-{i}"
        start = time.perf_counter()
        buf.write(f"R {tx} ten p1 s{(offset + i) % 512} 0.01\n".encode())
        buf.read(1)
        buf.write(f"C {tx}\n".encode())
        buf.read(1)
        latencies.append(time.perf_counter() - start)
    sock.close()
    ordered = sorted(latencies)
    out.put(
        {
            "n": len(ordered),
            "p50": ordered[len(ordered) // 2],
            "p99": ordered[min(len(ordered) - 1, int(len(ordered) * 0.99))],
            "mean": sum(ordered) / len(ordered),
        }
    )


CTX = mp.get_context("spawn")


def _xproc(n_procs: int, n_ops: int) -> dict[str, Any]:
    port_q: Any = CTX.Queue()
    ready = CTX.Event()
    server = CTX.Process(target=_serve, args=(port_q, ready, 4096), daemon=True)
    server.start()
    if not ready.wait(timeout=30):
        raise TimeoutError('settlement server did not start')
    port = port_q.get(timeout=30)

    out: Any = CTX.Queue()
    procs = [
        CTX.Process(target=_client, args=(port, n_ops, k * n_ops, out)) for k in range(n_procs)
    ]
    start = time.perf_counter()
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    elapsed = time.perf_counter() - start

    stats = [out.get(timeout=60) for _ in procs]
    server.terminate()
    total = sum(item["n"] for item in stats)
    p50 = sum(item["p50"] * item["n"] for item in stats) / total
    p99 = max(item["p99"] for item in stats)
    return {
        "mode": "xproc",
        "segment": "loopback-tcp",
        "clients": n_procs,
        "ops": n_procs * n_ops,
        "seconds": elapsed,
        "ops_per_second": n_procs * n_ops / elapsed,
        "p50_us": p50 * 1e6,
        "p99_us": p99 * 1e6,
    }


def main() -> None:
    xrows: list[dict[str, Any]] = []
    for rep in range(3):
        for n in (1, 2, 4):
            row = _xproc(n, 2500)
            row["rep"] = rep
            xrows.append(row)
    write_csv("e13_xproc", xrows)
    print("xproc done", flush=True)
    rows: list[dict[str, Any]] = []
    for rep in range(3):
        for striped in (True, False):
            for disjoint in (False, True):
                for threads in (1, 2, 4):
                    row = _disjoint(threads, 20000 // threads, striped, disjoint)
                    row["rep"] = rep
                    rows.append(row)
    write_csv("e13_disjoint", rows)
    print("disjoint done", flush=True)
    write_json(
        "e13_xproc_meta",
        {
            "transport": "loopback TCP, NODELAY, one reserve+commit round trip per op",
            "server": "single Coordinator process, striped locks, in-memory ledger",
            "note": "not a multi-node deployment; no consensus, replication or disk backend",
        },
    )
    for row in rows + xrows:
        print(row)


if __name__ == "__main__":
    main()
