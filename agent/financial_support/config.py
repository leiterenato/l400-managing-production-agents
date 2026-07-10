"""Central configuration for the financial-support agent.

Everything that changes between environments (dev / demo / CI) or between the
three L400 cases is read from the environment here, in ONE place. Tools,
callbacks and the eval harness all import :func:`get_settings` instead of
touching ``os.environ`` directly, so the demo can flip behaviour by exporting a
single variable.

Design note (extensibility for Case 2 / Case 3)
-----------------------------------------------
This module holds *app-level* settings only (model, GCP wiring, telemetry,
invariant enforcement mode, active scenario). Per-tool fault injection lives in
:mod:`financial_support.backends.faults`. Case 2 (resilience) and Case 3
(zero-trust) add new *scenario profiles* and new *enforcement flags* here
without changing any tool code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return val if val else default


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the agent configuration."""

    # --- Model / platform wiring ----------------------------------------
    model: str
    project: str | None
    location: str
    use_vertex: bool

    # --- Demo behaviour --------------------------------------------------
    # Name of the active scenario profile (see backends/faults.py). Selects a
    # bundle of fault flags so the demo is deterministic and repeatable.
    scenario: str

    # Active case (1-3). The callback registry only activates concerns whose
    # case <= this, so the Case 1 demo runs with ONLY the invariant seam on —
    # no Case 2 resilience middleware, no Case 3 identity middleware. One
    # codebase; a clean, scoped runtime per case. See callbacks/registry.py.
    case: int

    # --- Observability (substrate, always-on by default) -----------------
    telemetry_enabled: bool
    otel_to_cloud: bool

    # --- Verdict audit log (S4 flywheel: Cloud Logging -> BigQuery) ------
    # When on, the invariant seam emits a structured LogEntry per verdict; a
    # Cloud Logging -> BigQuery sink lands it in `audit_log_name`. Off by default
    # so offline/pytest never touch GCP. See observability/verdict_log.py.
    audit_log_enabled: bool
    audit_log_name: str

    # --- Invariant seam (Case 1) ----------------------------------------
    # "observe": record the violation on the span + session state but let the
    #   (wrong) tool result stand -> the eval is what catches it later. This is
    #   what powers the "the green score lies" demo: real money goes out and the
    #   offline/online eval flags it.
    # "block": the runtime callback overrides the tool response and refuses the
    #   action. Useful when demonstrating defence-in-depth.
    invariant_enforcement: str

    # --- A2A (external fraud-check agent) --------------------------------
    fraud_agent_url: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            model=_env_str("MODEL", "gemini-3.5-flash"),
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=_env_str("GOOGLE_CLOUD_LOCATION", "us-central1"),
            use_vertex=_env_bool("GOOGLE_GENAI_USE_VERTEXAI", True),
            scenario=_env_str("SCENARIO", "healthy"),
            case=int(_env_str("CASE", "1")),
            telemetry_enabled=_env_bool("TELEMETRY_ENABLED", True),
            otel_to_cloud=_env_bool("OTEL_TO_CLOUD", False),
            audit_log_enabled=_env_bool("EVAL_AUDIT_LOG", False),
            audit_log_name=_env_str("EVAL_AUDIT_LOG_NAME", "agent_spans_live"),
            invariant_enforcement=_env_str("INVARIANT_ENFORCEMENT", "observe"),
            fraud_agent_url=_env_str(
                "FRAUD_AGENT_URL", "http://localhost:8001"
            ),
        )


@lru_cache(maxsize=1)
def _cached_settings() -> Settings:
    return Settings.from_env()


def get_settings() -> Settings:
    """Return the process settings (cached).

    Call :func:`reload_settings` after mutating the environment (tests / demo
    scenario switches) to pick up changes.
    """

    return _cached_settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read the environment."""

    _cached_settings.cache_clear()
    return _cached_settings()
