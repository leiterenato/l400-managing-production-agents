-- Case 2 — cost per tenant, from self-instrumented cost spans in BigQuery.
--
-- RESOLVED COPY for the BigQuery console / stage demo. The canonical query lives
-- at ../cost_by_tenant.sql and keeps the `PROJECT.DATASET.cost_spans` placeholder
-- on purpose (the seeder string-replaces it). This copy has the real seeded table
-- baked in so you can paste-and-run. Save it as "Case 2".
--
-- Data provenance (the honest, GA path): the agent computes cost per model call
-- in the record_cost seam (tokens x price) and mirrors it to a Cloud Logging
-- entry; a Cloud Logging -> BigQuery sink lands cost at jsonPayload.cost_usd and
-- the tenant hierarchy at jsonPayload.project_id / org_id. This is SELF-
-- instrumented cost data, NOT the Billing export (which lags hours). The
-- per-session budget governs ONE runaway session locally; this query is the
-- global side — attribute and govern spend up the tree.

SELECT
  jsonPayload.project_id                                   AS project,
  jsonPayload.org_id                                       AS org,
  ROUND(SUM(jsonPayload.cost_usd), 4)                      AS cost_usd,
  COUNT(*)                                                 AS calls,
  SUM(jsonPayload.prompt_tokens) + SUM(jsonPayload.candidate_tokens) AS tokens
FROM
  `YOUR_PROJECT_ID.agent_eval.cost_spans`
WHERE
  timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY
  project, org
ORDER BY
  cost_usd DESC;
