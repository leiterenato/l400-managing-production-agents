"""Observability substrate (OTel). Always-on by default across all cases."""

from .otel import init_telemetry

__all__ = ["init_telemetry"]
