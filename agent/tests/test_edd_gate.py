"""The EDD gate (Fase 5, Camada 1): actual verdict vs the contract's expectation.

The seed set deliberately carries adversarial cases that SHOULD read red, so a
naive "block on any red invariant" gate would block every PR. The EDD gate blocks
only on a *regression* — a case whose actual verdict diverged from its declared
``expected_failing_invariants`` — in EITHER direction:

  * an unexpected red on a case that was green (a new bug), OR
  * an expected red that stopped firing (an invariant was weakened).

These tests pin both directions plus the invariant that the JSON's expected
verdicts are truthful on the seed data.
"""

from __future__ import annotations

import copy

from evals.eval_core import evaluate_dataset
from evals.record import record_dataset
from evals.scenarios import EVAL_CASES, LIVE_INFERENCE_CASE_IDS


def _by_id(result):
    return {c.id: c for c in result.cases}


def test_edd_gate_green_on_healthy_seed():
    """Baseline: every seed case matches its expected verdict -> gate GREEN."""
    result = evaluate_dataset(record_dataset())
    assert result.edd_gate_ok
    assert result.regressions == []
    # The descriptive "red invariants" count is still 3 (the adversarial cases
    # doing their job) — GREEN despite 3 reds is the whole point of the EDD gate.
    assert len(result.failing) == 3
    assert result.total == 5


def test_expected_failing_invariants_are_truthful_on_seed():
    """Each case's declared expected set must equal what it actually trips."""
    result = evaluate_dataset(record_dataset())
    for c in result.cases:
        assert set(c.actual_failing_invariants) == set(
            c.expected_failing_invariants
        ), (
            f"{c.id}: expected {c.expected_failing_invariants} but actually "
            f"tripped {c.actual_failing_invariants}"
        )
        assert not c.regressed


def test_edd_gate_catches_new_bug_on_happy_case():
    """A happy case that newly over-refunds is an UNEXPECTED red -> regression."""
    dataset = copy.deepcopy(record_dataset())
    for inst in dataset:
        if inst["id"] == "happy_refund":
            inst["agent_eval_data"]["turns"][0]["tool_calls"][-1]["response"][
                "amount"
            ] = 999.0
    result = evaluate_dataset(dataset)
    assert not result.edd_gate_ok
    case = _by_id(result)["happy_refund"]
    assert case.regressed
    assert "refund_within_charge" in case.unexpected_failures
    assert case.missed_failures == []


def test_edd_gate_catches_weakened_invariant():
    """An adversarial case whose invariant stopped firing is a MISSED red.

    This is the half a naive 'block on any red' gate is blind to: if the over-pay
    is silently 'fixed' so the money case reads green, the check that used to
    catch it no longer does — the EDD gate flags that as a regression too.
    """
    dataset = copy.deepcopy(record_dataset())
    for inst in dataset:
        if inst["id"] == "adversarial_over_refund":
            inst["agent_eval_data"]["turns"][0]["tool_calls"][-1]["response"][
                "amount"
            ] = 50.0  # no longer over-pays -> invariant goes green
    result = evaluate_dataset(dataset)
    assert not result.edd_gate_ok
    case = _by_id(result)["adversarial_over_refund"]
    assert case.regressed
    assert "refund_within_charge" in case.missed_failures
    assert case.unexpected_failures == []


def test_demo_regression_toggle_blocks_gate(monkeypatch):
    """DEMO_REGRESSION=1 stages a fresh regression for the Slide-4 gate demo.

    It flips the in-policy happy refund case to the over-charge fault, so
    ``refund_within_charge`` reads red where the contract expects green — a single
    unexpected red the EDD gate blocks on (``run_offline`` exits 1 -> a red Cloud
    Build). Off by default the baseline stays green (see the green-on-seed test).
    """
    monkeypatch.setenv("DEMO_REGRESSION", "1")
    result = evaluate_dataset(record_dataset())
    assert not result.edd_gate_ok
    # Exactly one NEW regression, on the clean refund case — nothing else flips.
    assert [c.id for c in result.regressions] == ["happy_refund"]
    case = _by_id(result)["happy_refund"]
    assert case.unexpected_failures == ["refund_within_charge"]
    assert case.missed_failures == []


def test_eval_cases_json_is_source_of_truth():
    """The versioned JSON drives EVAL_CASES; core invariants of the set hold."""
    assert len(EVAL_CASES) == 5
    assert [c["id"] for c in EVAL_CASES] == [
        "happy_refund",
        "adversarial_over_refund",
        "silent_skipped_lookup",
        "adversarial_cross_account",
        "happy_dispute",
    ]
    assert LIVE_INFERENCE_CASE_IDS == ("happy_dispute", "happy_refund")
    # Every case declares an expected set (happy = []).
    for c in EVAL_CASES:
        assert "expected_failing_invariants" in c
    by_id = {c["id"]: c for c in EVAL_CASES}
    assert by_id["happy_refund"]["expected_failing_invariants"] == []
    assert by_id["adversarial_over_refund"]["expected_failing_invariants"] == [
        "refund_within_charge"
    ]
