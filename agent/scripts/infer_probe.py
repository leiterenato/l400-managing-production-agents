"""Diagnostic (reusable): DETERMINISTIC single-turn inference -> dump agent_data.

Shows exactly which tools the agent called for each EDD prompt, so we can see
why the refund invariant did (or did not) fire. Cheaper than a full eval run
(no metrics). This is what surfaced the two Fase 2 root causes: a "$500" ask
tripping fraud review (never issuing the refund), and the SCENARIO fault not
being applied. Reach for it whenever a live invariant score is surprising.

    EVAL_LIVE_CONFIRM=1 uv run python -m scripts.infer_probe
"""

from __future__ import annotations

import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def main() -> int:
    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print("Set EVAL_LIVE_CONFIRM=1 to run (calls Preview APIs).")
        return 3
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        pass

    import pandas as pd
    import vertexai

    from financial_support.config import get_settings, reload_settings

    reload_settings()  # pick up SCENARIO from .env (see evals/live.py note)

    from financial_support import root_agent
    from evals.scenarios import live_inference_rows

    settings = get_settings()
    print(f"scenario={settings.scenario} model={settings.model}")
    project = settings.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = vertexai.Client(project=project, location=settings.location)

    rows = live_inference_rows()
    prompt_df = pd.DataFrame([{"prompt": r["prompt"]} for r in rows])
    traces = client.evals.run_inference(
        agent=root_agent, src=prompt_df, config={"allow_cross_region_model": True}
    )

    df = traces.eval_dataset_df
    print("columns:", list(df.columns))
    for i, r in enumerate(rows):
        print(f"\n===== [{r['case_id']}] {r['prompt']}")
        row = df.iloc[i].to_dict()
        agent_data = row.get("agent_data")
        if isinstance(agent_data, str):
            print("  agent_data (str):", agent_data[:400])
            continue
        if not isinstance(agent_data, dict):
            print("  agent_data type:", type(agent_data), repr(agent_data)[:300])
            continue
        for turn in agent_data.get("turns", []):
            for ev in turn.get("events", []):
                author = ev.get("author")
                parts = (ev.get("content") or {}).get("parts") or []
                for p in parts:
                    fc = p.get("function_call")
                    fr = p.get("function_response")
                    tx = p.get("text")
                    if fc:
                        print(f"  [{author}] CALL {fc.get('name')} args={fc.get('args')}")
                    elif fr:
                        print(f"  [{author}] RESP {fr.get('name')} -> {json.dumps(fr.get('response'))[:200]}")
                    elif tx:
                        print(f"  [{author}] TEXT {tx[:200]}")

    with open("/tmp/infer_probe_agentdata.json", "w") as fh:
        json.dump(
            [df.iloc[i].get("agent_data") for i in range(len(rows))],
            fh, indent=2, default=str,
        )
    print("\nwrote /tmp/infer_probe_agentdata.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
