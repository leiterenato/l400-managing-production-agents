"""Pure fraud-decision logic.

Shared by two callers so the behaviour is identical wherever fraud-check runs:

* the **local** ``fraud_check`` function tool (offline / deterministic dev), and
* the **external A2A agent** (:mod:`fraud_check_a2a`), which calls this from its
  own tool.

Keeping it here (pure, no ADK) is what lets the A2A agent be "the same brain,
different address" — the honest version of a microservice boundary.
"""

from __future__ import annotations

import time
from typing import Any

from .faults import fault_for


def assess(customer_id: str, charge_id: str, amount: float) -> dict[str, Any]:
    """Return a fraud decision: ``allow`` | ``review`` | ``deny``.

    Honours fault knobs:
      * ``latency_s`` — slow dependency (Case 2).
      * ``fail`` — service unavailable (Case 2 fallback ladder).
      * ``force_decision`` — pin the decision for a scripted demo.
    """

    fault = fault_for("fraud_check")

    if fault.latency_s:
        time.sleep(fault.latency_s)

    if fault.fail:
        return {"status": "error", "error": fault.fail}

    if fault.force_decision:
        decision = fault.force_decision
    else:
        # Simple, explainable heuristic: large refunds get a second look.
        decision = "review" if float(amount) >= 200 else "allow"

    return {
        "status": "ok",
        "decision": decision,
        "customer_id": customer_id,
        "charge_id": charge_id,
        "amount": float(amount),
        "risk_score": 0.82 if decision != "allow" else 0.05,
    }
