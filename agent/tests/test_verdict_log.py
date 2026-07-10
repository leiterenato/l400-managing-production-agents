"""The durable side of the seam — verdict LogEntry emission (S4 sink).

All offline: proves the payload shape matches the BigQuery schema and that
emission is a safe no-op unless explicitly enabled (never touches GCP, never
raises).
"""

import os

import pytest

from financial_support import contract
from financial_support.config import reload_settings
from financial_support.observability import verdict_log


@pytest.fixture(autouse=True)
def clean_env():
    saved = dict(os.environ)
    # Reset the module-level logger cache so tests don't leak into each other.
    verdict_log._logger = None
    verdict_log._logger_failed = False
    yield
    os.environ.clear()
    os.environ.update(saved)
    reload_settings()
    verdict_log._logger = None
    verdict_log._logger_failed = False


class FakeLogger:
    def __init__(self):
        self.calls = []

    def log_struct(self, payload, severity=None):
        self.calls.append((payload, severity))


# --- _build_payload: matches evals/queries/agent_spans_schema.json ----------

def test_build_payload_over_refund_carries_money_context():
    verdict = contract.refund_within_charge(500.0, 50.0)  # the $500-on-$50 bug
    payload = verdict_log._build_payload("issue_refund", verdict)
    assert payload["tool_name"] == "issue_refund"
    assert payload["invariant_name"] == "refund_within_charge"
    assert payload["invariant_passed"] is False
    assert payload["refund_amount"] == 500.0
    assert payload["charge_amount"] == 50.0


def test_build_payload_clean_pass():
    verdict = contract.refund_within_charge(50.0, 50.0)
    payload = verdict_log._build_payload("issue_refund", verdict)
    assert payload["invariant_passed"] is True
    assert payload["refund_amount"] == 50.0


def test_build_payload_read_verdict_and_drops_unknown_context():
    # A read verdict carries identity context...
    read = verdict_log._build_payload(
        "look_up_customer",
        contract.read_targets_session_customer("CUST-002", "CUST-001"),
    )
    assert read["read_customer_id"] == "CUST-002"
    assert read["session_customer_id"] == "CUST-001"
    # ...and a fraud verdict's context key (fraud_decision) is NOT in the schema,
    # so it is dropped — the row stays clean against the documented schema.
    fraud = verdict_log._build_payload(
        "issue_refund", contract.refund_allowed_by_fraud("deny")
    )
    assert "fraud_decision" not in fraud
    assert fraud["invariant_passed"] is False


# --- emit_verdict: safe no-op / never raises --------------------------------

def test_emit_is_noop_when_disabled(monkeypatch):
    # Default (EVAL_AUDIT_LOG unset) must return before touching the client.
    os.environ.pop("EVAL_AUDIT_LOG", None)
    reload_settings()

    def _boom():
        raise AssertionError("_get_logger must not be called when disabled")

    monkeypatch.setattr(verdict_log, "_get_logger", _boom)
    # Returns without raising -> _get_logger was never reached.
    verdict_log.emit_verdict("issue_refund", contract.refund_within_charge(500.0, 50.0))


def test_emit_writes_struct_when_enabled(monkeypatch):
    os.environ["EVAL_AUDIT_LOG"] = "true"
    reload_settings()
    fake = FakeLogger()
    monkeypatch.setattr(verdict_log, "_get_logger", lambda: fake)

    verdict_log.emit_verdict("issue_refund", contract.refund_within_charge(500.0, 50.0))

    assert len(fake.calls) == 1
    payload, severity = fake.calls[0]
    assert severity == "ERROR"  # failed invariant
    assert payload["invariant_passed"] is False


def test_emit_swallows_when_logger_unavailable(monkeypatch):
    os.environ["EVAL_AUDIT_LOG"] = "true"
    reload_settings()
    monkeypatch.setattr(verdict_log, "_get_logger", lambda: None)
    # No logger -> silent no-op, no exception.
    verdict_log.emit_verdict("issue_refund", contract.refund_within_charge(500.0, 50.0))


def test_emit_swallows_log_struct_errors(monkeypatch):
    os.environ["EVAL_AUDIT_LOG"] = "true"
    reload_settings()

    class Broken:
        def log_struct(self, *a, **k):
            raise RuntimeError("network down")

    monkeypatch.setattr(verdict_log, "_get_logger", lambda: Broken())
    # A logging failure must never break the tool call it observes.
    verdict_log.emit_verdict("issue_refund", contract.refund_within_charge(50.0, 50.0))
