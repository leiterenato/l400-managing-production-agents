"""Composable callback registry — the extensibility spine for Cases 2 & 3.

Each *concern* (a cross-cutting behaviour) registers a :class:`CallbackBundle`.
The root agent asks :func:`assemble` for the combined ADK callback keyword
arguments and splats them onto every agent. Adding a case is additive:

    # e.g. Case 2 (resilience) adds, in resilience.py:
    register(CallbackBundle(name="resilience", case=2,
                            before_tool=[circuit_breaker],
                            after_tool=[record_outcome],
                            before_model=[budget_guard],
                            after_model=[record_cost]))

No existing code changes; the new callbacks simply join the chain. ADK runs a
list of callbacks in order, so ordering across concerns is just registration
order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .identity import enforce_identity
from .invariants import enforce_invariants
from .resilience import (
    budget_guard,
    circuit_breaker,
    record_cost,
    record_outcome,
)


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

# --- Case 2 concern: resilience (semantic breaker + cost/budget) ----------
# Dormant under CASE=1 (assemble() filters case > active_case); the breaker also
# self-guards on BREAKER != "on". after_tool order becomes
# [enforce_invariants, record_outcome] — invariants returns None in observe mode,
# so record_outcome always runs after it.
register(
    CallbackBundle(
        name="resilience",
        case=2,
        before_tool=[circuit_breaker],
        after_tool=[record_outcome],
        before_model=[budget_guard],
        after_model=[record_cost],
    )
)

# --- Case 3 concern: zero-trust (delegated identity carrier) ---------------
# Dormant under CASE<3 (assemble() filters case > active_case) and the carrier
# self-guards on the active case. before_tool order becomes
# [circuit_breaker, enforce_identity]: the breaker (off in the C3 demo) is a
# no-op, then enforce_identity carries the caller's identity to the data plane.
# It NEVER blocks — the refusal (the real 403) belongs to BigQuery IAM.
register(
    CallbackBundle(name="identity", case=3, before_tool=[enforce_identity])
)
# With CASE=1 all later bundles stay dormant; the Case 1 demo shows only the
# invariant seam.
