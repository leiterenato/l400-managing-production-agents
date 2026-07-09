"""The BigQuery seeder and the trend query agree on the LogEntry schema.

This locks the schema reconciliation: the corpus the seeder writes
(:func:`synthetic_rows`) must re-aggregate — via the same Sunday-week grouping
the SQL uses — back into :func:`weekly_failure_rate`, and the row shape must be
the nested ``jsonPayload`` LogEntry the sink produces (not a dotted attribute).
"""

import datetime as dt
import json
import os

from evals import bigquery_scale as bq


def test_row_count_matches_corpus():
    rows = list(bq.synthetic_rows(weeks=12, per_week=1000))
    assert len(rows) == 12 * 1000


def test_rows_reaggregate_to_weekly_failure_rate():
    rows = bq.synthetic_rows(weeks=12, per_week=1000)
    got = bq.weekly_from_rows(rows)
    want = bq.weekly_failure_rate(weeks=12, per_week=1000)
    assert len(got) == len(want)
    for g, w in zip(got, want):
        assert (g.refunds, g.violations) == (w.refunds, w.violations)


def test_each_week_is_one_bigquery_bucket():
    # Every synthetic week must land in a single DATE_TRUNC(.., WEEK) bucket,
    # else the trend query would not return one row per week.
    weeks = {
        bq._week_sunday(dt.datetime.fromisoformat(r["timestamp"]).date())
        for r in bq.synthetic_rows(weeks=12, per_week=1000)
    }
    assert len(weeks) == 12


def test_row_shape_is_logentry_json_payload():
    row = next(bq.synthetic_rows())
    # LogEntry top-level columns present.
    for key in ("timestamp", "severity", "trace", "spanId", "resource", "jsonPayload"):
        assert key in row
    payload = row["jsonPayload"]
    assert payload["tool_name"] == "issue_refund"
    assert payload["invariant_name"] == "refund_within_charge"
    assert isinstance(payload["invariant_passed"], bool)
    assert row["resource"]["type"] == "aiplatform.googleapis.com/ReasoningEngine"


def test_failed_rows_are_the_money_bug_and_severity_error():
    failed = [r for r in bq.synthetic_rows() if r["jsonPayload"]["invariant_passed"] is False]
    assert failed, "corpus must contain violations"
    for r in failed:
        assert r["severity"] == "ERROR"
        assert r["jsonPayload"]["refund_amount"] > r["jsonPayload"]["charge_amount"]


def test_dump_is_deterministic_ndjson():
    # Fixed anchor -> byte-identical dumps across runs.
    a = [json.dumps(r) for r in bq.synthetic_rows()]
    b = [json.dumps(r) for r in bq.synthetic_rows()]
    assert a == b


def test_schema_file_matches_query_columns():
    with open(bq._SCHEMA_PATH) as fh:
        schema = json.load(fh)
    payload = next(f for f in schema if f["name"] == "jsonPayload")
    fields = {f["name"] for f in payload["fields"]}
    assert {"tool_name", "invariant_name", "invariant_passed"} <= fields

    with open(bq._QUERY_PATH) as fh:
        sql = fh.read()
    # The reconciled query reads the nested column, not the old dotted attribute.
    assert "jsonPayload.invariant_passed" in sql
    assert "eval.invariant.refund_within_charge" not in sql
