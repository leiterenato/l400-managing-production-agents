# Financial Support Agent — L400 reference build

The base agent for **"Managing Production Agents at Scale"**. One agent
(reads PII + issues refunds) that *matures* across the three cases. This repo is
the **Case 1** build — Continuous Evaluation & EDD — structured so Cases 2
(resilience) and 3 (zero-trust) plug in without a rewrite.

Everything runs on **mocks with deterministic feature flags**, so a click always
produces the same trace. Honest about what is mock; the discipline (the contract
invariants) is real and portable.

---

## What's here

```
financial_support/            # the ADK agent package (exposes root_agent)
  agent.py                    # root orchestrator (wires sub-agents + callbacks)
  contract.py                 # ★ behavioural contract + invariants (EDD source)
  prompts.py                  # instructions (happy-path only — correctness ≠ prompt)
  config.py                   # all env-driven settings in one place
  sub_agents/                 # refund_specialist, disputes_specialist
  tools/                      # look_up_customer, issue_refund, fraud_check, open_dispute
  backends/                   # mock external systems (swappable)
    customer_db.py            #   ↳ BigQuery (Case 3 adds RLS here)
    payment_processor.py      #   ↳ payments API (Case 2 hangs resilience here)
    fraud_service.py          #   ↳ shared fraud logic (also used by the A2A agent)
    faults.py                 # ★ deterministic fault injection ("feature flags")
    data.py                   # seed fixtures (TXN-1001 = $50)
  callbacks/                  # cross-cutting concerns, composed via a registry
    invariants.py             # ★ the seam: after_tool_callback runs the invariant
    telemetry.py              # OTel span enrichment
    registry.py               # ★ compose bundles per concern (extensibility spine)
  observability/otel.py       # OTel substrate (always on)
  observability/verdict_log.py# S4: emit verdict LogEntry → Cloud Logging → BQ sink

fraud_check_a2a/              # external fraud agent, served over A2A
evals/                        # Case 1 eval harness (the six surfaces)
  metrics.py                  # green types.Metric (custom_function local) + amber LLMMetric + local judge
  scenarios.py                # seed eval cases (EDD) + staged fixtures
  record.py                   # record traces (agent → dataset), offline-deterministic
  eval_core.py                # score a dataset → EvalResult + gate
  report.py                   # console report
  clusters.py                 # failure clustering (generate_loss_clusters analogue)
  online_monitor.py           # S4 sentinel: rolling invariant + alert (simulated)
  bigquery_scale.py           # S4 floor: weekly failure rate over months
  queries/invariant_trend.sql #   the real BigQuery trend query
  live.py                     # the real Evaluation Service pipeline (guarded)
  run_offline.py              # the gate: record → evaluate → report → clusters
deploy/opentelemetry.env      # OTel env for `adk web --otel_to_cloud`
deploy/cloudbuild.yaml        # the merge gate (Cloud Build runs the eval)
deploy/agent_engine.py        # OPTIONAL: deploy to Agent Runtime (managed prod)
scripts/run_local.py          # drive tool + invariant seam offline (no model)
tests/                        # pytest — the portable core
```

★ = the load-bearing pieces of the Case 1 story.

---

## Quickstart

```bash
# from the agent/ directory. uv manages the venv + Python 3.12.
uv sync

# 1) Offline — see the invariant seam catch the money bug (no GCP, no model):
uv run python -m scripts.run_local refund_over_charge   # $500 refund on $50 → FAIL
uv run python -m scripts.run_local wrong_account        # cross-account read → FAIL
uv run python -m scripts.run_local healthy              # clean → PASS

# 2) The eval / merge gate (offline, deterministic; non-zero exit on failure):
uv run python -m evals.run_offline          # record → evaluate → report → clusters
uv run python -m evals.record               # just show the recorded traces
uv run python -m evals.online_monitor       # S4: rolling invariant + alert
uv run python -m evals.bigquery_scale       # S4: weekly failure rate over months

# 3) Tests:
uv run pytest -q

# 4) Full agent with the model (needs GCP creds + a .env):
cp .env.example .env    # fill in GOOGLE_CLOUD_PROJECT etc.
uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud

# 5) With the external fraud agent over A2A (two terminals):
uv run python -m fraud_check_a2a                        # terminal 1 (port 8001)
USE_A2A_FRAUD=true uv run adk web                       # terminal 2

# 6) The real Evaluation Service pipeline (Preview; needs GCP + confirm):
EVAL_LIVE_CONFIRM=1 uv run python -m evals.run_offline --live

# 7) OPTIONAL: deploy to Agent Runtime (managed production; do NOT demo live):
GOOGLE_CLOUD_STAGING_BUCKET=gs://your-bucket \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py

# 8) S4 flywheel corpus (needs GCP + confirm): seed the months of drift, then
#    validate the real trend query against BigQuery:
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --seed
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --live
#    The live pipe (real rows): set EVAL_AUDIT_LOG=true so the seam emits a
#    verdict LogEntry (log id `agent_spans_live`); a Cloud Logging → BigQuery
#    sink lands it in `agent_eval.agent_spans_live`. See deploy notes below.
```

> **Agent Runtime placement.** It's the managed host + the honest home of
> "production" for the S4 flywheel (Online Monitors sample its live traces). Its
> observability is the *same* OTel → Cloud Trace/Monitoring/Logging you already
> use — it does **not** give eval/quality or cost metrics "for free". Keep it in
> the intro/substrate framing, not as a Case 1 beat. See `deploy/agent_engine.py`.

### The six eval surfaces (demos/case-1-demos.md) → code

| Surface | Slide | Code |
|---|---|---|
| Observability (trace/topology) | S2 | `observability/`, `callbacks/telemetry.py` |
| Manage metrics (green/amber/grey) | S3 | `evals/metrics.py` |
| Run offline + simulate + gate | S3 | `evals/record.py`, `eval_core.py`, `run_offline.py` |
| Failure clusters | S4 | `evals/clusters.py` |
| Online monitor + alert | S4 | `evals/online_monitor.py` |
| BigQuery scale floor | S4 | `evals/bigquery_scale.py`, `queries/invariant_trend.sql` |

---

## The idea that ties it together: one invariant, many surfaces

`refund ≤ charge` is **one function**, derived from the contract (that's EDD),
consumed in three places from a single definition in `contract.py`:

| Job | Where | Code |
|---|---|---|
| Runtime guard | `after_tool_callback` on `issue_refund` | `callbacks/invariants.py` |
| Test / eval metric | `types.Metric` custom_function local (green) | `evals/metrics.py` |
| Merge gate | Cloud Build runs the eval on the PR | `deploy/cloudbuild.yaml` |

The **LLM judge (amber)** grades tone and would happily pass a $500 refund on a
$50 charge. The **hard invariant (green)** is what catches it. That is "the green
score lies", with real money.

### The Slide 4 one-two: value vs. trajectory (two ways green lies)

Two invariants, two kinds of failure the demo shows side by side:

- **A · loud** — `refund_within_charge` (value). A $500 refund on a $50 charge:
  the amount check screams red while the tone judge stays green.
- **B · silent** — `refund_requires_lookup` (trajectory). A refund that is the
  right amount, on the right account, with a polite reply — *every value check
  green* — but the agent skipped the customer look-up. Only the **path** catches
  it; loss clustering names it **"Incorrect Tool Selection"**. This is the
  trace-level invariant in `contract.py`; it gates but has no runtime guard (the
  per-response seam sees one tool call at a time — trajectory needs the history).

### Demo scenarios (set `SCENARIO=` or pass to `run_local`)

| Scenario | What it stages | Bridges to |
|---|---|---|
| `healthy` | everything nominal | — |
| `refund_over_charge` | $500 refund on a $50 charge | **Case 1 wow** |
| `wrong_account` | `look_up_customer` returns another customer | Case 3 (RLS) |
| `slow_payment` | 15s payment latency | Case 2 (resilience) |
| `payment_declined` | payments API hard-fails | Case 2 |
| `fraud_unavailable` | A2A fraud service down | Case 2 (fallback) |

---

## Extensibility — how Cases 2 & 3 plug in

The structure is deliberately additive. Nothing below requires touching existing
tool code.

- **New failure modes** → add a scenario (and any new knobs) in
  `backends/faults.py`. Tools already honour `ToolFault`; unknown knobs are
  ignored, so new knobs don't break old tools.
- **New cross-cutting behaviour** (Case 2 circuit breaker / cost-per-span; Case 3
  identity / authz) → register a `CallbackBundle` in `callbacks/registry.py`:

  ```python
  register(CallbackBundle(
      name="resilience",
      before_tool=[circuit_breaker],   # Case 2
      after_tool=[record_cost_and_tokens],
  ))
  ```

  The new callbacks join the chain automatically — every agent picks them up via
  `assemble()`.
- **New specialists** → drop an agent in `sub_agents/` and add it to
  `build_root_agent`'s `sub_agents` list.
- **Real backends** → swap the mock modules in `backends/` (same function
  signatures). Case 3 replaces `customer_db.read_customer` with a BigQuery read
  scoped by the caller's identity (Row-Level Security).

---

## Honest disclaimers (say these on stage)

- The whole **Eval suite is Preview**; credibility rests on the **GA substrate**
  (OTel, Cloud Trace, Cloud Build, BigQuery) and on the invariants being
  **portable** (they run as plain `pytest`).
- The **CI/CD gate is not native** — Cloud Build runs the eval and fails the
  build. Quality Alerts only *notify*.
- **Cost is not captured** by observability; token counts are aggregated.
  Cost-per-span is your own instrumentation (Case 2).
- **EDD ≠ user simulation.** The platform's `generate_conversation_scenarios`
  produces *inputs*; the *criterion of correct* comes from the contract. Naming
  that boundary is the whole differentiation.
