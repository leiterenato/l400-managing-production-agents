# CI wiring — the eval gate (Fase 5)

There is **no native "eval gate"** in the platform. The gate is Cloud Build: a
build runs the eval and a non-zero exit becomes a red build; making that build a
**required status check** on `main` is what actually blocks a merge. This is the
honest story to tell on stage.

Three layers, two build configs:

| Layer | What | Config | When | Blocks merge? |
|------|------|--------|------|---------------|
| **1** | pytest + offline **EDD gate** (`run_offline`) | `cloudbuild.yaml` | pre-submit (PR) | **yes** (required check) |
| **2** | managed **cloud eval** + score gate (`live_run`) | `cloudbuild-postmerge.yaml` | post-merge / nightly | no (notify/record) |
| **3** | **Online Monitor** (`onlineEvaluators`) | `deploy/online_evaluator.py` | production, continuous | no (notify/record) |

Everything below is **ops, done once** — not code. Repo:
`leiterenato/l400-managing-production-agents`, project `YOUR_PROJECT_ID`
(number `YOUR_PROJECT_NUMBER`), region `us-central1`.

---

## 0. Prerequisite — connect the repo to Cloud Build (once)

Pick ONE integration; **the trigger flags below must match the one you chose**
(mixing them is the classic failure — 1st-gen flags with a `--region` fail).

- **1st-gen GitHub App (simplest, global) — what the commands below use.**
  Console: **Cloud Build → Triggers → Connect repository → GitHub (Cloud Build
  GitHub App)** and authorize `leiterenato/l400-managing-production-agents`.
  Triggers then address the repo with `--repo-owner` / `--repo-name` and **no**
  `--region` (1st-gen is global).

- **2nd-gen connection (regional) — alternative.** CLI:
  `gcloud builds connections create github --region=us-central1 ...` then
  `gcloud builds repositories create ... --connection=<CONN> --region=us-central1`.
  Triggers then address the repo with
  `--repository=projects/YOUR_PROJECT_NUMBER/locations/us-central1/connections/<CONN>/repositories/<REPO>`
  **and** `--region=us-central1` (see the note under each trigger). Do NOT use
  `--repo-owner`/`--repo-name` with 2nd-gen.

---

## 1. Camada 1 — pre-submit gate (the required check)

Create a **pull-request** trigger that runs the deterministic gate on every PR
targeting `main`. Build context is the repo root; the config lives under `agent/`
and each step uses `dir: agent`.

```bash
# 1st-gen GitHub App (matches section 0; note: NO --region for 1st-gen).
gcloud builds triggers create github \
  --name=case1-eval-gate \
  --repo-owner=leiterenato \
  --repo-name=l400-managing-production-agents \
  --pull-request-pattern='^main$' \
  --build-config=agent/deploy/cloudbuild.yaml
```

> **2nd-gen instead?** Drop `--repo-owner`/`--repo-name`, add
> `--repository=projects/YOUR_PROJECT_NUMBER/locations/us-central1/connections/<CONN>/repositories/<REPO>`
> **and** `--region=us-central1`.

Then make it a **required status check** so a red build blocks the merge. The
Cloud Build GitHub App posts a status context named `case1-eval-gate` (it may
appear as `case1-eval-gate (YOUR_PROJECT_ID)` on the PR — use the exact
string shown there):

```bash
gh api -X PUT repos/leiterenato/l400-managing-production-agents/branches/main/protection \
  --input - <<'JSON'
{
  "required_status_checks": { "strict": true, "contexts": ["case1-eval-gate"] },
  "enforce_admins": true,
  "required_pull_request_reviews": null,
  "restrictions": null
}
JSON
```

(Or via the GitHub UI: **Settings → Branches → Add branch protection rule** for
`main` → **Require status checks to pass** → select `case1-eval-gate`.)

**Smoke-test the config without a PR** (run from the repo root):

```bash
gcloud builds submit --config agent/deploy/cloudbuild.yaml .
```

Expect a GREEN build on a healthy tree (the EDD gate passes because every seed
case matches its expected verdict). Introduce a regression — e.g. weaken
`refund_within_charge` or break a happy case — and the build goes RED.

---

## 2. Camada 2 — post-merge / nightly managed eval

This calls the Preview Evaluation Service (costs, non-deterministic on
`--mode agent`), so it is **not** a required PR check. Run it either on push to
`main` or nightly.

**Push-to-main trigger:**

```bash
# 1st-gen GitHub App (matches section 0; NO --region for 1st-gen).
gcloud builds triggers create github \
  --name=case1-managed-eval \
  --repo-owner=leiterenato \
  --repo-name=l400-managing-production-agents \
  --branch-pattern='^main$' \
  --build-config=agent/deploy/cloudbuild-postmerge.yaml
```

> **2nd-gen instead?** Same swap as section 1 (`--repository=...` + `--region=us-central1`).

**Nightly instead of on-push:** create the trigger above, then have **Cloud
Scheduler run it** on a schedule — Console: **Cloud Build → Triggers → ⋮ → Run**
gives the trigger a run URL; point a daily Cloud Scheduler HTTP job at it (or use
the Triggers UI "Run trigger" scheduling). Keep the trigger itself; only the
firing is scheduled.

The build prints the **evaluationRun resource name + Console URL** and exits
non-zero when `refund_within_charge` AVERAGE < 1.0. See the config header for
`--mode dataset` (deterministic, red by design) vs `--mode agent` (green when the
deployed agent is healthy).

---

## 3. Camada 3 — Online Monitor (production sentinel)

Not a Cloud Build config — it is a live resource created via REST. See
`deploy/online_evaluator.py` (create/activate/suspend/delete) and
`scripts/drive_engine.py` (traffic driver) for the green→red demo sequence. It
**notifies/records**; it does not gate.
