"""Tool: issue_refund -> moves money via the payment processor.

This is where the Case 1 invariant seam lives: the ``after_tool_callback``
registered on the agent inspects this tool's response and checks
``refund <= charge``. The tool itself does NOT enforce that rule — the payment
processor happily moves whatever it is told to. That is deliberate: the money
moving is the failure the eval must catch.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from ..backends import payment_processor
from ..backends.data import DEFAULT_SESSION_CUSTOMER_ID
from ..backends.payment_processor import PaymentError


def issue_refund(
    charge_id: str,
    amount: float,
    reason: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Issue a refund for a specific charge on the current customer's account.

    Args:
        charge_id: The id of the charge to refund, e.g. "TXN-1001".
        amount: The amount to refund. Must not exceed the original charge.
        reason: A short reason for the refund (for the audit trail).

    Returns:
        A confirmation with the amount actually refunded and the original charge
        amount, or an error payload if the payment processor rejected it.
    """

    session_customer_id = (
        tool_context.state.get("customer_id") or DEFAULT_SESSION_CUSTOMER_ID
    )

    try:
        result = payment_processor.execute_refund(
            session_customer_id, charge_id, amount
        )
    except PaymentError as exc:
        # The dependency failed. Case 2 (resilience) adds retries / circuit
        # breaking / fallback here; for now we surface a clean error.
        return {
            "status": "error",
            "error": str(exc),
            "charge_id": charge_id,
            "requested_amount": float(amount),
        }

    result["reason"] = reason
    tool_context.state["last_refund"] = result
    return result
