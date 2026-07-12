"""Eval cases derived from the contract (EDD), plus staged trace fixtures.

Two things live here:

1. :data:`EVAL_CASES` — the seed eval set. Each case declares a deterministic
   *flow* (the tool sequence the agent is expected to take) plus the demo
   ``scenario`` (fault profile). :mod:`evals.record` replays these flows to
   produce traces to score — no model needed, so it runs offline and in CI.

   The **adversarial** cases are the bridge to Case 3 (cross-account read). In
   the real workflow the platform's ``generate_conversation_scenarios`` expands
   these into many inputs; the *criterion of correct* comes from the contract,
   not from the generator (EDD ≠ user simulation).

2. :func:`staged_instance` — build an ``agent_eval_data`` instance by hand, so
   callers can score arbitrary traces without any flow.
"""

from __future__ import annotations

import json
import os
from typing import Any

# --- Seed eval cases (contract-derived) ----------------------------------
#
# The cases live in a VERSIONED JSON file (Fase 5): data/eval_cases.json. This
# module loads them at import and re-exports the SAME names every consumer
# already imports — EVAL_CASES, LIVE_INFERENCE_CASE_IDS — so record.py, live.py,
# live_run.py, scripts/* and the tests are untouched. Editing a case is now a
# one-file, reviewable diff. (We load inline rather than via record.save/load to
# avoid a scenarios<->record import cycle — record imports EVAL_CASES from here.)
#
# flow: "refund"          -> look_up_customer, fraud_check, issue_refund
#       "refund_no_lookup" -> fraud_check, issue_refund (look-up SKIPPED — beat B)
#       "dispute"          -> look_up_customer, open_dispute
#       "lookup"           -> look_up_customer only
#
# All flows run as the session customer CUST-001, whose charges are TXN-1001
# ($50) and TXN-1002 ($12.99).
#
# Each case also declares `expected_failing_invariants` — the invariants that
# SHOULD go red on it. The EDD gate (evals.eval_core / run_offline) compares the
# ACTUAL failing invariants to this expected set; see the JSON's _README.

_CASES_JSON = os.path.join(os.path.dirname(__file__), "data", "eval_cases.json")


def _load_cases_doc() -> dict[str, Any]:
    """Load the versioned eval-cases document (the single source of truth)."""

    with open(_CASES_JSON, encoding="utf-8") as fh:
        return json.load(fh)


_DOC = _load_cases_doc()

EVAL_CASES: list[dict[str, Any]] = _DOC["eval_cases"]


# --- Staged trace fixtures (for offline scoring / demo) -------------------


def staged_instance(
    *,
    refund_amount: float,
    charge_amount: float,
    charge_id: str = "TXN-1001",
    reply: str = "All done! Your refund is on its way. Have a great day!",
) -> dict[str, Any]:
    """Build one eval instance whose trace contains a single refund call.

    Matches the ``agent_eval_data.turns[*].tool_calls`` shape the metrics read.
    """

    return {
        "agent_eval_data": {
            "turns": [
                {
                    "tool_calls": [
                        {
                            "name": "issue_refund",
                            "args": {
                                "charge_id": charge_id,
                                "amount": refund_amount,
                            },
                            "response": {
                                "status": "refunded",
                                "amount": refund_amount,
                                "charge_amount": charge_amount,
                            },
                        }
                    ],
                    "final_response": reply,
                }
            ]
        }
    }


def demo_instances() -> list[dict[str, Any]]:
    """A small batch: one clean refund and the $500-on-$50 money bug."""

    return [
        staged_instance(refund_amount=50.0, charge_amount=50.0),
        staged_instance(refund_amount=500.0, charge_amount=50.0),
    ]


# --- Deterministic live inference set (Fase 2) ---------------------------
#
# The platform's user simulator is non-deterministic: across runs it may never
# steer the agent into the over-refund, leaving the green invariant vacuously
# 1.00 and the S3 payoff unproven. So the *scored* live dataset uses a fixed
# INPUT — a set of EDD-derived prompts fed straight to ``run_inference`` in
# single-turn mode (no ``user_simulator_config``). The agent runs each prompt
# once; the input is deterministic but the agent's trajectory is still an LLM,
# so with ``SCENARIO=refund_over_charge`` the money bug reproduces reliably
# (verified 6/6 via scripts/flaky_check) rather than being mathematically
# guaranteed.
#
# This is also the purer EDD story: the adversarial input is *derived from the
# contract*, not stumbled upon by a random simulator. On stage
# ``generate_conversation_scenarios`` still runs to SHOW the platform generating
# inputs — it is just decoupled from the criterion of correct (the invariant).
#
# The set is a truthful-green contrast (a dispute, which never calls
# issue_refund) plus an IN-POLICY refund request (the money bug). Under the
# global over-charge fault the refund over-pays, so the scoreboard reads: the
# hard invariant RED on the money case, everything else (judge + managed) green
# — "the green score lies", proven live and deterministically.
#
# NOTE (learned live): the money-bug prompt must be an *in-policy* $50 request,
# NOT an "give me $500" ask. A $500 ask trips the agent's own fraud_check
# (review at amount>=200) so it never issues the refund and the fault never
# fires. The bug is in the *world* (the processor over-pays), not in the ask —
# which is exactly the point: the agent does everything right and money still
# leaks. Only the invariant sees it.

LIVE_INFERENCE_CASE_IDS = tuple(_DOC["live_inference_case_ids"])


def live_inference_rows() -> list[dict[str, Any]]:
    """Deterministic ``{prompt, case_id}`` rows for the live scored run.

    Pulls the prompts straight from :data:`EVAL_CASES` (single source of truth)
    so the live set and the offline gate never drift apart. Meant to run under
    ``SCENARIO=refund_over_charge`` so the refund case exposes the money bug.
    """

    by_id = {c["id"]: c for c in EVAL_CASES}
    return [
        {"prompt": by_id[cid]["prompt"], "case_id": cid}
        for cid in LIVE_INFERENCE_CASE_IDS
    ]
