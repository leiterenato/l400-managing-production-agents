"""Drive the REAL agent against Vertex and export spans to Cloud Trace.

This is the reusable **rehearsal driver**. It uses the *same* telemetry setup
ADK's ``adk web --otel_to_cloud`` uses (``google.adk.telemetry``), so the spans
it produces are identical to the on-stage Console view — but it is scriptable,
parametrized, and verifiable.

Use it to:
  * generate the Slide 2 trace (a refund with the invariant verdict on the span),
  * seed runs for later phases (S4), and
  * re-stage the demo deterministically, as many times as you like.

    # default: the $500-on-$50 money bug, with cloud export + trace verification
    uv run python -m scripts.live_drive

    uv run python -m scripts.live_drive --scenario healthy
    uv run python -m scripts.live_drive --scenario refund_over_charge \
        --prompt "Refund charge TXN-1001 — give me $500." --turns 1
    uv run python -m scripts.live_drive --no-cloud     # run the agent, skip export
    uv run python -m scripts.live_drive --no-verify    # export, skip the API check

Requires GCP credentials (ADC) and MODEL/PROJECT/LOCATION in the environment or
``agent/.env`` (auto-loaded).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from typing import Any, Optional

# Ensure the project root is importable when run as a script.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


# --- .env loading ---------------------------------------------------------
def _load_env() -> None:
    """Load agent/.env into os.environ (adk does this for us; scripts don't)."""

    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv  # ADK dependency; use it if present.

        load_dotenv(path)
        return
    except Exception:
        pass
    # Minimal fallback parser.
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())


# --- Telemetry (identical to `adk web --otel_to_cloud`) -------------------
def _make_trace_id_catcher():
    """A span processor (subclass of the SDK base) that records the root span's
    trace id. Subclassing SpanProcessor gives us the internal ``_on_ending``
    hook the SDK's multi-processor expects.
    """

    from opentelemetry.sdk.trace import SpanProcessor

    class _TraceIdCatcher(SpanProcessor):
        def __init__(self) -> None:
            self.root_trace_id: Optional[int] = None

        def on_start(self, span: Any, parent_context: Any = None) -> None:
            if self.root_trace_id is None and getattr(span, "parent", None) is None:
                self.root_trace_id = span.get_span_context().trace_id

    return _TraceIdCatcher()


def _setup_cloud_telemetry():
    """Install ADK's GCP OTel exporters, exactly as the CLI does under
    ``--otel_to_cloud``. Must be called BEFORE importing the agent so the local
    ``init_telemetry`` sees a provider already installed and stays out of the way.
    """

    import google.auth
    from opentelemetry import trace

    from google.adk.telemetry.google_cloud import (
        get_gcp_exporters,
        get_gcp_resource,
    )
    from google.adk.telemetry.setup import maybe_set_otel_providers

    credentials, project_id = google.auth.default()
    hooks = get_gcp_exporters(
        enable_cloud_tracing=True,
        enable_cloud_metrics=False,
        # Cloud logging is a Fase 4 concern (the Logging->BQ sink for S4); it
        # pulls a separate exporter dep. S2 only needs traces.
        enable_cloud_logging=False,
        google_auth=(credentials, project_id),
    )
    maybe_set_otel_providers(
        otel_hooks_to_setup=[hooks],
        otel_resource=get_gcp_resource(project_id),
    )

    # Attach our catcher to whatever provider is now active.
    catcher = _make_trace_id_catcher()
    provider = trace.get_tracer_provider()
    if hasattr(provider, "add_span_processor"):
        provider.add_span_processor(catcher)  # type: ignore[arg-type]
    return catcher


# --- Driving the agent ----------------------------------------------------
async def _run_turns(
    root_agent: Any, prompt: str, customer_id: str, user_id: str
) -> dict[str, Any]:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    app_name = "financial_support"
    runner = InMemoryRunner(agent=root_agent, app_name=app_name)
    session = await runner.session_service.create_session(
        app_name=app_name, user_id=user_id, state={"customer_id": customer_id}
    )

    message = types.Content(role="user", parts=[types.Part(text=prompt)])
    tool_calls: list[str] = []
    final_text = ""
    async for event in runner.run_async(
        user_id=user_id, session_id=session.id, new_message=message
    ):
        for call in event.get_function_calls() or []:
            tool_calls.append(call.name)
        if event.is_final_response() and event.content and event.content.parts:
            final_text = "".join(p.text or "" for p in event.content.parts)

    # Pull the invariant verdicts the seam recorded on session state.
    final_session = await runner.session_service.get_session(
        app_name=app_name, user_id=user_id, session_id=session.id
    )
    violations = (final_session.state or {}).get("invariant_violations", [])
    return {
        "tool_calls": tool_calls,
        "final_text": final_text,
        "violations": violations,
    }


# --- Cloud Trace verification --------------------------------------------
def _verify_trace(
    project: str, trace_id_hex: str, attempts: int = 14, interval: int = 15
) -> dict[str, Any]:
    """Poll the Cloud Trace v1 API for the trace and summarize its spans.

    Cloud Trace ingest lag is ~1-2 min, so we poll patiently (default up to
    ~3.5 min) and return as soon as the trace is queryable.
    """

    import google.auth
    from google.auth.transport.requests import AuthorizedSession

    credentials, _ = google.auth.default()
    session = AuthorizedSession(credentials)
    url = (
        f"https://cloudtrace.googleapis.com/v1/projects/{project}"
        f"/traces/{trace_id_hex}"
    )
    print("verifying trace in Cloud Trace (ingest lag ~1-2 min)", end="", flush=True)
    for i in range(attempts):
        resp = session.get(url, timeout=20)
        if resp.status_code == 200:
            print()  # close the progress dots line
            data = resp.json()
            spans = data.get("spans", [])
            names = [s.get("name", "") for s in spans]
            labels: dict[str, str] = {}
            for s in spans:
                labels.update(s.get("labels", {}) or {})
            invariant_labels = {
                k: v for k, v in labels.items() if k.startswith("eval.invariant.")
            }
            return {
                "found": True,
                "span_count": len(spans),
                "span_names": names,
                "invariant_labels": invariant_labels,
            }
        print(".", end="", flush=True)
        time.sleep(interval)
    print()
    return {"found": False}


# --- CLI ------------------------------------------------------------------
def drive(
    scenario: str,
    prompt: str,
    *,
    customer_id: str = "CUST-001",
    user_id: str = "rehearsal-user",
    cloud: bool = True,
    verify: bool = True,
) -> dict[str, Any]:
    """Drive one rehearsal run. Returns a result dict (also printed by main)."""

    _load_env()
    os.environ["SCENARIO"] = scenario

    catcher: Optional[_TraceIdCatcher] = None
    if cloud:
        # Cloud telemetry FIRST, then import the agent (order matters).
        catcher = _setup_cloud_telemetry()

    from financial_support.agent import build_root_agent
    from financial_support.config import reload_settings

    settings = reload_settings()
    root_agent = build_root_agent()

    result = asyncio.run(_run_turns(root_agent, prompt, customer_id, user_id))

    # Flush spans so they reach Cloud Trace before we verify / exit.
    if cloud:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()

    trace_id_hex = None
    if catcher and catcher.root_trace_id is not None:
        trace_id_hex = format(catcher.root_trace_id, "032x")
    result["trace_id"] = trace_id_hex
    result["project"] = settings.project
    result["model"] = settings.model

    if cloud and verify and trace_id_hex and settings.project:
        result["trace"] = _verify_trace(settings.project, trace_id_hex)

    return result


def _print(result: dict[str, Any]) -> None:
    print(f"\n=== live_drive: scenario={os.environ.get('SCENARIO')} "
          f"model={result.get('model')} ===")
    print(f"tool calls    : {' -> '.join(result['tool_calls']) or '(none)'}")
    print(f"final response: {result['final_text'][:200]}")
    viol = result.get("violations") or []
    if viol:
        print("INVARIANT VIOLATIONS (the eval catches these):")
        for v in viol:
            print(f"  - {v.get('name')}: {v.get('detail')}")
    else:
        print("invariant     : no violations recorded on session state")

    tid = result.get("trace_id")
    proj = result.get("project")
    if tid:
        print(f"\ntrace id      : {tid}")
        print(
            "Cloud Trace   : "
            f"https://console.cloud.google.com/traces/list?project={proj}"
            f"&tid={tid}"
        )
    t = result.get("trace")
    if t:
        if t.get("found"):
            print(f"verified      : {t['span_count']} spans in Cloud Trace")
            print(f"  span names  : {t['span_names']}")
            print(f"  invariant   : {t['invariant_labels'] or '(none on spans)'}")
        else:
            print("verified      : trace not visible via API yet "
                  "(ingest latency — check the Console link above)")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", default="refund_over_charge")
    parser.add_argument(
        "--prompt",
        default="I'd like a refund for my monthly subscription, charge TXN-1001.",
    )
    parser.add_argument("--customer", default="CUST-001")
    parser.add_argument("--user-id", default="rehearsal-user")
    parser.add_argument("--turns", type=int, default=1, help="(reserved; 1 for now)")
    parser.add_argument("--no-cloud", action="store_true", help="run without export")
    parser.add_argument("--no-verify", action="store_true", help="skip API check")
    args = parser.parse_args(argv)

    result = drive(
        args.scenario,
        args.prompt,
        customer_id=args.customer,
        user_id=args.user_id,
        cloud=not args.no_cloud,
        verify=not args.no_verify,
    )
    _print(result)
    # Non-zero exit only if the over-charge scenario ran but the seam did NOT
    # flag it (a real regression) — other scenarios legitimately have no
    # violations, so they must exit 0. Useful in CI / rehearsal smoke checks.
    if args.scenario == "refund_over_charge" and not result.get("violations"):
        print("\nEXPECTED an invariant violation under refund_over_charge — none "
              "recorded. This is a regression.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
