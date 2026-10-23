"""Attestation contract for the execution layer.

The breaker never reads an attestation, so the results in this repository do not
depend on this module. It is here because a deployment that executes queries
inside an enclave should bind the claimed cost to a measurement, and that
interface is worth fixing early.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Measurement:
    enclave_id: str
    code_hash: str
    nonce: str
    claims: dict[str, str]


class Attester(Protocol):
    def verify(self, measurement: Measurement) -> bool: ...


class NullAttester:
    """Accepts everything. Used by the simulator, never by a deployment."""

    def verify(self, measurement: Measurement) -> bool:
        return True
