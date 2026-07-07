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

    @property
    def gate_failed(self) -> bool:
        return any(self.scores.get(m, 1.0) < 1.0 for m in GATING_METRICS)

    def failed_metrics(self) -> list[str]:
        return [m for m, s in self.scores.items() if s < 1.0]


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


def evaluate_dataset(dataset: list[dict[str, Any]]) -> EvalResult:
    """Score every recorded instance in ``dataset``."""

    cases = [
        CaseResult(
            id=inst.get("id", f"case-{i}"),
            kind=inst.get("kind", ""),
            scenario=inst.get("scenario", ""),
            scores=evaluate_instance(inst),
            note=inst.get("note", ""),
        )
        for i, inst in enumerate(dataset)
    ]
    return EvalResult(cases=cases)
