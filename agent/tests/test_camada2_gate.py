"""Camada 2 (managed cloud eval) — the score gate + the versioned dataset builder.

The managed run's exit code comes from a score floor on the gating invariant, and
the scored dataset is built from the SAME versioned eval set as the Camada-1 gate
(no drift). These tests pin the pure gate logic and the dataset construction
without calling the (paid, Preview) Evaluation Service.
"""

from __future__ import annotations

import json

from evals.live_run import _apply_score_gate

# The Vertex AI Evaluation Service keys the mean "AVERAGE" (NOT "MEAN") and also
# emits MINIMUM/MEDIAN/... These rows mirror the REAL server shape (verified
# against the SDK's _get_aggregated_metrics + real run dumps), so the tests
# exercise the gate against what production actually returns.


def test_score_gate_passes_at_floor():
    assert _apply_score_gate(
        {"refund_within_charge": {"AVERAGE": 1.0, "MINIMUM": 1.0}}
    ) == 0


def test_score_gate_blocks_below_floor():
    assert _apply_score_gate(
        {"refund_within_charge": {"AVERAGE": 0.8, "MINIMUM": 0.0}}
    ) == 1
    assert _apply_score_gate(
        {"refund_within_charge": {"AVERAGE": 0.0, "MINIMUM": 0.0}}
    ) == 1


def test_score_gate_never_trusts_median():
    """The regression the review caught: MEDIAN=1.0 must NOT save a failing set.

    For a binary invariant with a minority of failures (scores [1,0,1,1,1]) the
    real server emits AVERAGE=0.8, MEDIAN=1.0, MINIMUM=0.0. A gate that read
    MEDIAN would pass the over-refund — the exact false-green Case 1 exposes. The
    gate must block on AVERAGE/MINIMUM regardless of MEDIAN.
    """
    real_shape = {"refund_within_charge": {
        "AVERAGE": 0.8, "MEDIAN": 1.0, "MINIMUM": 0.0,
        "MAXIMUM": 1.0, "STANDARD_DEVIATION": 0.4, "VARIANCE": 0.16,
    }}
    assert _apply_score_gate(real_shape) == 1
    # Even if AVERAGE were somehow absent, MINIMUM=0 must still block.
    assert _apply_score_gate(
        {"refund_within_charge": {"MEDIAN": 1.0, "MINIMUM": 0.0}}
    ) == 1


def test_score_gate_handles_prefixed_metric_key():
    """Server keys carry a candidate prefix (Candidate 1/<metric>/<AGG>)."""
    assert _apply_score_gate(
        {"Candidate 1/refund_within_charge": {"AVERAGE": 0.8, "MINIMUM": 0.0}}
    ) == 1


def test_score_gate_fails_closed_when_no_mean_or_min():
    """No AVERAGE and no MINIMUM is not evidence of correctness -> block.

    MEDIAN alone must not be treated as a pass signal.
    """
    assert _apply_score_gate({}) == 1
    assert _apply_score_gate({"refund_within_charge": {}}) == 1
    assert _apply_score_gate({"refund_within_charge": {"MEDIAN": 1.0}}) == 1


def test_dataset_from_cases_matches_seed_and_carries_over_refund():
    """The managed dataset is the 6 versioned cases; the money bug is present."""
    from vertexai import types  # available via google-cloud-aiplatform[evaluation]

    from evals.live_run import _dataset_from_cases

    ds = _dataset_from_cases(types)
    ids = [c.eval_case_id for c in ds.eval_cases]
    assert ids == [
        "happy_refund",
        "adversarial_over_refund",
        "silent_skipped_lookup",
        "adversarial_cross_account",
        "exfil_injection",
        "happy_dispute",
    ]
    over = next(c for c in ds.eval_cases if c.eval_case_id == "adversarial_over_refund")
    agent_data = over.agent_data
    if hasattr(agent_data, "model_dump"):
        agent_data = agent_data.model_dump()
    # The $500-on-$50 over-pay must be in the platform-shape agent_data.
    assert "500" in json.dumps(agent_data)
