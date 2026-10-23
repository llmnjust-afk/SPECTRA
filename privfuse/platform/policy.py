"""Policy interface shared by PrivFuse and the baselines."""

from __future__ import annotations

from typing import Protocol

from privfuse.control.admission import AdmissionController, Decision, QueryRequest


class Policy(Protocol):
    name: str

    def begin(self, request: QueryRequest) -> Decision: ...

    def finish(self, decision: Decision, now: float) -> None: ...

    def abort(self, decision: Decision, now: float) -> None: ...

    def tick(self, now: float) -> None: ...

    def stats(self) -> dict[str, float]: ...


class PrivFusePolicy:
    """Adapter turning the admission controller into a market policy."""

    name = "privfuse"

    def __init__(self, controller: AdmissionController) -> None:
        self.controller = controller

    def begin(self, request: QueryRequest) -> Decision:
        return self.controller.evaluate(request)

    def finish(self, decision: Decision, now: float) -> None:
        self.controller.complete(decision, now=now)

    def abort(self, decision: Decision, now: float) -> None:
        self.controller.abort(decision, now=now)

    def tick(self, now: float) -> None:
        self.controller.coordinator.tick(now)

    def stats(self) -> dict[str, float]:
        merged = self.controller.stats()
        merged.update(self.controller.coordinator.stats())
        merged.update(self.controller.accountant.stats())
        return merged
