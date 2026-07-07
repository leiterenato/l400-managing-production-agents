"""Online monitor, BigQuery trend, and case-scoping."""

import os

from evals.bigquery_scale import weekly_failure_rate
from evals.online_monitor import run_monitor
from financial_support.config import reload_settings


def test_monitor_alerts_after_drift():
    events = run_monitor(threshold=0.9, window=10, n=60, drift_at=40)
    fired = [e for e in events if e.alert]
    assert len(fired) == 1
    assert fired[0].index >= 40  # alert only after quality drifts


def test_monitor_stays_quiet_when_healthy():
    events = run_monitor(threshold=0.9, window=10, n=30, drift_at=999)
    assert not any(e.alert for e in events)


def test_bigquery_trend_increases():
    stats = weekly_failure_rate()
    assert stats[0].failure_rate < stats[-1].failure_rate
    assert stats[-1].failure_rate > 0.02


def test_case_scoping_gates_concerns():
    from financial_support.callbacks import active_bundles, register, CallbackBundle

    def _noop(*a, **k):
        return None

    register(CallbackBundle(name="_test_c2", case=2, after_tool=[_noop]))
    try:
        os.environ["CASE"] = "1"
        reload_settings()
        assert "_test_c2" not in {b.name for b in active_bundles()}
        os.environ["CASE"] = "2"
        reload_settings()
        assert "_test_c2" in {b.name for b in active_bundles()}
    finally:
        os.environ["CASE"] = "1"
        reload_settings()
