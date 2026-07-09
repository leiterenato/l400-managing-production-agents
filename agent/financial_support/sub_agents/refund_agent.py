"""Refund specialist sub-agent.

Owns the money-moving path: look up -> fraud check -> issue refund. The fraud
check is either the local tool or an external A2A agent, chosen by
``USE_A2A_FRAUD`` (see :func:`_fraud_tool`).
"""

from __future__ import annotations

import os

from google.adk.agents import LlmAgent
from google.adk.tools.agent_tool import AgentTool

from ..callbacks import assemble
from ..model import build_model
from ..prompts import REFUND_INSTRUCTION
from ..tools import build_remote_fraud_agent, fraud_check, issue_refund, look_up_customer


def _fraud_tool():
    """Return the fraud-check tool: A2A agent if enabled, else the local tool."""

    if os.environ.get("USE_A2A_FRAUD", "").strip().lower() in {"1", "true", "yes"}:
        return AgentTool(agent=build_remote_fraud_agent())
    return fraud_check


def build_refund_agent() -> LlmAgent:
    return LlmAgent(
        name="refund_specialist",
        model=build_model(),
        description="Handles refund requests: verifies the charge, runs a fraud "
        "check, and issues the refund.",
        instruction=REFUND_INSTRUCTION,
        tools=[look_up_customer, _fraud_tool(), issue_refund],
        **assemble(),
    )
