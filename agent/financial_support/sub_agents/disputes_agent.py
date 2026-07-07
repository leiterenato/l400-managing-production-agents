"""Disputes specialist sub-agent: opens dispute cases against charges."""

from __future__ import annotations

from google.adk.agents import LlmAgent

from ..callbacks import assemble
from ..config import get_settings
from ..prompts import DISPUTES_INSTRUCTION
from ..tools.customer import look_up_customer
from ..tools.dispute import open_dispute


def build_disputes_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="disputes_specialist",
        model=settings.model,
        description="Handles disputes and chargebacks: opens a dispute case "
        "against a charge on the customer's account.",
        instruction=DISPUTES_INSTRUCTION,
        tools=[look_up_customer, open_dispute],
        **assemble(),
    )
