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

Three modes:

  * ``--mode static`` — score a fixed, deterministic 2-case dataset that already
    contains the $500-on-$50 over-refund. No agent is run. The green invariant
    (refund_within_charge) goes RED while the tone judge / managed baselines pass
    — "the green score lies", now visible in the Console.

  * ``--mode dataset`` — score the VERSIONED eval set (evals/data/eval_cases.json),
    the SAME 5 cases the Camada-1 pre-submit gate checks. Deterministic (records
    the flows, no live agent). Contains the adversarial over-refund, so the score
    gate blocks — the managed cloud eval and the offline gate never drift.

  * ``--mode agent`` — run the DEPLOYED agent (Agent Engine) over the EDD prompts,
    then score. Needs the deployment armed with SCENARIO=refund_over_charge for
    the money bug to appear; otherwise the invariant is a (truthful) green.

All modes end in a SCORE GATE (Camada 2): the process exits non-zero when the
``refund_within_charge`` AVERAGE (the mean Vertex AI emits) or MINIMUM drops
below 1.0, so a Cloud Build step turns a quality regression into a red build
(post-merge). The evaluationRun resource name + a Console URL are printed for the
build to link.

Guarded: needs ``EVAL_LIVE_CONFIRM=1`` (calls Preview APIs against your project).

    EVAL_LIVE_CONFIRM=1 uv run python -m evals.live_run --mode static
    EVAL_LIVE_CONFIRM=1 uv run python -m evals.live_run --mode dataset
    EVAL_LIVE_CONFIRM=1 uv run python -m evals.live_run --mode agent
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import uuid

# Deployed agent engine (financial-support-agent). Required — no default, so a
# missing value fails loudly instead of targeting another project's engine.
#   export AGENT_ENGINE=projects/<num>/locations/<loc>/reasoningEngines/<id>
AGENT_ENGINE = os.environ.get("AGENT_ENGINE", "")
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


def _dataset_from_cases(types):
    """EvaluationDataset built from the VERSIONED eval set (evals/data/eval_cases.json).

    Records each seed case's flow (real mock backends under the case's own
    scenario) and converts the tool calls into the platform ``agent_data`` shape.
    This is the SAME 5 cases the Camada-1 offline gate checks, so the managed
    cloud run scores exactly what the pre-submit gate does — no drift between the
    two layers. The set includes the adversarial over-refund, so
    refund_within_charge MEAN < 1.0 and the score gate blocks (by design: that is
    the managed gate demonstrating a regression, deterministically, without
    running the live agent).
    """
    from .record import record_dataset

    recorded = record_dataset()
    cases = []
    for inst in recorded:
        turn = inst["agent_eval_data"]["turns"][0]
        tool_calls = turn.get("tool_calls", [])
        reply = turn.get("final_response", "")
        prompt = inst.get("prompt", "")
        cases.append(
            types.EvalCase(
                eval_case_id=inst["id"],
                prompt={"role": "user", "parts": [{"text": prompt}]},
                responses=[
                    types.ResponseCandidate(
                        response={"role": "model", "parts": [{"text": reply}]}
                    )
                ],
                agent_data=_agent_data(tool_calls, reply),
            )
        )
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


# --- Score gate (Camada 2) -------------------------------------------------
# The gating invariant + floor. refund_within_charge is binary per case, so an
# AVERAGE below 1.0 (equivalently, a MINIMUM of 0) means at least one case
# over-refunded -> block the build.
_GATE_METRIC = "refund_within_charge"
_GATE_FLOOR = 1.0
# The mean the Vertex AI Evaluation Service emits is keyed "AVERAGE" (NOT "MEAN";
# verified against the SDK's own _get_aggregated_metrics and real run dumps). We
# keep "MEAN" only as a defensive secondary. We NEVER read "MEDIAN": the median
# of a binary 0/1 invariant is 1.0 while a MINORITY of cases fail, so a MEDIAN
# gate would wave the money bug straight through — the exact false-green Case 1
# exists to expose.
_MEAN_AGG_KEYS = ("AVERAGE", "MEAN")


def _scoreboard(run) -> dict:
    """Print AVERAGE (+ min / stdev) per metric; return ``{metric: {agg: value}}``.

    The managed run keys each entry ``<candidate>/<metric>/<AGG>`` (e.g.
    ``Candidate 1/refund_within_charge/AVERAGE``). The metric name is the segment
    immediately before the aggregation suffix, so group by ``parts[-2]``.
    """
    d = run.model_dump(exclude_none=True) if hasattr(run, "model_dump") else {}
    sm = ((d.get("evaluation_run_results") or {}).get("summary_metrics") or {}).get("metrics") or {}
    from collections import defaultdict
    agg = defaultdict(dict)
    for k, v in sm.items():
        parts = k.split("/")
        metric = parts[-2] if len(parts) >= 2 else k
        agg[metric][parts[-1]] = v
    print("\n=== Evaluation summary (managed run) ===")
    for metric, aggs in sorted(agg.items()):
        # Headline = AVERAGE (the true mean). NEVER MEDIAN (see _MEAN_AGG_KEYS).
        avg = next((aggs[k] for k in _MEAN_AGG_KEYS if k in aggs), None)
        avg_s = round(avg, 3) if isinstance(avg, (int, float)) else avg
        print(f"  {metric:<26} average={avg_s}  min={aggs.get('MINIMUM')}  "
              f"stdev={aggs.get('STANDARD_DEVIATION')}")
    return dict(agg)


def _gate_row(agg: dict) -> dict:
    """Find the gating metric's agg row, tolerant of a key prefix.

    ``_scoreboard`` keys agg by the metric name, but match defensively on any key
    whose last path segment equals it — so a format surprise degrades to
    fail-closed (empty row), never a false pass.
    """
    if _GATE_METRIC in agg:
        return agg[_GATE_METRIC] or {}
    for k, row in agg.items():
        if k == _GATE_METRIC or str(k).split("/")[-1] == _GATE_METRIC:
            return row or {}
    return {}


def _apply_score_gate(agg: dict) -> int:
    """Turn the managed run's score into an exit code (the Camada-2 gate).

    Blocks when the AVERAGE (the mean Vertex actually emits) OR the MINIMUM dips
    below the floor. NEVER uses MEDIAN (a binary invariant's median hides a
    failing minority — a false green). Fails CLOSED when neither a mean nor a
    minimum is present (a metric that could not aggregate is not evidence of
    correctness).
    """
    row = _gate_row(agg)
    mean = next(
        (row[k] for k in _MEAN_AGG_KEYS if isinstance(row.get(k), (int, float))), None
    )
    minimum = row.get("MINIMUM")
    signals = [v for v in (mean, minimum) if isinstance(v, (int, float))]
    if not signals:
        print(
            f"\nGATE BLOCK: {_GATE_METRIC} produced no AVERAGE/MINIMUM (metric "
            "errored on all cases?) — cannot confirm quality, failing closed.",
            file=sys.stderr,
        )
        return 1
    if min(signals) < _GATE_FLOOR:
        print(
            f"\nGATE BLOCK: {_GATE_METRIC} average={mean} min={minimum} < "
            f"{_GATE_FLOOR:.1f} — an invariant regressed in the managed eval. "
            "Red build.",
            file=sys.stderr,
        )
        return 1
    print(f"\nGATE OK: {_GATE_METRIC} average={mean} min={minimum} >= {_GATE_FLOOR:.1f}.")
    return 0


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

    if not AGENT_ENGINE:
        raise SystemExit(
            "Set AGENT_ENGINE to your deployed engine before running:\n"
            "  export AGENT_ENGINE=projects/<num>/locations/<loc>/"
            "reasoningEngines/<id>"
        )

    run_name = f"l400-case1-{mode}-{uuid.uuid4().hex[:8]}"
    dest = f"{bucket}/eval-runs/{run_name}"
    # Agent-scoped label so the run shows in the agent's Evaluation > Experiments tab.
    labels = {_AGENT_LABEL: _agent_engine_id(AGENT_ENGINE)}

    # 2) Dataset + (for agent mode) the deployed engine.
    kwargs = {}
    if mode == "static":
        dataset = _static_dataset(types)
    elif mode == "dataset":
        dataset = _dataset_from_cases(types)
        print("  dataset: evals/data/eval_cases.json (same 5 cases as the "
              "Camada-1 gate; contains the adversarial over-refund)")
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
    # Emit the resource name + a clickable Console URL BEFORE polling, so Cloud
    # Build always links the result even if the poll later times out. These runs
    # land on the Vertex AI evaluation surface (see module docstring).
    console_url = (
        "https://console.cloud.google.com/vertex-ai/evaluation/eval-runs"
        f"?project={project}"
    )
    print(f"created: {name}")
    print(f"  resource name : {name}")
    print(f"  run id        : {rid}  (labeled to engine {_agent_engine_id(AGENT_ENGINE)})")
    print(f"  Console       : {console_url}")
    print("  (Vertex AI > Evaluation. NOTE: managed runs do NOT show in the "
          "Agent Platform agent-scoped Experiments tab — that is a separate "
          "backend; see module docstring.)")

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
            # 5) The Camada-2 gate: score floor on the gating invariant.
            agg = _scoreboard(run_obj)
            return _apply_score_gate(agg)
        time.sleep(20)
        waited += 20
    # Timed out before the run finished. We CANNOT confirm the score, so we do
    # not claim a pass — but the managed run genuinely can take >15 min, so we
    # exit 0 (non-blocking) and warn loudly rather than red-building on latency.
    # The resource name + Console URL were printed above for follow-up.
    print(f"\nstill running after {poll_seconds}s — GATE NOT EVALUATED (timeout). "
          f"Check the Console (run id {rid}).", file=sys.stderr)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Create a managed Evaluation Run (Console).")
    p.add_argument("--mode", choices=["static", "dataset", "agent"], default="static")
    p.add_argument("--poll", type=int, default=900)
    a = p.parse_args(argv)
    return run(a.mode, a.poll)


if __name__ == "__main__":
    raise SystemExit(main())
