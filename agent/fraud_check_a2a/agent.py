"""External fraud-check agent, exposed over A2A.

A deliberately simple agent that stands in for a separately-owned fraud service.
It exposes one tool, ``assess_fraud``, which reuses the shared decision logic in
``financial_support.backends.fraud_service`` ("the same brain, different
address"). Served as an A2A app by :mod:`fraud_check_a2a.__main__`, it becomes
the A2A edge the main agent calls — visible in the Observability Topology graph
and the seed for Case 3's identity-propagation story.
"""

from __future__ import annotations

from typing import Any

from google.adk.agents import LlmAgent

from financial_support.backends import fraud_service
from financial_support.model import build_model


def assess_fraud(customer_id: str, charge_id: str, amount: float) -> dict[str, Any]:
    """Assess fraud risk for a proposed refund.

    Args:
        customer_id: The customer the refund is for.
        charge_id: The charge being refunded.
        amount: The proposed refund amount.

    Returns:
        A decision of "allow", "review", or "deny" with a risk score.
    """

    return fraud_service.assess(customer_id, charge_id, amount)


INSTRUCTION = """
You are a fraud-check service. When asked to assess a refund, call `assess_fraud`
with the customer id, charge id, and amount, then return the decision (allow,
review, or deny) and the risk score in one short sentence.
"""


root_agent = LlmAgent(
    name="fraud_check",
    model=build_model(),
    description="External fraud-check service for proposed refunds.",
    instruction=INSTRUCTION,
    tools=[assess_fraud],
)
