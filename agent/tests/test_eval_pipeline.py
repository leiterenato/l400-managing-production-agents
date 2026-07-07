"""End-to-end offline eval: record -> evaluate -> gate -> clusters."""

from evals.clusters import cluster_failures
from evals.eval_core import evaluate_dataset
from evals.record import record_dataset


def _by_id(result):
    return {c.id: c for c in result.cases}


def test_over_refund_fails_but_tone_passes():
    result = evaluate_dataset(record_dataset())
    case = _by_id(result)["adversarial_over_refund"]
    assert case.scores["refund_within_charge"] == 0.0  # green catches the money bug
    assert case.scores["tone_check"] == 1.0            # amber judge waves it through
    assert case.gate_failed


def test_cross_account_fails_read_invariant():
    result = evaluate_dataset(record_dataset())
    case = _by_id(result)["adversarial_cross_account"]
    assert case.scores["read_targets_session_customer"] == 0.0
    assert case.gate_failed


def test_happy_cases_pass():
    result = evaluate_dataset(record_dataset())
    by_id = _by_id(result)
    assert not by_id["happy_refund"].gate_failed
    assert not by_id["happy_dispute"].gate_failed


def test_gate_blocks_and_pass_rate():
    result = evaluate_dataset(record_dataset())
    assert not result.gate_ok
    assert len(result.failing) == 2
    assert result.pass_rate == 0.5


def test_failure_clusters_named():
    result = evaluate_dataset(record_dataset())
    clusters = {c.pattern: c.count for c in cluster_failures(result)}
    assert clusters.get("Refund Exceeds Charge") == 1
    assert clusters.get("Cross-Account Data Access") == 1
