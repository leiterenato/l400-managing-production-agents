"""Customer database — mock by default, BigQuery-as-the-caller for Case 3.

Two backends, selected by ``CUSTOMER_DB_BACKEND`` (see config.py):

  * ``mock`` (default) — an in-memory lookup that honours the fault knobs so we
    can stage the cross-account *leak* deterministically (the S13 "wound"). No
    ADK, no GCP: Cases 1 and 2 never touch the network.

  * ``bigquery`` (Case 3) — the read runs **as the caller's delegated principal**
    against a per-tenant dataset. BigQuery IAM is then the boundary: the tenant's
    owner reads their row; anyone else gets a **real 403** from IAM. That 403 is
    the only genuinely-real beat of the talk — we surface it, we never fabricate
    it (a 0-row result is ``not_found``, NOT a denial). The GCP imports are lazy
    so this module still imports cleanly without google-cloud-bigquery installed.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import get_settings
from . import data
from .faults import fault_for


def read_customer(
    session_customer_id: str, principal: str | None = None
) -> dict[str, Any]:
    """Read the record for the session's customer.

    Routes to the configured backend. ``principal`` is the delegated identity the
    Case 3 seam carries here; the mock backend ignores it, the BigQuery backend
    runs the read as it. Absent (Cases 1/2), the mock path behaves exactly as
    before.
    """

    if get_settings().customer_db_backend == "bigquery":
        return _read_bigquery(session_customer_id, principal)
    return _read_mock(session_customer_id)


def _read_mock(session_customer_id: str) -> dict[str, Any]:
    """In-memory lookup (Cases 1 & 2).

    Under the ``wrong_account`` scenario the ``return_customer_id`` knob makes
    this return a *different* customer — the cross-account read that Case 3
    hardens. We surface both ids in the payload so the invariant / eval can see
    the mismatch.
    """

    fault = fault_for("look_up_customer")

    if fault.latency_s:
        time.sleep(fault.latency_s)

    if fault.fail:
        return {
            "status": "error",
            "error": fault.fail,
            "session_customer_id": session_customer_id,
        }

    queried_id = fault.return_customer_id or session_customer_id
    customer = data.get_customer(queried_id)
    if customer is None:
        return {
            "status": "not_found",
            "session_customer_id": session_customer_id,
            "queried_customer_id": queried_id,
        }

    return {
        "status": "ok",
        # The row-level truth: which record did we actually return?
        "session_customer_id": session_customer_id,
        "queried_customer_id": customer.customer_id,
        "customer_id": customer.customer_id,
        "name": customer.name,
        "email": customer.email,
        "tier": customer.tier,
        "charges": [
            {
                "charge_id": c.charge_id,
                "amount": c.amount,
                "currency": c.currency,
                "description": c.description,
                "refundable": c.refundable,
            }
            for c in customer.charges.values()
        ],
    }


# --- Case 3: BigQuery read scoped to the caller's identity -------------------
def _dataset_for(customer_id: str) -> str:
    """Per-tenant dataset name: ``CUST-001`` -> ``tenant_cust001`` (template)."""

    cust = customer_id.replace("-", "").lower()
    return get_settings().bq_customers_dataset_template.format(cust=cust)


def _delegated_credentials(principal: str | None):
    """Credentials to run the read AS.

    With a principal, impersonate it (keyless — matches the SPIFFE "no long-lived
    keys" story; the running identity needs ``roles/iam.serviceAccountTokenCreator``
    on it). Without one, fall back to ADC (the running identity) — a deliberate,
    honest fallback that has NO per-tenant scoping, so it is only for local
    smoke-tests, never the on-stage 403.
    """

    import google.auth

    source, _ = google.auth.default()
    if not principal:
        return source

    from google.auth import impersonated_credentials

    return impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=principal,
        target_scopes=[
            "https://www.googleapis.com/auth/bigquery",
            "https://www.googleapis.com/auth/cloud-platform",
        ],
    )


def _read_bigquery(customer_id: str, principal: str | None) -> dict[str, Any]:
    """Read the customer row from the per-tenant dataset, AS the caller.

    The client runs with the delegated principal's credentials (the per-user
    service account the run impersonates, standing in for the user's 3LO token).
    BigQuery IAM decides: the owner reads their row; anyone else triggers a real
    ``google.api_core.exceptions.Forbidden`` (403), which we surface as a
    ``denied`` status. We NEVER synthesize a 403 — a 0-row result is ``not_found``.
    """

    from google.api_core.exceptions import Forbidden
    from google.cloud import bigquery

    settings = get_settings()
    project = settings.project
    dataset = _dataset_for(customer_id)
    table = settings.bq_customers_table

    client = bigquery.Client(
        project=project, credentials=_delegated_credentials(principal)
    )
    fq_table = f"`{project}.{dataset}.{table}`"
    sql = (
        "SELECT customer_id, name, email, tier, charges "
        f"FROM {fq_table} WHERE customer_id = @cid"
    )
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("cid", "STRING", customer_id)
        ]
    )

    try:
        rows = list(client.query(sql, job_config=job_config).result())
    except Forbidden as exc:
        # THE REAL 403 — IAM refused THIS principal on THIS tenant's resource.
        # The only genuinely-real beat of the talk. Surface it; never fabricate
        # it, and never fall back to another identity to "get the data anyway".
        return {
            "status": "denied",
            "reason": "PERMISSION_DENIED",
            "principal": principal,
            "session_customer_id": customer_id,
            "detail": str(exc),
        }

    if not rows:
        return {
            "status": "not_found",
            "session_customer_id": customer_id,
            "queried_customer_id": customer_id,
            "principal": principal,
        }

    row = rows[0]
    charges = row.get("charges")
    if isinstance(charges, str):
        charges = json.loads(charges) if charges else []
    return {
        "status": "ok",
        "session_customer_id": customer_id,
        "queried_customer_id": row["customer_id"],
        "customer_id": row["customer_id"],
        "name": row["name"],
        "email": row["email"],
        "tier": row["tier"],
        "charges": charges or [],
        "principal": principal,
    }
