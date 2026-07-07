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
    """A named group of ADK callbacks contributed by one concern."""

    name: str
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


def assemble() -> dict[str, list[Callable]]:
    """Return non-empty ADK callback kwargs, e.g. ``{"after_tool_callback": [...]}``."""

    fields = [
        "before_agent",
        "after_agent",
        "before_model",
        "after_model",
        "before_tool",
        "after_tool",
    ]
    out: dict[str, list[Callable]] = {}
    for f in fields:
        combined = [cb for b in _REGISTRY for cb in getattr(b, f)]
        if combined:
            out[f"{f}_callback"] = combined
    return out


# --- Built-in concern: Case 1 invariants ---------------------------------
register(CallbackBundle(name="invariants", after_tool=[enforce_invariants]))
