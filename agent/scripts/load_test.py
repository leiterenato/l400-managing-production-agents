"""The fleet + the breaker OFF/ON A/B table (Case 2 load generator).

This is the deterministic evidence for the "Contain the blast" beat: the SAME
load, run with the semantic circuit breaker OFF then ON, side by side. OFF, a
degraded dependency drives high latency and a token spike (the retry storm); ON,
the breaker opens after a few slow calls and the rest of the fleet short-circuits
in milliseconds — latency and tokens flatten, and sessions degrade honestly.

Two targets:
  * ``--target local``  (default) — N concurrent sessions via ADK's InMemoryRunner.
    Deploy-free and deterministic; tokens/cost come from the ``record_cost`` seam
    on session state, so the A/B table is exact. This is the primary stage artifact.
  * ``--target engine`` — N concurrent ``stream_query`` calls against the DEPLOYED
    Agent Engine (the real fleet). Latency + breaker-open are captured; token
    totals come from Cloud Monitoring, not here (printed as n/a).

Honest cost note: every session is a REAL Vertex call = real tokens = $. Keep
``--n`` small and use Flash. The breaker opens after ``BREAKER_OPEN_AFTER`` slow
calls (default 3) — for a crisp table with few calls, export a low value, e.g.
``BREAKER_OPEN_AFTER=2``.

    # the money shot: same load, breaker OFF then ON, local
    CASE=2 uv run python -m scripts.load_test --ab --scenario slow_payment \
        --n 6 --concurrency 2

    # single pass (breaker forced on), local
    CASE=2 uv run python -m scripts.load_test --scenario slow_payment --breaker on --n 4

    # the deployed fleet (after the CASE=2 engine is up)
    CASE=2 uv run python -m scripts.load_test --ab --target engine --n 8 --concurrency 4

Requires GCP creds (ADC) + MODEL/PROJECT/LOCATION in env or agent/.env.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

DEFAULT_PROMPT = "Please refund my $50 monthly subscription, charge TXN-1001."
DEFAULT_ENGINE = os.environ.get(
    "AGENT_ENGINE_C2",
    os.environ.get("AGENT_ENGINE", ""),
)


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
    """Linear-interpolation percentile (pure python; no numpy)."""

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


# --- Local target: InMemoryRunner, N concurrent sessions --------------------
async def _run_fleet_local(
    prompt: str, n: int, concurrency: int, customer_id: str
) -> list[dict[str, Any]]:
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    from financial_support.agent import build_root_agent

    app = "financial_support"
    runner = InMemoryRunner(agent=build_root_agent(), app_name=app)
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(i: int) -> dict[str, Any]:
        async with sem:
            user_id = f"fleet-{i}"
            session = await runner.session_service.create_session(
                app_name=app, user_id=user_id, state={"customer_id": customer_id}
            )
            msg = types.Content(role="user", parts=[types.Part(text=prompt)])
            tool_calls: list[str] = []
            final_text = ""
            breaker_open = False
            ok, err = True, None
            t0 = time.time()
            try:
                async for event in runner.run_async(
                    user_id=user_id, session_id=session.id, new_message=msg
                ):
                    for call in event.get_function_calls() or []:
                        tool_calls.append(call.name)
                    fr_getter = getattr(event, "get_function_responses", None)
                    if fr_getter:
                        for fr in fr_getter() or []:
                            resp = getattr(fr, "response", None) or {}
                            if isinstance(resp, dict) and resp.get("status") == "unavailable":
                                breaker_open = True
                    if event.is_final_response() and event.content and event.content.parts:
                        final_text = "".join(p.text or "" for p in event.content.parts)
            except Exception as exc:  # a session dying should not kill the fleet
                ok, err = False, f"{type(exc).__name__}:{exc}"
            latency = time.time() - t0

            final = await runner.session_service.get_session(
                app_name=app, user_id=user_id, session_id=session.id
            )
            st = final.state or {}
            return {
                "ok": ok,
                "err": err,
                "latency": latency,
                "prompt_tokens": st.get("session_prompt_tokens", 0),
                "candidate_tokens": st.get("session_candidate_tokens", 0),
                "cost": st.get("session_cost_usd", 0.0),
                "tool_calls": tool_calls,
                "final_text": final_text,
                "breaker_open": breaker_open,
            }

    return await asyncio.gather(*[_one(i) for i in range(n)])


# --- Engine target: stream_query against the deployed fleet -----------------
def _run_one_engine(engine, prompt: str, user_id: str) -> dict[str, Any]:
    tool_calls: list[str] = []
    final_text = ""
    breaker_open = False
    ok, err = True, None
    t0 = time.time()
    try:
        for event in engine.stream_query(user_id=user_id, message=prompt):
            content = event.get("content", {}) if isinstance(event, dict) else {}
            for part in content.get("parts", []) or []:
                fc = part.get("function_call")
                if fc:
                    tool_calls.append(fc.get("name", "?"))
                fr = part.get("function_response")
                if fr:
                    resp = fr.get("response") or {}
                    if isinstance(resp, dict) and resp.get("status") == "unavailable":
                        breaker_open = True
                if part.get("text"):
                    final_text = part["text"]
    except Exception as exc:
        ok, err = False, f"{type(exc).__name__}:{exc}"
    return {
        "ok": ok,
        "err": err,
        "latency": time.time() - t0,
        "prompt_tokens": 0,  # engine token totals come from Cloud Monitoring
        "candidate_tokens": 0,
        "cost": 0.0,
        "tool_calls": tool_calls,
        "final_text": final_text,
        "breaker_open": breaker_open,
    }


def _run_fleet_engine(
    engine_id: str, prompt: str, n: int, concurrency: int
) -> list[dict[str, Any]]:
    import vertexai
    from vertexai import agent_engines

    project = engine_id.split("/")[1]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    vertexai.init(project=project, location=location)
    engine = agent_engines.get(engine_id)

    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(concurrency, n))) as pool:
        futures = [
            pool.submit(_run_one_engine, engine, prompt, f"fleet-{i}")
            for i in range(n)
        ]
        for fut in as_completed(futures):
            results.append(fut.result())
    return results


# --- Aggregation + the A/B table --------------------------------------------
def _aggregate(results: list[dict[str, Any]], target: str) -> dict[str, Any]:
    ok = [r for r in results if r.get("ok")]
    lat = [r["latency"] for r in ok]
    return {
        "sessions": len(results),
        "ok": len(ok),
        "errors": len(results) - len(ok),
        "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in ok),
        "candidate_tokens": sum(r.get("candidate_tokens", 0) for r in ok),
        "cost": sum(r.get("cost", 0.0) for r in ok),
        "p50": _pct(lat, 50),
        "p95": _pct(lat, 95),
        "breaker_open": sum(1 for r in ok if r.get("breaker_open")),
        "target": target,
    }


def _fmt_tokens(agg: dict[str, Any]) -> str:
    if agg["target"] == "engine":
        return "n/a (Monitoring)"
    total = agg["prompt_tokens"] + agg["candidate_tokens"]
    return f"{total:,}"


def _fmt_cost(agg: dict[str, Any]) -> str:
    return "n/a" if agg["target"] == "engine" else f"${agg['cost']:.4f}"


def _print_ab(off: dict[str, Any], on: dict[str, Any]) -> None:
    rows = [
        ("sessions", str(off["sessions"]), str(on["sessions"])),
        ("total tokens", _fmt_tokens(off), _fmt_tokens(on)),
        ("total cost", _fmt_cost(off), _fmt_cost(on)),
        ("p50 latency", f"{off['p50']:.1f}s", f"{on['p50']:.1f}s"),
        ("p95 latency", f"{off['p95']:.1f}s", f"{on['p95']:.1f}s"),
        ("breaker-open (fallback)", str(off["breaker_open"]), str(on["breaker_open"])),
        ("errors", str(off["errors"]), str(on["errors"])),
    ]
    w0 = max(len(r[0]) for r in rows)
    w1 = max(len("BREAKER OFF"), max(len(r[1]) for r in rows))
    w2 = max(len("BREAKER ON"), max(len(r[2]) for r in rows))
    line = f"| {{:<{w0}}} | {{:>{w1}}} | {{:>{w2}}} |"
    sep = f"+-{'-'*w0}-+-{'-'*w1}-+-{'-'*w2}-+"
    print("\n" + sep)
    print(line.format("metric", "BREAKER OFF", "BREAKER ON"))
    print(sep)
    for r in rows:
        print(line.format(*r))
    print(sep)


def _print_single(tag: str, agg: dict[str, Any]) -> None:
    print(f"\n=== load_test [{tag}] target={agg['target']} ===")
    print(f"sessions      : {agg['ok']}/{agg['sessions']} ok  errors={agg['errors']}")
    print(f"total tokens  : {_fmt_tokens(agg)}   cost {_fmt_cost(agg)}")
    print(f"latency       : p50 {agg['p50']:.1f}s  p95 {agg['p95']:.1f}s")
    print(f"breaker-open  : {agg['breaker_open']} session(s) hit an open circuit")


# --- Orchestration ----------------------------------------------------------
def _run_pass(target: str, prompt: str, n: int, concurrency: int, customer_id: str,
              engine_id: str) -> list[dict[str, Any]]:
    if target == "engine":
        if not engine_id:
            print("--target engine needs AGENT_ENGINE_C2 (or AGENT_ENGINE) set to the "
                  "deployed CASE=2 engine resource name.", file=sys.stderr)
            raise SystemExit(2)
        return _run_fleet_engine(engine_id, prompt, n, concurrency)
    return asyncio.run(_run_fleet_local(prompt, n, concurrency, customer_id))


def run(args: argparse.Namespace) -> int:
    _load_env()

    # --ab is LOCAL-ONLY. The deployed engine's BREAKER is baked at deploy time,
    # so flipping BREAKER in this process would NOT change the remote engine —
    # both passes would hit the same baked state and the table would be a lie.
    if args.ab and args.target == "engine":
        print(
            "--ab is local-only. The deployed engine's BREAKER is fixed at deploy, "
            "so an in-process flip does nothing remotely. For an engine A/B: deploy "
            "with BREAKER=off and drive one pass, then redeploy (UPDATE_RESOURCE) "
            "with BREAKER=on and drive the other.",
            file=sys.stderr,
        )
        return 2

    # This is the Case 2 harness: the resilience bundle must be wired.
    os.environ["CASE"] = "2"
    os.environ["SCENARIO"] = args.scenario
    # Isolate the BREAKER as the only variable in the A/B: neutralize the
    # per-session budget unless the operator set one explicitly. budget_guard is
    # active under CASE=2 and would otherwise contain a runaway OFF-pass session,
    # confounding "OFF = uncontained". Export SESSION_BUDGET_USD to demo the budget.
    os.environ.setdefault("SESSION_BUDGET_USD", "1000000")

    from financial_support.callbacks import resilience
    from financial_support.config import reload_settings

    def _pass(breaker: str, tag: str) -> dict[str, Any]:
        os.environ["BREAKER"] = breaker
        reload_settings()
        resilience.reset()
        print(f"\n>> running {args.n} session(s), breaker={breaker}, "
              f"scenario={args.scenario}, target={args.target}...")
        results = _run_pass(args.target, args.prompt, args.n, args.concurrency,
                            args.customer, args.engine)
        return _aggregate(results, args.target)

    if args.ab:
        off = _pass("off", "OFF")
        on = _pass("on", "ON")
        _print_single("OFF", off)
        _print_single("ON", on)
        _print_ab(off, on)
    else:
        agg = _pass(args.breaker, args.breaker.upper())
        _print_single(args.breaker.upper(), agg)
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--scenario", default="slow_payment",
                   help="fault profile (slow_payment | retry_storm | ...)")
    p.add_argument("--breaker", choices=["on", "off"], default="off",
                   help="single-pass breaker state (ignored with --ab)")
    p.add_argument("--ab", action="store_true",
                   help="run OFF then ON and print the A/B table")
    p.add_argument("--target", choices=["local", "engine"], default="local")
    p.add_argument("--n", type=int, default=6, help="number of sessions (real $)")
    p.add_argument("--concurrency", type=int, default=2,
                   help="parallel in-flight sessions")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--customer", default="CUST-001")
    p.add_argument("--engine", default=DEFAULT_ENGINE,
                   help="deployed CASE=2 engine resource name (--target engine)")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
