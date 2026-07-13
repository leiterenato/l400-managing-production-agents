"""Fault engine + mock backends: deterministic staging of the demo scenarios."""

import os

import pytest

from financial_support.backends import customer_db, payment_processor
from financial_support.backends.faults import fault_for
from financial_support.backends.payment_processor import PaymentError
from financial_support.config import reload_settings


@pytest.fixture(autouse=True)
def clean_env():
    saved = dict(os.environ)
    os.environ.pop("FAULTS_JSON", None)
    yield
    os.environ.clear()
    os.environ.update(saved)
    reload_settings()


def _set_scenario(name: str) -> None:
    os.environ["SCENARIO"] = name
    reload_settings()


def test_healthy_has_no_faults():
    _set_scenario("healthy")
    assert fault_for("issue_refund").over_charge_multiplier is None


def test_over_charge_multiplier_forces_over_refund():
    _set_scenario("refund_over_charge")
    resp = payment_processor.execute_refund("CUST-001", "TXN-1001", 50.0)
    assert resp["amount"] == 500.0  # 50 * 10
    assert resp["charge_amount"] == 50.0


def test_payment_declined_raises():
    _set_scenario("payment_declined")
    with pytest.raises(PaymentError):
        payment_processor.execute_refund("CUST-001", "TXN-1001", 50.0)


def test_retry_storm_is_slow_and_failing():
    # Case 2 robustness profile: trips the breaker on BOTH signals (latency +
    # hard error). Assert the knobs directly (calling execute_refund would sleep).
    _set_scenario("retry_storm")
    fault = fault_for("issue_refund")
    assert fault.latency_s == 8.0
    assert fault.fail == "timeout"


def test_wrong_account_reads_other_customer():
    _set_scenario("wrong_account")
    rec = customer_db.read_customer("CUST-001")
    assert rec["session_customer_id"] == "CUST-001"
    assert rec["queried_customer_id"] == "CUST-002"  # the leak


def test_faults_json_override():
    _set_scenario("healthy")
    os.environ["FAULTS_JSON"] = '{"issue_refund": {"over_charge_multiplier": 3}}'
    assert fault_for("issue_refund").over_charge_multiplier == 3
