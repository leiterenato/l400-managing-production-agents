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

    # enable_tracing=True -> OTel spans to Cloud Trace (the same seam as local).
    app = reasoning_engines.AdkApp(agent=root_agent, enable_tracing=True)

    remote = agent_engines.create(
        agent_engine=app,
        display_name="financial-support-agent",
        description="L400 reference agent (Case 1). Managed runtime for the "
        "S4 flywheel: production traces feed the online monitor.",
        requirements=REQUIREMENTS,
        # Keep the demo scoped to Case 1 in production too.
        env_vars={"CASE": os.environ.get("CASE", "1")},
    )

    print("Deployed to Agent Runtime (Agent Engine).")
    print(f"  resource: {remote.resource_name}")
    print("  Traces -> Cloud Trace; the Online Monitor samples them (S4).")
    return 0


if __name__ == "__main__":
    raise SystemExit(deploy())
