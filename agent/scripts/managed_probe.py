"""Diagnostic (reusable): measure the STABILITY of managed grey candidates.

Why it exists: FINAL_RESPONSE_QUALITY proved unusable as the "grey" baseline —
it is an adaptive rubric that dings the CLEAN case and varies run to run. This
probe is how we PICKED SAFETY (stable 1.00) over it, and how to re-verify before
a talk if the platform's autoraters drift. It answers, empirically and cheaply,
which managed metric is a stable green on our scored set (dispute + over-refund):

  * run_inference ONCE (agent LLM) -> traces
  * evaluate() N times on the SAME traces with [SAFETY, TOOL_USE_QUALITY,
    FINAL_RESPONSE_QUALITY] -> isolates the autorater's non-determinism
  * print per-case scores across runs so we can see variance at a glance

    EVAL_LIVE_CONFIRM=1 uv run python -m scripts.managed_probe 3
"""

from __future__ import annotations

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

_CANDIDATES = ["SAFETY", "TOOL_USE_QUALITY", "FINAL_RESPONSE_QUALITY"]


def _case_scores(result, metric_name):
    """Return the per-case scores for one metric_name from an EvaluationResult."""

    scores = []
    for case in getattr(result, "eval_case_results", None) or []:
        found = None

        def rec(o):
            nonlocal found
            if isinstance(o, dict):
                if o.get("metric_name") == metric_name and "score" in o:
                    found = o.get("score")
                for v in o.values():
                    rec(v)
            elif isinstance(o, list):
                for x in o:
                    rec(x)

        rec(case.model_dump(mode="json") if hasattr(case, "model_dump") else case)
        scores.append(found)
    return scores


def main() -> int:
    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print("Set EVAL_LIVE_CONFIRM=1 (calls Preview APIs, spends).")
        return 3
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3

    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
    from financial_support.config import get_settings, reload_settings

    reload_settings()
    settings = get_settings()
    if settings.scenario != "refund_over_charge":
        print(f"SCENARIO={settings.scenario}; need refund_over_charge. Abort.")
        return 4

    import pandas as pd
    import vertexai
    from vertexai import types

    from financial_support import root_agent
    from evals.scenarios import live_inference_rows

    print(f"scenario={settings.scenario} model={settings.model} evaluate_runs={n}")
    client = vertexai.Client(
        project=settings.project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=settings.location,
    )

    rows = live_inference_rows()
    df = pd.DataFrame([{"prompt": r["prompt"]} for r in rows])

    # ONE inference (agent LLM) -> traces reused across every evaluate().
    traces = client.evals.run_inference(
        agent=root_agent, src=df, config={"allow_cross_region_model": True}
    )

    managed = [getattr(types.RubricMetric, c) for c in _CANDIDATES]

    # metric -> case -> [score per run]
    table = {c: {r["case_id"]: [] for r in rows} for c in _CANDIDATES}
    for run in range(n):
        result = client.evals.evaluate(dataset=traces, metrics=managed)
        for c in _CANDIDATES:
            per_case = _case_scores(result, c.lower() + "_v1") or _case_scores(result, c.lower())
            # fall back: the summary uses "<enum lower>_v1"; try both.
            if not any(s is not None for s in per_case):
                per_case = _case_scores(result, c.lower())
            for i, r in enumerate(rows):
                table[c][r["case_id"]].append(per_case[i] if i < len(per_case) else None)
        print(f"  evaluate run {run + 1}/{n} done")

    print("\n===== MANAGED METRIC STABILITY =====")
    print("(the grey baseline must be a STABLE ~1.0 on BOTH cases to wave the bug through)\n")
    for c in _CANDIDATES:
        print(f"{c}:")
        for r in rows:
            vals = table[c][r["case_id"]]
            pretty = ", ".join(
                f"{v:.2f}" if isinstance(v, (int, float)) else str(v) for v in vals
            )
            print(f"  [{r['case_id']:<14}] {pretty}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
