"""Measure live consistency of the fixed-input scored inference.

The input prompts are deterministic, but the agent's trajectory is an LLM — so
whether the money bug reproduces is EMPIRICAL, not guaranteed. This script is
what proves it (measured 6/6 to date).

Runs the happy_refund + happy_dispute inference N times and reports, per run:
  - did issue_refund fire, with what amount / charge_amount
  - did any case come back as an error string (SDK parse crash -> num_cases_error)
  - what tools each case called

Answers the only question that matters for stage: does the payoff reproduce?

    EVAL_LIVE_CONFIRM=1 uv run python -m scripts.flaky_check 5
"""

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _refund_summary(agent_data) -> tuple[str, dict | None]:
    """Return (human summary, refund response dict|None) for one case's trace."""

    if isinstance(agent_data, str):
        try:
            err = json.loads(agent_data).get("error", agent_data)
        except Exception:
            err = agent_data
        return f"ERROR-STRING ({str(err)[:60]})", None
    if not isinstance(agent_data, dict):
        return f"non-dict {type(agent_data)}", None
    calls = []
    refund = None
    for turn in agent_data.get("turns", []):
        for ev in turn.get("events", []):
            for p in (ev.get("content") or {}).get("parts") or []:
                fc = p.get("function_call")
                fr = p.get("function_response")
                if fc:
                    calls.append(fc.get("name"))
                if fr and fr.get("name") == "issue_refund":
                    refund = fr.get("response") or {}
    seq = ">".join(calls)
    if refund is not None:
        return f"paid={refund.get('amount')} charge={refund.get('charge_amount')} | {seq}", refund
    return f"NO issue_refund | {seq}", None


def _is_money_bug(refund: dict | None) -> bool:
    """The money bug = a refund that paid out MORE than the charge (numeric)."""

    if not refund or refund.get("status") != "refunded":
        return False
    try:
        return float(refund["amount"]) > float(refund["charge_amount"])
    except (KeyError, TypeError, ValueError):
        return False


def main() -> int:
    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print("Set EVAL_LIVE_CONFIRM=1.")
        return 3
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5

    from dotenv import load_dotenv

    load_dotenv(os.path.join(_ROOT, ".env"))
    from financial_support.config import get_settings, reload_settings

    reload_settings()
    import pandas as pd
    import vertexai

    from financial_support import root_agent
    from evals.scenarios import live_inference_rows

    settings = get_settings()
    print(f"scenario={settings.scenario} model={settings.model} runs={n}")
    client = vertexai.Client(
        project=settings.project or os.environ.get("GOOGLE_CLOUD_PROJECT"),
        location=settings.location,
    )
    rows = live_inference_rows()
    df = pd.DataFrame([{"prompt": r["prompt"]} for r in rows])

    money_bug_hits = 0
    for k in range(n):
        traces = client.evals.run_inference(
            agent=root_agent, src=df, config={"allow_cross_region_model": True}
        )
        out = traces.eval_dataset_df
        print(f"\n--- run {k + 1}/{n} ---")
        for i, r in enumerate(rows):
            summ, refund = _refund_summary(out.iloc[i].get("agent_data"))
            print(f"  [{r['case_id']}] {summ}")
            if r["case_id"] == "happy_refund" and _is_money_bug(refund):
                money_bug_hits += 1
    print(f"\nMONEY BUG reproduced: {money_bug_hits}/{n} runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
