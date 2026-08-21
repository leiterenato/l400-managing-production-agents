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

**This README covers two things: standing the agent up on Google Cloud, and
generating load against it.** For the agent's internals (the contract, all
failure scenarios, how the resilience and zero-trust layers are wired) read
[`agent/README.md`](agent/README.md).

Every command below is run **from inside the `agent/` directory**, and uses
[`uv`](https://docs.astral.sh/uv/) to manage the virtual environment and the
Python interpreter (Python ≥3.12; `uv sync` provisions both — no manual `venv`
or `pip install` needed).

> **Read this before anything else — how configuration is loaded.** This repo
> has *two* configuration channels and they are not interchangeable:
>
> - **`agent/.env`** is auto-loaded by the `adk` CLI and by the driver scripts
>   under `scripts/` (including all four used below: `live_drive`,
>   `load_test`, `monitoring_demo`, `drive_engine`).
> - **The shell environment** is the *only* channel read by
>   `deploy/agent_engine.py` and by every eval module this README invokes
>   (`evals.run_offline`, `evals.bigquery_scale`, `evals.cost_scale`,
>   `evals.online_monitor`) — **they never read `.env`.**
>
> So: put your settings in `.env` **and** export the core ones in your shell
> (step 1.1 does exactly that). Exported shell variables always win over
> `.env`. Skipping the exports is the #1 way the deploy in step 1.6 fails.

---

## 1. Deploy to a Google Cloud environment

### 1.0 Prerequisites

- A **Google Cloud project with billing enabled**. Every command that reaches
  real GCP costs money (Gemini calls are fractions of a cent each; Agent
  Engine, BigQuery and Monitoring have their own low usage-based costs).
- The [`gcloud` CLI](https://cloud.google.com/sdk/docs/install), authenticated
  with an account allowed to enable APIs and create resources in that project.
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/):
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Access to the `gemini-3.5-flash` publisher model on Vertex AI in your
  project (available by default once `aiplatform.googleapis.com` is enabled).
- The repo cloned locally:
  ```bash
  git clone https://github.com/leiterenato/l400-managing-production-agents.git
  cd l400-managing-production-agents
  ```

### 1.1 One-time GCP project setup

Run this once per GCP project. **Keep this shell open** — steps 1.2–2.5 rely
on the variables it exports (or re-run this block in any new terminal).

```bash
# 1) Project + region.
export PROJECT_ID=<your-project-id>
export REGION=us-central1

# The code reads these two names specifically. Exporting them is REQUIRED:
# deploy/agent_engine.py and the eval modules used below do NOT read agent/.env.
export GOOGLE_CLOUD_PROJECT="$PROJECT_ID"
export GOOGLE_CLOUD_LOCATION="$REGION"

# NOTE: keep GOOGLE_CLOUD_LOCATION regional. Gemini 3.x models only resolve on
# Vertex's "global" endpoint, but the agent's model factory already routes the
# model call there by itself (agent/financial_support/model.py). Setting this
# variable to "global" does NOT help and breaks the regional platform services.

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

# 3) Application Default Credentials — how every script authenticates.
gcloud auth application-default login

# 4) Grant the identity that runs the code the roles it needs. For a project
#    dedicated to this demo, the simplest correct choice is Editor.
#    (The prefix differs for a service account, e.g. on a GCE VM or Cloud Shell.)
ACCOUNT=$(gcloud config get-value account)
case "$ACCOUNT" in
  *gserviceaccount.com) PRINCIPAL="serviceAccount:$ACCOUNT" ;;
  *)                    PRINCIPAL="user:$ACCOUNT" ;;
esac
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="$PRINCIPAL" --role="roles/editor"

# 5) Staging bucket for the Agent Runtime deploy (globally unique name).
export GOOGLE_CLOUD_STAGING_BUCKET="gs://${PROJECT_ID}-agent-staging"
gcloud storage buckets create "$GOOGLE_CLOUD_STAGING_BUCKET" --location="$REGION"
```

<details>
<summary>Narrower roles instead of Editor (shared projects)</summary>

`roles/aiplatform.user`, `roles/bigquery.dataEditor`, `roles/bigquery.jobUser`,
`roles/cloudtrace.agent` (write spans), `roles/cloudtrace.user` (the trace
verification poll in `scripts/live_drive.py`), `roles/logging.logWriter`,
`roles/monitoring.editor`, `roles/storage.objectAdmin` on the staging bucket,
and `roles/cloudbuild.builds.editor` only if you wire the CI gate.
</details>

> **Brand-new project?** `gcloud services enable` can fail with
> `SERVICE_DISABLED` because Service Usage / Resource Manager are themselves
> off. Enable `serviceusage.googleapis.com` and
> `cloudresourcemanager.googleapis.com` once from the Cloud Console as project
> owner, then re-run the `gcloud services enable` block in step 1.1.

### 1.2 Install dependencies

```bash
cd agent
uv sync
```

Creates `agent/.venv` with everything pinned in `pyproject.toml`/`uv.lock`.
Every command below runs through `uv run`, which uses that venv automatically.

### 1.3 Configure the agent

```bash
cp .env.example .env
```

Edit `agent/.env` and set at least `GOOGLE_CLOUD_PROJECT` and
`GOOGLE_CLOUD_LOCATION` to the same values you exported in 1.1. The remaining
variables have working code defaults even when absent from the file — you only
add them to change behaviour. Source of truth:
`agent/financial_support/config.py`.

| Variable | Default | What it does |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | *(none)* | **Required.** Your GCP project id. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Region for platform services (Agent Engine, BigQuery, Trace, Monitoring). |
| `MODEL` | `gemini-3.5-flash` | The model the agent talks to. |
| `CASE` | `1` | Which layer is active: `1` = eval/invariants only, `2` = + circuit breaker and cost budget, `3` = + zero-trust identity. Later cases' callbacks stay dormant until you raise this. |
| `SCENARIO` | `healthy` | Deterministic fault to inject: `healthy`, `refund_over_charge`, `wrong_account`, `slow_payment`, `payment_declined`, `retry_storm`, `fraud_unavailable`. This is how you make the agent misbehave on demand without touching code (`backends/faults.py`). |
| `INVARIANT_ENFORCEMENT` | `observe` | `observe`: let the bad action stand so the eval catches it later (the "the green score lies" story). `block`: the runtime callback refuses it. |
| `TELEMETRY_ENABLED` | `true` | Installs a local tracer provider when nothing else has. **Cloud Trace export is turned on by the `--otel_to_cloud` CLI flag.** The `OTEL_TO_CLOUD` line in `.env.example` is parsed into `Settings` but read by no code — setting it has no effect. |
| `BREAKER` | `off` | Case 2: master switch for the semantic circuit breaker. |
| `BREAKER_OPEN_AFTER` | `3` | Case 2: slow-or-failed calls before the circuit opens. |
| `BREAKER_TIMEOUT_S` | `5.0` | Case 2: what counts as "slow" — a call is a failure if it errors **or** exceeds this many seconds. |
| `SESSION_BUDGET_USD` | `0.50` | Case 2: per-session cost budget the agent self-enforces. |
| `CUSTOMER_DB_BACKEND` | `mock` | Case 3: `mock` uses an in-memory fixture. `bigquery` runs the lookup as the caller's own identity so IAM returns a real 403 — this needs one-time provisioning via `scripts/setup_case3_identity.sh` (override its `GOOGLE_CLOUD_PROJECT`/`IMPERSONATOR` defaults; needs project Owner). |

`.env.example` covers the model/platform, `CASE`, `SCENARIO`,
`INVARIANT_ENFORCEMENT`, telemetry and the A2A settings. The Case 2 and Case 3
variables above (`BREAKER*`, `SESSION_BUDGET_USD`, `CUSTOMER_DB_BACKEND`) are
absent from it, which is fine — add them only to override the defaults.

### 1.4 Validate offline first (no GCP calls, no cost)

```bash
uv run pytest -q                      # expect: 103 passed
uv run python -m evals.run_offline    # expect: "EDD gate GREEN", exit 0
```

**Read the output carefully.** `run_offline` prints `cases=6 red=4 (4 expected
catches) EDD_gate=OK` and **exits 0**. Those 4 red invariants are the
adversarial seed cases the checks are *supposed* to catch — the gate blocks
only on a **regression**, meaning a verdict that diverged from what
`evals/data/eval_cases.json` expects. A red gate here is a real problem, not
normal output.

To watch the gate legitimately go red (this is the "Deploy Blocked" demo — it
stages one regression where a healthy refund starts over-paying):

```bash
DEMO_REGRESSION=1 uv run python -m evals.run_offline   # expect: "BLOCK MERGE", exit 1
```

*(Both commands above were run against a clean clone of this repo while writing
these instructions; the stated outputs and exit codes are what they actually
produce.)*

### 1.5 Run the agent locally against real Vertex AI

Real model calls (billable), no deploy.

```bash
uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud
```

Open <http://localhost:8000>. ⚠️ The picker lists **every subdirectory of
`agent/`** — `deploy`, `evals`, `financial_support`, `fraud_check_a2a`,
`scripts`, `tests` — because that is simply how `adk web` enumerates an agents
directory. Only two of those are real agents: choose **`financial_support`**
(`fraud_check_a2a` is the external fraud service used only for the A2A demo).
The other four will fail to load. Send it something like
*"Please refund my $50 monthly subscription, charge TXN-1001."* and watch the
tool trajectory `look_up_customer → transfer_to_agent → fraud_check →
issue_refund`. With `--otel_to_cloud`, the run also lands a trace in **Cloud
Trace → Trace explorer** within a minute or two.

### 1.6 Deploy to the Agent Runtime (managed production)

Publishes the agent as a managed Vertex AI `ReasoningEngine` — a real
production endpoint to point load and monitoring at.

```bash
# These MUST be exported in the shell — agent_engine.py does not read .env.
# (Step 1.1 already exported all three; re-export if you opened a new terminal.)
echo "$GOOGLE_CLOUD_PROJECT / $GOOGLE_CLOUD_LOCATION / $GOOGLE_CLOUD_STAGING_BUCKET"

CASE=1 SCENARIO=healthy DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

`DEPLOY_CONFIRM=1` is mandatory by design — this creates a billable resource;
omitting it exits **3**. If `GOOGLE_CLOUD_PROJECT` or
`GOOGLE_CLOUD_STAGING_BUCKET` is missing, the script exits **4** with
`Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_STAGING_BUCKET (gs://...) before
deploying.` Note that **`GOOGLE_CLOUD_LOCATION` is not validated** — if unset
it silently defaults to `us-central1`, so export it explicitly if you work in
another region. On success:

```
Deployed to Agent Runtime (Agent Engine).
  resource: projects/123456789/locations/us-central1/reasoningEngines/1234567890123456789
  Traces -> Cloud Trace; the Online Monitor samples them (S4).
```

**Save that `resource:` value** — section 2 needs it. You can also find it
under **Vertex AI → Agent Engines** in the Console.

```bash
export AGENT_ENGINE=<the resource: value printed above>
```

To change a setting on an existing deployment without losing its id, redeploy
in place (this is also how you arm a fault on the deployed agent):

```bash
UPDATE_RESOURCE="$AGENT_ENGINE" CASE=1 SCENARIO=refund_over_charge \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

Notes:
- The first deploy is slow (cold start of a new managed service) — expected.
- `agent/deploy/agent_engine.py` lists every variable it forwards into the
  deployed container (cost logging, breaker tuning, Case 3 backend, …).
- Optional: to run the eval gate automatically on pull requests, see
  [`agent/deploy/README-ci.md`](agent/deploy/README-ci.md). ⚠️ That document is
  written against the presenter's own project and GitHub repo — substitute
  your project id, project number and repo before using its commands, **and
  edit `_STAGING_BUCKET` in `deploy/cloudbuild-postmerge.yaml:26`** (it is
  hardcoded to `gs://YOUR_PROJECT_ID-agent-staging`).
- **Clean up when done** — a deployed engine bills until deleted:
  ```bash
  uv run python -c "
  import os, vertexai
  from vertexai import agent_engines
  vertexai.init(project=os.environ['GOOGLE_CLOUD_PROJECT'],
                location=os.environ['GOOGLE_CLOUD_LOCATION'])
  agent_engines.get(os.environ['AGENT_ENGINE']).delete(force=True)
  "
  ```
  `force=True` is required once you have run section 2: driving the engine
  creates Session child resources, and a plain `.delete()` then fails with
  `FAILED_PRECONDITION` — leaving the engine running and billing.

---

## 2. Generate load (simulate traffic) against the agent

A single chat message shows you nothing about observability, resilience or
cost. These scripts simulate concurrent users so the behaviour becomes visible.
All are run from `agent/`.

> ⚠️ **Export `AGENT_ENGINE` in the shell** (step 1.6 already did). Putting it
> only in `.env` works for `scripts/drive_engine.py`, but **not** for
> `scripts/load_test.py`, which reads it at **import time**, before `.env` is
> loaded — there, pass `--engine` explicitly or export the variable.
> `load_test.py` also honours `AGENT_ENGINE_C2`, which takes precedence when
> set. If `AGENT_ENGINE` is missing, `drive_engine` now exits 4 with a message
> rather than guessing an engine.

### 2.1 One scripted run, with automatic trace verification

The fastest end-to-end check: drives the agent once, exports a trace, and polls
the Cloud Trace API until it appears.

```bash
uv run python -m scripts.live_drive --scenario refund_over_charge
```

Expect the tool trajectory, the final reply, an **invariant violation** (this
scenario deliberately over-pays the refund), a trace id and a Cloud Trace
console link, then the verification result — which may report "trace not
visible via API yet" on the first attempt, since ingest lags ~1–2 min; open the
link anyway. Use `--scenario healthy` for a clean run. `--no-cloud` skips only
the export and the verification poll — **it still makes a real, billable model
call**; for a genuinely free check use `uv run pytest -q`.

### 2.2 Drive N concurrent requests against the deployed engine

```bash
uv run python -m scripts.drive_engine --n 8 --concurrency 2
```

Fires 8 refund requests (2 in flight) at `$AGENT_ENGINE` through its
`stream_query` API. Each produces a real trace scoped to that engine — exactly
what an Online Monitor samples in production. The script also tallies how many
refunds stayed **within the charged amount** (invariant green) versus
**over-refunded** (invariant red).

To actually see red here, the **deployed** engine must be armed — the fault is
baked in at deploy time, and step 1.6 deployed `SCENARIO=healthy`. Redeploy in
place first:

```bash
UPDATE_RESOURCE="$AGENT_ENGINE" CASE=1 SCENARIO=refund_over_charge \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

That is the Case 1 story under load: the reply text always reads fine, but the
money that moved does not always match it.

### 2.3 The resilience A/B: same load, breaker OFF vs. ON (Case 2)

The most illustrative script. It runs the **same load twice** — once with the
circuit breaker disabled, once enabled — and prints a side-by-side table.

```bash
# runs locally (no deploy needed) but every session is a REAL, billable
# Vertex call; simulates a slow payment dependency
CASE=2 BREAKER_OPEN_AFTER=2 uv run python -m scripts.load_test \
  --ab --scenario slow_payment --n 6 --concurrency 2
```

It prints a seven-row comparison — `sessions`, `total tokens`, `total cost`
(formatted to four decimals, e.g. `$0.1700`), `p50 latency`, `p95 latency`,
`breaker-open (fallback)`, `errors`:

```
+-------------------------+-------------+------------+
| metric                  | BREAKER OFF | BREAKER ON |
+-------------------------+-------------+------------+
| sessions                |           6 |          6 |
| total tokens            |        high |        low |   <- roughly 3x fewer
| total cost              |        high |        low |   <- tracks the tokens
| p50 latency             |        high |        low |
| p95 latency             |        high |        low |   <- the storm's tail
| breaker-open (fallback) |           0 |        > 0 |   <- the fix engaging
| errors                  |         0-n |          0 |
+-------------------------+-------------+------------+
```

Don't expect stable numbers: the OFF pass is a non-deterministic retry storm,
so its totals swing run to run. The **direction** is the point, and the
`breaker-open` row going from 0 to non-zero is what proves the mechanism fired.

OFF, the slow dependency drives latency and tokens up as retries pile on. ON,
the breaker opens after a couple of slow calls and the rest of the fleet fails
fast with an injected, honest fallback instead of retrying. Try
`--scenario retry_storm` (slow *and* failing) for the sharpest contrast.

`--ab` is **local-only**: a deployed engine's breaker state is fixed at deploy
time, so flipping the variable in the local driver process cannot change it
remotely (the script rejects that combination outright). To compare on the
deployed engine, redeploy between the two passes:

```bash
# pass A — breaker off
UPDATE_RESOURCE="$AGENT_ENGINE" CASE=2 SCENARIO=slow_payment BREAKER=off \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
uv run python -m scripts.load_test --target engine \
  --n 8 --concurrency 4 --engine "$AGENT_ENGINE"

# pass B — breaker on
UPDATE_RESOURCE="$AGENT_ENGINE" CASE=2 SCENARIO=slow_payment BREAKER=on \
  BREAKER_OPEN_AFTER=2 DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
uv run python -m scripts.load_test --target engine \
  --n 8 --concurrency 4 --engine "$AGENT_ENGINE"
```

⚠️ With `--target engine`, the `--breaker` and `--scenario` flags are **inert**
— they only mutate the local driver process, while the agent runs remotely with
whatever was baked in at deploy time. That is why the redeploys above are what
actually changes the behaviour.

### 2.4 A live Cloud Monitoring dashboard: baseline → incident → recovery

Three acts against the real agent: healthy traffic, then an incident (slow
dependency, breaker off), then recovery (same incident, breaker on).

```bash
# import the prebuilt dashboard once
gcloud monitoring dashboards create --config-from-file=scripts/case2_dashboard.json

# smoke test — short acts, confirms metrics reach Cloud Monitoring
CASE=2 uv run python -m scripts.monitoring_demo --smoke --run-label case2-final

# a fuller run: longer acts make the timeline legible (real Vertex cost)
CASE=2 uv run python -m scripts.monitoring_demo \
  --act-seconds 300 --concurrency 6 --run-label case2-final
```

⚠️ **`--run-label case2-final` is required.** Every chart in
`case2_dashboard.json` filters on `metric.label."run"="case2-final"`, but the
script's own default label is `case2-slide10` — omit the flag and the dashboard
stays empty.

Open **Cloud Monitoring → Dashboards → "Case 2 — Contain the Blast (Slide
10)"**. Its three tiles are request latency (**p50**), sessions/min
(throughput) and breaker-open fallbacks/min: the storm spikes during the
incident act and flattens during recovery. `request_latency_p95` and
`request_latency_mean` are also published but not charted — find them in
Metrics Explorer under `custom.googleapis.com/agent/`. Per-request cost is not
here either; it lives as the `gen_ai.cost.usd` attribute on `call_llm` spans in
Cloud Trace, and per-tenant in BigQuery via 2.5.

### 2.5 Scale artifacts: BigQuery trend and cost-per-tenant

One run shows no trend. These seed and query real BigQuery tables that do.

```bash
# Case 1: weeks of evaluated traces -> the weekly invariant failure-rate trend
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_LOCATION=US uv run python -m evals.bigquery_scale --seed
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_LOCATION=US uv run python -m evals.bigquery_scale --live

# Case 2: per-tenant cost spans -> cost by tenant (one tenant ~10x the rest)
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_LOCATION=US uv run python -m evals.cost_scale --seed
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_LOCATION=US uv run python -m evals.cost_scale --live
```

⚠️ **`GOOGLE_CLOUD_LOCATION=US` on these four commands is deliberate.** The
seeder creates the dataset in `GOOGLE_CLOUD_LOCATION`, but the `--live` query
runs without an explicit location (so BigQuery defaults to the `US`
multi-region). Leaving your regional `us-central1` in place makes `--seed`
succeed and `--live` then fail with *"Dataset … not found in location US"*.

`EVAL_LIVE_CONFIRM=1` is required because these create and query real,
billable BigQuery resources. Run the same modules with **no flags** to render
the identical tables from synthetic local data, with zero GCP cost:

```bash
uv run python -m evals.bigquery_scale   # synthetic trend, no creds, no cost
uv run python -m evals.cost_scale       # synthetic cost-by-tenant, no creds, no cost
uv run python -m evals.online_monitor   # rolling-window sentinel + alert (fully local)
```

`evals.online_monitor` is a self-contained simulation of the production
sentinel — no GCP, no flags, no cost. It shows the same invariant that gates
the merge firing an alert as quality degrades.

---

## 3. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Set GOOGLE_CLOUD_PROJECT and GOOGLE_CLOUD_STAGING_BUCKET ... before deploying` (exit 4) | `deploy/agent_engine.py` reads only the shell environment, never `agent/.env` | Re-run the exports from step 1.1 in the current terminal |
| `Set AGENT_ENGINE to the resource name printed by deploy/agent_engine.py` (exit 4) | `AGENT_ENGINE` is unset | `export AGENT_ENGINE=<your resource name>` from step 1.6 |
| `load_test --target engine` ignores your `AGENT_ENGINE` | `load_test.py` reads it at **import time**, before `.env` loads, and prefers `AGENT_ENGINE_C2` | Export it in the shell, or pass `--engine "$AGENT_ENGINE"` |
| Deleting the engine fails with `FAILED_PRECONDITION` | Load runs created Session child resources | Use `.delete(force=True)` — see the cleanup snippet in 1.6 |
| `--live` fails with *"Dataset … not found in location US"* | Dataset was seeded in a regional location, the query runs in the `US` multi-region | Prefix both `--seed` and `--live` with `GOOGLE_CLOUD_LOCATION=US` (section 2.5) |
| The Case 2 dashboard is empty | Metrics were published under the default `case2-slide10` label; the dashboard filters `case2-final` | Re-run `monitoring_demo` with `--run-label case2-final` |
| `gcloud services enable` fails with `SERVICE_DISABLED` | Service Usage / Resource Manager are off in a new project | Enable both from the Console as owner, then retry |
| `404` on the model, or "only available in global" | `GOOGLE_CLOUD_LOCATION` was set to `global`, or the project lacks Gemini 3.x access | Keep it regional — the agent already routes the model call to `global` internally |
| Auth/credentials errors everywhere | No Application Default Credentials | `gcloud auth application-default login` (on a GCE VM, confirm the `cloud-platform` scope) |
| A trace never appears in Cloud Trace | Ingest lag, or `--no-cloud` / no `--otel_to_cloud` | Wait ~2 min and confirm you passed `--otel_to_cloud`. Setting `OTEL_TO_CLOUD=true` in `.env` does **not** work — it is parsed into `Settings` but no code reads it |
| `load_test --ab --target engine` is rejected | The deployed breaker state is baked at deploy time, so an in-process flip would make the table a lie | Deploy twice (`BREAKER=off`, then `BREAKER=on` via `UPDATE_RESOURCE`) and drive each separately |
| `run_offline` prints 4 red invariants | Expected — those are the adversarial cases the checks are meant to catch | Only a **regression** (`EDD_gate=BLOCK MERGE`, exit 1) is a real failure |

---

## Disclaimer and license

This is **sample code written for a conference talk**, not a production
library. It is optimised to make failure modes visible on stage: it injects
faults on purpose, ships an intentionally over-refunding scenario, and takes
shortcuts a real financial system would not. Read it as an illustration of the
patterns — eval-driven development, semantic circuit breaking, zero-trust data
access — and not as something to deploy as-is.

Running it costs real money. Every scenario in section 2 makes billable Vertex
AI calls, and a deployed Agent Engine bills until you delete it (see the
cleanup snippet in 1.6). Use a dedicated project and tear it down when done.

This is a personal project and is not an officially supported Google product.

Licensed under the [Apache License 2.0](LICENSE).
