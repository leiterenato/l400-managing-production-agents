"""Root orchestrator for the financial-support agent.

This is the entry point ADK discovers (``root_agent``). It wires:

  * the two specialists as ``sub_agents`` (so the model can transfer), and
  * ``look_up_customer`` as a root-level tool (routing needs the account), and
  * the composed cross-cutting callbacks from the registry (Case 1 invariants
    today; Case 2/3 concerns join automatically once registered).

The whole graph — root -> refund/disputes -> tools -> backends, plus the A2A
fraud edge — is the accumulating diagram from Slide 1 of the talk.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent

from .callbacks import assemble
from .model import build_model
from .observability import init_telemetry
from .prompts import ROOT_INSTRUCTION
from .sub_agents import build_disputes_agent, build_refund_agent
from .tools import look_up_customer


def build_root_agent() -> LlmAgent:
    # Bring up telemetry substrate (no-op if disabled / already running).
    init_telemetry()

    return LlmAgent(
        name="financial_support",
        model=build_model(),
        description="Front door of the financial support team. Routes to the "
        "refund and disputes specialists.",
        instruction=ROOT_INSTRUCTION,
        sub_agents=[build_refund_agent(), build_disputes_agent()],
        tools=[look_up_customer],
        **assemble(),
    )


# ADK entry point.
root_agent = build_root_agent()
