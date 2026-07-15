"""Slide 10 "Contain the blast" — the three-act Cloud Monitoring timeline.

Drives the REAL agent under a simulated fleet and streams measured latency / cost
/ breaker metrics to Cloud Monitoring, so on stage you point at ONE continuous
dashboard that tells the whole story:

    Act 1  baseline   scenario=healthy      breaker=off  -> green, fast
    Act 2  incident   scenario=slow_payment breaker=off  -> the storm (p95 + cost spike)
    Act 3  recovery   scenario=slow_payment breaker=on   -> the fix contains it (p95 + cost fall,
                                                            breaker_open_count rises)

The breaker is process-local, so a single local process = one shared counter =
a real fleet-wide trip. That is why the ON act genuinely flattens here (the
deployed multi-instance engine would not — the counter is per instance).

Latency is sampled from BOTH in-flight session age and recent completions every
tick, so the storm shows as a dense, honest signal even when few sessions finish
inside a window.

    # smoke test first (short acts, proves the pipe end-to-end)
    uv run python -m scripts.monitoring_demo --smoke

    # the real pre-record (~10 min/act = ~30 min); shows on the dashboard for weeks
    uv run python -m scripts.monitoring_demo --act-seconds 600 --concurrency 6

Requires GCP creds (ADC) + GOOGLE_CLOUD_PROJECT. Real Vertex calls = real $.
"""

from __future__ import annotations

import argparse
import asyncio
import itertools
import os
import sys
import time
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

DEFAULT_PROMPT = "Please refund my $50 monthly subscription, charge TXN-1001."

ACTS = [
    {"name": "baseline", "scenario": "healthy", "breaker": "off"},
    {"name": "incident", "scenario": "slow_payment", "breaker": "off"},
    {"name": "recovery", "scenario": "slow_payment", "breaker": "on"},
]


def _load_env() -> None:
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
    except Exception:
        pass


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(s) - 1)
    if f == c:
        return s[f]
    return s[f] + (s[c] - s[f]) * (k - f)


async def _one_session(runner, app, prompt, customer_id, i, timeout_s) -> dict[str, Any]:
    """Run one session; return latency + cost + whether the breaker short-circuited.

    ``timeout_s`` caps a runaway session (the retry storm) — a real resilience
    practice, and what keeps the incident act's cost/completion data dense instead
    of every session running ~200s. Cost is read from session state in a finally,
    so a timed-out storm session still reports the tokens it burned.
    """

    from google.genai import types

    user_id = f"fleet-{i}"
    session = await runner.session_service.create_session(
        app_name=app, user_id=user_id, state={"customer_id": customer_id}
    )
    msg = types.Content(role="user", parts=[types.Part(text=prompt)])
    breaker_open = False
    ok = True
    timed_out = False
    t0 = time.time()

    async def _drive():
        nonlocal breaker_open
        async for event in runner.run_async(
            user_id=user_id, session_id=session.id, new_message=msg
        ):
            fr_getter = getattr(event, "get_function_responses", None)
            if fr_getter:
                for fr in fr_getter() or []:
                    resp = getattr(fr, "response", None) or {}
                    if isinstance(resp, dict) and resp.get("status") == "unavailable":
                        breaker_open = True

    try:
        if timeout_s and timeout_s > 0:
            await asyncio.wait_for(_drive(), timeout=timeout_s)
        else:
            await _drive()
    except asyncio.TimeoutError:  # runaway session capped — realistic + keeps data dense
        timed_out, ok = True, False
    except asyncio.CancelledError:  # act deadline: propagate, do NOT record
        raise
    except Exception:  # a dying session must not kill the fleet
        ok = False
    latency = time.time() - t0

    cost = 0.0
    try:
        final = await runner.session_service.get_session(
            app_name=app, user_id=user_id, session_id=session.id
        )
        cost = (final.state or {}).get("session_cost_usd", 0.0)
    except Exception:
        pass
    # Free the session from the in-memory store so a long run does not accumulate
    # hundreds of sessions (which slows down every subsequent call and degrades the
    # baseline latency over time). Best-effort.
    try:
        await runner.session_service.delete_session(
            app_name=app, user_id=user_id, session_id=session.id
        )
    except Exception:
        pass
    return {
        "latency": latency,
        "cost": cost,
        "breaker_open": breaker_open,
        "ok": ok,
        "timed_out": timed_out,
    }


def _compute_window(completed, inflight, window_s, now, last) -> dict[str, float]:
    """Compute one point per metric for the trailing window (pure; no I/O)."""

    # Latency from COMPLETED sessions only (the session cap keeps completions dense
    # in every act). Feature MEAN + p50 — both tail-robust, so a few healthy
    # sessions that hang under load do not pollute the baseline (p95 does, so it is
    # emitted for reference but not the headline line).
    recent = [c for c in completed if c["ts"] >= now - window_s]
    lat = [c["latency"] for c in recent]
    breaker_min = sum(
        1 for c in completed if c["ts"] >= now - 60.0 and c["breaker_open"]
    )
    sessions_min = sum(1 for c in completed if c["ts"] >= now - 60.0)

    if lat:
        mean = sum(lat) / len(lat)
        p50 = _pct(lat, 50)
        p95 = _pct(lat, 95)
        last["mean"], last["p50"], last["p95"] = mean, p50, p95
    else:  # carry forward — no completions in the window (sparse storm)
        mean, p50, p95 = last["mean"], last["p50"], last["p95"]

    print(
        f"    [{time.strftime('%H:%M:%S', time.localtime(now))}] "
        f"mean={mean:6.1f}s p50={p50:6.1f}s p95={p95:6.1f}s "
        f"breaker-open/min={breaker_min:2d} sessions/min={sessions_min:2d} "
        f"(inflight={len(inflight)})"
    )
    return {
        "request_latency_mean": mean,
        "request_latency_p50": p50,
        "request_latency_p95": p95,
        "breaker_open_count": float(breaker_min),
        "sessions_per_min": float(sessions_min),
    }


async def _publish(emitter, values, now, gate):
    """Write a point off the event loop (blocking gRPC), honouring the 10s min
    sampling period. Never lets a write error kill the run."""

    if emitter is None or now - gate[0] < 11.0:
        return
    gate[0] = now
    try:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, emitter.write, values, now)
    except Exception as exc:  # a bad point must not abort a 30-min pre-record
        print(f"    ! metric write failed: {type(exc).__name__}: {exc}")


async def _run_act(act, duration_s, concurrency, tick_s, window_s, prompt,
                   customer_id, emitter, session_timeout, last) -> None:
    from google.adk.runners import InMemoryRunner

    from financial_support.agent import build_root_agent
    from financial_support.callbacks import resilience
    from financial_support.config import reload_settings

    os.environ["CASE"] = "2"
    os.environ["SCENARIO"] = act["scenario"]
    os.environ["BREAKER"] = act["breaker"]
    # Isolate the breaker: never let the per-session budget confound the OFF storm.
    os.environ.setdefault("SESSION_BUDGET_USD", "1000000")
    reload_settings()
    resilience.reset()

    app = "financial_support"
    runner = InMemoryRunner(agent=build_root_agent(), app_name=app)

    print(f"\n=== ACT: {act['name']}  scenario={act['scenario']} "
          f"breaker={act['breaker']}  ({duration_s}s) ===")

    completed: list[dict[str, Any]] = []
    inflight: dict[int, float] = {}
    # `last` is shared across acts (created in run()) so the timeline carries
    # forward smoothly at each act boundary instead of dropping to 0 before the
    # first completion of the new act.
    gate = [0.0]  # last publish time — enforces the 10s min sampling period
    counter = itertools.count()

    async def worker():
        # Runs until cancelled at the act deadline. A slow session (the storm)
        # can outlive the deadline; cancelling here keeps act boundaries crisp
        # instead of overrunning by a full ~200s session.
        while True:
            i = next(counter)
            inflight[i] = time.time()
            try:
                r = await _one_session(runner, app, prompt, customer_id, i,
                                       session_timeout)
                r["ts"] = time.time()
                completed.append(r)
            finally:
                inflight.pop(i, None)

    async def ticker():
        while True:
            await asyncio.sleep(tick_s)
            now = time.time()
            values = _compute_window(completed, inflight, window_s, now, last)
            await _publish(emitter, values, now, gate)

    workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
    tick = asyncio.create_task(ticker())
    await asyncio.sleep(duration_s)
    for w in workers:
        w.cancel()
    tick.cancel()
    await asyncio.gather(*workers, tick, return_exceptions=True)
    # Tail flush so the act's final state lands on the graph.
    now = time.time()
    values = _compute_window(completed, inflight, window_s, now, last)
    await _publish(emitter, values, now, gate)
    print(f"    act done: {len(completed)} sessions completed")


def run(args: argparse.Namespace) -> int:
    _load_env()
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        print("GOOGLE_CLOUD_PROJECT not set (need it for Cloud Monitoring).",
              file=sys.stderr)
        return 2

    emitter = None
    if not args.no_publish:
        from financial_support.observability.monitoring_metrics import MetricEmitter

        emitter = MetricEmitter(project, run_label=args.run_label)
        print(f"publishing custom metrics to project {project} "
              f"(run label: {args.run_label})")

    act_s = 120 if args.smoke else args.act_seconds
    tick_s = 15 if args.smoke else args.tick_seconds
    session_timeout = 30 if args.smoke else args.session_timeout
    window_s = args.window_seconds

    acts = ACTS
    if args.acts:
        want = {a.strip() for a in args.acts.split(",")}
        acts = [a for a in ACTS if a["name"] in want]

    last = {"mean": 0.0, "p50": 0.0, "p95": 0.0}  # carried across acts
    t_start = time.time()
    for act in acts:
        asyncio.run(
            _run_act(act, act_s, args.concurrency, tick_s, window_s,
                     args.prompt, args.customer, emitter, session_timeout, last)
        )
    mins = (time.time() - t_start) / 60.0
    print(f"\nall acts done in {mins:.1f} min. "
          f"View: Cloud Monitoring > Metrics Explorer > custom.googleapis.com/agent/*")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--act-seconds", type=int, default=600,
                   help="duration of EACH act (default 600 = 10 min)")
    p.add_argument("--tick-seconds", type=int, default=30,
                   help="seconds between published points")
    p.add_argument("--window-seconds", type=int, default=120,
                   help="trailing window for the latency percentile")
    p.add_argument("--concurrency", type=int, default=6,
                   help="parallel in-flight sessions (real $)")
    p.add_argument("--session-timeout", type=int, default=90,
                   help="cap a runaway (storm) session, seconds; keeps data dense")
    p.add_argument("--smoke", action="store_true",
                   help="short acts (120s each, 30s cap) to prove the dynamics")
    p.add_argument("--no-publish", action="store_true",
                   help="run + print but do NOT write to Cloud Monitoring")
    p.add_argument("--run-label", default="case2-slide10")
    p.add_argument("--acts", default="",
                   help="comma-sep act names to run (default all): baseline,incident,recovery")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--customer", default="CUST-001")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
