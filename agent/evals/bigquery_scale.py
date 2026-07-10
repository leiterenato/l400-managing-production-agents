"""Scale floor — the invariant's failure rate over months, in BigQuery (S4/S0).

"At scale" doesn't fit in one trace; it fits in BigQuery. The honest, GA path:
ADK exports OTel spans to Cloud Trace, which has *no* native BigQuery export — so
the durable corpus is built from Cloud **Logging**. For every money-moving tool
call the agent emits a structured log entry mirroring the span's invariant
verdict, and a Cloud Logging -> BigQuery sink (GA) lands it in the ``agent_spans``
table. The sink writes the standard **LogEntry** schema, so the verdict lives at
``jsonPayload.invariant_passed`` — a real nested column, not a dotted attribute.

This module has three jobs:

* :func:`weekly_failure_rate` / :func:`render` — deterministic synthetic trend
  for the *offline* demo (no creds), flat then drifting after week 6.
* :func:`synthetic_rows` — the same corpus expanded to per-refund LogEntry rows,
  in the exact shape the Logging sink produces (so the seeder and the trend query
  agree). :func:`weekly_from_rows` re-aggregates them the way the SQL does, which
  is what the tests assert.
* :func:`seed_bigquery` / :func:`run_bigquery` — create+load the table and run the
  real ``queries/invariant_trend.sql`` against your project (guarded).

Bridge to Case 3 (one sentence on stage): this same BigQuery table gains
Row-Level Security there, so a cross-account read returns no rows.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Iterator

_SPARK = " ▁▂▃▄▅▆▇█"

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "queries", "agent_spans_schema.json")
_QUERY_PATH = os.path.join(_HERE, "queries", "invariant_trend.sql")

# Deterministic anchor for offline dumps/tests: the corpus ends on the Sunday of
# this week. A fixed date keeps `--dump` and the tests reproducible; the live
# seeder uses "today" so the rows land inside the query's 90-day window.
_DEFAULT_ANCHOR = dt.date(2026, 6, 28)  # a Sunday

# Where the seeder creates/loads the table (override via env for your project).
_DATASET = os.environ.get("BQ_DATASET", "agent_eval")
_TABLE = os.environ.get("BQ_TABLE", "agent_spans")


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


# ---------------------------------------------------------------------------
# LogEntry rows — what the Cloud Logging -> BigQuery sink actually writes.
# ---------------------------------------------------------------------------

def _week_sunday(d: dt.date) -> dt.date:
    """The Sunday that starts d's week — matches BigQuery DATE_TRUNC(.., WEEK)."""

    # Python weekday(): Mon=0 .. Sun=6. Sunday-started week -> back (weekday+1)%7.
    return d - dt.timedelta(days=(d.weekday() + 1) % 7)


def _row(ts: dt.datetime, failed: bool, n: int) -> dict:
    """One LogEntry row mirroring an issue_refund invariant verdict."""

    iso = ts.isoformat()
    return {
        "timestamp": iso,
        "receiveTimestamp": iso,
        "severity": "ERROR" if failed else "INFO",
        "logName": "projects/PROJECT/logs/agent_spans",
        "insertId": f"{n:032x}",
        "trace": f"projects/PROJECT/traces/{n:032x}",
        "spanId": f"{n:016x}",
        "resource": {
            "type": "aiplatform.googleapis.com/ReasoningEngine",
            "labels": {
                "project_id": "PROJECT",
                "location": "us-central1",
                "reasoning_engine_id": "financial-support",
            },
        },
        "labels": {"agent": "financial_support"},
        "jsonPayload": {
            "tool_name": "issue_refund",
            "invariant_name": "refund_within_charge",
            "invariant_passed": not failed,
            # A failed row is the demo money bug: $500 on a $50 charge.
            "refund_amount": 500.0 if failed else 50.0,
            "charge_amount": 50.0,
            "session_customer_id": "CUST-001",
            "read_customer_id": "CUST-001",
        },
    }


def synthetic_rows(
    weeks: int = 12,
    per_week: int = 1000,
    end_date: dt.date | None = None,
) -> Iterator[dict]:
    """Expand :func:`weekly_failure_rate` into per-refund LogEntry rows.

    Rows for week *w* are spread across the six days Sun..Sat of a single
    Sunday-started calendar week, so ``DATE_TRUNC(DATE(timestamp), WEEK)`` buckets
    each synthetic week into exactly one row of the trend query. The most recent
    week ends on ``end_date``'s Sunday; older weeks step back 7 days each.
    """

    anchor_sunday = _week_sunday(end_date or _DEFAULT_ANCHOR)
    stats = weekly_failure_rate(weeks, per_week)
    # Spread within Sun..Sat (< 7 days) to stay inside one weekly bucket.
    step = (6 * 86400) // per_week
    n = 0
    for s in stats:
        weeks_back = weeks - s.week  # week==weeks is the most recent
        week_start = anchor_sunday - dt.timedelta(days=7 * weeks_back)
        base = dt.datetime.combine(week_start, dt.time(), tzinfo=dt.timezone.utc)
        for i in range(per_week):
            n += 1
            ts = base + dt.timedelta(seconds=i * step)
            yield _row(ts, failed=i < s.violations, n=n)


def weekly_from_rows(rows: Iterable[dict]) -> list[WeekStat]:
    """Re-aggregate LogEntry rows the way invariant_trend.sql does.

    Groups by the Sunday-started week and counts issue_refund /
    refund_within_charge rows and their violations. This is the offline proof
    that the seeded corpus and the SQL agree.
    """

    agg: dict[dt.date, list[int]] = defaultdict(lambda: [0, 0])  # week -> [refunds, violations]
    for r in rows:
        payload = r.get("jsonPayload", {})
        if (
            payload.get("tool_name") != "issue_refund"
            or payload.get("invariant_name") != "refund_within_charge"
        ):
            continue
        ts = dt.datetime.fromisoformat(r["timestamp"])
        week = _week_sunday(ts.date())
        agg[week][0] += 1
        if payload.get("invariant_passed") is False:
            agg[week][1] += 1

    ordered = sorted(agg.items())
    return [
        WeekStat(week=i + 1, refunds=refunds, violations=violations)
        for i, (_, (refunds, violations)) in enumerate(ordered)
    ]


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


# ---------------------------------------------------------------------------
# Live path — create the table from the schema, load the corpus, run the query.
# ---------------------------------------------------------------------------

def _load_schema():
    from google.cloud import bigquery

    with open(_SCHEMA_PATH) as fh:
        return [bigquery.SchemaField.from_api_repr(f) for f in json.load(fh)]


def seed_bigquery(project: str | None = None) -> int:
    """Create ``DATASET.TABLE`` from the schema and load the historical corpus.

    Guarded by the caller (EVAL_LIVE_CONFIRM). Uses "today" as the anchor so the
    seeded weeks fall inside the trend query's 90-day window.
    """

    try:
        from google.cloud import bigquery
    except Exception as exc:  # pragma: no cover
        print(f"BigQuery client unavailable: {exc}", file=sys.stderr)
        return 2

    client = bigquery.Client(project=project)
    schema = _load_schema()

    dataset_ref = bigquery.Dataset(f"{client.project}.{_DATASET}")
    dataset_ref.location = os.environ.get("GOOGLE_CLOUD_LOCATION", "US")
    client.create_dataset(dataset_ref, exists_ok=True)

    table_id = f"{client.project}.{_DATASET}.{_TABLE}"
    table = bigquery.Table(table_id, schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="timestamp")
    client.create_table(table, exists_ok=True)

    today = dt.datetime.now(dt.timezone.utc).date()
    rows = list(synthetic_rows(end_date=today))
    job_config = bigquery.LoadJobConfig(
        schema=schema, write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE
    )
    client.load_table_from_json(rows, table_id, job_config=job_config).result()
    print(f"Seeded {len(rows)} rows into {table_id} (anchor {today}).")
    return 0


def run_bigquery(project: str | None = None) -> int:
    """Run the real trend query against BigQuery (requires creds)."""

    try:
        from google.cloud import bigquery
    except Exception as exc:  # pragma: no cover
        print(f"BigQuery client unavailable: {exc}", file=sys.stderr)
        return 2

    with open(_QUERY_PATH) as fh:
        query = fh.read()

    client = bigquery.Client(project=project)
    # The .sql keeps a `PROJECT.DATASET.agent_spans` placeholder (documents the
    # shape); point it at the real seeded table before running.
    query = query.replace(
        "PROJECT.DATASET.agent_spans", f"{client.project}.{_DATASET}.{_TABLE}"
    )
    for row in client.query(query).result():
        print(dict(row))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    # Offline: dump the seed corpus as NDJSON to inspect the LogEntry shape.
    if "--dump" in argv:
        for row in synthetic_rows():
            print(json.dumps(row))
        return 0

    if "--seed" in argv:
        if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
            print("Set EVAL_LIVE_CONFIRM=1 to seed the real BigQuery table.", file=sys.stderr)
            return 3
        return seed_bigquery(os.environ.get("GOOGLE_CLOUD_PROJECT"))

    if "--live" in argv:
        if os.environ.get("EVAL_LIVE_CONFIRM") != "1":
            print("Set EVAL_LIVE_CONFIRM=1 to run the real BigQuery query.", file=sys.stderr)
            return 3
        return run_bigquery(os.environ.get("GOOGLE_CLOUD_PROJECT"))

    print(render(weekly_failure_rate()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
