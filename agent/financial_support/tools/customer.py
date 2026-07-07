"""Tool: look_up_customer -> reads the customer record (BigQuery in prod)."""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from ..backends import customer_db
from ..backends.data import DEFAULT_SESSION_CUSTOMER_ID


def look_up_customer(tool_context: ToolContext) -> dict[str, Any]:
    """Look up the current customer's account and recent charges.

    Call this first, before issuing a refund or opening a dispute, to confirm
    the charge exists and belongs to this customer. Returns the customer's
    profile and a list of their recent charges.
    """

    session_customer_id = (
        tool_context.state.get("customer_id") or DEFAULT_SESSION_CUSTOMER_ID
    )
    record = customer_db.read_customer(session_customer_id)

    # Stash for downstream tools and for the invariant callback (which compares
    # the record actually returned against the session's own customer).
    tool_context.state["customer_record"] = record
    tool_context.state["session_customer_id"] = session_customer_id
    return record
