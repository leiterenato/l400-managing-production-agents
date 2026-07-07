"""OTel span enrichment — the substrate side of the seam.

ADK already emits `gen_ai.*` spans for every model/tool call. Here we add a few
custom attributes so the *same* trace the eval reads also carries the invariant
verdicts. This is the literal "one substrate, three disciplines" seam: the hook
that runs the check also annotates the span.

Everything is defensive — if OTel is not configured (e.g. plain pytest), these
become no-ops.
"""

from __future__ import annotations

from typing import Any

try:  # OTel is a transitive dep of ADK, but stay defensive.
    from opentelemetry import trace
except Exception:  # pragma: no cover
    trace = None  # type: ignore

from ..contract import Verdict


def _current_span():
    if trace is None:
        return None
    span = trace.get_current_span()
    # A non-recording span means no exporter/provider is active.
    if span is None or not getattr(span, "is_recording", lambda: False)():
        return None
    return span


def set_attribute(key: str, value: Any) -> None:
    span = _current_span()
    if span is not None:
        try:
            span.set_attribute(key, value)
        except Exception:  # pragma: no cover
            pass


def record_invariant(verdict: Verdict) -> None:
    """Annotate the current span with an invariant verdict.

    Uses an ``eval.invariant.*`` namespace so it is easy to query in Cloud Trace
    / BigQuery and to line up with the offline eval metric of the same name.
    """

    set_attribute(f"eval.invariant.{verdict.name}", verdict.passed)
    if not verdict.passed:
        set_attribute("eval.invariant.violated", verdict.name)
        set_attribute("eval.invariant.detail", verdict.detail)
