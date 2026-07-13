"""The identity seam (Case 3): delegated-identity carrier + case gating + backend.

Mirrors the fixture/fake style of ``test_resilience.py``. The load-bearing claims
under test: (1) ``enforce_identity`` is a CARRIER — it stamps the principal and
NEVER blocks; (2) it is dormant under CASE<3; (3) ``read_customer`` routes to the
right backend; (4) a BigQuery ``Forbidden`` becomes a ``denied`` status and is
never fabricated (0 rows -> not_found, not a 403).
"""

import os

import pytest

from financial_support.callbacks import registry
from financial_support.callbacks.identity import enforce_identity
from financial_support.config import reload_settings
from financial_support.prompts import with_identity_clause


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeToolContext:
    def __init__(self, state=None):
        self.state = {} if state is None else state


@pytest.fixture(autouse=True)
def clean_env():
    saved = dict(os.environ)
    yield
    os.environ.clear()
    os.environ.update(saved)
    reload_settings()


def _set(**env):
    for k, v in env.items():
        os.environ[k] = str(v)
    reload_settings()


# --- enforce_identity is a CARRIER, not a boundary --------------------------

def test_enforce_identity_carries_principal_under_case3():
    _set(CASE=3)
    ctx = FakeToolContext(state={"delegated_principal": "sa-user-a@proj.iam"})
    out = enforce_identity(FakeTool("look_up_customer"), {}, ctx)
    assert out is None  # it NEVER blocks
    assert ctx.state["data_access_principal"] == "sa-user-a@proj.iam"


def test_enforce_identity_never_blocks_even_without_a_principal():
    # No principal carried: still returns None (the data plane is the boundary,
    # not this callback) and stamps None so the backend can decide/fallback.
    _set(CASE=3)
    ctx = FakeToolContext(state={})
    out = enforce_identity(FakeTool("look_up_customer"), {}, ctx)
    assert out is None
    assert ctx.state["data_access_principal"] is None


def test_enforce_identity_dormant_under_case2():
    # Self-guard: even if a stray wiring called it, CASE<3 makes it a no-op that
    # does not touch state.
    _set(CASE=2)
    ctx = FakeToolContext(state={"delegated_principal": "sa-user-b@proj.iam"})
    assert enforce_identity(FakeTool("look_up_customer"), {}, ctx) is None
    assert "data_access_principal" not in ctx.state


# --- Case gating (Cases 1 & 2 stay byte-identical) --------------------------

def test_case3_wires_identity_on_top_of_earlier_seams():
    _set(CASE=3)
    from financial_support.agent import build_root_agent

    root = build_root_agent()
    names = lambda cbs: {getattr(c, "__name__", "") for c in (cbs or [])}
    before = names(root.before_tool_callback)
    # Accumulative: Case 2 breaker + Case 3 identity both present, in order.
    assert "enforce_identity" in before
    assert "circuit_breaker" in before
    assert "enforce_invariants" in names(root.after_tool_callback)


def test_case2_leaves_identity_dormant():
    _set(CASE=2)
    assert "identity" not in [b.name for b in registry.active_bundles()]
    from financial_support.agent import build_root_agent

    root = build_root_agent()
    before = {getattr(c, "__name__", "") for c in (root.before_tool_callback or [])}
    assert "enforce_identity" not in before
    assert "circuit_breaker" in before  # Case 2 seam still wired


def test_case1_has_no_before_tool_callbacks():
    _set(CASE=1)
    asm = registry.assemble()
    assert "before_tool_callback" not in asm


# --- The Case 3 prompt clause is CASE>=3-gated ------------------------------

def test_identity_clause_only_appended_from_case3():
    _set(CASE=1)
    assert with_identity_clause("BASE") == "BASE"
    _set(CASE=2)
    assert with_identity_clause("BASE") == "BASE"
    _set(CASE=3)
    out = with_identity_clause("BASE")
    assert out != "BASE" and "denied" in out.lower()


# --- customer_db backend routing + the REAL 403 mapping ---------------------

def test_read_customer_defaults_to_mock():
    _set()  # CUSTOMER_DB_BACKEND defaults to "mock"
    from financial_support.backends import customer_db

    out = customer_db.read_customer("CUST-001")
    assert out["status"] == "ok" and out["customer_id"] == "CUST-001"


def test_read_customer_routes_to_bigquery(monkeypatch):
    _set(CUSTOMER_DB_BACKEND="bigquery")
    from financial_support.backends import customer_db

    monkeypatch.setattr(
        customer_db,
        "_read_bigquery",
        lambda cid, principal: {"status": "sentinel", "cid": cid, "p": principal},
    )
    out = customer_db.read_customer("CUST-001", principal="sa-user-a@proj.iam")
    assert out == {"status": "sentinel", "cid": "CUST-001", "p": "sa-user-a@proj.iam"}


def test_bigquery_forbidden_becomes_denied_never_fabricated(monkeypatch):
    # The only genuinely-real beat: a real IAM 403 must surface as "denied".
    from google.api_core.exceptions import Forbidden
    from google.cloud import bigquery

    from financial_support.backends import customer_db

    _set(CUSTOMER_DB_BACKEND="bigquery", GOOGLE_CLOUD_PROJECT="proj")
    monkeypatch.setattr(customer_db, "_delegated_credentials", lambda p: None)

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            raise Forbidden("Access Denied: Table proj:tenant_cust001.customer")

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    out = customer_db.read_customer("CUST-001", principal="sa-user-b@proj.iam")
    assert out["status"] == "denied"
    assert out["reason"] == "PERMISSION_DENIED"
    assert out["principal"] == "sa-user-b@proj.iam"


def test_bigquery_zero_rows_is_not_found_not_a_403(monkeypatch):
    # Honesty guard: an empty result is NOT a denial. Never synthesize a 403.
    from google.cloud import bigquery

    from financial_support.backends import customer_db

    _set(CUSTOMER_DB_BACKEND="bigquery", GOOGLE_CLOUD_PROJECT="proj")
    monkeypatch.setattr(customer_db, "_delegated_credentials", lambda p: None)

    class FakeJob:
        def result(self):
            return []

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            return FakeJob()

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    out = customer_db.read_customer("CUST-001", principal="sa-user-a@proj.iam")
    assert out["status"] == "not_found"


def test_bigquery_success_returns_row_with_parsed_charges(monkeypatch):
    from google.cloud import bigquery

    from financial_support.backends import customer_db

    _set(CUSTOMER_DB_BACKEND="bigquery", GOOGLE_CLOUD_PROJECT="proj")
    monkeypatch.setattr(customer_db, "_delegated_credentials", lambda p: None)

    row = {
        "customer_id": "CUST-001",
        "name": "Alice Martin",
        "email": "alice.martin@example.com",
        "tier": "standard",
        "charges": '[{"charge_id": "TXN-1001", "amount": 50.0}]',
    }

    class FakeJob:
        def result(self):
            return [row]

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def query(self, *a, **k):
            return FakeJob()

    monkeypatch.setattr(bigquery, "Client", FakeClient)
    out = customer_db.read_customer("CUST-001", principal="sa-user-a@proj.iam")
    assert out["status"] == "ok"
    assert out["customer_id"] == "CUST-001"
    assert out["charges"] == [{"charge_id": "TXN-1001", "amount": 50.0}]
