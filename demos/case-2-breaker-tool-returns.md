# Case 2 · Slide 10 — the two tool returns (breaker OFF/ON evidence)

Captured live on **2026-07-17** with `gemini-3.5-flash` (no 429 at `--concurrency 2`).
Reproduce:

```bash
CASE=2 BREAKER_AUDIT_LOG=on BREAKER_OPEN_AFTER=2 \
  uv run python -m scripts.load_test --ab --scenario slow_payment --n 4 --concurrency 2
```

The injection is deterministic breaker code — model-agnostic. If 3.5-flash ever
429s on the day, `MODEL=gemini-2.5-flash` produces the identical evidence (only the
model label changes; the two tool returns are the same).

---

## The A/B table (flags changing: BREAKER OFF → ON)

```
+-------------------------+-------------+------------+
| metric                  | BREAKER OFF | BREAKER ON |
+-------------------------+-------------+------------+
| sessions                |           4 |          4 |
| total tokens            |      20,786 |     20,856 |
| total cost              |     $0.0076 |    $0.0077 |
| p50 latency             |       38.1s |      23.6s |
| p95 latency             |       38.3s |      39.0s |
| breaker-open (fallback) |           0 |          2 |
| errors                  |           0 |          0 |
+-------------------------+-------------+------------+
```

In the ON pass, 2 of 4 sessions ran before the circuit opened (real refund) and
2 hit the open circuit (injected fact). Same fleet, same code — both returns below.

---

## [1] Request that SUCCEEDED — the real `issue_refund` ran and moved money

```json
{
  "status": "refunded",
  "customer_id": "CUST-001",
  "charge_id": "TXN-1001",
  "amount": 50.0,
  "requested_amount": 50.0,
  "charge_amount": 50.0,
  "currency": "USD",
  "confirmation_id": "RF-TXN-1001",
  "duplicate": false,
  "reason": "Customer requested refund for monthly subscription"
}
```

## [2] Request that TRIPPED THE BREAKER — real tool SKIPPED, this dict injected as the tool result

```json
{
  "status": "unavailable",
  "dependency": "issue_refund",
  "instruction": "This tool is unavailable right now. Do NOT retry it. Follow the fallback: if a cached value is provided, relay it and say it may be out of date; otherwise hand off to a human. Never invent a value.",
  "cached_last_refund": null
}
```

**The twist:** `status: "unavailable"` is a **fact the model acts on** (follow the
fallback), NOT an error it retries. A library breaker returns an error; the model
reads an error as "I called it wrong" and retries into the storm. This returns a
normal-looking tool result carrying an instruction — so the model degrades honestly.

Source: `financial_support/callbacks/resilience.py` → `circuit_breaker` (the
`return {...}` when the circuit is open). It is a `before_tool_callback`: a non-None
return makes ADK skip the real tool and hand this dict to the model as the
`function_response`.

---

## Where to SEE it live (the breaker firing) — Logs Explorer

Real `WARNING` `breaker_open` line per circuit trip (`BREAKER_AUDIT_LOG=on`):

https://console.cloud.google.com/logs/query;query=logName%3D%22projects%2FYOUR_PROJECT_ID%2Flogs%2Fbreaker_events_live%22%0AjsonPayload.event%3D%22breaker_open%22;duration=PT1H?project=YOUR_PROJECT_ID

Confirmed entries (2026-07-17):

```
TIMESTAMP                       SEVERITY  TOOL          REASON  ELAPSED_S  FAILURES
2026-07-17T21:04:07Z            WARNING   issue_refund  slow    15.001     2
2026-07-17T21:00:06Z            WARNING   issue_refund  slow    15.001     2
```

> The `duration=PT1H` in the link is a 1-hour window — if you open it later, widen
> the time range or re-run the command above to emit a fresh line.

---

## Where to SEE it live (the injected return itself) — Cloud Trace ✅

**Yes — the injected tool return is fully visible in Cloud Trace**, not just the
flag. On the `execute_tool issue_refund` span, two attributes tell the whole story:

- `resilience.breaker.open = issue_refund` — our custom flag (from `telemetry.set_attribute`)
- `gcp.vertex.agent.tool_response = {"status":"unavailable", ..., "instruction":"...Do NOT retry..."}`
  — **ADK records the injected dict natively as the tool response.** The real tool
  was skipped; this is what the model received.

And the FULL prompt with the injected return in context is on the NEXT `call_llm`
span: `gcp.vertex.agent.llm_request` (the model's input, containing the
function_response) and `gcp.vertex.agent.llm_response` (the honest degraded reply:
"refund processing system is currently unavailable … a human agent has been
notified"). Cost is on each `call_llm` span as `gen_ai.cost.usd` (Slide 11).

Verified trace (2026-07-17), full Slide-10 trajectory
`look_up_customer (ok) → fraud_check (allow) → issue_refund (BREAKER OPEN) → honest handoff`:

https://console.cloud.google.com/traces/list?project=YOUR_PROJECT_ID&tid=8d04d8fff10d937f829abaaac5fc0bbf

To reproduce a fresh trace where the breaker opens on `issue_refund` in ONE session
(the shared per-tool counter is a fleet phenomenon — a single session calls
issue_refund once and can't trip it alone, so pre-set the counter to the state a
fleet would produce):

```python
# CASE=2 BREAKER=on BREAKER_OPEN_AFTER=2 SCENARIO=slow_payment, cloud export on:
from financial_support.callbacks import resilience
resilience._failures["issue_refund"] = 5   # earlier fleet sessions already tripped it
# then drive one refund turn (see scripts.live_drive helpers)
```

> Trace ingest is not atomic — spans land over ~1-2 min. If the `issue_refund`
> span isn't there yet, re-query; don't conclude it's missing on the first read.
> Cloud Trace keeps ~weeks, so regenerate near the talk date.
