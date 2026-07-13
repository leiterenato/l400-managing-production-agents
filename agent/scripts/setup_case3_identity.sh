#!/usr/bin/env bash
# Fase 0 — provisioning for the Case 3 (Zero-Trust) real 403.
#
# Stands up the ONLY genuinely-real beat of the talk: a per-tenant BigQuery
# resource model where IAM (not code) denies a cross-account read. Two service
# accounts stand in for two users; the demo driver (scripts/identity_ab.py)
# impersonates each and reads the SAME account — the owner gets the row, the
# other gets a real 403 PERMISSION_DENIED from IAM.
#
# Steps are tagged:
#   [editor] runnable by the VM's Compute SA (roles/editor)
#   [OWNER]  needs a human Owner (setIamPolicy) — run these with `gcloud auth login`
#            as an Owner, or do them once in the Console.
#
# Idempotent-ish: creates use `|| true` so re-runs are safe. Review before running.
#
#   bash scripts/setup_case3_identity.sh            # provision
#   bash scripts/setup_case3_identity.sh validate   # just the 403 pre-check
set -uo pipefail

# --- Config (override via env) ----------------------------------------------
PROJECT="${GOOGLE_CLOUD_PROJECT:-YOUR_PROJECT_ID}"
LOCATION="${BQ_LOCATION:-us-central1}"
# The running identity that impersonates the two user SAs (keyless).
IMPERSONATOR="${IMPERSONATOR:-YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com}"
# The two per-user principals. A owns CUST-001; B owns CUST-002 (no access to A).
SA_A_NAME="${SA_A_NAME:-sa-user-a}"
SA_B_NAME="${SA_B_NAME:-sa-user-b}"
SA_A="${SA_A_NAME}@${PROJECT}.iam.gserviceaccount.com"
SA_B="${SA_B_NAME}@${PROJECT}.iam.gserviceaccount.com"
DS_A="tenant_cust001"   # must match BQ_CUSTOMERS_DATASET_TEMPLATE=tenant_{cust}
DS_B="tenant_cust002"
TABLE="customer"        # must match BQ_CUSTOMERS_TABLE

echo "project=$PROJECT  location=$LOCATION"
echo "impersonator=$IMPERSONATOR"
echo "SA_A=$SA_A (owns $DS_A)   SA_B=$SA_B (owns $DS_B)"

# --- validate-only shortcut -------------------------------------------------
# Classify a read attempt AS a given principal. Prints one of:
#   ROW        — authorized, returned data
#   BQ_403     — the real BigQuery/IAM data-plane denial (the beat)
#   NO_IMPERS  — impersonation itself failed (token-creator grant missing = setup incomplete)
#   ZERO_ROWS  — authorized but empty (NOT a 403 — usually means RLS/data, not IAM)
#   OTHER      — anything else
_classify_read() {
  local sa="$1" out
  out="$(CLOUDSDK_AUTH_IMPERSONATE_SERVICE_ACCOUNT="$sa" \
    bq query --project_id="$PROJECT" --use_legacy_sql=false --format=pretty \
    "SELECT customer_id, name FROM \`$PROJECT.$DS_A.$TABLE\` WHERE customer_id='CUST-001'" 2>&1)"
  if grep -qiE "Failed to impersonate|getAccessToken|serviceAccountTokenCreator" <<<"$out"; then
    echo "NO_IMPERS"
  elif grep -qiE "Access Denied|does not have|permission.*denied|bigquery\.tables\.getData" <<<"$out"; then
    echo "BQ_403"
  elif grep -q "CUST-001" <<<"$out"; then
    echo "ROW"
  elif grep -qiE "0 rows|Query produced no|^$" <<<"$out"; then
    echo "ZERO_ROWS"
  else
    echo "OTHER"; echo "$out" >&2
  fi
}
validate() {
  echo; echo "== Validation: same query on $DS_A, two identities =="
  local a b
  a="$(_classify_read "$SA_A")"; echo "-- User A (owner)   -> $a"
  b="$(_classify_read "$SA_B")"; echo "-- User B (attacker)-> $b"
  echo
  if [[ "$a" == "NO_IMPERS" || "$b" == "NO_IMPERS" ]]; then
    echo "SETUP INCOMPLETE: cannot impersonate the SAs yet — run grant (1) token-creator"
    echo "  (roles/iam.serviceAccountTokenCreator for $IMPERSONATOR on each SA)."
    echo "  This is NOT the demo 403; it fails before BigQuery. Re-run validate after grants."
    return 1
  fi
  if [[ "$a" == "ROW" && "$b" == "BQ_403" ]]; then
    echo "OK: User A authorized, User B denied by IAM (a REAL 403). This is the on-stage climax."
    return 0
  fi
  echo "NOT VALIDATED — do NOT record:"
  [[ "$a" != "ROW"    ]] && echo "  - User A should return a ROW but got '$a' (check A's dataViewer + jobUser)."
  [[ "$b" != "BQ_403" ]] && echo "  - User B should be a BQ_403 but got '$b'. ZERO_ROWS is NOT a 403 — B must have NO IAM access to $DS_A (revoke any viewer reaching it)."
  return 1
}
if [[ "${1:-}" == "validate" ]]; then validate; exit $?; fi

# --- [editor] Two service accounts ------------------------------------------
echo; echo "== [editor] service accounts =="
gcloud iam service-accounts create "$SA_A_NAME" --project="$PROJECT" \
  --display-name="Case3 User A (Alice / CUST-001 owner)" || true
gcloud iam service-accounts create "$SA_B_NAME" --project="$PROJECT" \
  --display-name="Case3 User B (attacker / CUST-002 owner)" || true

# --- [OWNER] Let the impersonator mint tokens for both SAs (keyless) --------
echo; echo "== [OWNER] token-creator (setIamPolicy on the SAs) =="
for SA in "$SA_A" "$SA_B"; do
  gcloud iam service-accounts add-iam-policy-binding "$SA" --project="$PROJECT" \
    --member="serviceAccount:$IMPERSONATOR" \
    --role="roles/iam.serviceAccountTokenCreator"
done

# --- [editor] Per-tenant datasets + customer tables + seed rows -------------
echo; echo "== [editor] datasets + seed =="
bq --location="$LOCATION" mk --dataset "$PROJECT:$DS_A" || true
bq --location="$LOCATION" mk --dataset "$PROJECT:$DS_B" || true

# Schema mirrors backends/data.py; charges is JSON text (parsed by _read_bigquery).
bq query --project_id="$PROJECT" --use_legacy_sql=false "
CREATE TABLE IF NOT EXISTS \`$PROJECT.$DS_A.$TABLE\`
  (customer_id STRING, name STRING, email STRING, tier STRING, charges STRING);
DELETE FROM \`$PROJECT.$DS_A.$TABLE\` WHERE TRUE;
INSERT INTO \`$PROJECT.$DS_A.$TABLE\` VALUES
  ('CUST-001','Alice Martin','alice.martin@example.com','standard',
   '[{\"charge_id\":\"TXN-1001\",\"amount\":50.0,\"currency\":\"USD\",\"description\":\"Monthly subscription\",\"refundable\":true}]');
"
bq query --project_id="$PROJECT" --use_legacy_sql=false "
CREATE TABLE IF NOT EXISTS \`$PROJECT.$DS_B.$TABLE\`
  (customer_id STRING, name STRING, email STRING, tier STRING, charges STRING);
DELETE FROM \`$PROJECT.$DS_B.$TABLE\` WHERE TRUE;
INSERT INTO \`$PROJECT.$DS_B.$TABLE\` VALUES
  ('CUST-002','Bob Nguyen','bob.nguyen@example.com','premium',
   '[{\"charge_id\":\"TXN-2001\",\"amount\":999.0,\"currency\":\"USD\",\"description\":\"Annual plan\",\"refundable\":true}]');
"

# --- [OWNER] Differential IAM — the SOURCE of the 403 -----------------------
# Both SAs can RUN jobs; only the owner SA can READ its own tenant dataset.
echo; echo "== [OWNER] differential IAM (the 403 comes from here) =="
for SA in "$SA_A" "$SA_B"; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:$SA" --role="roles/bigquery.jobUser" --condition=None
done
# dataViewer scoped per tenant: A -> DS_A only, B -> DS_B only. (B has NO grant on
# DS_A, so B reading DS_A is a real IAM 403 — NOT RLS 0-rows.) `-d` = dataset resource.
bq add-iam-policy-binding -d --member="serviceAccount:$SA_A" \
  --role="roles/bigquery.dataViewer" "$PROJECT:$DS_A"
bq add-iam-policy-binding -d --member="serviceAccount:$SA_B" \
  --role="roles/bigquery.dataViewer" "$PROJECT:$DS_B"

# --- [OWNER] BigQuery Data Access audit logs (the "who was it?" beat) --------
# Enables DATA_READ logging so the audit entry shows BOTH the impersonator (agent)
# and the delegated SA (user). Simplest in Console: IAM & Admin -> Audit Logs ->
# BigQuery -> tick "Data Read" -> Save. (Or edit the project policy auditConfigs
# and gcloud projects set-iam-policy — Owner only.)
echo; echo "== [OWNER] enable BigQuery Data Access (DATA_READ) audit logs in the Console =="

echo; echo "== Done. Now validate the 403: =="
echo "  bash scripts/setup_case3_identity.sh validate"
echo "Then the full agent path:"
echo "  CASE=3 uv run python -m scripts.identity_ab --principal-a $SA_A --principal-b $SA_B"
