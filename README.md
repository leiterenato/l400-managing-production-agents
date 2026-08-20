# l400-managing-production-agents

This repository is the companion code for the talk **"Managing Production
Agents at Scale — from Chaos to Reliability"** (L400 session, 30 min). It
exists to show, with a real agent running on Google Cloud, the three problems
almost every team hits once an agent leaves the demo and reaches production —
and how to fix each one:

1. **You change the agent and can't tell if you made it worse.** Fixed with
   **Eval-Driven Development (EDD)**: deterministic contracts/invariants
   tested before every deploy and continuously in production (**Case 1**).
2. **One slow dependency takes down the whole fleet — and the bill with it.**
   Fixed with **resilience**: a semantic circuit breaker, honest degradation,
   and a per-session cost budget (**Case 2**).
3. **A malicious message turns the agent against you.** Fixed with
   **zero-trust**: the infrastructure itself (IAM + Row-Level Security)
   denies access at the data boundary, instead of relying only on a prompt
   filter (**Case 3**).

All three cases are **the same agent** — a financial-support assistant that
looks up a customer, runs a fraud check, and issues refunds — maturing over
time. Nothing is rewritten between cases; each case only adds a new layer on
top of the previous one.

## Repository structure

```
agent/                     # the code: the ADK agent + evals + deploy + load scripts + tests
  financial_support/       # the agent itself (orchestrator + sub-agents + tools + callbacks)
    contract.py            #   the behavioural contract / invariants (the EDD source of truth)
    config.py              #   every env-driven setting, in one place (see table below)
    backends/faults.py     #   deterministic fault injection ("scenarios" like slow_payment)
  fraud_check_a2a/         # a second, external agent, served over the A2A protocol
  evals/                   # the Case 1 evaluation harness: metrics, offline gate, online
                           # monitor, BigQuery trend/cost queries
  deploy/                  # deploy/agent_engine.py (Agent Runtime deploy) + Cloud Build configs
  scripts/                 # drivers to run/observe the agent and GENERATE LOAD (see below)
  tests/                   # pytest — the portable, deterministic core
  README.md                # full technical documentation of the agent (structure, quickstart,
                           # every demo scenario, how Cases 2/3 plug into Case 1)
  .env.example             # configuration template (project, model, active scenario, etc.)

demos/                     # presentation runbooks, speaker notes, live-implementation plans
docs/                      # narrative/fundamentals per case (Case 2, Case 3, agent evaluation)
en/                        # English talk material: slide source, one-pagers, per-case description
```

**This README covers only two things: standing the agent up on Google Cloud,
and generating load against it.** For everything about the agent's internals
(the contract, the available failure scenarios, how the resilience and
zero-trust layers are wired) read [`agent/README.md`](agent/README.md) — it is
the primary technical reference.

Every command below is run **from inside the `agent/` directory**, and uses
[`uv`](https://docs.astral.sh/uv/) to manage the Python 3.12 virtual
environment (`uv sync` installs it automatically — no manual venv needed).

---

## 1. Deploy to a Google Cloud environment

### 1.0 Prerequisites

Before starting, make sure you have:

- A **Google Cloud project with billing enabled**. Every command that talks
  to real GCP resources costs a small amount of money (Gemini calls are
  fractions of a cent each; Agent Engine and BigQuery have their own low
  usage-based costs). Nothing here is free-tier-only.
- The [`gcloud` CLI](https://cloud.google.com/sdk/docs/install) installed and
  logged in as a user (or service account) with permission to enable APIs and
  create resources in that project.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed
  locally (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- This repository cloned locally, with a shell open at its root.
- Access to the `gemini-3.5-flash` publisher model on Vertex AI in your
  project (this is the model the agent itself talks to; it must be enabled/
  available — most projects have it by default once `aiplatform.googleapis.com`
  is on).

Everything from here on assumes these are satisfied.

### 1.1 One-time GCP project setup

Run this once per GCP project you plan to use for the demo.

```bash
# 1) Pick the project + region. Replace PROJECT_ID with your real project id.
export PROJECT_ID=<your-project-id>
export REGION=us-central1   # the platform region. NOTE: Gemini 3.x models only
                             # resolve on Vertex's "global" endpoint; the agent's
                             # model client already routes there automatically
                             # (see agent/financial_support/model.py) — you do
                             # NOT need to (and must NOT) set REGION=global here,
                             # that would break the regional platform services.

gcloud config set project "$PROJECT_ID"

# 2) Enable the APIs this repo uses.
gcloud services enable \
  aiplatform.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com \
  storage.googleapis.com

# 3) Application Default Credentials (ADC) — every script and the ADK CLI
#    read these to call Vertex AI / Trace / Logging / BigQuery.
gcloud auth application-default login

# 4) Grant the identity that will run the code (your own user, or the service
#    account behind a VM/Cloud Shell) the roles it needs. For a project used
#    ONLY for this demo, the simplest correct choice is:
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$(gcloud config get-value account)" \
  --role="roles/editor"
#    Editor covers Vertex AI, BigQuery, Logging, Trace, Cloud Build and GCS,
#    which is everything this README's deploy/load-generation steps touch. If
#    you'd rather grant narrower roles in a shared project, the equivalent set
#    is: roles/aiplatform.user, roles/bigquery.dataEditor, roles/bigquery.jobUser,
#    roles/logging.logWriter, roles/monitoring.editor, roles/storage.objectAdmin
#    (on the staging bucket) and roles/cloudbuild.builds.editor (only if you
#    wire the CI gate from agent/deploy/README-ci.md). Note: wiring the
#    optional Logging -> BigQuery sink used by the "audit log" flywheel in
#    agent/README.md needs a broader Logging role and is not covered here.

# 5) Create the staging bucket the Agent Runtime deploy needs to stage the
#    agent's packaged code. The name must be globally unique.
export STAGING_BUCKET="gs://${PROJECT_ID}-agent-staging"
gcloud storage buckets create "$STAGING_BUCKET" --location="$REGION"
```

> If this is a brand-new project, `gcloud services enable` can fail with
> `SERVICE_DISABLED` because the Service Usage / Cloud Resource Manager APIs
> themselves are not yet on. If that happens, enable
> `serviceusage.googleapis.com` and `cloudresourcemanager.googleapis.com`
> once from the Cloud Console (as the project owner), then re-run step 2.

### 1.2 Install dependencies

```bash
cd agent
uv sync
```

This creates `agent/.venv` and installs every dependency pinned in
`pyproject.toml`/`uv.lock` (the ADK, `google-cloud-aiplatform`, OpenTelemetry
exporters, etc.). You never need to `pip install` or activate the venv by
hand — every command below is run through `uv run`, which does that for you.

### 1.3 Configure the agent

```bash
cp .env.example .env
```

Then edit `agent/.env` and set at least:

```bash
GOOGLE_CLOUD_PROJECT=<your-project-id>
GOOGLE_CLOUD_LOCATION=us-central1
```

The rest of the file already has sensible defaults for a first run. The
variables that matter, and what they control (full source of truth:
`agent/financial_support/config.py`):

| Variable | Default | What it does |
|---|---|---|
| `MODEL` | `gemini-3.5-flash` | The model the agent talks to. |
| `GOOGLE_CLOUD_PROJECT` | — | **Required.** Your GCP project id. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Region for platform services (Agent Engine, BigQuery, Trace, Monitoring). |
| `CASE` | `1` | Which case's extra behaviour is active: `1` = eval/invariants only, `2` = + circuit breaker/cost budget, `3` = + zero-trust identity checks. Later cases' code is dormant until you raise this. |
| `SCENARIO` | `healthy` | Which deterministic fault to inject. One of `healthy`, `refund_over_charge`, `wrong_account`, `slow_payment`, `payment_declined`, `fraud_unavailable`. This is how you make the agent misbehave on demand, without touching any code. |
| `INVARIANT_ENFORCEMENT` | `observe` | `observe`: let a bad action happen and let the eval catch it later (the "the green score lies" story). `block`: the runtime callback refuses the action outright. |
| `TELEMETRY_ENABLED` / `OTEL_TO_CLOUD` | `true` / `false` | Whether spans are exported to Cloud Trace. |
| `BREAKER` | `off` | Case 2: master switch for the semantic circuit breaker. |
| `SESSION_BUDGET_USD` | `0.50` | Case 2: per-session cost budget the agent self-enforces. |
| `CUSTOMER_DB_BACKEND` | `mock` | Case 3: `mock` uses an in-memory fixture; `bigquery` runs the customer lookup as the caller's own identity against BigQuery, so IAM can return a real 403. |

### 1.4 Validate offline first (no GCP calls, no cost)

Before spending any money on real model calls, confirm the code itself is
healthy:

```bash
uv run pytest -q                 # the full test suite
uv run python -m evals.run_offline   # the deterministic EDD gate (record -> evaluate -> report)
```

`run_offline` is expected to **exit non-zero** on a healthy checkout — by
design it stages several failing scenarios (like `refund_over_charge`) to
prove the invariant catches them. That is the gate working correctly, not a
bug.

### 1.5 Run the agent locally against real Vertex AI

This talks to the real model and (optionally) exports real traces to Cloud
Trace, but does not deploy anything.

```bash
# exports OTel spans to Cloud Trace, exactly like a production deploy would
uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud
```

Open `http://localhost:8000` and send it a message, e.g. *"Please refund my
$50 monthly subscription, charge TXN-1001."* Watch the terminal for tool
calls (`look_up_customer -> transfer_to_agent -> fraud_check -> issue_refund`).
If `OTEL_TO_CLOUD`/`--otel_to_cloud` is on, the run also produces a trace in
**Cloud Trace → Trace list** in your project within a minute or two.

### 1.6 Deploy to the Agent Runtime (managed production)

This step publishes the agent as a managed, autoscaling service (a Vertex AI
`ReasoningEngine`) — a real "production" endpoint you can point load and
monitoring at, instead of only running it on your machine.

```bash
export GOOGLE_CLOUD_STAGING_BUCKET="$STAGING_BUCKET"   # from step 1.1

# CASE selects which layer of behaviour ships (1, 2, or 3 — see the table above).
# SCENARIO arms a deterministic fault so you have something interesting to see
# once traffic hits it (use "healthy" for a first, uneventful deploy).
CASE=1 SCENARIO=healthy DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

`DEPLOY_CONFIRM=1` is required on purpose — this creates a billable resource,
so the script refuses to run without it. On success it prints something like:

```
Deployed to Agent Runtime (Agent Engine).
  resource: projects/123456789/locations/us-central1/reasoningEngines/1234567890123456789
```

**Save that `resource:` line** — it is the `AGENT_ENGINE` identifier every
load-generation command in section 2 needs. You can also find it later at
**Vertex AI → Agent Engines** in the Cloud Console.

To change a setting (e.g. flip `SCENARIO` or `BREAKER`) on an existing
deployment without losing its id/history, redeploy in place:

```bash
UPDATE_RESOURCE=<resource_name_from_above> CASE=1 SCENARIO=refund_over_charge \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

Notes:
- The first deploy is slow (cold start of a new managed service); this is
  expected, not an error.
- See `agent/deploy/agent_engine.py` for the full list of environment
  variables it forwards to the deployed container (cost logging, breaker
  tuning, Case 3 identity backend, etc.).
- To wire the automated evaluation gate on pull requests / merges to `main`
  (Cloud Build running `evals.run_offline` as a required check), follow
  [`agent/deploy/README-ci.md`](agent/deploy/README-ci.md) — that is a
  separate, optional layer on top of the manual deploy above.
- **Clean up when you're done** — a deployed Agent Engine keeps running (and
  billing) until deleted:
  ```bash
  uv run python -c "
  import vertexai
  from vertexai import agent_engines
  vertexai.init(project='$PROJECT_ID', location='$REGION')
  agent_engines.get('<resource_name>').delete()
  "
  ```

---

## 2. Generate load (simulate traffic) against the agent

Once the agent is running — locally (1.5) and/or deployed (1.6) — use the
scripts below to simulate multiple concurrent users. A single manual chat
message does not show you observability, resilience, or cost in action; a
batch of concurrent, scripted requests does. All commands below are run from
`agent/`, with `.env` already filled in from step 1.3.

### 2.1 One scripted run with automatic trace verification

The quickest way to confirm everything is wired end-to-end: this drives the
agent once, exports a trace, and polls Cloud Trace's API until it shows up.

```bash
uv run python -m scripts.live_drive --scenario refund_over_charge
```

Expected output: the tool-call trajectory, the final response text, an
**invariant violation** (this scenario deliberately over-pays the refund), a
trace id, and a direct Cloud Trace console link once the trace is verified
(ingest lag is ~1-2 minutes). Use `--scenario healthy` for a clean run with no
violation, or `--no-cloud` to skip the export entirely (useful for a fast,
free sanity check).

### 2.2 Drive N concurrent requests against the deployed engine

```bash
export AGENT_ENGINE=<resource_name_from_step_1.6>
uv run python -m scripts.drive_engine --n 8 --concurrency 2
```

This fires 8 refund requests (2 at a time) at the deployed engine over its
`stream_query` API. Each one produces a real trace scoped to that engine
(`cloud.resource_id`) — the same traces an Online Monitor would sample in
production. The script also tallies, client-side, how many refunds stayed
**within the charged amount** (the invariant holding, green) versus how many
**over-refunded** (the invariant breaking, red) — this is the Case 1 "the
green score lies" story made visible under load: the reply text always reads
fine, but the money moved does not always match it.

### 2.3 The resilience A/B: same load, circuit breaker OFF vs. ON (Case 2)

This is the most illustrative script to "see it all working": it runs the
**exact same load twice** — once with the circuit breaker disabled, once with
it enabled — and prints a side-by-side table of latency, tokens, cost, and
how many calls were short-circuited.

```bash
# fully local, no deploy required — targets a simulated slow dependency
CASE=2 BREAKER_OPEN_AFTER=2 uv run python -m scripts.load_test \
  --ab --scenario slow_payment --n 6 --concurrency 2
```

Expected shape of the result (exact numbers vary run to run):

```
+-------------------------+-------------+------------+
| metric                  | BREAKER OFF | BREAKER ON |
+-------------------------+-------------+------------+
| total tokens            |     ~95,000 |    ~31,000 |
| total cost              |      ~$0.17 |     ~$0.01 |
| p95 latency             |       ~200s |       ~40s |
| breaker-open (fallback) |           0 |          4 |
+-------------------------+-------------+------------+
```

With the breaker OFF, the slow dependency drives latency and token usage way
up (retries pile up). With it ON, the breaker opens after a few slow calls
and the rest of the fleet fails fast with an honest, injected fallback fact
instead of continuing to retry.

To run the same idea against the **deployed** engine instead of locally, note
that the breaker state is baked in at deploy time (an in-process flag), so a
true A/B there means two deploys — one with `BREAKER=off`, one with
`BREAKER=on` (via `UPDATE_RESOURCE=...`, see 1.6) — each driven separately:

```bash
uv run python -m scripts.load_test --target engine --breaker on \
  --n 8 --concurrency 4 --engine "$AGENT_ENGINE"
```

### 2.4 A live Cloud Monitoring dashboard: baseline → incident → recovery

To watch the effect of load on a Cloud Monitoring dashboard/timeline instead
of only in the terminal, use the three-act driver: healthy traffic, then an
incident (slow dependency, breaker off), then recovery (same incident,
breaker on).

```bash
# smoke test first — short acts, confirms metrics actually reach Cloud Monitoring
CASE=2 uv run python -m scripts.monitoring_demo --smoke

# a fuller run (longer acts -> a more legible dashboard; real cost, keep modest)
CASE=2 uv run python -m scripts.monitoring_demo --act-seconds 300 --concurrency 6
```

Open **Cloud Monitoring → Metrics Explorer** in the Console (or build a
dashboard from `agent/scripts/case2_dashboard.json`) to see latency, cost,
and the "breaker opened" count spike during the incident act and fall during
recovery.

### 2.5 Scale artifacts: BigQuery trend + cost-per-tenant + online monitor

A single run or a short A/B doesn't show a trend over time. These populate
and query BigQuery tables that do:

```bash
# Case 1: seed weeks of evaluated traces, then read the real weekly failure-rate trend
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --seed
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --live

# Case 2: seed per-tenant cost spans, then read cost-by-tenant (one tenant ~10x the rest)
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_PROJECT="$PROJECT_ID" uv run python -m evals.cost_scale --seed
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_PROJECT="$PROJECT_ID" uv run python -m evals.cost_scale --live

# a rolling-window sentinel that fires an alert when the invariant degrades
uv run python -m evals.online_monitor
```

`EVAL_LIVE_CONFIRM=1` is required for the same reason `DEPLOY_CONFIRM=1` is:
these create/query real, billable BigQuery resources. Without it, running the
same modules with no flags (e.g. `uv run python -m evals.bigquery_scale`)
renders the same tables against **synthetic, local data** — good for
exploring the shape of the demo with zero GCP cost.

---

## 3. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `gcloud services enable` fails with `SERVICE_DISABLED` | Service Usage / Resource Manager APIs are themselves off in a brand-new project | Enable `serviceusage.googleapis.com` and `cloudresourcemanager.googleapis.com` once via the Console as the project owner, then retry |
| `404` calling the model, or "model only available in global" | You set `GOOGLE_CLOUD_LOCATION=global` (breaks regional platform services) or your project lacks Gemini 3.x access | Keep `GOOGLE_CLOUD_LOCATION` regional (e.g. `us-central1`) — the agent already routes the model call to the `global` endpoint internally; do not override it |
| Everything fails with an auth/credentials error | No Application Default Credentials | Re-run `gcloud auth application-default login` (or, on a GCE/Cloud Shell VM, confirm it has the `cloud-platform` scope) |
| `evals.run_offline` / `load_test --ab` A/B pass looks unchanged after switching `BREAKER` | Settings are cached per-process | The scripts already call `reload_settings()` after flipping env vars; if you're scripting your own driver, do the same |
| A trace never shows up in Cloud Trace | Ingest lag (wait ~1-2 min) or `OTEL_TO_CLOUD=false` / `--no-cloud` was set | Re-run without `--no-cloud`, or just wait and refresh the Console |
| `--ab` against `--target engine` shows no contrast | The deployed engine's breaker state is baked in at deploy time; flipping the env var locally does not change it remotely | Redeploy the engine once with `BREAKER=off` and once with `BREAKER=on` (`UPDATE_RESOURCE=...`) and drive each separately |
