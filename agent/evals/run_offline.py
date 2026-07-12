"""Run the Case 1 offline evaluation — the merge gate.

Records deterministic traces for the seed cases, scores them with the local
metrics, prints the report and (on failure) the failure clusters, and exits
non-zero if any hard invariant regressed. That non-zero exit is what
``deploy/cloudbuild.yaml`` turns into a blocked merge (the gate is Cloud Build,
not a native platform feature).

    uv run python -m evals.run_offline            # offline gate (default)
    uv run python -m evals.run_offline --live     # real Evaluation Service

The ``--live`` path calls the real Gen AI Evaluation Service (Preview); results
appear in the Console's Evaluation tab. See :mod:`evals.live`.
"""

from __future__ import annotations

import argparse
import sys

from .clusters import cluster_failures, render_clusters
from .eval_core import evaluate_dataset
from .record import record_dataset
from .report import print_report, render_regressions


def offline_run() -> int:
    dataset = record_dataset()
    result = evaluate_dataset(dataset)
    print_report(result)

    # The EDD gate (Fase 5): block only on a REGRESSION — a case whose actual
    # verdict diverged from what the contract expects. The seed set deliberately
    # carries adversarial cases that SHOULD read red; a naive "block on any red"
    # gate would block every PR forever (and, worse, be blind to an invariant
    # that silently STOPPED catching its bug). Comparing to the per-case expected
    # set catches both a new red and a red that vanished.
    if result.regressions:
        print("\n" + render_regressions(result.regressions))
        # The failure clusters name the dominant pattern (the S4 flywheel view).
        print("\n" + render_clusters(cluster_failures(result)))
        return 1

    caught = sorted(
        {m for c in result.cases for m in c.expected_failing_invariants}
    )
    print(
        f"\nEDD gate GREEN — {result.total}/{result.total} cases match their "
        "expected verdicts."
    )
    if caught:
        print(
            "  the adversarial/silent cases tripped exactly the invariants they "
            f"target ({', '.join(caught)}); the checks work."
        )
    return 0


def live_run() -> int:
    from .live import run_live

    return run_live()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Case 1 offline evaluation / gate.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run the real Evaluation Service pipeline (requires GCP).",
    )
    args = parser.parse_args(argv)
    return live_run() if args.live else offline_run()


if __name__ == "__main__":
    raise SystemExit(main())
