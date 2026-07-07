"""Tool: open_dispute -> opens a dispute case against a charge (mock)."""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from ..backends import data
from ..backends.data import DEFAULT_SESSION_CUSTOMER_ID


def open_dispute(
    charge_id: str,
    reason: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Open a dispute case against a charge on the current customer's account.

    Args:
        charge_id: The id of the disputed charge, e.g. "TXN-1001".
        reason: The customer's stated reason for the dispute.

    Returns:
        A confirmation with a dispute case id, or an error if the charge is not
        found on this account.
    """

    session_customer_id = (
        tool_context.state.get("customer_id") or DEFAULT_SESSION_CUSTOMER_ID
    )
    charge = data.get_charge(session_customer_id, charge_id)
    if charge is None:
        return {
            "status": "not_found",
            "charge_id": charge_id,
            "detail": "No such charge on this account.",
        }

    case = {
        "status": "opened",
        "dispute_case_id": f"DSP-{charge_id}",
        "charge_id": charge_id,
        "amount": charge.amount,
        "currency": charge.currency,
        "reason": reason,
        "expected_resolution_days": 10,
    }
    tool_context.state["last_dispute"] = case
    return case
