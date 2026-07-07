"""The invariant seam (Case 1).

A single ``after_tool_callback`` that, for the money-moving / data-reading tools,
applies the contract invariants from :mod:`financial_support.contract` to the raw
tool response. It:

  1. records the verdict on the OTel span (defense-in-depth observability), and
  2. appends it to session state (so the eval and the UI can see it), and
  3. in ``block`` enforcement mode, overrides the response to refuse the action.

The default enforcement mode is ``observe`` — the wrong action is allowed to
stand so the "green score lies" demo can show real money leaving and the eval
catching it. Flip ``INVARIANT_ENFORCEMENT=block`` to demonstrate defense in
depth.

This is the runtime edge of "one function, three jobs": the exact predicates
used here are re-used verbatim by the offline eval metric and by pytest.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool

from .. import contract
from ..config import get_settings
from . import telemetry


def _record(tool_context: ToolContext, verdict: contract.Verdict) -> None:
    telemetry.record_invariant(verdict)
    violations = tool_context.state.get("invariant_violations", [])
    if not verdict.passed:
        violations = violations + [
            {"name": verdict.name, "detail": verdict.detail, **verdict.context}
        ]
        tool_context.state["invariant_violations"] = violations


def _check_issue_refund(response: dict[str, Any]) -> Optional[contract.Verdict]:
    if response.get("status") != "refunded":
        return None
    return contract.refund_within_charge(
        response.get("amount", 0.0), response.get("charge_amount", 0.0)
    )


def _check_look_up_customer(response: dict[str, Any]) -> Optional[contract.Verdict]:
    if response.get("status") != "ok":
        return None
    return contract.read_targets_session_customer(
        response.get("queried_customer_id", ""),
        response.get("session_customer_id", ""),
    )


# Map tool name -> the invariant check for its response.
_CHECKS = {
    "issue_refund": _check_issue_refund,
    "look_up_customer": _check_look_up_customer,
}


def enforce_invariants(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    """ADK ``after_tool_callback``: apply contract invariants to the response."""

    check = _CHECKS.get(tool.name)
    if check is None or not isinstance(tool_response, dict):
        return None

    verdict = check(tool_response)
    if verdict is None:
        return None

    _record(tool_context, verdict)

    if not verdict.passed and get_settings().invariant_enforcement == "block":
        # Refuse the action and hand the model a structured error it can relay.
        return {
            "status": "blocked",
            "blocked_by_invariant": verdict.name,
            "detail": verdict.detail,
            "original_response": tool_response,
        }

    # observe mode: let the (possibly wrong) response stand.
    return None
