"""Mock customer database — stands in for BigQuery.

In production this is a BigQuery read scoped to the caller's identity (Case 3
adds Row-Level Security here so a cross-account read returns *no rows* instead of
another customer's PII). Here it is an in-memory lookup that honours the fault
knobs so we can stage the leak deterministically.

Pure module: no ADK, no GCP. Returns plain dicts.
"""

from __future__ import annotations

import time
from typing import Any

from . import data
from .faults import fault_for


def read_customer(session_customer_id: str) -> dict[str, Any]:
    """Read the record for the session's customer.

    Under the ``wrong_account`` scenario the ``return_customer_id`` knob makes
    this return a *different* customer — the cross-account read that Case 3
    hardens. We surface both ids in the payload so the invariant / eval can see
    the mismatch.
    """

    fault = fault_for("look_up_customer")

    if fault.latency_s:
        time.sleep(fault.latency_s)

    if fault.fail:
        return {
            "status": "error",
            "error": fault.fail,
            "session_customer_id": session_customer_id,
        }

    queried_id = fault.return_customer_id or session_customer_id
    customer = data.get_customer(queried_id)
    if customer is None:
        return {
            "status": "not_found",
            "session_customer_id": session_customer_id,
            "queried_customer_id": queried_id,
        }

    return {
        "status": "ok",
        # The row-level truth: which record did we actually return?
        "session_customer_id": session_customer_id,
        "queried_customer_id": customer.customer_id,
        "customer_id": customer.customer_id,
        "name": customer.name,
        "email": customer.email,
        "tier": customer.tier,
        "charges": [
            {
                "charge_id": c.charge_id,
                "amount": c.amount,
                "currency": c.currency,
                "description": c.description,
                "refundable": c.refundable,
            }
            for c in customer.charges.values()
        ],
    }
