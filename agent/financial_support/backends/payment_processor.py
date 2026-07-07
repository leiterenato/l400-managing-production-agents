"""Mock payment processor — stands in for the external payments API.

This is the slow, money-moving dependency. Case 2 (resilience) hangs its
circuit-breaker / retry story off the ``latency_s`` and ``fail`` knobs here;
Case 1 hangs its "the green score lies" money bug off ``over_charge_multiplier``.

Pure module: no ADK, no GCP. Returns plain dicts.
"""

from __future__ import annotations

import time
from typing import Any

from . import data
from .faults import fault_for


class PaymentError(Exception):
    """Raised to simulate a hard failure from the payments API (Case 2)."""


def get_charge(customer_id: str, charge_id: str) -> dict[str, Any]:
    """Look up the original charge so we know the ceiling for a refund."""

    charge = data.get_charge(customer_id, charge_id)
    if charge is None:
        return {"status": "not_found", "charge_id": charge_id}
    return {
        "status": "ok",
        "charge_id": charge.charge_id,
        "amount": charge.amount,
        "currency": charge.currency,
        "refundable": charge.refundable,
    }


def execute_refund(
    customer_id: str, charge_id: str, amount: float
) -> dict[str, Any]:
    """Execute a refund against ``charge_id`` for ``amount``.

    Honours fault knobs:
      * ``latency_s`` — slow dependency (Case 2).
      * ``fail`` — hard decline / timeout (Case 2). Raises :class:`PaymentError`.
      * ``force_amount`` / ``over_charge_multiplier`` — pay the *wrong* amount so
        the invariant has something to catch (Case 1). The processor itself does
        NOT enforce ``refund <= charge`` — that is exactly the point: the money
        moves, and the eval is what catches it.
    """

    fault = fault_for("issue_refund")

    if fault.latency_s:
        time.sleep(fault.latency_s)

    if fault.fail:
        raise PaymentError(fault.fail)

    charge = data.get_charge(customer_id, charge_id)
    charge_amount = charge.amount if charge else 0.0

    # Determine what actually gets paid. Faults can force an over-refund.
    paid = float(amount)
    if fault.force_amount is not None:
        paid = float(fault.force_amount)
    elif fault.over_charge_multiplier is not None and charge is not None:
        paid = round(charge_amount * fault.over_charge_multiplier, 2)

    return {
        "status": "refunded",
        "customer_id": customer_id,
        "charge_id": charge_id,
        # `amount` is what moved; `charge_amount` is the ceiling. The invariant
        # compares the two.
        "amount": paid,
        "requested_amount": float(amount),
        "charge_amount": charge_amount,
        "currency": charge.currency if charge else "USD",
        "confirmation_id": f"RF-{charge_id}",
        "duplicate": bool(fault.duplicate),
    }
