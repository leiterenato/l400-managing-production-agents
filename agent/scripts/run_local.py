"""Drive the tool + invariant seam locally — no model, no GCP, fully offline.

This exercises the exact runtime path the demo cares about: a tool runs, the
``after_tool_callback`` applies the contract invariant, and the verdict is
recorded. It makes "the green score lies" visible without needing the LLM.

    uv run python -m scripts.run_local                 # healthy
    uv run python -m scripts.run_local refund_over_charge
    uv run python -m scripts.run_local wrong_account

For the full agent (with the model + transfers), use `adk web` instead.
"""

from __future__ import annotations

import os
import sys

# Ensure the project root is importable when run as a script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeToolContext:
    """Minimal stand-in for ADK's ToolContext (tools only touch `.state`)."""

    def __init__(self, customer_id: str = "CUST-001") -> None:
        self.state: dict = {"customer_id": customer_id}


class FakeTool:
    def __init__(self, name: str) -> None:
        self.name = name


def main(argv: list[str]) -> int:
    scenario = argv[0] if argv else "healthy"
    os.environ["SCENARIO"] = scenario

    from financial_support.callbacks.invariants import enforce_invariants
    from financial_support.config import reload_settings
    from financial_support.tools.customer import look_up_customer
    from financial_support.tools.refund import issue_refund

    reload_settings()
    ctx = FakeToolContext()

    print(f"=== scenario: {scenario} ===\n")

    # 1) look_up_customer
    record = look_up_customer(ctx)
    enforce_invariants(FakeTool("look_up_customer"), {}, ctx, record)
    print(
        f"look_up_customer -> queried={record.get('queried_customer_id')} "
        f"session={record.get('session_customer_id')} name={record.get('name')}"
    )

    # 2) issue_refund ($50 requested on charge TXN-1001)
    resp = issue_refund("TXN-1001", 50.0, "customer request", ctx)
    enforce_invariants(FakeTool("issue_refund"), {}, ctx, resp)
    if resp.get("status") == "refunded":
        print(
            f"issue_refund   -> paid={resp['amount']} charge={resp['charge_amount']} "
            f"conf={resp['confirmation_id']}"
        )
    else:
        print(f"issue_refund   -> {resp}")

    # 3) report invariant violations recorded by the seam
    violations = ctx.state.get("invariant_violations", [])
    print()
    if violations:
        print("INVARIANT VIOLATIONS (the eval catches these):")
        for v in violations:
            print(f"  - {v['name']}: {v['detail']}")
        return 1
    print("No invariant violations. (Green — and this time it's true.)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
