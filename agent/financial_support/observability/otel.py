"""OpenTelemetry substrate.

In the real demo, OTel is configured by ADK itself:

    uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud

That exports `gen_ai.*` spans to Cloud Trace, which is the same substrate the
Evaluation Service reads — the literal "seam" of Case 1. See
``deploy/opentelemetry.env`` for the full variable set.

:func:`init_telemetry` here is a light, idempotent helper for *local* runs
(scripts / ``python -m``) so span attributes set by the invariant callback are
recorded even without ``adk web``. It never fights ADK's own configuration: if a
real tracer provider is already installed, it does nothing.
"""

from __future__ import annotations

import os

from ..config import get_settings

_initialised = False


def _has_real_provider() -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except Exception:
        return False
    provider = trace.get_tracer_provider()
    return isinstance(provider, TracerProvider)


def init_telemetry() -> None:
    """Install a local tracer provider if telemetry is on and none exists."""

    global _initialised
    if _initialised:
        return
    _initialised = True

    settings = get_settings()
    if not settings.telemetry_enabled:
        return
    if _has_real_provider():
        return  # ADK (or something else) already owns telemetry.

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
    except Exception:
        # SDK not present -> span enrichment degrades to no-op. Fine for tests.
        return

    resource = Resource.create({"service.name": "financial-support-agent"})
    provider = TracerProvider(resource=resource)

    # Optional: print spans (with the eval.invariant.* attributes) to the console
    # for local dev — set OTEL_CONSOLE=true. Cloud export is handled by ADK's
    # `--otel_to_cloud` in the real demo.
    if os.environ.get("OTEL_CONSOLE", "").strip().lower() in {"1", "true", "yes"}:
        try:
            from opentelemetry.sdk.trace.export import (
                BatchSpanProcessor,
                ConsoleSpanExporter,
            )

            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        except Exception:
            pass

    trace.set_tracer_provider(provider)
