"""Run the Case 1 offline evaluation.

Two modes:

  * ``--dry-run`` (default): score staged traces with the **portable** invariant
    (no GCP, no model). This is what CI and pytest use, and what proves "the
    green score lies" deterministically — the $500-on-$50 case scores 0.0 while
    a tone judge would pass it.

  * ``--live``: run the real Gen AI Evaluation Service pipeline
    (generate_conversation_scenarios -> run_inference -> evaluate). Requires
    ``google-cloud-aiplatform[evaluation]`` and GCP credentials; results appear
    in the **Evaluation** tab of the Console (not ``.show()``, which is a
    notebook renderer).

Exit code is non-zero when any invariant fails, so this doubles as the merge
gate that ``deploy/cloudbuild.yaml`` runs on a PR (the gate is Cloud Build, not
a native platform feature).
"""

from __future__ import annotations

import argparse
import sys

from .metrics import local_invariant_score
from .scenarios import demo_instances


def dry_run() -> int:
    """Score staged instances locally. Returns process exit code."""

    instances = demo_instances()
    print(f"Scoring {len(instances)} staged instance(s) with refund_within_charge\n")

    failures = 0
    for inst in instances:
        turn = inst["agent_eval_data"]["turns"][0]
        call = turn["tool_calls"][0]["response"]
        score = local_invariant_score(inst)
        ok = score == 1.0
        failures += 0 if ok else 1
        flag = "PASS" if ok else "FAIL  <-- the green score would have lied"
        print(
            f"  refund={call['amount']:>7} charge={call['charge_amount']:>6} "
            f"| refund_within_charge={score:.1f}  [{flag}]"
        )

    print()
    if failures:
        print(f"{failures} invariant failure(s). Gate: BLOCK MERGE.")
        return 1
    print("All invariants passed. Gate: OK.")
    return 0


def live_run() -> int:
    """Run the real Evaluation Service pipeline (requires GCP)."""

    try:
        from vertexai import Client, types  # noqa: F401
    except Exception as exc:  # pragma: no cover
        print(
            "Live eval needs google-cloud-aiplatform[evaluation] and GCP creds.\n"
            f"Import failed: {exc}\n"
            "Run with --dry-run for the offline, portable path.",
            file=sys.stderr,
        )
        return 2

    from financial_support.config import get_settings

    from .metrics import build_invariant_metric, build_judge_metric

    settings = get_settings()
    client = Client(project=settings.project, location=settings.location)

    # NOTE: wiring shown for reference; a runnable agent + dataset are required.
    # generate_conversation_scenarios -> run_inference -> evaluate.
    print(
        "Live pipeline scaffold ready.\n"
        f"  project={settings.project} location={settings.location}\n"
        "  metrics: refund_within_charge (green), tone_check (amber),\n"
        "           FINAL_RESPONSE_QUALITY / HALLUCINATION / SAFETY (grey).\n"
        "Fill in dataset + client.evals.evaluate(...) for your project."
    )
    _ = (build_invariant_metric, build_judge_metric, client)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Case 1 offline evaluation.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the real Evaluation Service pipeline (requires GCP).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score staged traces locally (default).",
    )
    args = parser.parse_args(argv)

    if args.live:
        return live_run()
    return dry_run()


if __name__ == "__main__":
    raise SystemExit(main())
