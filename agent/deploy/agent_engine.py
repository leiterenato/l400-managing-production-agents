"""Deploy the agent to Agent Runtime (Agent Engine) — OPTIONAL, guarded.

Agent Runtime (API resource ``ReasoningEngine``) is the managed hosting that
deploys/scales the agent in production. Its observability is the *same* substrate
you already use locally — Cloud Trace (OpenTelemetry) + Cloud Monitoring + Cloud
Logging — so the "seam" (spans the eval reads) is identical. What it adds is a
real "production": the honest home for the S4 flywheel, where the Online Monitor
samples live traces from a *deployed* agent.

IMPORTANT — read before using in the talk
------------------------------------------
* Do NOT demo the deploy live (cold start / failure surface). Pre-deploy and show
  the Console. The Case 1 demo stays in VSCode + Console (locked decision).
* Agent Runtime gives you the observability *surfaces* and operational telemetry
  — NOT eval/quality metrics and NOT cost (cost is not captured; token is
  aggregated). The invariant metrics are YOUR instrumentation; that is the whole
  point of EDD. Don't sell runtime as "free quality metrics".
* Verify the GA status of the base runtime before anchoring on it. Much of the
  surrounding surface (Agent identity, Agent Gateway, Quality & evaluation,
  Threat Detection) is Preview.

Usage
-----
    export GOOGLE_CLOUD_PROJECT=... GOOGLE_CLOUD_LOCATION=us-central1
    export GOOGLE_CLOUD_STAGING_BUCKET=gs://your-bucket
    DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
"""

from __future__ import annotations

import os
import sys

# Make the project importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Requirements the deployed container needs (kept in sync with pyproject).
REQUIREMENTS = [
    "google-adk[a2a]>=2.3.0",
    "google-cloud-aiplatform[agent-engines]>=1.159.0",
    # The seam emits verdict LogEntries via the Cloud Logging client (S4 sink).
    "google-cloud-logging>=3.11.0",
]


def deploy() -> int:
    try:
        import vertexai
        from vertexai import agent_engines
        from vertexai.preview import reasoning_engines
    except Exception as exc:  # pragma: no cover
        print(
            "Agent Engine deploy needs google-cloud-aiplatform[agent-engines].\n"
            f"  import failed: {exc}",
            file=sys.stderr,
        )
        return 2

    if os.environ.get("DEPLOY_CONFIRM") != "1":
        print(
            "Refusing to deploy without DEPLOY_CONFIRM=1.\n"
            "This creates a managed Agent Engine in your project (billable).\n"
            "  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py",
            file=sys.stderr,
        )
        return 3

    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    staging_bucket = os.environ.get("GOOGLE_CLOUD_STAGING_BUCKET")
    if not project or not staging_bucket:
        print(
            "Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_STAGING_BUCKET "
            "(gs://...) before deploying.",
            file=sys.stderr,
        )
        return 4

    vertexai.init(project=project, location=location, staging_bucket=staging_bucket)

    from financial_support import root_agent

    # Tracing config below follows Google's Agent Runtime tracing guide. Do NOT
    # use the deprecated `enable_tracing` flag (it forces
    # ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true -> oversized span attributes).
    app = reasoning_engines.AdkApp(agent=root_agent)

    common = dict(
        display_name="financial-support-agent",
        description="L400 reference agent (Case 1). Managed runtime for the "
        "S4 flywheel: production traces feed the online monitor.",
        requirements=REQUIREMENTS,
        # Ship our source: the pickled agent references the local
        # `financial_support` package, so the container needs its code too
        # (otherwise it starts up with "No module named 'financial_support'").
        extra_packages=["financial_support"],
        env_vars={
            # Keep the demo scoped to Case 1 in production too.
            "CASE": os.environ.get("CASE", "1"),
            # Fault profile the DEPLOYED agent runs under. Default healthy; arm
            # with SCENARIO=refund_over_charge so a real refund over-pays ($500
            # on a $50 charge) and the invariant goes RED on the agent tab.
            # Revert to healthy after the demo.
            "SCENARIO": os.environ.get("SCENARIO", "healthy"),
            # S4 flywheel: the deployed agent emits verdict LogEntries so the
            # Cloud Logging -> BigQuery sink builds the durable corpus. Off by
            # default in code; turned on here for the "production" origin.
            "EVAL_AUDIT_LOG": os.environ.get("EVAL_AUDIT_LOG", "true"),
            "EVAL_AUDIT_LOG_NAME": os.environ.get(
                "EVAL_AUDIT_LOG_NAME", "agent_spans_live"
            ),
            # Documented ADK tracing env vars (the replacement for enable_tracing).
            # These three are all that's needed: the platform's own telemetry
            # set_up() then builds the CANONICAL OTel Resource
            # (service.name=<engine id> + cloud.resource_id=.../reasoningEngines/
            # <engine id>), which is what scopes spans to the agent-scoped
            # console Traces / Topology / Sessions tabs.
            "GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY": "true",
            "OTEL_SEMCONV_STABILITY_OPT_IN": "gen_ai_latest_experimental",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "EVENT_ONLY",
            "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS": "false",
            # NOTE: do NOT set OTEL_RESOURCE_ATTRIBUTES=gcp.project_id here. It is
            # unnecessary — the template resolves the project number to the
            # project id via the Resource Manager API at set_up time (verified by
            # probe: gcp.project_id lands as the id, spans export 200). It is also
            # a trap: an earlier attempt added it to fix a 400 that was really
            # caused by our own financial_support.observability.init_telemetry()
            # racing ahead of the platform at import and pinning a bare
            # service.name="financial-support-agent" Resource. That is now fixed
            # in the agent (init_telemetry no longer auto-runs), so the canonical
            # resource wins and the agent-scoped tabs populate.
        },
    )

    # Update an existing engine in place (preserves the engine id the demo and
    # console tabs reference) when UPDATE_RESOURCE is set; otherwise create new.
    update_resource = os.environ.get("UPDATE_RESOURCE")
    if update_resource:
        remote = agent_engines.update(
            update_resource, agent_engine=app, **common
        )
        print("Updated Agent Runtime (Agent Engine) in place.")
    else:
        remote = agent_engines.create(agent_engine=app, **common)
        print("Deployed to Agent Runtime (Agent Engine).")
    print(f"  resource: {remote.resource_name}")
    print("  Traces -> Cloud Trace; the Online Monitor samples them (S4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(deploy())
