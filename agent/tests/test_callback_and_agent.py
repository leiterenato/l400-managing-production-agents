"""The invariant seam (after_tool_callback) and the agent graph shape."""

import os

import pytest

from financial_support.callbacks.invariants import enforce_invariants
from financial_support.config import reload_settings


class FakeToolContext:
    def __init__(self):
        self.state = {"customer_id": "CUST-001", "session_customer_id": "CUST-001"}


class FakeTool:
    def __init__(self, name):
        self.name = name


@pytest.fixture(autouse=True)
def clean_env():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    reload_settings()


def test_observe_mode_records_but_does_not_override():
    os.environ["INVARIANT_ENFORCEMENT"] = "observe"
    reload_settings()
    ctx = FakeToolContext()
    resp = {"status": "refunded", "amount": 500.0, "charge_amount": 50.0}
    out = enforce_invariants(FakeTool("issue_refund"), {}, ctx, resp)
    assert out is None  # response stands (the money moved)
    assert ctx.state["invariant_violations"][0]["name"] == "refund_within_charge"


def test_block_mode_overrides_response():
    os.environ["INVARIANT_ENFORCEMENT"] = "block"
    reload_settings()
    ctx = FakeToolContext()
    resp = {"status": "refunded", "amount": 500.0, "charge_amount": 50.0}
    out = enforce_invariants(FakeTool("issue_refund"), {}, ctx, resp)
    assert out is not None
    assert out["status"] == "blocked"
    assert out["blocked_by_invariant"] == "refund_within_charge"


def test_passing_refund_records_nothing():
    os.environ["INVARIANT_ENFORCEMENT"] = "observe"
    reload_settings()
    ctx = FakeToolContext()
    resp = {"status": "refunded", "amount": 50.0, "charge_amount": 50.0}
    out = enforce_invariants(FakeTool("issue_refund"), {}, ctx, resp)
    assert out is None
    assert "invariant_violations" not in ctx.state


def test_agent_graph_shape():
    from financial_support import root_agent

    assert root_agent.name == "financial_support"
    names = {a.name for a in root_agent.sub_agents}
    assert names == {"refund_specialist", "disputes_specialist"}
    # invariant callback is wired on the root
    cb_names = {getattr(c, "__name__", "") for c in (root_agent.after_tool_callback or [])}
    assert "enforce_invariants" in cb_names
