"""The identity seam (Case 3) — a delegated-identity CARRIER, not a boundary.

Case 1 used an ``after_tool`` seam to *check* the money; Case 2 reused the seam to
*protect* and *measure* it. Case 3 reuses the very same ``before_tool`` seam for a
third job: it **carries the caller's identity** down to the data-access tools so
the data plane (BigQuery IAM) is the one that decides.

The load-bearing honesty of the whole talk lives here:

    enforce_identity does NOT block. It only says WHO is asking.

If this callback tried to refuse the cross-account read, we would have put the
security boundary back *on top of code running in the agent's process* — the same
class of mistake as "a filter in front of the model". The boundary belongs BELOW
all of this, in BigQuery: a request carrying User B's identity is denied by IAM
(a real 403), not by us. Contrast Case 2, where the breaker *is* the mechanism;
here the seam is a carrier and the mechanism is IAM + Row-Level Security.

Dormant under CASE<3 (the registry does not wire this bundle) and it self-guards
on the active case, so Cases 1 and 2 are byte-for-byte unaffected.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool

from ..config import get_settings
from . import telemetry


def enforce_identity(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """ADK ``before_tool_callback``: carry the caller's identity to the data plane.

    Reads the delegated principal the caller authenticated as — in production the
    user's token obtained via 3-legged OAuth / Auth Manager; in the demo the
    per-user service account the run impersonates — off session state, stamps it
    where the data-access backend reads it, and annotates the span.

    It **always returns None**. It never refuses a call: the refusal is the data
    plane's job (IAM on the per-tenant BigQuery resource). "enforce" here means
    "make the caller's identity travel with the request", not "gate the request".
    """

    # Dormant unless Case 3 is active. The registry already filters case>active,
    # but self-guard so a stray wiring can never turn the carrier into a blocker.
    if get_settings().case < 3:
        return None

    principal = tool_context.state.get("delegated_principal")
    # Carry it to where customer_db reads it. A carrier, not a gate: even with no
    # principal we return None and let the data plane (IAM) be the boundary.
    tool_context.state["data_access_principal"] = principal
    telemetry.set_attribute("identity.delegated", principal is not None)
    if principal:
        telemetry.set_attribute("identity.delegated_principal", principal)
    return None
