"""Cross-cutting callbacks, composed through :mod:`registry`.

* :mod:`invariants` — Case 1 contract invariants (the runtime seam).
* :mod:`telemetry` — OTel span enrichment.
* :mod:`registry` — composes callback bundles per concern (extensible: Case 2/3
  register their own bundles here).
"""

from .registry import (
    CallbackBundle,
    active_bundles,
    assemble,
    register,
    registered_concerns,
)

__all__ = [
    "CallbackBundle",
    "active_bundles",
    "assemble",
    "register",
    "registered_concerns",
]
