"""Cost governance floor — spend per tenant, in BigQuery (Case 2, Slide 7).

The per-session budget (``callbacks.resilience.budget_guard``) contains ONE
runaway session locally. This module is the *global* side of the same number: the
cost each model call incurred, attributed up a label hierarchy (user -> project
-> org), so you can see which team is burning tokens and govern it — chargeback,
alerts, quotas per tenant. Visibility is not management.

Same honest, GA path as the Case 1 corpus (see ``evals/bigquery_scale.py``): the
platform does not give you cost, so ``record_cost`` computes it (tokens x price),
puts it on the span as ``gen_ai.cost.usd`` and mirrors it to Cloud Logging; a
Logging -> BigQuery sink (GA) lands the LogEntry here. This is SELF-instrumented
cost, NOT the Billing export (which lags hours).

Three jobs, mirroring bigquery_scale:
* :func:`synthetic_rows` — a deterministic per-call LogEntry corpus across tenants
  where ONE ``project_id`` is ~10x the rest (the runaway team), in the exact shape
  the Logging sink produces.
* :func:`by_tenant` — re-aggregate rows the way ``queries/cost_by_tenant.sql``
  does (the offline proof the seeder and the query agree).
* :func:`seed_bigquery` / :func:`run_bigquery` — create+load the table and run the
  real query against your project (guarded by ``EVAL_LIVE_CONFIRM``).
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict
from typing import Iterable, Iterator

_HERE = os.path.dirname(os.path.abspath(__file__))
_SCHEMA_PATH = os.path.join(_HERE, "queries", "cost_spans_schema.json")
_QUERY_PATH = os.path.join(_HERE, "queries", "cost_by_tenant.sql")

# Fixed anchor keeps `--dump` and the tests reproducible; the live seeder uses
# "today" so rows fall inside the query's 90-day window.
_DEFAULT_ANCHOR = dt.date(2026, 6, 28)

_DATASET = os.environ.get("BQ_DATASET", "agent_eval")
_TABLE = os.environ.get("BQ_COST_TABLE", "cost_spans")
_MODEL = os.environ.get("MODEL", "gemini-3.5-flash")

# Illustrative Gemini Flash pricing, USD per 1M tokens. Mirrors
# ``callbacks.resilience._PRICE``; kept local so evals stays independent of the
# runtime package. Verify against the current list price before quoting.
_PRICE = {"in": 0.30, "out": 2.50}

# (project_id, org_id, calls, prompt_tokens/call, candidate_tokens/call).
# proj-runaway is the fleet with no per-session budget: more calls AND fatter
# context -> ~10x the spend of the next-highest tenant. That is the headline bar.
_TENANTS = [
    ("proj-support", "org-acme", 200, 1200, 350),
    ("proj-sales", "org-acme", 150, 1000, 300),
    ("proj-ops", "org-acme", 120, 900, 280),
    ("proj-runaway", "org-acme", 600, 4000, 1200),
]


def _cost(prompt_tokens: int, candidate_tokens: int) -> float:
    return (
        prompt_tokens * _PRICE["in"] + candidate_tokens * _PRICE["out"]
    ) / 1_000_000


def _row(
    ts: dt.datetime,
    n: int,
    project_id: str,
    org_id: str,
    prompt_tokens: int,
    candidate_tokens: int,
    cost: float,
) -> dict:
    """One LogEntry row mirroring a model call's gen_ai.cost.usd attribute."""

    iso = ts.isoformat()
    return {
        "timestamp": iso,
        "receiveTimestamp": iso,
        "severity": "INFO",
        "logName": "projects/PROJECT/logs/cost_spans",
        "insertId": f"{n:032x}",
        "trace": f"projects/PROJECT/traces/{n:032x}",
        "spanId": f"{n:016x}",
        "resource": {
            "type": "aiplatform.googleapis.com/ReasoningEngine",
            "labels": {
                "project_id": project_id,
                "location": "us-central1",
                "reasoning_engine_id": "financial-support",
            },
        },
        "labels": {"agent": "financial_support"},
        "jsonPayload": {
            "model": _MODEL,
            "tool_name": "call_llm",
            "cost_usd": round(cost, 8),
            "prompt_tokens": prompt_tokens,
            "candidate_tokens": candidate_tokens,
            "session_id": f"sess-{n:06d}",
            "user_id": f"{project_id}-user",
            "project_id": project_id,
            "org_id": org_id,
        },
    }


def synthetic_rows(end_date: dt.date | None = None) -> Iterator[dict]:
    """Per-call cost LogEntry rows across tenants (one runaway ~10x the rest)."""

    anchor = end_date or _DEFAULT_ANCHOR
    base = dt.datetime.combine(anchor, dt.time(12, 0), tzinfo=dt.timezone.utc)
    n = 0
    for project_id, org_id, calls, ptok, ctok in _TENANTS:
        cost = _cost(ptok, ctok)
        for i in range(calls):
            n += 1
            # Spread back one hour per call -> all within the query's 90-day window.
            ts = base - dt.timedelta(hours=i)
            yield _row(ts, n, project_id, org_id, ptok, ctok, cost)


def by_tenant(rows: Iterable[dict]) -> list[list]:
    """Re-aggregate rows the way cost_by_tenant.sql does: SUM(cost) per project.

    Returns ``[[project, cost_usd, calls, tokens], ...]`` sorted by cost desc.
    """

    agg: dict[str, list] = defaultdict(lambda: [0.0, 0, 0])  # cost, calls, tokens
    for r in rows:
        p = r.get("jsonPayload", {})
        proj = p.get("project_id")
        if proj is None:
            continue
        agg[proj][0] += p.get("cost_usd", 0.0)
        agg[proj][1] += 1
        agg[proj][2] += p.get("prompt_tokens", 0) + p.get("candidate_tokens", 0)
    out = [[proj, round(c, 6), calls, tokens] for proj, (c, calls, tokens) in agg.items()]
    out.sort(key=lambda x: x[1], reverse=True)
    return out


def render(stats: list[list]) -> str:
    hi = max((s[1] for s in stats), default=1.0) or 1.0
    lines = [
        "BigQuery — cost by tenant (self-instrumented gen_ai.cost.usd corpus)",
        "=" * 68,
        f"{'project':<16}{'cost_usd':>12}{'calls':>8}  bar",
    ]
    for proj, cost, calls, _tokens in stats:
        bar = "#" * int(cost / hi * 34)
        lines.append(f"{proj:<16}{cost:>12.4f}{calls:>8}  {bar}")
    lines.append("-" * 68)
    lines.append(
        "One project ~10x the rest. Per-session budget contains ONE session; the "
        "label tree governs the whole org (chargeback / alerts / quotas per tenant)."
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
    """Create ``DATASET.cost_spans`` from the schema and load the tenant corpus."""

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
    print(f"Seeded {len(rows)} cost rows into {table_id} (anchor {today}).")
    return 0


def run_bigquery(project: str | None = None) -> int:
    """Run the real cost-by-tenant query against BigQuery (requires creds)."""

    try:
        from google.cloud import bigquery
    except Exception as exc:  # pragma: no cover
        print(f"BigQuery client unavailable: {exc}", file=sys.stderr)
        return 2

    with open(_QUERY_PATH) as fh:
        query = fh.read()

    client = bigquery.Client(project=project)
    query = query.replace(
        "PROJECT.DATASET.cost_spans", f"{client.project}.{_DATASET}.{_TABLE}"
    )
    for row in client.query(query).result():
        print(dict(row))
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

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

    print(render(by_tenant(synthetic_rows())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
