"""Deterministic fault injection — the demo's "feature flags".

The whole point of the L400 demo is to stage failures *on purpose*, with zero
non-determinism, so the same click always produces the same broken trace. This
module is where that lives.

A **scenario** is a named bundle of per-tool knobs. Tools never branch on the
scenario name; they only ask :func:`fault_for` for their own knobs and honour
them. That keeps the tools clean and makes the system extensible: Case 2
(resilience) and Case 3 (zero-trust) add new scenarios *here* — no tool changes.

Resolution order (later wins):
    1. the active scenario profile (``SCENARIO`` env / settings)
    2. a JSON override in the ``FAULTS_JSON`` env var (handy for live tweaks)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any

from ..config import get_settings


@dataclass
class ToolFault:
    """Knobs a tool consults before doing its work.

    Not every tool honours every knob; each tool reads the ones that make sense
    for it (documented on the tool). Unknown knobs are ignored, so new cases can
    add knobs without breaking older tools.
    """

    # Common knobs (all tools) -------------------------------------------
    latency_s: float = 0.0
    fail: str | None = None  # e.g. "timeout", "declined", "unavailable"

    # issue_refund knobs -------------------------------------------------
    force_amount: float | None = None
    over_charge_multiplier: float | None = None  # pay charge * this
    duplicate: bool = False

    # look_up_customer knobs (Case 3 bridge) -----------------------------
    return_customer_id: str | None = None  # read someone else's record

    # fraud_check knobs (Case 2 bridge) ----------------------------------
    force_decision: str | None = None  # "allow" | "review" | "deny"

    # Escape hatch for case-specific knobs added later -------------------
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolFault":
        known = {f for f in cls.__dataclass_fields__ if f != "extra"}
        kwargs = {k: v for k, v in data.items() if k in known}
        extra = {k: v for k, v in data.items() if k not in known}
        return cls(**kwargs, extra=extra)


# ---------------------------------------------------------------------------
# Scenario registry. Each scenario maps tool name -> knob dict.
#
# Case 1 owns the eval/quality scenarios. Case 2 and Case 3 scenarios are
# stubbed here so the shape is established and the demo repo tells the whole
# story; their deep behaviour is wired when those cases are built.
# ---------------------------------------------------------------------------

SCENARIOS: dict[str, dict[str, dict[str, Any]]] = {
    # Everything nominal — the "green" run.
    "healthy": {},

    # ---- Case 1: the money bug the LLM judge cannot catch --------------
    # $50 charge -> $500 refund. The invariant fails; tone/quality pass.
    "refund_over_charge": {
        "issue_refund": {"over_charge_multiplier": 10.0},
    },

    # ---- Case 1 (adversarial) / Case 3 bridge: cross-account read ------
    # look_up_customer returns a DIFFERENT customer -> PII leak.
    "wrong_account": {
        "look_up_customer": {"return_customer_id": "CUST-002"},
    },

    # ---- Case 2 bridge: slow dependency / retry storm ------------------
    "slow_payment": {
        "issue_refund": {"latency_s": 15.0},
    },
    "payment_declined": {
        "issue_refund": {"fail": "declined"},
    },

    # ---- Case 2 bridge: external A2A dependency down ------------------
    "fraud_unavailable": {
        "fraud_check": {"fail": "unavailable"},
    },
}


def _active_scenario_faults() -> dict[str, dict[str, Any]]:
    settings = get_settings()
    base = SCENARIOS.get(settings.scenario, {})
    merged: dict[str, dict[str, Any]] = {
        tool: dict(knobs) for tool, knobs in base.items()
    }

    raw = os.environ.get("FAULTS_JSON")
    if raw:
        try:
            override = json.loads(raw)
        except json.JSONDecodeError:
            override = {}
        for tool, knobs in override.items():
            merged.setdefault(tool, {}).update(knobs)

    return merged


def fault_for(tool_name: str) -> ToolFault:
    """Return the :class:`ToolFault` knobs for ``tool_name`` (never ``None``)."""

    knobs = _active_scenario_faults().get(tool_name, {})
    return ToolFault.from_dict(knobs)


def available_scenarios() -> list[str]:
    return sorted(SCENARIOS)
