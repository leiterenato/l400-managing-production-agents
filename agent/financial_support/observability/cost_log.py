"""The durable side of the cost seam — cost per call as Cloud Logging entries.

Mirror of :mod:`financial_support.observability.verdict_log`, but for Case 2
cost. :func:`financial_support.callbacks.resilience.record_cost` annotates the
OTel span with ``gen_ai.cost.usd``; this module mirrors the same number to a
structured ``LogEntry`` so a Cloud Logging -> BigQuery sink (GA) lands it in a
per-tenant cost table. The ``jsonPayload`` shape matches
``evals/queries/cost_spans_schema.json`` and ``evals/queries/cost_by_tenant.sql``
(``jsonPayload.project_id``, ``jsonPayload.cost_usd``, ...).

Everything degrades to a no-op: emission is off unless ``COST_AUDIT_LOG`` is set,
the Logging client is imported lazily, and every exception is swallowed — cost
telemetry must never break a model call. So pytest / offline paths are clean.

Tenant attribution (user / project / org) is a label hierarchy. In a real deploy
it comes from request labels; here it is read from the environment (``COST_ORG_ID``
etc.) so a deployed instance can tag its own tenant, while the historical corpus
is seeded synthetically by ``evals/cost_scale.py``.
"""

from __future__ import annotations

import os
from typing import Any

from ..config import get_settings

# Lazily-built, process-wide logger (creating a client per call is expensive).
_logger = None
_logger_failed = False


def _enabled() -> bool:
    return os.environ.get("COST_AUDIT_LOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _tenant() -> dict[str, str]:
    """The label hierarchy for cost attribution (env-provided in a real deploy)."""

    return {
        "org_id": os.environ.get("COST_ORG_ID", "org-acme"),
        "project_id": os.environ.get("COST_PROJECT_ID", "proj-support"),
        "user_id": os.environ.get("COST_USER_ID", "user-anon"),
    }


def _build_payload(
    callback_context, cost_usd: float, prompt_tokens: int, candidate_tokens: int
) -> dict[str, Any]:
    """The ``jsonPayload`` of the cost LogEntry — pure and side-effect free."""

    state = getattr(callback_context, "state", None) or {}
    payload: dict[str, Any] = {
        "model": get_settings().model,
        "tool_name": "call_llm",
        "cost_usd": float(cost_usd),
        "prompt_tokens": int(prompt_tokens),
        "candidate_tokens": int(candidate_tokens),
        "session_id": state.get("session_id") or state.get("customer_id", ""),
    }
    payload.update(_tenant())
    return payload


def _get_logger():
    """Return a cached Cloud Logging logger, or ``None`` if unavailable.

    Imported lazily so the module never pulls ``google.cloud.logging`` (or hits
    ADC) at import time — that keeps offline/pytest paths clean.
    """

    global _logger, _logger_failed
    if _logger is not None or _logger_failed:
        return _logger
    try:
        from google.cloud import logging as cloud_logging

        settings = get_settings()
        client = cloud_logging.Client(project=settings.project)
        _logger = client.logger(
            os.environ.get("COST_AUDIT_LOG_NAME", "cost_spans_live")
        )
    except Exception:  # pragma: no cover - depends on GCP env
        _logger_failed = True
        _logger = None
    return _logger


def emit_cost(
    callback_context, cost_usd: float, prompt_tokens: int, candidate_tokens: int
) -> None:
    """Emit one structured cost LogEntry. No-op unless ``COST_AUDIT_LOG`` is on."""

    if not _enabled():
        return
    logger = _get_logger()
    if logger is None:
        return
    try:
        logger.log_struct(
            _build_payload(callback_context, cost_usd, prompt_tokens, candidate_tokens),
            severity="INFO",
        )
    except Exception:  # pragma: no cover - depends on GCP env
        pass
