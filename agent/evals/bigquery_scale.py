"""Scale floor — the invariant's failure rate over months, in BigQuery (S4/S0).

"At scale" doesn't fit in one trace; it fits in BigQuery. Cloud Logging sinks the
agent's OTel spans (carrying the invariant verdict) to BigQuery, giving months of
scored traces. The trend query (``queries/invariant_trend.sql``) computes the
weekly failure rate of ``refund_within_charge`` — how you *see* a slow regression
that no single green run would reveal.

Offline, :func:`weekly_failure_rate` produces a deterministic synthetic corpus
with a drift so the demo shows the climb. :func:`run_bigquery` runs the real
query against your project (guarded).

Bridge to Case 3 (one sentence on stage): this same BigQuery table gains
Row-Level Security there, so a cross-account read returns no rows.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

_SPARK = " ▁▂▃▄▅▆▇█"


@dataclass
class WeekStat:
    week: int
    refunds: int
    violations: int

    @property
    def failure_rate(self) -> float:
        return self.violations / self.refunds if self.refunds else 0.0


def weekly_failure_rate(weeks: int = 12, per_week: int = 1000) -> list[WeekStat]:
    """Deterministic synthetic corpus: flat, then a drift after week 6."""

    stats: list[WeekStat] = []
    for w in range(1, weeks + 1):
        rate = 0.002 if w <= 6 else 0.002 + 0.005 * (w - 6)
        violations = round(per_week * rate)
        stats.append(WeekStat(week=w, refunds=per_week, violations=violations))
    return stats


def _sparkline(rates: list[float]) -> str:
    hi = max(rates) or 1.0
    return "".join(_SPARK[min(len(_SPARK) - 1, int(r / hi * (len(_SPARK) - 1)))] for r in rates)


def render(stats: list[WeekStat]) -> str:
    lines = [
        "BigQuery — weekly refund_within_charge failure rate (scored trace corpus)",
        "=" * 68,
        f"{'week':>4}  {'refunds':>8}  {'violations':>10}  {'failure_rate':>12}",
    ]
    for s in stats:
        lines.append(
            f"{s.week:>4}  {s.refunds:>8}  {s.violations:>10}  {s.failure_rate:>11.2%}"
        )
    lines.append("-" * 68)
    lines.append("trend  " + _sparkline([s.failure_rate for s in stats]))
    lines.append(
        "The green run stays green; the corpus shows the drift. Scale lives in "
        "BigQuery, not in one trace."
    )
    return "\n".join(lines)


def run_bigquery(project: str | None = None) -> int:
    """Run the real trend query against BigQuery (requires creds)."""

    try:
        from google.cloud import bigquery
    except Exception as exc:  # pragma: no cover
        print(f"BigQuery client unavailable: {exc}", file=sys.stderr)
        return 2

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "queries", "invariant_trend.sql")) as fh:
        query = fh.read()

    client = bigquery.Client(project=project)
    for row in client.query(query).result():
        print(dict(row))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if "--live" in argv:
        if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
            print("Set EVAL_LIVE_CONFIRM=1 to run the real BigQuery query.", file=sys.stderr)
            return 3
        return run_bigquery(os.environ.get("GOOGLE_CLOUD_PROJECT"))
    print(render(weekly_failure_rate()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
