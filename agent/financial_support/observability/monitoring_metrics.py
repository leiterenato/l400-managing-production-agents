"""Custom Cloud Monitoring metrics for the Case 2 "Contain the blast" dashboard.

The platform does not give you cost per decision, and its built-in latency metric
only exists for a *deployed* Agent Engine. For the Slide 10 story we drive the
REAL agent under a simulated fleet + injected slowness locally, MEASURE the real
latency / cost / breaker behaviour, and push those measurements here as custom
metrics. The Cloud Monitoring dashboard then tells the three-act story on a real
GCP surface: green baseline -> incident (the storm) -> the fix (breaker) recovers.

Honesty: these are metrics *we instrument*, not the platform's built-ins — which
is exactly the Case 2 thesis ("you instrument the number the console won't give
you"). The values are measured from the real agent, not hand-drawn.

Series (all GAUGE, monitored resource ``global``):
    custom.googleapis.com/agent/request_latency_p95   seconds
    custom.googleapis.com/agent/request_latency_p50   seconds
    custom.googleapis.com/agent/cost_per_min_usd      USD/min
    custom.googleapis.com/agent/breaker_open_count    fallbacks in the last window
    custom.googleapis.com/agent/sessions_per_min      throughput
"""

from __future__ import annotations

import time
from typing import Optional

_PREFIX = "custom.googleapis.com/agent/"


class MetricEmitter:
    """Writes one point per metric per tick to Cloud Monitoring (custom metrics).

    Uses the ``global`` monitored resource so no deploy is needed — any process
    with ADC can publish. A stable ``run`` metric label keeps re-runs on the same
    time series (you just view the latest window). Exceptions are NOT swallowed:
    for a pre-recorded demo we want to know immediately if a write fails.
    """

    def __init__(self, project_id: str, run_label: str = "case2-slide10") -> None:
        from google.cloud import monitoring_v3

        self._mv3 = monitoring_v3
        self._client = monitoring_v3.MetricServiceClient()
        self._project_id = project_id
        self._project_name = f"projects/{project_id}"
        self._run_label = run_label

    def _series(self, metric_type: str, value: float, end_time: float):
        mv3 = self._mv3
        series = mv3.TimeSeries()
        series.metric.type = _PREFIX + metric_type
        series.metric.labels["run"] = self._run_label
        series.resource.type = "global"
        series.resource.labels["project_id"] = self._project_id
        seconds = int(end_time)
        nanos = int((end_time - seconds) * 1_000_000_000)
        series.points = [
            mv3.Point(
                interval=mv3.TimeInterval(
                    end_time={"seconds": seconds, "nanos": nanos}
                ),
                value=mv3.TypedValue(double_value=float(value)),
            )
        ]
        return series

    def write(self, values: dict[str, float], end_time: Optional[float] = None) -> None:
        """Publish a batch of ``{metric_type: value}`` at ``end_time`` (now if None)."""

        if not values:
            return
        end_time = time.time() if end_time is None else end_time
        series = [self._series(mt, v, end_time) for mt, v in values.items()]
        self._client.create_time_series(
            name=self._project_name, time_series=series
        )
