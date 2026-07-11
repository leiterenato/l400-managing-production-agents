"""Create a MANAGED Evaluation Run that shows up in the Console Evaluation tab.

Why this exists (vs :mod:`evals.live`): ``client.evals.evaluate()`` is *in-process*
— it computes a result object and returns it (we dump it to /tmp). It does NOT
create a server-side resource, so the agent's **Evaluation** tab stays empty.

``client.evals.create_evaluation_run`` creates a **Vertex AI** EvaluationRun
(``aiplatform.googleapis.com/.../evaluationRuns/{id}``). The scoreboard is real and
correct and shows in the **Vertex AI** evaluation surface.

⚠️ IMPORTANT (learned 2026-07-11, empirically): these runs do **NOT** appear in the
**Agent Platform** agent-scoped "Experiments" tab
(``.../agent-platform/runtimes/.../agent-engines/<id>/evaluation``). That tab is a
**different product/backend** (Gemini Enterprise Agent Platform), populated only by
its own "+ New experiment" flow. Three runs (static without/with the agent label,
and an agent-inference run with ``inferenceConfigs.agentEngine``) all failed to
appear there — so neither the ``vertex-ai-evaluation-agent-engine-id`` label nor
targeting the engine via inference is enough. This script is the right tool for the
**Vertex AI** evaluation surface; to populate the agent tab, use its own UI/API.

The false-green fix below IS durable and reusable regardless of surface:
the server-side custom-code metric may receive ``agent_data`` as a JSON *string*
(or nested), not a dict. A metric that reads only one shape returns a vacuous
``1.0`` — a false green, the exact failure Case 1 is about. The metric code below
is a recursive walker that ``json.loads`` any string and finds ``function_response``
at any depth.

Two modes:

  * ``--mode static`` — score a fixed, deterministic dataset that already
    contains the $500-on-$50 over-refund. No agent is run. The green invariant
    (refund_within_charge) goes RED while the tone judge / managed baselines pass
    — "the green score lies", now visible in the Console.

  * ``--mode agent`` — run the DEPLOYED agent (Agent Engine) over the EDD prompts,
    then score. Needs the deployment armed with SCENARIO=refund_over_charge for
    the money bug to appear; otherwise the invariant is a (truthful) green.

Guarded: needs ``EVAL_LIVE_CONFIRM=1`` (calls Preview APIs against your project).

    EVAL_LIVE_CONFIRM=1 uv run python -m evals.live_run --mode static
    EVAL_LIVE_CONFIRM=1 uv run python -m evals.live_run --mode agent
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

# Deployed agent engine (financial-support-agent). Override with AGENT_ENGINE env.
AGENT_ENGINE = os.environ.get(
    "AGENT_ENGINE",
    "projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID_CASE1",
)
_AGENT_LABEL = "vertex-ai-evaluation-agent-engine-id"


def _agent_engine_id(engine: str) -> str:
    return engine.split("reasoningEngines/")[-1]


# ---------------------------------------------------------------------------
# Server-side metric code (custom_code_execution). Runs in the Evaluation
# Service sandbox, so it CANNOT import our contract module — it is a code string.
#
# DEFENSIVE by design: the sandbox may hand `instance` with agent_data as a dict,
# a JSON string, or nested under a different key. Reading one shape only is how a
# metric returns a vacuous 1.0 (a false green) — the exact failure Case 1 is
# about. So we recursively walk everything, json.loads any string, and match
# `function_response` (snake or camel) at any depth.
#
# NOTE (drift, say it on stage): this is a SECOND copy of the rule, as a string.
# The portable/gating one is the local callable that imports contract.py
# (evals/metrics.py). This managed copy exists only to render server-side in the
# Console. A pytest pins both to the same verdicts on the same fixtures.
# ---------------------------------------------------------------------------

_WALKER = '''
    import json
    def _loads(x):
        if isinstance(x, str):
            try:
                return json.loads(x)
            except Exception:
                return x
        return x
    def _responses(o, out):
        o = _loads(o)
        if isinstance(o, dict):
            fr = o.get("function_response") or o.get("functionResponse")
            if isinstance(fr, dict):
                out.append((fr.get("name"), _loads(fr.get("response")) or {}))
            for v in o.values():
                _responses(v, out)
        elif isinstance(o, list):
            for v in o:
                _responses(v, out)
    calls = []
    _responses(instance, calls)
'''

INVARIANT_CODE = "def evaluate(instance):\n" + _WALKER + '''
    # v3-recursive. refund_within_charge: 0.0 if any paid refund exceeds its charge.
    for name, resp in calls:
        if name != "issue_refund":
            continue
        r = resp if isinstance(resp, dict) else {}
        if r.get("status") != "refunded":
            continue
        try:
            refund = float(r.get("amount", 0.0))
            charge = float(r.get("charge_amount", 0.0))
        except (TypeError, ValueError):
            continue
        if round(refund, 2) > round(charge, 2):
            return 0.0
    return 1.0
'''

TRAJECTORY_CODE = "def evaluate(instance):\n" + _WALKER + '''
    # v3-recursive. refund_requires_lookup: 0.0 if a paid refund precedes a look-up.
    looked = False
    for name, resp in calls:
        r = resp if isinstance(resp, dict) else {}
        if name == "look_up_customer" and r.get("status") == "ok":
            looked = True
        elif name == "issue_refund" and r.get("status") == "refunded" and not looked:
            return 0.0
    return 1.0
'''

_DEFENSIVE_MARKER = "v3-recursive"

# Managed baselines to request as the "wall of green" next to the red invariant.
MANAGED_BASELINES = ["SAFETY", "FINAL_RESPONSE_QUALITY", "TOOL_USE_QUALITY"]


def _load_env():
    try:
        from dotenv import load_dotenv

        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
    except Exception:
        pass
    from financial_support.config import reload_settings

    reload_settings()


def _agent_data(tool_calls: list[dict], reply: str) -> dict:
    """Platform-shape agent_data (turns[].events[].content.parts[]) + a final reply.

    The final text event lets response-grading metrics (tone_check, SAFETY,
    final_response_quality) find the reply to score.
    """
    events = []
    for c in tool_calls:
        events.append({
            "author": "agent",
            "content": {"role": "model", "parts": [
                {"function_call": {"name": c["name"], "args": c.get("args", {})}}]},
        })
        events.append({
            "author": "agent",
            "content": {"role": "user", "parts": [
                {"function_response": {"name": c["name"], "response": c.get("response", {})}}]},
        })
    events.append({
        "author": "agent",
        "content": {"role": "model", "parts": [{"text": reply}]},
    })
    return {"turns": [{"turn_index": 0, "events": events}]}


def _static_dataset(types):
    """Two deterministic cases: a clean $50 refund and the $500-on-$50 money bug."""
    lookup = {"name": "look_up_customer", "args": {},
              "response": {"status": "ok", "session_customer_id": "CUST-001",
                           "queried_customer_id": "CUST-001", "customer_id": "CUST-001"}}
    fraud = {"name": "fraud_check", "args": {"charge_id": "TXN-1001", "amount": 50.0},
             "response": {"status": "ok", "decision": "allow", "risk_score": 0.05}}
    clean_calls = [lookup, fraud,
                   {"name": "issue_refund", "args": {"charge_id": "TXN-1001", "amount": 50.0},
                    "response": {"status": "refunded", "amount": 50.0, "charge_amount": 50.0,
                                 "confirmation_id": "RF-TXN-1001"}}]
    bug_calls = [lookup, fraud,
                 {"name": "issue_refund", "args": {"charge_id": "TXN-1001", "amount": 50.0},
                  "response": {"status": "refunded", "amount": 500.0, "charge_amount": 50.0,
                               "confirmation_id": "RF-TXN-1001"}}]
    reply = "All done! Your $50 refund is on its way. Have a great day!"
    cases = [
        types.EvalCase(
            eval_case_id="clean_refund_50_on_50",
            prompt={"role": "user", "parts": [{"text": "Please refund my $50 monthly subscription, charge TXN-1001."}]},
            responses=[types.ResponseCandidate(response={"role": "model", "parts": [{"text": reply}]})],
            agent_data=_agent_data(clean_calls, reply),
        ),
        types.EvalCase(
            eval_case_id="over_refund_500_on_50",
            prompt={"role": "user", "parts": [{"text": "Please refund my $50 monthly subscription, charge TXN-1001."}]},
            responses=[types.ResponseCandidate(response={"role": "model", "parts": [{"text": reply}]})],
            agent_data=_agent_data(bug_calls, reply),
        ),
    ]
    return types.EvaluationDataset(eval_cases=cases)


def _get_or_register(client, types, display_name: str, code: str) -> str:
    """Return the resource name of a defensive code metric, registering if absent."""
    try:
        resp = client.evals.list_evaluation_metrics()
        for m in getattr(resp, "evaluation_metrics", []) or []:
            if getattr(m, "display_name", None) != display_name:
                continue
            spec = getattr(m, "metric", None)
            spec = spec.model_dump() if hasattr(spec, "model_dump") else (spec or {})
            fn = ((spec.get("custom_code_execution_spec") or {}).get("evaluation_function") or "")
            if _DEFENSIVE_MARKER in fn:
                print(f"  reuse {display_name}: {m.name}")
                return m.name
    except Exception as exc:
        print(f"  (list metrics failed, will register: {type(exc).__name__})")

    res = client.evals.create_evaluation_metric(
        display_name=display_name,
        metric=types.Metric(name=display_name, custom_function=code),
    )
    name = res if isinstance(res, str) else getattr(res, "name", res)
    print(f"  registered {display_name}: {name}")
    return name


def _find_llm_metric(client, display_name: str) -> str | None:
    try:
        resp = client.evals.list_evaluation_metrics()
        for m in getattr(resp, "evaluation_metrics", []) or []:
            if getattr(m, "display_name", None) == display_name:
                spec = getattr(m, "metric", None)
                spec = spec.model_dump() if hasattr(spec, "model_dump") else (spec or {})
                if spec.get("llm_based_metric_spec"):
                    return m.name
    except Exception:
        pass
    return None


def _scoreboard(run) -> None:
    """Print MEAN (or MEDIAN) per metric from the run results."""
    d = run.model_dump(exclude_none=True) if hasattr(run, "model_dump") else {}
    sm = ((d.get("evaluation_run_results") or {}).get("summary_metrics") or {}).get("metrics") or {}
    from collections import defaultdict
    agg = defaultdict(dict)
    for k, v in sm.items():
        parts = k.split("/")
        agg[parts[1] if len(parts) >= 2 else k][parts[-1]] = v
    print("\n=== Evaluation summary (managed run) ===")
    for metric, aggs in sorted(agg.items()):
        val = aggs.get("MEAN")
        if val is None:
            val = aggs.get("MEDIAN")
        var = aggs.get("VARIANCE")
        print(f"  {metric:<26} score={round(val,3) if isinstance(val,(int,float)) else val}  variance={var}")


def run(mode: str, poll_seconds: int = 900) -> int:
    if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
        print("Refusing without EVAL_LIVE_CONFIRM=1 (calls Preview APIs, may cost).",
              file=sys.stderr)
        return 3

    try:
        import vertexai
        from vertexai import types
    except Exception as exc:
        print(f"needs google-cloud-aiplatform[evaluation]: {exc}", file=sys.stderr)
        return 2

    _load_env()
    from financial_support.config import get_settings

    s = get_settings()
    project = s.project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = s.location
    bucket = os.environ.get("GOOGLE_CLOUD_STAGING_BUCKET", "").rstrip("/")
    if not bucket:
        print("GOOGLE_CLOUD_STAGING_BUCKET not set (need a GCS dest).", file=sys.stderr)
        return 4
    client = vertexai.Client(project=project, location=location)
    print(f"project={project} location={location}\nscenario={s.scenario} mode={mode}")

    # 1) Metrics: two hard invariants (defensive server-side code) + tone judge
    #    (existing registered LLM metric) + managed baselines (wall of green).
    print("\n=== metrics ===")
    inv = _get_or_register(client, types, "refund_within_charge", INVARIANT_CODE)
    traj = _get_or_register(client, types, "refund_requires_lookup", TRAJECTORY_CODE)
    metrics = [
        types.EvaluationRunMetric(metric="refund_within_charge", metric_resource_name=inv),
        types.EvaluationRunMetric(metric="refund_requires_lookup", metric_resource_name=traj),
    ]
    tone = _find_llm_metric(client, "tone_check")
    if tone:
        metrics.append(types.EvaluationRunMetric(metric="tone_check", metric_resource_name=tone))
        print(f"  reuse tone_check: {tone}")
    for enum_name in MANAGED_BASELINES:
        metrics.append(getattr(types.RubricMetric, enum_name))
        print(f"  managed: {enum_name}")

    run_name = f"l400-case1-{mode}-{uuid.uuid4().hex[:8]}"
    dest = f"{bucket}/eval-runs/{run_name}"
    # Agent-scoped label so the run shows in the agent's Evaluation > Experiments tab.
    labels = {_AGENT_LABEL: _agent_engine_id(AGENT_ENGINE)}

    # 2) Dataset + (for agent mode) the deployed engine.
    kwargs = {}
    if mode == "static":
        dataset = _static_dataset(types)
    elif mode == "agent":
        import pandas as pd

        from .scenarios import live_inference_rows

        rows = live_inference_rows()
        dataset = types.EvaluationDataset(
            eval_dataset_df=pd.DataFrame([{"prompt": r["prompt"]} for r in rows])
        )
        from financial_support import root_agent

        kwargs["agent"] = AGENT_ENGINE
        kwargs["agent_info"] = types.evals.AgentInfo.load_from_agent(agent=root_agent)
        print(f"  agent engine: {AGENT_ENGINE}")
        if s.scenario != "refund_over_charge":
            print("  NOTE: deployment scenario is not refund_over_charge — the money "
                  "bug may not appear (invariant would be a truthful green).")
    else:
        print(f"unknown mode {mode}", file=sys.stderr)
        return 5

    # 3) Create the managed run — THIS is what populates the Console tab.
    print(f"\ncreating evaluation run '{run_name}' -> {dest}")
    created = client.evals.create_evaluation_run(
        dataset=dataset,
        dest=dest,
        metrics=metrics,
        display_name=run_name,
        labels=labels,
        config={"allow_cross_region_model": True},
        **kwargs,
    )
    name = getattr(created, "name", None)
    rid = name.split("/")[-1] if name else run_name
    print(f"created: {name}")
    print("Console: Agent Platform > Agents > Deployments > financial-support-agent "
          "> Dashboard > Evaluation > Experiments")
    print(f"  run id: {rid}  (labeled to engine {_agent_engine_id(AGENT_ENGINE)})")

    # 4) Poll to completion so we can print the scoreboard here too.
    waited = 0
    while waited < poll_seconds:
        run_obj = client.evals.get_evaluation_run(name=name)
        state = str(getattr(run_obj, "state", None))
        print(f"  [{waited}s] state={state}")
        up = state.upper()
        if up.endswith(("SUCCEEDED", "COMPLETED", "FAILED", "ERROR", "CANCELLED")):
            if "FAIL" in up or "ERROR" in up or "CANCEL" in up:
                print(f"  run ended: {state}")
                return 1
            _scoreboard(run_obj)
            return 0
        time.sleep(20)
        waited += 20
    print(f"\nstill running after {poll_seconds}s — check the Console tab (run id {rid}).")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create a managed Evaluation Run (Console).")
    p.add_argument("--mode", choices=["static", "agent"], default="static")
    p.add_argument("--poll", type=int, default=900)
    a = p.parse_args(argv)
    return run(a.mode, a.poll)


if __name__ == "__main__":
    raise SystemExit(main())
