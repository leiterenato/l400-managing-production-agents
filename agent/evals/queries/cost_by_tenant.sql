-- Cost per tenant, from the corpus of self-instrumented cost spans in BigQuery.
--
-- WHERE THIS DATA COMES FROM (the honest, GA path):
-- The platform captures I/O and latency per span but NOT cost, and token counts
-- arrive aggregated. So the agent computes cost per model call in the record_cost
-- seam (tokens x price), writes it on the span as `gen_ai.cost.usd`, AND mirrors
-- it to a structured Cloud Logging entry; a Cloud Logging -> BigQuery sink (GA)
-- lands it here. The sink writes the standard LogEntry schema, so cost lives at
-- `jsonPayload.cost_usd` (a real nested column) and the tenant hierarchy at
-- `jsonPayload.project_id` / `org_id` / `user_id`. This is SELF-instrumented cost
-- data — NOT the Billing -> BigQuery export (which lags hours). See
-- evals/cost_scale.py (the seeder writes this exact shape) and
-- queries/cost_spans_schema.json (the table schema).
--
-- The per-session budget contains ONE runaway session locally; this query is the
-- global side — attribute and govern spend up the tree (which team is burning it).
--
-- Replace `PROJECT.DATASET.cost_spans` with your sink table.

SELECT
  jsonPayload.project_id                                   AS project,
  jsonPayload.org_id                                       AS org,
  ROUND(SUM(jsonPayload.cost_usd), 4)                      AS cost_usd,
  COUNT(*)                                                 AS calls,
  SUM(jsonPayload.prompt_tokens) + SUM(jsonPayload.candidate_tokens) AS tokens
FROM
  `PROJECT.DATASET.cost_spans`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY
  project, org
ORDER BY
  cost_usd DESC;
