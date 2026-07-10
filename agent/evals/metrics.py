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

from .agent_data import platform_instance_to_turns

# ---------------------------------------------------------------------------
# Green invariants as LOCAL custom_function callables.
#
# The Evaluation Service supports a metric whose custom_function is a *local
# Python callable* (run in-process by CustomMetricHandler), not only a remote
# code string. We use that so the live metric imports the SAME contract module
# the runtime callback and pytest use — "one function, three jobs" becomes
# literal, with no second hand-copied predicate that can drift.
#
# Each callable returns {"score", "explanation"} and FAILS LOUD (raises via the
# adapter) if the instance carries no agent data — a false green is exactly the
# failure Case 1 is about.
# ---------------------------------------------------------------------------


def invariant_refund_within_charge(instance: dict[str, Any]) -> dict[str, Any]:
    """refund_within_charge over the platform instance (green, gating)."""

    turns = platform_instance_to_turns(instance)
    verdict = contract.check_refund_within_charge_trace(turns)
    return {"score": verdict.score, "explanation": verdict.detail}


def invariant_refund_requires_lookup(instance: dict[str, Any]) -> dict[str, Any]:
    """refund_requires_lookup over the platform instance (green, beat B)."""

    turns = platform_instance_to_turns(instance)
    verdict = contract.check_refund_requires_lookup_trace(turns)
    return {"score": verdict.score, "explanation": verdict.detail}


# The judge's rubric — decomposed and binary, and (crucially) with an explicit
# JSON output contract. The service parses the judge's raw output; free-text like
# "SCORE: 0" fails that parse. Asking for a strict JSON object matching the
# result schema (score + explanation) is the SDK-native way to make it robust.
JUDGE_PROMPT_TEMPLATE = """
You are grading ONLY the tone of a customer-support reply — politeness and
absence of blame. Do NOT judge factual correctness.

Reply to grade:
{response}

Consider:
1. Is the reply polite and professional?
2. Is it free of blame toward the customer?

Output ONLY a JSON object, no other text:
{"score": <1 if both are yes, otherwise 0>, "explanation": "<one short sentence>"}
"""

# The judge runs server-side in the eval region (us-central1). Pin it to a model
# available there so it never trips the global-only cross-region error.
#
# IMPORTANT (Fase 2): the Evaluation Service rejects a bare model name for the
# judge's autorater — it wants a *resource name* ("Invalid autorater model
# resource name" / 400). Build the fully-qualified publisher path.
JUDGE_MODEL = "gemini-2.5-flash"


def _judge_model_resource_name(project: str | None, location: str) -> str:
    """Fully-qualified autorater model resource name for the judge (LLMMetric).

    The Evaluation Service's ``judge_autorater_config.autorater_model`` requires
    a resource name, not a bare id like ``gemini-2.5-flash``.
    """

    loc = location or "us-central1"
    if project:
        return (
            f"projects/{project}/locations/{loc}"
            f"/publishers/google/models/{JUDGE_MODEL}"
        )
    return f"publishers/google/models/{JUDGE_MODEL}"


def build_invariant_metric():
    """Green metric: refund_within_charge as a local-callable Metric."""

    from vertexai import types

    return types.Metric(
        name="refund_within_charge",
        custom_function=invariant_refund_within_charge,
    )


def build_trajectory_metric():
    """Green metric: refund_requires_lookup as a local-callable Metric (beat B)."""

    from vertexai import types

    return types.Metric(
        name="refund_requires_lookup",
        custom_function=invariant_refund_requires_lookup,
    )


def build_judge_metric(project: str | None = None, location: str = "us-central1"):
    """Amber metric: a tone judge as an LLMMetric with a JSON output contract.

    ``project``/``location`` build the autorater's fully-qualified model resource
    name (the service rejects a bare model id).
    """

    from vertexai import types

    return types.LLMMetric(
        name="tone_check",
        prompt_template=JUDGE_PROMPT_TEMPLATE,
        judge_model=_judge_model_resource_name(project, location),
    )


def managed_metric_enums() -> list[str]:
    """Grey baselines to request from the Evaluation Service (by enum name)."""

    # SINGLE-TURN managed metric. Correct here: the live pipeline runs
    # DETERMINISTIC single-turn inference (see evals/live.py), so the scored data
    # is single-turn and this baseline applies cleanly (it errored earlier only
    # on multi-turn user-simulation data). Confirmed live at 1.00 (100%) across
    # runs: a real Google managed *quality* metric waves the over-refund through
    # just like the tone judge does — only the hard invariant catches it. THIS is
    # the honest "green score lies" evidence.
    #
    # HALLUCINATION was DROPPED on purpose (Fase 2 review): it is a non-
    # deterministic autorater (0.76–0.92 across runs, pass_rate flipping 0%/50%)
    # and it scores the *correct* dispute case ~0.67 — i.e. it flags a clean
    # response. On stage that (a) breaks the "all managed green -> ship it?"
    # naive-green moment and (b) muddies the message. A wobbling grey row on a
    # correct case is a credibility risk, not a bonus. Keep the baseline stable.
    return [
        "FINAL_RESPONSE_QUALITY",
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
    # Blame -> fail; anything else passes. (A polite reply about a WRONG amount
    # still passes on tone — that is the whole point: tone can't see the money.)
    return 0.0 if any(w in text for w in _BLAME_WORDS) else 1.0


def evaluate_instance(instance: dict[str, Any]) -> dict[str, float]:
    """Score one instance with all local metrics (green + amber)."""

    turns = instance.get("agent_eval_data", {}).get("turns", [])
    scores: dict[str, float] = {}
    for name, fn in contract.TRACE_INVARIANTS.items():
        scores[name] = fn(turns).score
    scores["tone_check"] = local_tone_score(instance)
    return scores
