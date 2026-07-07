"""Composable callback registry — the extensibility spine for Cases 2 & 3.

Each *concern* (a cross-cutting behaviour) registers a :class:`CallbackBundle`.
The root agent asks :func:`assemble` for the combined ADK callback keyword
arguments and splats them onto every agent. Adding a case is additive:

    # e.g. Case 2 (resilience) would add, in its own module:
    register(CallbackBundle(name="resilience",
                            before_tool=[circuit_breaker],
                            after_tool=[record_cost]))

No existing code changes; the new callbacks simply join the chain. ADK runs a
list of callbacks in order, so ordering across concerns is just registration
order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .invariants import enforce_invariants


@dataclass
class CallbackBundle:
    """A named group of ADK callbacks contributed by one concern.

    ``case`` is the case this concern belongs to (1 = evaluation/invariants,
    2 = resilience, 3 = zero-trust). :func:`assemble` only activates bundles
    whose ``case`` is <= the active ``CASE`` setting, so the Case 1 demo runs
    lean while the code for later cases stays dormant in the same codebase.
    """

    name: str
    case: int = 1
    before_agent: list[Callable] = field(default_factory=list)
    after_agent: list[Callable] = field(default_factory=list)
    before_model: list[Callable] = field(default_factory=list)
    after_model: list[Callable] = field(default_factory=list)
    before_tool: list[Callable] = field(default_factory=list)
    after_tool: list[Callable] = field(default_factory=list)


_REGISTRY: list[CallbackBundle] = []


def register(bundle: CallbackBundle) -> None:
    _REGISTRY.append(bundle)


def registered_concerns() -> list[str]:
    return [b.name for b in _REGISTRY]


def active_bundles() -> list[CallbackBundle]:
    """Bundles whose case is <= the active CASE setting."""

    from ..config import get_settings

    active_case = get_settings().case
    return [b for b in _REGISTRY if b.case <= active_case]


def assemble() -> dict[str, list[Callable]]:
    """Return non-empty ADK callback kwargs, e.g. ``{"after_tool_callback": [...]}``.

    Only concerns for the active case (and earlier) are wired.
    """

    fields = [
        "before_agent",
        "after_agent",
        "before_model",
        "after_model",
        "before_tool",
        "after_tool",
    ]
    bundles = active_bundles()
    out: dict[str, list[Callable]] = {}
    for f in fields:
        combined = [cb for b in bundles for cb in getattr(b, f)]
        if combined:
            out[f"{f}_callback"] = combined
    return out


# --- Built-in concern: Case 1 invariants ---------------------------------
register(CallbackBundle(name="invariants", case=1, after_tool=[enforce_invariants]))

# Case 2 (resilience) and Case 3 (zero-trust) register their bundles here when
# those cases are built, e.g.:
#   register(CallbackBundle(name="resilience", case=2,
#                           before_tool=[circuit_breaker], after_tool=[record_cost]))
#   register(CallbackBundle(name="identity", case=3,
#                           before_tool=[enforce_identity]))
# With CASE=1 they stay dormant; the Case 1 demo shows only the invariant seam.
