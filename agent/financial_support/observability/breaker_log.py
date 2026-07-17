"""Durable side of the resilience seam — breaker transitions as Cloud Logging.

Mirror of :mod:`financial_support.observability.cost_log`, but for the Case 2
circuit breaker. :func:`financial_support.callbacks.resilience.record_outcome`
already annotates the OTel span with ``resilience.breaker.open``; this module
mirrors the breaker's STATE TRANSITIONS (closed->open when it trips, open->closed
when a fast success recovers it) to structured ``LogEntry`` rows. So the breaker
signal is not only a trace attribute and a dashboard metric — it is a log line you
can see in Logs Explorer and page on with an alert policy. That is the "page on
the breaker" beat on Slide 10, made literal.

An ``open`` transition is emitted at ``WARNING`` (the incident signal you page
on); a ``closed`` transition at ``INFO`` (recovery). Exactly one line per
transition, not one per short-circuited call — the ``record_outcome`` guard only
calls this when the counter actually crosses the threshold.

Everything degrades to a no-op: emission is off unless ``BREAKER_AUDIT_LOG`` is
set, the Logging client is imported lazily, and every exception is swallowed —
resilience telemetry must never break a tool call. So pytest / offline paths stay
clean.
"""

from __future__ import annotations

import os
from typing import Any

from ..config import get_settings

# Lazily-built, process-wide logger (creating a client per call is expensive).
_logger = None
_logger_failed = False


def _enabled() -> bool:
    return os.environ.get("BREAKER_AUDIT_LOG", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


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
            os.environ.get("BREAKER_AUDIT_LOG_NAME", "breaker_events_live")
        )
    except Exception:  # pragma: no cover - depends on GCP env
        _logger_failed = True
        _logger = None
    return _logger


def _build_payload(
    tool_context,
    *,
    tool: str,
    state: str,
    reason: str,
    failures: int,
    threshold: int,
    elapsed_s: float,
) -> dict[str, Any]:
    """The ``jsonPayload`` of the breaker LogEntry — pure and side-effect free."""

    st = getattr(tool_context, "state", None) or {}
    return {
        "event": f"breaker_{state}",  # breaker_open | breaker_closed
        "state": state,  # open | closed
        "tool": tool,  # the degraded dependency
        "reason": reason,  # slow | error | recovered
        "failures": int(failures),
        "threshold": int(threshold),
        "elapsed_s": round(float(elapsed_s), 3),
        "session_id": st.get("session_id") or st.get("customer_id", ""),
    }


def emit_transition(
    tool_context,
    *,
    tool: str,
    state: str,
    reason: str,
    failures: int,
    threshold: int,
    elapsed_s: float = 0.0,
) -> None:
    """Emit one structured LogEntry for a breaker state transition.

    No-op unless ``BREAKER_AUDIT_LOG`` is on. ``state`` is ``"open"`` or
    ``"closed"``; open logs at ``WARNING`` (page-worthy), closed at ``INFO``.
    """

    if not _enabled():
        return
    logger = _get_logger()
    if logger is None:
        return
    try:
        logger.log_struct(
            _build_payload(
                tool_context,
                tool=tool,
                state=state,
                reason=reason,
                failures=failures,
                threshold=threshold,
                elapsed_s=elapsed_s,
            ),
            severity="WARNING" if state == "open" else "INFO",
        )
    except Exception:  # pragma: no cover - depends on GCP env
        pass
