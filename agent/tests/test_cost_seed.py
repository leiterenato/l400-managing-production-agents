"""The cost seeder and the cost-by-tenant query agree on the LogEntry schema.

Locks the reconciliation (mirrors test_bigquery_seed.py): the corpus the seeder
writes re-aggregates — by the same GROUP BY project the SQL uses — into a clear
"one tenant ~10x the rest" ranking, and the row shape is the nested ``jsonPayload``
LogEntry the sink produces (not a dotted attribute).
"""

import json

from evals import cost_scale as cs


def test_row_count_matches_corpus():
    rows = list(cs.synthetic_rows())
    assert len(rows) == sum(t[2] for t in cs._TENANTS)


def test_one_tenant_is_the_runaway():
    stats = cs.by_tenant(cs.synthetic_rows())
    assert stats, "corpus must produce tenants"
    top = stats[0]
    others = stats[1:]
    assert top[0] == "proj-runaway"
    # The headline: the top tenant dwarfs the next-highest (~10x; assert >= 8x).
    assert top[1] >= 8 * max(o[1] for o in others)


def test_by_tenant_is_sorted_desc_by_cost():
    stats = cs.by_tenant(cs.synthetic_rows())
    costs = [s[1] for s in stats]
    assert costs == sorted(costs, reverse=True)


def test_costs_are_positive_and_match_price():
    stats = cs.by_tenant(cs.synthetic_rows())
    assert all(s[1] > 0 for s in stats)
    # proj-support: 200 calls * cost(1200, 350)
    expected = 200 * cs._cost(1200, 350)
    support = next(s for s in stats if s[0] == "proj-support")
    assert abs(support[1] - round(expected, 6)) < 1e-6


def test_row_shape_is_logentry_cost_payload():
    row = next(cs.synthetic_rows())
    for key in ("timestamp", "severity", "trace", "spanId", "resource", "jsonPayload"):
        assert key in row
    p = row["jsonPayload"]
    for field in ("model", "tool_name", "cost_usd", "project_id", "org_id", "user_id"):
        assert field in p
    assert p["tool_name"] == "call_llm"
    assert isinstance(p["cost_usd"], float)
    assert row["resource"]["type"] == "aiplatform.googleapis.com/ReasoningEngine"


def test_dump_is_deterministic_ndjson():
    a = [json.dumps(r) for r in cs.synthetic_rows()]
    b = [json.dumps(r) for r in cs.synthetic_rows()]
    assert a == b


def test_schema_file_matches_query_columns():
    with open(cs._SCHEMA_PATH) as fh:
        schema = json.load(fh)
    payload = next(f for f in schema if f["name"] == "jsonPayload")
    fields = {f["name"] for f in payload["fields"]}
    assert {"project_id", "cost_usd", "org_id"} <= fields

    with open(cs._QUERY_PATH) as fh:
        sql = fh.read()
    # The query reads the nested columns, not dotted span-attribute keys.
    assert "jsonPayload.cost_usd" in sql
    assert "jsonPayload.project_id" in sql
    # Check the executable query (comments stripped) — the header comment may
    # legitimately mention the span attribute name in prose.
    body = "\n".join(l for l in sql.splitlines() if not l.strip().startswith("--"))
    assert "gen_ai.cost.usd" not in body
