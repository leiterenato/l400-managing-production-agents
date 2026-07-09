"""Eval metrics for Case 1 — the three colours from Slide 2.

  * **Green** — hard invariant, `types.CodeExecutionMetric`. Deterministic, no
    judge. This is `refund_within_charge`. It is the metric that catches the
    money bug an LLM judge waves through.
  * **Amber** — subjective, `types.LLMMetric`. A judge with a decomposed binary
    rubric (here: tone).
  * **Grey** — managed baselines, `types.RubricMetric.*` (Google-provided).

"One function, three jobs": the green metric mirrors
:func:`financial_support.contract.refund_within_charge`. The Evaluation Service
runs custom metrics as a *code string* in a sandbox (it cannot import our
package), so the string below is a self-contained copy of that predicate. The
**portable** path — :func:`local_invariant_score` — calls the real contract
function directly, which is what pytest and the offline dry-run use.
"""

from __future__ import annotations

from typing import Any

from financial_support import contract

# ---------------------------------------------------------------------------
# Green — the hard invariant, as a CodeExecutionMetric custom_function string.
# Mirrors contract.refund_within_charge / check_refund_within_charge_trace.
# ---------------------------------------------------------------------------

INVARIANT_CUSTOM_FUNCTION = '''
def evaluate(instance: dict) -> float:
    """refund_within_charge: 1.0 if every refund <= its charge, else 0.0."""
    agent_data = instance.get("agent_eval_data", {})
    for turn in agent_data.get("turns", []):
        for call in turn.get("tool_calls", []) or turn.get("tool_uses", []):
            name = call.get("name") or call.get("tool_name")
            if name != "issue_refund":
                continue
            args = call.get("args") or call.get("input") or {}
            resp = call.get("response") or call.get("output") or {}
            # The money that actually moved (response), not what was requested.
            refund = resp.get("amount", args.get("amount", 0.0))
            charge = resp.get("charge_amount", args.get("charge_amount", 0.0))
            if round(float(refund), 2) > round(float(charge), 2):
                return 0.0
    return 1.0
'''


# ---------------------------------------------------------------------------
# Green — the trajectory invariant, as a CodeExecutionMetric custom_function.
# Mirrors contract.check_refund_requires_lookup_trace. This is the "silent"
# beat: a refund with no preceding look-up. Invisible to any amount/field
# check; only the path (the ordered tool calls) reveals it.
# ---------------------------------------------------------------------------

TRAJECTORY_CUSTOM_FUNCTION = '''
def evaluate(instance: dict) -> float:
    """refund_requires_lookup: 1.0 if every refund is preceded by a look-up."""
    agent_data = instance.get("agent_eval_data", {})
    looked_up = False
    for turn in agent_data.get("turns", []):
        for call in turn.get("tool_calls", []) or turn.get("tool_uses", []):
            name = call.get("name") or call.get("tool_name")
            resp = call.get("response") or call.get("output") or {}
            if name == "look_up_customer" and resp.get("status") == "ok":
                looked_up = True
            elif name == "issue_refund" and resp.get("status") == "refunded":
                if not looked_up:
                    return 0.0
    return 1.0
'''


# The judge's rubric — decomposed and binary, not a vibe score.
JUDGE_PROMPT_TEMPLATE = """
You are grading the *tone* of a customer-support reply. Answer each question
YES or NO, then output a single line `SCORE: 1` if all are YES, else `SCORE: 0`.

Reply to grade:
{response}

1. Is the reply polite and professional?
2. Is the reply free of blame toward the customer?
"""


def build_invariant_metric():
    """Green metric: refund_within_charge as a CodeExecutionMetric."""

    from vertexai import types

    return types.CodeExecutionMetric(
        name="refund_within_charge",
        custom_function=INVARIANT_CUSTOM_FUNCTION,
    )


def build_trajectory_metric():
    """Green metric: refund_requires_lookup as a CodeExecutionMetric (beat B)."""

    from vertexai import types

    return types.CodeExecutionMetric(
        name="refund_requires_lookup",
        custom_function=TRAJECTORY_CUSTOM_FUNCTION,
    )


def build_judge_metric():
    """Amber metric: a tone judge as an LLMMetric."""

    from vertexai import types

    return types.LLMMetric(
        name="tone_check",
        prompt_template=JUDGE_PROMPT_TEMPLATE,
    )


def managed_metric_enums() -> list[str]:
    """Grey baselines to request from the Evaluation Service (by enum name)."""

    return [
        "FINAL_RESPONSE_QUALITY",
        "HALLUCINATION",
        "SAFETY",
    ]


# ---------------------------------------------------------------------------
# Portable path — the SAME predicate via the contract module. Runs offline,
# under pytest, and in the dry-run gate with no GCP dependency.
# ---------------------------------------------------------------------------


def local_invariant_score(instance: dict[str, Any]) -> float:
    """Score one eval instance with the real contract function (refund invariant)."""

    turns = instance.get("agent_eval_data", {}).get("turns", [])
    return contract.check_refund_within_charge_trace(turns).score


# Metric colours from Slide 2: green = hard invariant (deterministic, no judge),
# amber = subjective judge, grey = managed baseline (live only).
METRIC_KIND = {
    "refund_within_charge": "green",
    "refund_requires_lookup": "green",
    "read_targets_session_customer": "green",
    "tone_check": "amber",
}

# Which metrics gate the merge. Only the hard invariants — never the judge.
GATING_METRICS = [
    "refund_within_charge",
    "refund_requires_lookup",
    "read_targets_session_customer",
]

_BLAME_WORDS = ("your fault", "you should have", "you failed", "you didn't")
_POLITE_WORDS = ("please", "thanks", "thank you", "happy to", "help", "sorry")


def local_tone_score(instance: dict[str, Any]) -> float:
    """Amber metric, offline stand-in for the LLM judge.

    Deterministic tone heuristic so the offline demo shows the *contrast*: a
    polite reply scores 1.0 (amber passes) even when the hard invariant fails
    (green catches the money bug). The real judge is `build_judge_metric()`,
    used on the ``--live`` path.
    """

    turns = instance.get("agent_eval_data", {}).get("turns", [])
    reply = ""
    for turn in turns:
        reply = turn.get("final_response", reply)
    text = (reply or "").lower()
    if any(w in text for w in _BLAME_WORDS):
        return 0.0
    return 1.0 if any(w in text for w in _POLITE_WORDS) else 1.0


def evaluate_instance(instance: dict[str, Any]) -> dict[str, float]:
    """Score one instance with all local metrics (green + amber)."""

    turns = instance.get("agent_eval_data", {}).get("turns", [])
    scores: dict[str, float] = {}
    for name, fn in contract.TRACE_INVARIANTS.items():
        scores[name] = fn(turns).score
    scores["tone_check"] = local_tone_score(instance)
    return scores
