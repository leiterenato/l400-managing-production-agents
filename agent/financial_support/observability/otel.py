"""OpenTelemetry substrate.

In the real demo, OTel is configured by *the runtime*, not by us:

    uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud

That exports `gen_ai.*` spans to Cloud Trace, which is the same substrate the
Evaluation Service reads — the literal "seam" of Case 1. See
``deploy/opentelemetry.env`` for the full variable set.

Who owns the tracer provider (and why it matters)
-------------------------------------------------
The provider's OTel **Resource** is what scopes spans to a deployment. On Agent
Runtime (Agent Engine) the platform installs a provider whose Resource carries
``service.name=<engine id>`` and
``cloud.resource_id=//aiplatform.../reasoningEngines/<engine id>`` — and the
console's agent-scoped **Traces** tab filters on exactly those. ``adk web`` /
``adk api_server`` install their own provider too.

:func:`init_telemetry` here is a light helper for *local* runs (a bare
``python -m`` that drives the agent through a Runner and wants console spans).
It must **never** win a race against the runtime: if it installs a provider
first, its bare ``service.name="financial-support-agent"`` Resource shadows the
canonical one and the agent-scoped Traces tab silently goes empty. Two guards
enforce that: it no-ops (a) under a managed runtime, and (b) if a real provider
is already installed. It is NOT auto-called at import — see ``agent.py``.
"""

from __future__ import annotations

import os

from ..config import get_settings

_initialised = False


def _running_on_managed_runtime() -> bool:
    """True when a runtime (Agent Engine / Cloud Run) owns telemetry setup.

    On Agent Runtime the container sets ``GOOGLE_CLOUD_AGENT_ENGINE_*`` and a
    ``K_SERVICE=reasoning-engine-<id>`` (Cloud Run underneath). In any of these
    cases the platform installs the canonical provider itself, so the local
    helper must stay out of the way.
    """
    if os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        return True
    if os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY"):
        return True
    if os.environ.get("K_SERVICE", "").startswith("reasoning-engine"):
        return True
    return False


def _has_real_provider() -> bool:
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
    except Exception:
        return False
    provider = trace.get_tracer_provider()
    return isinstance(provider, TracerProvider)


def init_telemetry() -> None:
    """Install a local tracer provider if telemetry is on and none exists.

    No-op under a managed runtime (the platform owns the canonical provider) or
    if a real provider is already installed.
    """

    global _initialised
    if _initialised:
        return
    _initialised = True

    settings = get_settings()
    if not settings.telemetry_enabled:
        return
    if _running_on_managed_runtime():
        return  # Agent Engine / Cloud Run installs the canonical provider.
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
