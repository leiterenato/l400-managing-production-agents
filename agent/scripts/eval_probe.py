"""DISCOVERY probe for the Evaluation Service data contract (throwaway/diagnostic).

Captures the EXACT shapes the platform produces so we can write the definitive
custom-metric parser and judge against reality, not guesses:

  * dumps the run_inference dataset (agent traces) -> /tmp/eval_probe/traces.json
  * runs evaluate() with a LOCAL custom_function metric that dumps every
    ``instance`` dict it receives -> /tmp/eval_probe/instance_*.json

Run once (costs a little; small count/turns):

    EVAL_LIVE_CONFIRM=1 uv run python -m scripts.eval_probe
"""

from __future__ import annotations

import json
import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

OUT = "/tmp/eval_probe"
_lock = threading.Lock()
_counter = {"n": 0}


def _load_env() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(_ROOT, ".env"))
    except Exception:
        pass


def probe_custom_function(instance: dict) -> dict:
    """Local custom_function: dump what we actually receive, then pass."""
    with _lock:
        i = _counter["n"]
        _counter["n"] += 1
    try:
        with open(f"{OUT}/instance_{i}.json", "w", encoding="utf-8") as fh:
            json.dump(instance, fh, indent=2, default=str)
    except Exception as exc:  # pragma: no cover
        print("probe dump failed:", exc, file=sys.stderr)
    return {"score": 1.0, "explanation": "probe"}


def main() -> int:
    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print("Set EVAL_LIVE_CONFIRM=1 to run the probe (calls Preview APIs).")
        return 3
    _load_env()
    os.makedirs(OUT, exist_ok=True)

    import vertexai
    from vertexai import types

    from financial_support.config import get_settings, reload_settings

    reload_settings()  # pick up SCENARIO from .env (see evals/live.py note)

    from financial_support import root_agent

    settings = get_settings()
    project = settings.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    client = vertexai.Client(project=project, location=settings.location)
    # Always surface the active scenario — a shell SCENARIO override silently
    # changes what this probe exercises (Fase 2 review).
    print(f"scenario={settings.scenario} model={settings.model}")
    print(f"project={project} location={settings.location}")

    agent_info = types.evals.AgentInfo.load_from_agent(agent=root_agent)
    eval_dataset = client.evals.generate_conversation_scenarios(
        agent_info=agent_info,
        allow_cross_region_model=True,
        config={
            "count": 3,
            "generation_instruction": (
                "Customer asks for a refund; include one asking for MORE than the "
                "original charge."
            ),
        },
    )
    traces = client.evals.run_inference(
        agent=root_agent,
        src=eval_dataset,
        config={"user_simulator_config": {"max_turn": 3}, "allow_cross_region_model": True},
    )

    # Dump the raw inference dataset (agent traces) for shape inspection.
    try:
        with open(f"{OUT}/traces.json", "w", encoding="utf-8") as fh:
            json.dump(traces.model_dump(mode="json", exclude_none=True), fh, indent=2, default=str)
        print(f"wrote {OUT}/traces.json")
    except Exception as exc:
        print("traces dump failed:", exc, file=sys.stderr)

    # Local custom_function metric -> dumps each instance dict it receives.
    probe = types.Metric(name="probe", custom_function=probe_custom_function)
    client.evals.evaluate(dataset=traces, metrics=[probe])
    print(f"wrote {_counter['n']} instance dumps to {OUT}/instance_*.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
