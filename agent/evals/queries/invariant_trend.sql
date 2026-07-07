-- Weekly failure rate of the `refund_within_charge` invariant, from the
-- corpus of scored traces in BigQuery.
--
-- Cloud Logging sinks the agent's OTel spans to BigQuery. The invariant verdict
-- rides on the span as the attribute `eval.invariant.refund_within_charge`
-- (set by callbacks/telemetry.py). Cloud Trace keeps weeks; BigQuery keeps the
-- months of history that "at scale" actually means — this is the Case 1 floor,
-- and the same table gains Row-Level Security in Case 3.
--
-- Replace `PROJECT.DATASET.agent_spans` with your sink table.

SELECT
  DATE_TRUNC(DATE(timestamp), WEEK)                              AS week,
  COUNT(*)                                                       AS refunds,
  COUNTIF(attributes.`eval.invariant.refund_within_charge` = false) AS violations,
  SAFE_DIVIDE(
    COUNTIF(attributes.`eval.invariant.refund_within_charge` = false),
    COUNT(*)
  )                                                              AS failure_rate
FROM
  `PROJECT.DATASET.agent_spans`
WHERE
  attributes.`gen_ai.tool.name` = 'issue_refund'
  AND timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
GROUP BY
  week
ORDER BY
  week;
