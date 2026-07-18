-- Case 1 — weekly failure rate of the refund_within_charge invariant.
--
-- RESOLVED COPY for the BigQuery console / stage demo. The canonical query lives
-- at ../invariant_trend.sql and keeps the `PROJECT.DATASET.agent_spans`
-- placeholder on purpose (the seeder string-replaces it). This copy has the real
-- seeded table baked in so you can paste-and-run. Save it as "Case 1".
--
-- Data provenance (the honest, GA path): Cloud Logging -> BigQuery sink lands the
-- structured verdict at jsonPayload.invariant_passed. Cloud Trace keeps weeks;
-- BigQuery keeps the months that "at scale" means.

SELECT
  DATE_TRUNC(DATE(timestamp), WEEK)              AS week,
  COUNT(*)                                       AS refunds,
  COUNTIF(jsonPayload.invariant_passed = FALSE)  AS violations,
  SAFE_DIVIDE(
    COUNTIF(jsonPayload.invariant_passed = FALSE),
    COUNT(*)
  )                                              AS failure_rate
FROM
  `YOUR_PROJECT_ID.agent_eval.agent_spans`
WHERE
  jsonPayload.tool_name = 'issue_refund'
  AND jsonPayload.invariant_name = 'refund_within_charge'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY
  week
ORDER BY
  week;
