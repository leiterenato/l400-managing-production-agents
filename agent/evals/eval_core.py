"""Offline evaluation core: score a dataset, decide the gate.

Pure, no GCP. Runs the local metrics over recorded traces and produces an
:class:`EvalResult`. The gate fails if any *hard invariant* (green) fails —
the judge (amber) never gates. This is the same shape the live Evaluation
Service returns; here it runs offline so CI and the demo are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .metrics import GATING_METRICS, evaluate_instance


@dataclass
class CaseResult:
    id: str
    kind: str
    scenario: str
    scores: dict[str, float]
    note: str = ""
    # The EDD gate's oracle: the invariants this case is EXPECTED to trip (from
    # the versioned eval set). Happy cases: []. Adversarial/silent: the one they
    # target. See :meth:`regressed`.
    expected_failing_invariants: list[str] = field(default_factory=list)

    @property
    def gate_failed(self) -> bool:
        # A gating metric that is MISSING from the scores must fail the gate, not
        # pass it (a metric that could not run is not evidence of correctness).
        # NOTE: this is the DESCRIPTIVE "does any invariant read red" property
        # (drives the report + failure clusters). The MERGE gate is `regressed`
        # below — it compares red invariants to what the contract EXPECTS.
        return any(self.scores.get(m, 0.0) < 1.0 for m in GATING_METRICS)

    def failed_metrics(self) -> list[str]:
        return [m for m, s in self.scores.items() if s < 1.0]

    @property
    def actual_failing_invariants(self) -> list[str]:
        """Gating invariants that ACTUALLY read red on this case."""

        return [m for m in GATING_METRICS if self.scores.get(m, 0.0) < 1.0]

    @property
    def unexpected_failures(self) -> list[str]:
        """Red invariants the case was NOT expected to trip — a NEW regression."""

        expected = set(self.expected_failing_invariants)
        return [m for m in self.actual_failing_invariants if m not in expected]

    @property
    def missed_failures(self) -> list[str]:
        """Invariants the case SHOULD trip but no longer does — a WEAKENED check.

        This is the half a naive "block on any red" gate is blind to: if someone
        loosens ``refund_within_charge`` so the $500-on-$50 case slips through,
        the case goes green and a naive gate cheers. The EDD gate treats a
        no-longer-firing invariant as a failure too.
        """

        actual = set(self.actual_failing_invariants)
        return [m for m in self.expected_failing_invariants if m not in actual]

    @property
    def regressed(self) -> bool:
        """EDD gate verdict: actual invariants diverged from the contract.

        Fails on a mismatch in EITHER direction — an unexpected red (new bug) or
        an expected red that stopped firing (check weakened).
        """

        return bool(self.unexpected_failures or self.missed_failures)


@dataclass
class EvalResult:
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cases)

    @property
    def failing(self) -> list[CaseResult]:
        return [c for c in self.cases if c.gate_failed]

    @property
    def pass_rate(self) -> float:
        if not self.cases:
            return 1.0
        return (self.total - len(self.failing)) / self.total

    @property
    def gate_ok(self) -> bool:
        return not self.failing

    # --- EDD gate (the real merge gate) ----------------------------------
    # `failing`/`gate_ok` above describe which invariants read red — but the seed
    # set carries adversarial cases that are SUPPOSED to be red, so blocking on
    # those would block every PR. The EDD gate below blocks only on a *regression*
    # (actual verdict != the contract's expected verdict), in either direction.

    @property
    def regressions(self) -> list[CaseResult]:
        return [c for c in self.cases if c.regressed]

    @property
    def edd_gate_ok(self) -> bool:
        return not self.regressions


def evaluate_dataset(dataset: list[dict[str, Any]]) -> EvalResult:
    """Score every recorded instance in ``dataset``."""

    cases = [
        CaseResult(
            id=inst.get("id", f"case-{i}"),
            kind=inst.get("kind", ""),
            scenario=inst.get("scenario", ""),
            scores=evaluate_instance(inst),
            note=inst.get("note", ""),
            expected_failing_invariants=list(
                inst.get("expected_failing_invariants", [])
            ),
        )
        for i, inst in enumerate(dataset)
    ]
    return EvalResult(cases=cases)
