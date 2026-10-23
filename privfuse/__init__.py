"""PrivFuse: runtime privacy SLOs for multi-tenant data trading systems.

The package is organised around four mechanisms described in the design notes:

``privfuse.dp``          privacy cost algebra (basic and RDP composition)
``privfuse.sketch``      one-sided sketches used by the online accountant
``privfuse.accounting``  composition-aware online accountant
``privfuse.slo``         privacy service-level objectives
``privfuse.control``     admission control and hysteresis circuit breaker
``privfuse.ledger``      reserve/commit/release settlement ledger
``privfuse.platform``    reference trading platform and market simulator
``privfuse.baselines``   comparison policies
``privfuse.experiments`` reproducible experiment runners
"""

from privfuse.dp.cost import CostVector
from privfuse.dp.accountant import ExactAccountant

__all__ = ["CostVector", "ExactAccountant", "__version__"]
__version__ = "0.1.0"
