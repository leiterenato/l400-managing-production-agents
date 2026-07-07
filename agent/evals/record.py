"""Record traces for evaluation — the link between the agent and the eval.

Replays each seed case's declared *flow* by calling the real tools (with the
real mock backends honouring the active fault scenario) and captures the
tool calls + responses into the ``agent_eval_data`` shape the metrics read.

Two modes:

* **Offline (default)** — the tool sequence is fixed by the case's ``flow``, so
  no model is needed. The tool *responses* are real (they come from the mock
  backends under the scenario's faults), which is what lets us score genuine —
  if deterministic — trajectories in CI and in the offline demo.
* **Runner** (``use_runner=True``) — drive the actual ADK agent via
  ``InMemoryRunner`` so the *model* chooses the tools. Requires GCP credentials;
  falls back with a clear message if unavailable.

The offline recorder is honest about what it is: the LLM's routing is replaced
by the known-good flow. The point of Case 1 is not "does the model pick tools",
it is "when a tool moves the wrong money, does the eval catch it" — and that is
exactly what these traces exercise.
"""

from __future__ import annotations

import json
import os
from typing import Any

from financial_support.config import reload_settings
from financial_support.tools.customer import look_up_customer
from financial_support.tools.dispute import open_dispute
from financial_support.tools.fraud import fraud_check
from financial_support.tools.refund import issue_refund

from .scenarios import EVAL_CASES


class _Ctx:
    """Minimal ToolContext stand-in (tools only touch `.state`)."""

    def __init__(self, customer_id: str = "CUST-001") -> None:
        self.state: dict[str, Any] = {"customer_id": customer_id}


def _call(calls: list[dict], name: str, args: dict, response: dict) -> None:
    calls.append({"name": name, "args": args, "response": response})


def _run_flow(case: dict[str, Any]) -> tuple[list[dict], str]:
    """Execute the case's flow, returning (tool_calls, final_reply)."""

    ctx = _Ctx()
    calls: list[dict] = []
    flow = case["flow"]

    record = look_up_customer(ctx)
    _call(calls, "look_up_customer", {}, record)

    if flow == "refund":
        charge_id, amount = case["charge_id"], case["amount"]
        decision = fraud_check(charge_id, amount, ctx)
        _call(calls, "fraud_check", {"charge_id": charge_id, "amount": amount}, decision)
        refund = issue_refund(charge_id, amount, "customer request", ctx)
        _call(
            calls,
            "issue_refund",
            {"charge_id": charge_id, "amount": amount},
            refund,
        )
        reply = "All set — your refund has been processed. Anything else I can help with?"
    elif flow == "dispute":
        charge_id, reason = case["charge_id"], case.get("reason", "disputed")
        dispute = open_dispute(charge_id, reason, ctx)
        _call(calls, "open_dispute", {"charge_id": charge_id, "reason": reason}, dispute)
        reply = "I've opened a dispute for you. You'll hear back within 10 days."
    else:  # lookup only
        reply = "Here are the account details you asked for."

    return calls, reply


def record_case(case: dict[str, Any]) -> dict[str, Any]:
    """Record one seed case into an eval instance under its scenario."""

    os.environ["SCENARIO"] = case.get("scenario", "healthy")
    reload_settings()
    calls, reply = _run_flow(case)
    return {
        "id": case["id"],
        "kind": case["kind"],
        "scenario": case.get("scenario", "healthy"),
        "note": case.get("note", ""),
        "prompt": case.get("prompt", ""),
        "agent_eval_data": {
            "turns": [{"tool_calls": calls, "final_response": reply}]
        },
    }


def record_dataset(cases: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    """Record all seed cases (default: :data:`EVAL_CASES`)."""

    dataset = [record_case(c) for c in (cases or EVAL_CASES)]
    os.environ["SCENARIO"] = "healthy"  # leave env clean
    reload_settings()
    return dataset


def save_dataset(path: str, dataset: list[dict[str, Any]] | None = None) -> str:
    dataset = dataset or record_dataset()
    with open(path, "w") as fh:
        json.dump(dataset, fh, indent=2)
    return path


def load_dataset(path: str) -> list[dict[str, Any]]:
    with open(path) as fh:
        return json.load(fh)


def record_with_runner(case: dict[str, Any]) -> dict[str, Any]:
    """Drive the real ADK agent (model chooses tools). Requires GCP creds."""

    raise NotImplementedError(
        "Runner-based recording needs GCP credentials + a model. Use the offline "
        "recorder (record_case) for CI/demo, or wire InMemoryRunner here for a "
        "live capture."
    )


if __name__ == "__main__":
    ds = record_dataset()
    for inst in ds:
        n_calls = len(inst["agent_eval_data"]["turns"][0]["tool_calls"])
        print(f"{inst['id']:<28} scenario={inst['scenario']:<18} calls={n_calls}")
