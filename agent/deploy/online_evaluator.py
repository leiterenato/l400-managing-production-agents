"""Camada 3 — the Online Monitor (Vertex AI ``onlineEvaluators``, REST).

The production, always-on version of the trace Experiment: a real
``OnlineEvaluator`` that samples the DEPLOYED agent's production traces (~every
10 min), scores each with the SAME invariant used at merge time, and writes the
verdicts to the agent's Evaluation (online monitors) tab. This is what turns the
demo's S4 beat — "it was green, then the API changed, then it went red" — into a
time series in the Console, with no re-running.

NOT to be confused with :mod:`evals.online_monitor`, which is the offline
BigQuery/seeded-drift analogue (a local render of a rolling pass-rate). THIS
module talks to the live platform.

Honesty for the stage:
  * Billable + continuous: **create takes the evaluator straight to state=ACTIVE**
    (it does NOT wait for :activate — verified live 2026-07-12), so it starts
    sampling/billing immediately. create/activate/suspend/delete are guarded by
    ``MONITOR_CONFIRM=1``; :activate is only for re-activating a suspended one.
  * It notifies/records; it does NOT gate. The merge gate is Cloud Build
    (Camada 1/2). This is the production sentinel, not a blocker.
  * The green->red demo is PRE-RUN (the sampling loop is ~10 min; you cannot do it
    live). See the sequence at the bottom of this docstring.

VERIFIED LIVE 2026-07-12 (created a real evaluator -> ACTIVE, then deleted):
  * body shape: OnlineEvaluator{displayName, agentResource, config.randomSampling
    .percentage:int, cloudObservability{traceScope, openTelemetry.semconvVersion},
    metricSources[]}. metricSources item = {metric:{...inline...}} OR
    {metricResourceName:"..."}.
  * ⚠️ ``cloudObservability.traceScope`` is REQUIRED: without it create returns an
    opaque HTTP 400 (no field detail) even on an otherwise-minimal valid body.
    ``openTelemetry.semconvVersion`` alone does NOT satisfy it. ``traceScope: {}``
    (empty = no filter) works. semconvVersion "1.39.0" accepted.
  * Safety predefined metricSpecName = "safety_v1" (confirmed).
  * ⚠️ IAM PREREQ: the evaluator's service identity needs
    ``observability.views.access`` on the project's trace view
    (``.../buckets/_Trace/datasets/Spans/views/_AllSpans``); otherwise state=FAILED
    "Permission denied when querying traces" (may be transient right after create).
  * ⚠️ The custom metric must carry ``metadata.scoreRange`` or the evaluator lands
    in state=WARNING "incomplete score range" and skips it (see build_body note).
  * create + activate + delete are Long-Running Operations (poll to done).

Usage
-----
    # Free, no side effects — print the exact request body and exit:
    uv run python deploy/online_evaluator.py body

    # Create (inactive; billing only starts on activate):
    MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py create

    uv run python deploy/online_evaluator.py get <id>
    uv run python deploy/online_evaluator.py list
    MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py activate <id>
    MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py suspend <id>
    MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py delete  <id>

Green->red demo (pre-run, ~30-40 min end to end)
------------------------------------------------
  0. One-time prereqs: grant the evaluator identity observability.views.access on
     the _Trace/_AllSpans view (see IAM PREREQ above), and give the custom metric
     a metadata.scoreRange (see build_body note) so it is not skipped.
  1. Ensure the engine is HEALTHY:  UPDATE_RESOURCE=<eng> SCENARIO=healthy
     DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
  2. `create` the monitor (it goes ACTIVE on create — no separate activate needed).
  3. Drive healthy refunds:  uv run python -m scripts.drive_engine --n 8
     wait 1-2 sampling cycles -> GREEN points on the Evaluation tab.
  4. Flip to armed ("the API changed"):  UPDATE_RESOURCE=<eng>
     SCENARIO=refund_over_charge DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
  5. Drive again: uv run python -m scripts.drive_engine --n 8
     wait 1-2 cycles -> RED points. Screenshot the platform (green -> drop to red).
  6. `delete` (or `suspend`) the monitor to stop sampling/billing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# The deployed, armed engine (financial-support-agent). agentResource uses the
# project NUMBER form; the OnlineEvaluator filters traces by matching this.
# Required — no default, so this never points at another project's engine.
#   export AGENT_ENGINE=projects/<num>/locations/<loc>/reasoningEngines/<id>
AGENT_ENGINE = os.environ.get("AGENT_ENGINE", "")

# Our green invariant, registered server-side and referenced by resource name so
# the monitor scores production with the SAME rule. The metric must carry
# metadata.scoreRange{0,1,1} — the online evaluator skips one without it
# (state=WARNING). Required; register the metric first, then export its name:
#   export ONLINE_MONITOR_METRIC=projects/<num>/locations/<loc>/evaluationMetrics/<id>
CUSTOM_METRIC = os.environ.get("ONLINE_MONITOR_METRIC", "")

# The one runtime unknown (see docstring). Configurable so a validation error is
# a one-env-var flip, not a code edit.
SAFETY_METRIC_SPEC = os.environ.get("SAFETY_METRIC_SPEC", "safety_v1")
SEMCONV_VERSION = os.environ.get("SEMCONV_VERSION", "1.39.0")
SAMPLING_PERCENT = int(os.environ.get("SAMPLING_PERCENT", "100"))
DISPLAY_NAME = os.environ.get("MONITOR_DISPLAY_NAME", "financial-support-online-monitor")


def _location() -> str:
    return os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")


def _parent() -> str:
    """projects/<num>/locations/<loc> — reuse the engine's project for consistency."""

    # AGENT_ENGINE = projects/<num>/locations/<loc>/reasoningEngines/<id>
    parts = AGENT_ENGINE.split("/")
    project_num = parts[1] if len(parts) > 1 else os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    return f"projects/{project_num}/locations/{_location()}"


def _base() -> str:
    return f"https://{_location()}-aiplatform.googleapis.com/v1beta1"


def build_body() -> dict:
    """The OnlineEvaluator create body (VERIFIED live 2026-07-12 -> state=ACTIVE).

    Hard-won shape (a body missing ``cloudObservability.traceScope`` returns an
    opaque HTTP 400 "invalid argument" with no field detail — even a minimal
    otherwise-valid body). ``traceScope: {}`` (no filter = all of the agent's
    traces) is what the create validation actually requires; ``openTelemetry``
    alone does NOT satisfy it.
    """

    missing = [
        name
        for name, value in (
            ("AGENT_ENGINE", AGENT_ENGINE),
            ("ONLINE_MONITOR_METRIC", CUSTOM_METRIC),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            f"Set {' and '.join(missing)} before building the evaluator body.\n"
            "  AGENT_ENGINE=projects/<num>/locations/<loc>/reasoningEngines/<id>\n"
            "  ONLINE_MONITOR_METRIC=projects/<num>/locations/<loc>/"
            "evaluationMetrics/<id>"
        )

    return {
        "displayName": DISPLAY_NAME,
        "agentResource": AGENT_ENGINE,
        # Sample production traces; 100% for the demo so points appear fast.
        "config": {"randomSampling": {"percentage": SAMPLING_PERCENT}},
        "cloudObservability": {
            # REQUIRED to pass create validation (the field that clears the 400).
            "traceScope": {},
            # The emitter runs OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental;
            # 1.39.0 is the minimum the API accepts for that data.
            "openTelemetry": {"semconvVersion": SEMCONV_VERSION},
        },
        "metricSources": [
            # Grey managed baseline (the "wall of green" next to the red invariant).
            # "safety_v1" confirmed correct (a managed create_evaluation_run reports
            # its Safety baseline under exactly this name).
            {"metric": {"predefinedMetricSpec": {"metricSpecName": SAFETY_METRIC_SPEC}}},
            # Our green invariant, by registered resource name (no drift).
            # ⚠️ The registered metric MUST carry metadata.scoreRange {min,max} or the
            # evaluator lands in state=WARNING "incomplete score range" and skips it.
            # See _METRIC_SCORE_RANGE_NOTE below to fix the registration.
            {"metricResourceName": CUSTOM_METRIC},
        ],
    }


# How to give the custom metric a score range (fixes the WARNING above). The
# range lives in the registered metric's Metric.metadata.scoreRange; re-register
# (or PATCH) refund_within_charge with metadata like:
#     {"metric": {"customCodeExecutionSpec": {...},
#                 "metadata": {"title": "refund_within_charge",
#                              "scoreRange": {"min": 0, "max": 1, "step": 1}}}}
# For a binary invariant: min=0, max=1, step=1.
_METRIC_SCORE_RANGE_NOTE = "metadata.scoreRange {min:0,max:1,step:1}"


# --- REST plumbing --------------------------------------------------------


def _session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default()
    return AuthorizedSession(credentials)


def _confirm() -> bool:
    if os.environ.get("MONITOR_CONFIRM") != "1":
        print(
            "Refusing without MONITOR_CONFIRM=1 — an OnlineEvaluator is billable and\n"
            "continuous once ACTIVE (it samples production traces on a timer).\n"
            "  MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py <cmd>",
            file=sys.stderr,
        )
        return False
    return True


def _full_name(id_or_name: str) -> str:
    """Accept a bare id or a full resource name; return the full resource name."""

    if id_or_name.startswith("projects/"):
        return id_or_name
    return f"{_parent()}/onlineEvaluators/{id_or_name}"


def _lro_wait(session, op: dict, poll_seconds: int = 180) -> dict:
    """Poll a Long-Running Operation to completion; return its final JSON."""

    name = op.get("name")
    if not name:
        return op  # not an LRO (already the resource)
    waited = 0
    while waited < poll_seconds:
        if op.get("done"):
            if op.get("error"):
                print(f"  LRO error: {op['error']}", file=sys.stderr)
            return op
        time.sleep(5)
        waited += 5
        resp = session.get(f"{_base()}/{name}", timeout=30)
        op = resp.json()
        print(f"  [{waited}s] op done={op.get('done', False)}")
    print(f"  LRO still running after {poll_seconds}s (name={name})", file=sys.stderr)
    return op


# --- Commands -------------------------------------------------------------


def cmd_body(_args) -> int:
    print(json.dumps(build_body(), indent=2))
    print(f"\nPOST {_base()}/{_parent()}/onlineEvaluators", file=sys.stderr)
    return 0


def cmd_create(_args) -> int:
    if not _confirm():
        return 3
    session = _session()
    url = f"{_base()}/{_parent()}/onlineEvaluators"
    body = build_body()
    print(f"POST {url}")
    print(json.dumps(body, indent=2))
    resp = session.post(url, json=body, timeout=60)
    if resp.status_code >= 400:
        # Surface the server's validation verbatim — this is how the SAFETY_METRIC_SPEC
        # unknown gets resolved (read the error, flip the env var, re-run).
        print(f"\nHTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
        return 1
    op = resp.json()
    op = _lro_wait(session, op)
    ev = op.get("response", op)
    name = ev.get("name")
    state = ev.get("state")
    print(f"\ncreated: {name}")
    print(f"  state: {state}  (create goes straight to ACTIVE — it is already "
          "sampling/billing; use `suspend`/`delete` to stop)")
    details = ev.get("stateDetails")
    if details:
        # Surfaces the IAM (observability.views.access) / score-range warnings.
        print(f"  stateDetails: {details}")
    if name:
        print(f"  inspect: uv run python deploy/online_evaluator.py get {name.split('/')[-1]}")
        print(f"  stop:    MONITOR_CONFIRM=1 uv run python deploy/online_evaluator.py "
              f"delete {name.split('/')[-1]}")
    return 0


def cmd_get(args) -> int:
    session = _session()
    url = f"{_base()}/{_full_name(args.id)}"
    resp = session.get(url, timeout=30)
    print(f"HTTP {resp.status_code}")
    print(json.dumps(resp.json(), indent=2))
    return 0 if resp.status_code < 400 else 1


def cmd_list(_args) -> int:
    session = _session()
    url = f"{_base()}/{_parent()}/onlineEvaluators"
    resp = session.get(url, timeout=30)
    data = resp.json()
    evs = data.get("onlineEvaluators", []) if isinstance(data, dict) else []
    if not evs:
        print(f"(no onlineEvaluators in {_parent()})")
        if resp.status_code >= 400:
            print(json.dumps(data, indent=2), file=sys.stderr)
            return 1
        return 0
    for ev in evs:
        print(f"  {ev.get('name')}  state={ev.get('state')}  "
              f"display={ev.get('displayName')}")
    return 0


def _post_verb(id_: str, verb: str) -> int:
    if not _confirm():
        return 3
    session = _session()
    url = f"{_base()}/{_full_name(id_)}:{verb}"
    print(f"POST {url}")
    resp = session.post(url, json={}, timeout=60)
    if resp.status_code >= 400:
        print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
        return 1
    op = _lro_wait(session, resp.json())
    print(f"{verb}: done={op.get('done', True)} error={op.get('error')}")
    return 0 if not op.get("error") else 1


def cmd_activate(args) -> int:
    return _post_verb(args.id, "activate")


def cmd_suspend(args) -> int:
    return _post_verb(args.id, "suspend")


def cmd_delete(args) -> int:
    if not _confirm():
        return 3
    session = _session()
    url = f"{_base()}/{_full_name(args.id)}"
    print(f"DELETE {url}")
    resp = session.delete(url, timeout=60)
    if resp.status_code >= 400:
        print(f"HTTP {resp.status_code}:\n{resp.text}", file=sys.stderr)
        return 1
    op = _lro_wait(session, resp.json())
    print(f"deleted: done={op.get('done', True)} error={op.get('error')}")
    return 0 if not op.get("error") else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Vertex AI OnlineEvaluator (Camada 3).")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("body", help="print the request body (free, no side effects)")
    sub.add_parser("create", help="create the monitor (inactive; MONITOR_CONFIRM=1)")
    g = sub.add_parser("get", help="get one monitor")
    g.add_argument("id")
    sub.add_parser("list", help="list monitors in the project/location")
    for verb in ("activate", "suspend", "delete"):
        s = sub.add_parser(verb, help=f"{verb} a monitor (MONITOR_CONFIRM=1)")
        s.add_argument("id")

    args = p.parse_args(argv)
    return {
        "body": cmd_body, "create": cmd_create, "get": cmd_get, "list": cmd_list,
        "activate": cmd_activate, "suspend": cmd_suspend, "delete": cmd_delete,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
