"""The resilience seam (Case 2): semantic breaker + cost/budget + case gating.

Mirrors the fixture/fake style of ``test_callback_and_agent.py``. Every test runs
with a snapshotted env and a fresh breaker so the process-global failure counters
never leak between tests.
"""

import os
import time

import pytest

from financial_support.callbacks import registry, resilience
from financial_support.callbacks.resilience import (
    budget_guard,
    circuit_breaker,
    record_cost,
    record_outcome,
)
from financial_support.config import reload_settings


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeToolContext:
    def __init__(self, state=None):
        self.state = {} if state is None else state


class FakeCallbackContext:
    def __init__(self, state=None):
        self.state = {} if state is None else state


class FakeUsage:
    def __init__(self, prompt_token_count, candidates_token_count):
        self.prompt_token_count = prompt_token_count
        self.candidates_token_count = candidates_token_count


class FakeLlmResponse:
    def __init__(self, usage_metadata):
        self.usage_metadata = usage_metadata


@pytest.fixture(autouse=True)
def clean_env():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    reload_settings()


@pytest.fixture(autouse=True)
def clean_breaker():
    resilience.reset()
    yield
    resilience.reset()


def _set(**env):
    for k, v in env.items():
        os.environ[k] = str(v)
    reload_settings()


# --- The semantic circuit breaker -------------------------------------------

def test_breaker_opens_after_n_slow_calls():
    # The headline: a *slow* (not failing) dependency must trip the breaker.
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3, BREAKER_TIMEOUT_S=0.001)
    ctx = FakeToolContext()
    tool = FakeTool("issue_refund")
    for _ in range(3):
        ctx.state[resilience._start_key("issue_refund")] = time.time() - 1.0
        assert record_outcome(tool, {}, ctx, {"status": "refunded"}) is None
    out = circuit_breaker(tool, {}, ctx)
    assert out is not None and out["status"] == "unavailable"


def test_breaker_opens_after_n_errors():
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3)
    ctx = FakeToolContext()
    tool = FakeTool("issue_refund")
    for _ in range(3):
        record_outcome(tool, {}, ctx, {"status": "error", "error": "timeout"})
    assert circuit_breaker(tool, {}, ctx) is not None


def test_open_breaker_injects_deterministic_fact():
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3)
    resilience._failures["issue_refund"] = 3
    out = circuit_breaker(FakeTool("issue_refund"), {}, FakeToolContext())
    assert out["status"] == "unavailable"
    assert "do not retry" in out["instruction"].lower()
    assert "fallback" in out["instruction"].lower()


def test_unavailable_response_does_not_flap_the_breaker():
    # ADK runs after_tool even on a short-circuited before_tool. record_outcome
    # must ignore our own injection, or the counter resets and the storm resumes.
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3)
    resilience._failures["issue_refund"] = 3
    ctx = FakeToolContext()
    record_outcome(FakeTool("issue_refund"), {}, ctx, {"status": "unavailable"})
    assert resilience._failures["issue_refund"] == 3  # unchanged


def test_fast_success_resets_the_breaker():
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3, BREAKER_TIMEOUT_S=5.0)
    resilience._failures["issue_refund"] = 2
    ctx = FakeToolContext()
    ctx.state[resilience._start_key("issue_refund")] = time.time()  # ~0 elapsed
    record_outcome(FakeTool("issue_refund"), {}, ctx, {"status": "refunded"})
    assert resilience._failures["issue_refund"] == 0


def test_breaker_off_is_a_noop():
    _set(BREAKER="off")
    resilience._failures["issue_refund"] = 99
    assert circuit_breaker(FakeTool("issue_refund"), {}, FakeToolContext()) is None
    ctx = FakeToolContext()
    record_outcome(FakeTool("issue_refund"), {}, ctx, {"status": "error"})
    assert resilience._failures["issue_refund"] == 99  # untouched


# --- Breaker transition logging (the pageable log line) ---------------------

def test_open_transition_emits_exactly_one_log(monkeypatch):
    # The signal you page on: one WARNING when the circuit trips, not one per
    # short-circuited call. Extra in-flight slow completions must not re-log.
    _set(BREAKER="on", BREAKER_OPEN_AFTER=2, BREAKER_TIMEOUT_S=0.001)
    calls = []
    monkeypatch.setattr(
        resilience.breaker_log, "emit_transition", lambda *a, **k: calls.append(k)
    )
    ctx = FakeToolContext()
    tool = FakeTool("issue_refund")
    for _ in range(4):  # trips at 2, then stays open
        ctx.state[resilience._start_key("issue_refund")] = time.time() - 1.0
        record_outcome(tool, {}, ctx, {"status": "refunded"})
    opens = [c for c in calls if c["state"] == "open"]
    assert len(opens) == 1
    assert opens[0]["tool"] == "issue_refund"
    assert opens[0]["reason"] == "slow"


def test_open_transition_reason_is_error_on_hard_failure(monkeypatch):
    _set(BREAKER="on", BREAKER_OPEN_AFTER=1)
    calls = []
    monkeypatch.setattr(
        resilience.breaker_log, "emit_transition", lambda *a, **k: calls.append(k)
    )
    record_outcome(FakeTool("issue_refund"), {}, FakeToolContext(), {"status": "error"})
    assert calls and calls[0]["state"] == "open" and calls[0]["reason"] == "error"


def test_close_transition_logs_on_recovery(monkeypatch):
    _set(BREAKER="on", BREAKER_OPEN_AFTER=2, BREAKER_TIMEOUT_S=5.0)
    calls = []
    monkeypatch.setattr(
        resilience.breaker_log, "emit_transition", lambda *a, **k: calls.append(k)
    )
    resilience._failures["issue_refund"] = 2  # already open
    ctx = FakeToolContext()
    ctx.state[resilience._start_key("issue_refund")] = time.time()  # ~0 elapsed
    record_outcome(FakeTool("issue_refund"), {}, ctx, {"status": "refunded"})
    assert resilience._failures["issue_refund"] == 0
    closes = [c for c in calls if c["state"] == "closed"]
    assert len(closes) == 1 and closes[0]["reason"] == "recovered"


def test_fast_success_below_threshold_does_not_log_close(monkeypatch):
    # A reset from a not-yet-open counter is not a transition — no log.
    _set(BREAKER="on", BREAKER_OPEN_AFTER=3, BREAKER_TIMEOUT_S=5.0)
    calls = []
    monkeypatch.setattr(
        resilience.breaker_log, "emit_transition", lambda *a, **k: calls.append(k)
    )
    resilience._failures["issue_refund"] = 2  # below threshold, still closed
    ctx = FakeToolContext()
    ctx.state[resilience._start_key("issue_refund")] = time.time()
    record_outcome(FakeTool("issue_refund"), {}, ctx, {"status": "refunded"})
    assert calls == []


def test_transition_emit_is_noop_when_audit_off(monkeypatch):
    # The emit itself must not even build a logger unless BREAKER_AUDIT_LOG is set.
    monkeypatch.delenv("BREAKER_AUDIT_LOG", raising=False)
    built = []
    monkeypatch.setattr(
        resilience.breaker_log, "_get_logger", lambda: built.append(1)
    )
    resilience.breaker_log.emit_transition(
        FakeToolContext(),
        tool="issue_refund",
        state="open",
        reason="slow",
        failures=2,
        threshold=2,
        elapsed_s=1.0,
    )
    assert built == []


# --- Cost per span + per-session budget -------------------------------------

def test_record_cost_accumulates_on_state():
    ctx = FakeCallbackContext(state={})
    resp = FakeLlmResponse(FakeUsage(1000, 500))
    record_cost(ctx, resp)
    expected = (
        1000 * resilience._PRICE["in"] + 500 * resilience._PRICE["out"]
    ) / 1_000_000
    assert ctx.state["session_cost_usd"] == pytest.approx(expected)
    assert ctx.state["session_prompt_tokens"] == 1000
    assert ctx.state["session_candidate_tokens"] == 500
    record_cost(ctx, resp)
    assert ctx.state["session_cost_usd"] == pytest.approx(2 * expected)
    assert ctx.state["session_prompt_tokens"] == 2000


def test_record_cost_without_usage_is_noop():
    ctx = FakeCallbackContext(state={})
    record_cost(ctx, FakeLlmResponse(None))
    assert "session_cost_usd" not in ctx.state


def test_budget_guard_over_budget_returns_canned_content():
    # The ADK bug we fixed: never return an empty response.
    _set(SESSION_BUDGET_USD=0.5)
    ctx = FakeCallbackContext(state={"session_cost_usd": 1.0})
    out = budget_guard(ctx, None)
    assert out is not None
    text = out.content.parts[0].text
    assert text and text.strip()


def test_budget_guard_under_budget_returns_none():
    _set(SESSION_BUDGET_USD=0.5)
    ctx = FakeCallbackContext(state={"session_cost_usd": 0.0})
    assert budget_guard(ctx, None) is None


# --- Case gating (Case 1 must stay dormant) ---------------------------------

def test_case1_leaves_resilience_dormant():
    _set(CASE=1, BREAKER="on")  # even with the breaker "on", nothing is wired
    assert "resilience" not in [b.name for b in registry.active_bundles()]
    asm = registry.assemble()
    assert "before_tool_callback" not in asm
    assert "before_model_callback" not in asm
    assert "after_model_callback" not in asm
    at = [getattr(c, "__name__", "") for c in asm.get("after_tool_callback", [])]
    assert at == ["enforce_invariants"]


def test_case2_wires_all_resilience_callbacks():
    _set(CASE=2)
    from financial_support.agent import build_root_agent

    root = build_root_agent()
    names = lambda cbs: {getattr(c, "__name__", "") for c in (cbs or [])}
    assert "circuit_breaker" in names(root.before_tool_callback)
    at = names(root.after_tool_callback)
    assert "enforce_invariants" in at and "record_outcome" in at
    assert "budget_guard" in names(root.before_model_callback)
    assert "record_cost" in names(root.after_model_callback)
