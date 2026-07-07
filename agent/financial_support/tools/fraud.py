"""Fraud check — exposed either as a local tool or over A2A.

Two interchangeable wirings, chosen in :mod:`financial_support.agent`:

* **Local** (default, offline-friendly): :func:`fraud_check`, a function tool
  that calls the shared :mod:`financial_support.backends.fraud_service`.
* **A2A** (``USE_A2A_FRAUD=true``): :func:`build_remote_fraud_agent` returns a
  ``RemoteA2aAgent`` that talks to the external fraud agent
  (:mod:`fraud_check_a2a`) over the A2A protocol. Wrapped as an ``AgentTool`` it
  behaves like the same ``fraud_check`` tool, and shows up as an A2A edge in the
  Observability Topology graph (Slide 1 / Case 3 bridge).

Both paths return the same decision shape, so the refund specialist's prompt and
the eval do not care which is active.
"""

from __future__ import annotations

from typing import Any

from google.adk.tools import ToolContext

from ..backends import fraud_service
from ..backends.data import DEFAULT_SESSION_CUSTOMER_ID
from ..config import get_settings


def fraud_check(
    charge_id: str,
    amount: float,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Run a fraud check on a proposed refund before issuing it.

    Args:
        charge_id: The charge the refund is for, e.g. "TXN-1001".
        amount: The proposed refund amount.

    Returns:
        A decision of "allow", "review", or "deny" with a risk score. If the
        fraud service is unavailable, returns an error payload.
    """

    session_customer_id = (
        tool_context.state.get("customer_id") or DEFAULT_SESSION_CUSTOMER_ID
    )
    decision = fraud_service.assess(session_customer_id, charge_id, amount)
    tool_context.state["last_fraud_decision"] = decision
    return decision


def build_remote_fraud_agent():
    """Return a ``RemoteA2aAgent`` pointing at the external fraud-check agent.

    Imported lazily so the a2a extra is only required when the A2A path is used.
    """

    from google.adk.agents.remote_a2a_agent import (
        AGENT_CARD_WELL_KNOWN_PATH,
        RemoteA2aAgent,
    )

    settings = get_settings()
    return RemoteA2aAgent(
        name="fraud_check",
        description=(
            "External fraud-check service. Given a proposed refund (charge and "
            "amount), returns allow / review / deny."
        ),
        agent_card=f"{settings.fraud_agent_url}{AGENT_CARD_WELL_KNOWN_PATH}",
    )
