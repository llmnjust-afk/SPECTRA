"""Ground-truth accountant used as the reference implementation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Iterator

from privfuse.dp.cost import CostVector


@dataclass(frozen=True)
class Entry:
    timestamp: float
    cost: CostVector


class ExactAccountant:
    """Per-subject exact composition.

    This is the semantics the online accountant must approximate.  Keeping the
    full event log lets experiments compute windowed ground truth without
    re-implementing the window logic.
    """

    def __init__(self) -> None:
        self._log: dict[str, list[Entry]] = defaultdict(list)

    def add(self, subject: str, cost: CostVector, timestamp: float = 0.0) -> None:
        self._log[subject].append(Entry(timestamp=timestamp, cost=cost))

    def subjects(self) -> Iterator[str]:
        return iter(self._log)

    def get(self, subject: str, since: float | None = None) -> CostVector:
        entries = self._log.get(subject)
        if not entries:
            return CostVector.zero()
        total = CostVector.zero()
        for entry in entries:
            if since is not None and entry.timestamp < since:
                continue
            total = total + entry.cost
        return total

    def total(self, since: float | None = None) -> CostVector:
        total = CostVector.zero()
        for subject in self._log:
            total = total + self.get(subject, since=since)
        return total

    def max_eps(self, delta: float | None = None, since: float | None = None) -> tuple[str, float]:
        best_subject, best = "", 0.0
        for subject in self._log:
            value = self.get(subject, since=since).eps(delta)
            if value > best:
                best_subject, best = subject, value
        return best_subject, best

    def n_subjects(self) -> int:
        return len(self._log)

    def n_events(self) -> int:
        return sum(len(v) for v in self._log.values())
