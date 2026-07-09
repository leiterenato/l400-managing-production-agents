"""Disputes specialist sub-agent: opens dispute cases against charges."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..callbacks import assemble
from ..model import build_model
from ..prompts import DISPUTES_INSTRUCTION
from ..tools.customer import look_up_customer
from ..tools.dispute import open_dispute


def build_disputes_agent() -> LlmAgent:
    return LlmAgent(
        name="disputes_specialist",
        model=build_model(),
        description="Handles disputes and chargebacks: opens a dispute case "
        "against a charge on the customer's account.",
        instruction=DISPUTES_INSTRUCTION,
        tools=[look_up_customer, open_dispute],
        **assemble(),
    )
