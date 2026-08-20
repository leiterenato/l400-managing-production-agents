"""Drive the DEPLOYED agent (Agent Engine) to generate production traffic.

The Camada-3 companion to :mod:`deploy.online_evaluator`. The online monitor only
scores traces it SAMPLES from production, so the green->red demo needs real
traffic hitting the deployed engine. This sends a batch of refund requests via
``stream_query`` (the remote query surface); each call produces a trace with the
engine's ``cloud.resource_id``, which is exactly what the monitor filters on.

Unlike :mod:`scripts.live_drive` (which runs the agent LOCALLY via InMemoryRunner
for the S2 trace), this hits the REMOTE deployed engine — because Camada 3 is
about *production* traces, not local ones. The fault profile is whatever the
DEPLOYED engine is running (SCENARIO env baked at deploy); flip it by redeploying
in place (see deploy/online_evaluator.py's green->red sequence).

Requires GCP creds (ADC) + PROJECT/LOCATION in env or agent/.env.

    uv run python -m scripts.drive_engine --n 8
    uv run python -m scripts.drive_engine --n 8 --prompt "Refund my $50 charge TXN-1001."
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# Same armed engine the monitor watches. Resolved AFTER _load_env() so that
# agent/.env works too; no default, because a hardcoded fallback would silently
# drive an engine in someone else's project.
AGENT_ENGINE = ""

# In-policy $50 refund (below the fraud review threshold of 200, so the agent
# proceeds and — under an armed deployment — the processor over-pays; that is the
# money bug the monitor's invariant catches). Do NOT ask for >= $200 here.
DEFAULT_PROMPT = "Please refund my $50 monthly subscription, charge TXN-1001."


def _load_env() -> None:
    path = os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(path)
    except Exception:
        pass


def _one(engine, prompt: str, user_id: str) -> dict:
    """Drive a single request; return a result dict.

    Also captures the issue_refund tool RESPONSE (the money that actually moved)
    so we can verify the invariant client-side — the reply text always says "$50"
    even when the processor over-pays $500 (that is the whole "green lies" point),
    so we read the response payload, not the prose.
    """
    tool_calls: list[str] = []
    final_text = ""
    refund_amt = charge_amt = None
    try:
        for event in engine.stream_query(user_id=user_id, message=prompt):
            content = event.get("content", {}) if isinstance(event, dict) else {}
            for part in content.get("parts", []) or []:
                fc = part.get("function_call")
                if fc:
                    tool_calls.append(fc.get("name", "?"))
                fr = part.get("function_response")
                if fr and fr.get("name") == "issue_refund":
                    resp = fr.get("response") or {}
                    if isinstance(resp, dict):
                        refund_amt = resp.get("amount", refund_amt)
                        charge_amt = resp.get("charge_amount", charge_amt)
                if part.get("text"):
                    final_text = part["text"]
        over = (
            isinstance(refund_amt, (int, float))
            and isinstance(charge_amt, (int, float))
            and round(refund_amt, 2) > round(charge_amt, 2)
        )
        return {"ok": True, "tool_calls": tool_calls, "final_text": final_text,
                "refund": refund_amt, "charge": charge_amt, "over_refund": over}
    except Exception as exc:
        return {"ok": False, "err": f"{type(exc).__name__}:{exc}"}


def drive(n: int, prompt: str, user_prefix: str = "prod-traffic",
          concurrency: int = 1) -> int:
    _load_env()
    engine_name = os.environ.get("AGENT_ENGINE", AGENT_ENGINE)
    if not engine_name:
        print(
            "Set AGENT_ENGINE to the resource name printed by "
            "deploy/agent_engine.py, e.g.\n"
            "  export AGENT_ENGINE=projects/<num>/locations/<loc>/"
            "reasoningEngines/<id>",
            file=sys.stderr,
        )
        return 4

    try:
        import vertexai
        from vertexai import agent_engines
    except Exception as exc:  # pragma: no cover
        print(f"needs google-cloud-aiplatform[agent-engines]: {exc}", file=sys.stderr)
        return 2

    project = engine_name.split("/")[1]
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
    vertexai.init(project=project, location=location)

    engine = agent_engines.get(engine_name)
    concurrency = max(1, min(concurrency, n))
    print(f"driving {n} request(s) at {engine_name} (concurrency={concurrency})")
    print(f"  prompt: {prompt}")

    ok = 0
    done = 0
    over = 0        # refunds that over-paid (invariant RED)
    within = 0      # refunds within charge (invariant GREEN)
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {
            pool.submit(_one, engine, prompt, f"{user_prefix}-{i}"): i
            for i in range(n)
        }
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            if r.get("ok"):
                ok += 1
                if r.get("over_refund"):
                    over += 1
                elif r.get("refund") is not None:
                    within += 1
                if done % 10 == 0 or done == n:
                    verdict = ("OVER $%.0f/$%.0f" % (r["refund"], r["charge"])
                               if r.get("over_refund")
                               else "within $%s/$%s" % (r.get("refund"), r.get("charge")))
                    print(f"  [{done}/{n}] {' -> '.join(r['tool_calls'])}  [{verdict}]")
            else:
                print(f"  [{done}/{n}] FAILED: {r.get('err')}", file=sys.stderr)

    print(f"\ndone: {ok}/{n} ok  |  invariant: {within} within-charge (GREEN), "
          f"{over} over-refund (RED)")
    print("Traces flow to Cloud Trace; the online monitor samples them ~every 10 min.")
    return 0 if ok else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--n", type=int, default=8, help="number of requests to send")
    p.add_argument("--prompt", default=DEFAULT_PROMPT)
    p.add_argument("--user-prefix", default="prod-traffic")
    p.add_argument("--concurrency", type=int, default=1,
                   help="parallel in-flight requests (keep modest to avoid quota)")
    a = p.parse_args(argv)
    return drive(a.n, a.prompt, a.user_prefix, a.concurrency)


if __name__ == "__main__":
    raise SystemExit(main())
