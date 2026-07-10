"""The durable side of the seam — verdicts as structured Cloud Logging entries.

The invariant seam already annotates the OTel span (see
:mod:`financial_support.callbacks.telemetry`). Spans go to Cloud Trace, which
keeps *weeks* and has **no native BigQuery export**. "At scale" — the months of
drift the S4 flywheel shows — lives in BigQuery, and the honest GA path there is
Cloud **Logging**: for every money-moving / data-reading tool call the agent
emits a structured ``LogEntry`` mirroring the span's invariant verdict, and a
Cloud Logging -> BigQuery sink (GA) lands it in a table. The ``jsonPayload`` of
that entry is exactly the shape ``evals/queries/agent_spans_schema.json`` and
``evals/queries/invariant_trend.sql`` read (``jsonPayload.invariant_passed`` etc).

Design mirrors :mod:`financial_support.observability.otel` /
:mod:`financial_support.callbacks.telemetry`: **everything degrades to a no-op**.
Emission is off by default (``EVAL_AUDIT_LOG``), the Cloud Logging client is
imported lazily inside the call, and every exception is swallowed — telemetry
must never break a tool call. So plain ``pytest`` / ``run_offline`` / ``run_local``
are completely unaffected, and only the live/deployed paths write real entries.

The live log id is ``agent_spans_live`` by default (``EVAL_AUDIT_LOG_NAME``): the
Logging -> BigQuery sink names its destination table after the log id and owns
its schema, so routing live entries to a distinct id keeps them in their own
table (``agent_spans_live``) and away from the hand-seeded historical corpus
(``agent_spans``) the trend query reads.
"""

from __future__ import annotations

from typing import Any

from ..config import get_settings
from ..contract import Verdict

# The jsonPayload fields the BigQuery schema/query know about. Any of these that
# appear in a verdict's context are copied onto the payload; the rest of the
# context (e.g. fraud_decision) is dropped so the row matches the documented
# schema. All are nullable in the schema, so a missing key is fine.
_CONTEXT_KEYS = (
    "refund_amount",
    "charge_amount",
    "session_customer_id",
    "read_customer_id",
)

# Lazily-built, process-wide logger (creating a client per call is expensive).
_logger = None
_logger_failed = False


def _build_payload(tool_name: str, verdict: Verdict) -> dict[str, Any]:
    """The ``jsonPayload`` of the verdict LogEntry — pure and side-effect free.

    Mirrors the span attributes the eval reads: which tool, which invariant, and
    whether it held, plus the money/identity context the trend query needs.
    """

    payload: dict[str, Any] = {
        "tool_name": tool_name,
        "invariant_name": verdict.name,
        "invariant_passed": verdict.passed,
    }
    for key in _CONTEXT_KEYS:
        if key in verdict.context:
            payload[key] = verdict.context[key]
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
        _logger = client.logger(settings.audit_log_name)
    except Exception:  # pragma: no cover - depends on GCP env
        _logger_failed = True
        _logger = None
    return _logger


def emit_verdict(tool_name: str, verdict: Verdict) -> None:
    """Emit one structured verdict LogEntry to Cloud Logging.

    No-op unless ``EVAL_AUDIT_LOG`` is on. Never raises: a logging failure must
    not break the tool call it is observing.
    """

    if not get_settings().audit_log_enabled:
        return
    logger = _get_logger()
    if logger is None:
        return
    try:
        logger.log_struct(
            _build_payload(tool_name, verdict),
            severity="ERROR" if not verdict.passed else "INFO",
        )
    except Exception:  # pragma: no cover - depends on GCP env
        pass
