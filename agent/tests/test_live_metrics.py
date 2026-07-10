"""Anti-drift tests for the live eval metrics against REAL platform data.

The fixture ``eval_instance_over_refund.json`` is a real ``instance`` dict
captured from the Gen AI Evaluation Service (the $500-on-$50 money bug). These
tests pin the contract between the platform's ``agent_data`` shape and our
adapter + invariants, so a future SDK/schema change can never silently turn the
live metric green again.
"""

from __future__ import annotations

import json
import os

import pytest

from evals.agent_data import platform_instance_to_turns
from evals.metrics import (
    invariant_refund_requires_lookup,
    invariant_refund_within_charge,
)

_FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "eval_instance_over_refund.json")


def _load():
    with open(_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


def test_adapter_extracts_refund_from_real_platform_data():
    turns = platform_instance_to_turns(_load())
    names = [c["name"] for c in turns[0]["tool_calls"]]
    assert "issue_refund" in names
    refund = next(c for c in turns[0]["tool_calls"] if c["name"] == "issue_refund")
    # The money that actually moved is on the response.
    assert refund["response"].get("amount") == 500.0
    assert refund["response"].get("charge_amount") == 50.0


def test_invariant_catches_money_bug_on_real_data():
    """The whole point: the green invariant goes RED on real platform data."""
    result = invariant_refund_within_charge(_load())
    assert result["score"] == 0.0
    assert "OVER-REFUND" in result["explanation"]


def test_trajectory_passes_when_lookup_precedes_refund():
    result = invariant_refund_requires_lookup(_load())
    assert result["score"] == 1.0


def test_live_inference_prompts_are_in_policy():
    """The live money-bug driver must be an IN-POLICY refund request.

    Learned live (Fase 2): a "give me $500" ask trips the agent's own
    fraud_check (review at amount>=200), so it never issues the refund and the
    over-charge fault never fires -> the invariant stays vacuously green and the
    payoff vanishes. The scored case must request an amount BELOW that threshold
    so the agent proceeds and the fault (the processor over-paying) is what the
    invariant catches.
    """

    import re

    from evals.scenarios import EVAL_CASES, live_inference_rows

    _FRAUD_REVIEW_THRESHOLD = 200.0  # fraud_service.assess: review if amount>=200
    by_id = {c["id"]: c for c in EVAL_CASES}
    rows = live_inference_rows()
    assert rows, "live inference set must not be empty"

    refund_cases = [r for r in rows if by_id[r["case_id"]].get("flow") == "refund"]
    assert refund_cases, "live set must contain a refund case (the money bug)"
    for r in refund_cases:
        # (1) metadata guard
        amount = by_id[r["case_id"]].get("amount")
        assert amount is not None and amount < _FRAUD_REVIEW_THRESHOLD, (
            f"live refund case {r['case_id']} requests {amount} — at/above the "
            "fraud review threshold it would never reach issue_refund"
        )
        # (2) PROMPT-TEXT guard — the model reads the prompt, not the metadata.
        # A "$500" ask in the prompt trips fraud even if metadata says 50, so scan
        # the actual dollar figures the customer states.
        dollar_amounts = [
            float(m.replace(",", ""))
            for m in re.findall(r"\$\s?(\d[\d,]*(?:\.\d+)?)", r["prompt"])
        ]
        assert all(a < _FRAUD_REVIEW_THRESHOLD for a in dollar_amounts), (
            f"live refund PROMPT for {r['case_id']} names {dollar_amounts} — a "
            "figure >= the fraud threshold would trip review and skip the refund"
        )


def test_over_charge_fault_triggers_money_bug_end_to_end():
    """Under refund_over_charge the processor over-pays and the invariant fails.

    Guards the whole mechanism the live payoff depends on: the fault must apply
    (settings actually reloaded to the over-charge scenario) AND the invariant
    must read the money that MOVED (the response), going RED on $500-on-$50.
    """

    import os

    from financial_support import contract
    from financial_support.backends import payment_processor
    from financial_support.config import reload_settings

    prev = os.environ.get("SCENARIO")
    os.environ["SCENARIO"] = "refund_over_charge"
    reload_settings()
    try:
        result = payment_processor.execute_refund(
            customer_id="CUST-001", charge_id="TXN-1001", amount=50.0
        )
        assert result["amount"] == 500.0 and result["charge_amount"] == 50.0
        turns = [
            {
                "tool_calls": [
                    {"name": "issue_refund", "args": {"amount": 50.0}, "response": result}
                ]
            }
        ]
        verdict = contract.check_refund_within_charge_trace(turns)
        assert verdict.score == 0.0
    finally:
        if prev is None:
            os.environ.pop("SCENARIO", None)
        else:
            os.environ["SCENARIO"] = prev
        reload_settings()


def test_metric_fails_loud_on_placeholder():
    """A failed/placeholder run must ERROR, never score a false green."""
    placeholder = {"eval_case_id": "x", "response": {"parts": [{"text": "Missing"}]}}
    with pytest.raises(ValueError):
        platform_instance_to_turns(placeholder)
    # And the metric callable surfaces that as an exception (-> num_cases_error).
    with pytest.raises(ValueError):
        invariant_refund_within_charge(placeholder)
