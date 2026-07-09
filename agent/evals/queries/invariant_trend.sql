-- Weekly failure rate of the `refund_within_charge` invariant, from the corpus
-- of scored traces in BigQuery.
--
-- WHERE THIS DATA COMES FROM (the honest, GA path):
-- ADK exports OTel spans to Cloud Trace, and Cloud Trace has no native BigQuery
-- export. So the durable, months-long corpus is built from Cloud LOGGING: for
-- every money-moving tool call the agent emits a structured log entry mirroring
-- the span's invariant verdict, and a Cloud Logging -> BigQuery sink (GA) lands
-- it here. The sink writes the standard LogEntry schema, so the verdict lives at
-- `jsonPayload.invariant_passed` (a real nested column) — NOT at a dotted
-- attribute key. See evals/bigquery_scale.py (the seeder writes this exact shape)
-- and queries/agent_spans_schema.json (the table schema).
--
-- Cloud Trace keeps weeks; BigQuery keeps the months that "at scale" means — this
-- is the Case 1 floor, and the same table gains Row-Level Security in Case 3.
--
-- Replace `PROJECT.DATASET.agent_spans` with your sink table.

SELECT
  DATE_TRUNC(DATE(timestamp), WEEK)                       AS week,
  COUNT(*)                                                AS refunds,
  COUNTIF(jsonPayload.invariant_passed = FALSE)           AS violations,
  SAFE_DIVIDE(
    COUNTIF(jsonPayload.invariant_passed = FALSE),
    COUNT(*)
  )                                                       AS failure_rate
FROM
  `PROJECT.DATASET.agent_spans`
WHERE
  jsonPayload.tool_name = 'issue_refund'
  AND jsonPayload.invariant_name = 'refund_within_charge'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY
  week
ORDER BY
  week;
