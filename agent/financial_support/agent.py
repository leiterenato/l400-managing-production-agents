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
from .prompts import ROOT_INSTRUCTION, with_identity_clause, with_resilience_fallback
from .sub_agents import build_disputes_agent, build_refund_agent
from .tools import look_up_customer


def build_root_agent() -> LlmAgent:
    # Telemetry is owned by the *runtime*, so we deliberately do NOT install a
    # provider here. This module is imported before the runtime's own telemetry
    # set_up runs (Agent Runtime unpickles/imports the agent, THEN calls
    # set_up; `adk web` imports the agent, THEN configures OTel). If we called
    # observability.init_telemetry() at import it would win that race and pin a
    # bare service.name="financial-support-agent" Resource onto the global
    # provider — which shadows the canonical Agent Engine Resource
    # (service.name=<engine id> + cloud.resource_id) and silently empties the
    # agent-scoped console Traces tab. Local bare runs that want console spans
    # call observability.init_telemetry() explicitly (it no-ops on a runtime).

    return LlmAgent(
        name="financial_support",
        model=build_model(),
        description="Front door of the financial support team. Routes to the "
        "refund and disputes specialists.",
        instruction=with_identity_clause(with_resilience_fallback(ROOT_INSTRUCTION)),
        sub_agents=[build_refund_agent(), build_disputes_agent()],
        tools=[look_up_customer],
        **assemble(),
    )


# ADK entry point.
root_agent = build_root_agent()
