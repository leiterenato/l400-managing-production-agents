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


def test_metric_fails_loud_on_placeholder():
    """A failed/placeholder run must ERROR, never score a false green."""
    placeholder = {"eval_case_id": "x", "response": {"parts": [{"text": "Missing"}]}}
    with pytest.raises(ValueError):
        platform_instance_to_turns(placeholder)
    # And the metric callable surfaces that as an exception (-> num_cases_error).
    with pytest.raises(ValueError):
        invariant_refund_within_charge(placeholder)
