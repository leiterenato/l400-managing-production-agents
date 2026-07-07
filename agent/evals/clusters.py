"""Failure clustering — turn "it failed" into "here is the dominant pattern".

Local, offline analogue of the platform's ``client.evals.generate_loss_clusters``.
It groups failing cases by a named pattern and counts them, so the demo's S4 beat
lands: not "one flaky case" but "Incorrect Tool Selection ×N".

The real service classifies against published taxonomies
(``multi_turn_task_success_v1``, ``multi_turn_tool_use_quality_v1``); the exact
label on stage comes from the Console. Here we map our contract invariants to the
closest named pattern so the offline story is coherent and testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .eval_core import EvalResult

# Map a failing metric to a human pattern name + the closest platform taxonomy.
_PATTERN = {
    "refund_within_charge": (
        "Refund Exceeds Charge",
        "multi_turn_task_success_v1 (policy / Incorrect Tool Selection)",
    ),
    "read_targets_session_customer": (
        "Cross-Account Data Access",
        "multi_turn_task_success_v1 (safety / data exfiltration)",
    ),
    "tone_check": (
        "Unprofessional Tone",
        "final_response_quality",
    ),
}


@dataclass
class Cluster:
    pattern: str
    taxonomy_hint: str
    count: int = 0
    case_ids: list[str] = field(default_factory=list)


def cluster_failures(result: EvalResult) -> list[Cluster]:
    """Group failing cases by the invariant they broke."""

    by_pattern: dict[str, Cluster] = {}
    for case in result.failing:
        for metric in case.failed_metrics():
            name, taxonomy = _PATTERN.get(metric, (metric, "uncategorised"))
            cluster = by_pattern.get(name)
            if cluster is None:
                cluster = Cluster(pattern=name, taxonomy_hint=taxonomy)
                by_pattern[name] = cluster
            cluster.count += 1
            cluster.case_ids.append(case.id)
    return sorted(by_pattern.values(), key=lambda c: c.count, reverse=True)


def render_clusters(clusters: list[Cluster]) -> str:
    if not clusters:
        return "No failure clusters."
    lines = ["Failure clusters (generate_loss_clusters, offline analogue):"]
    for c in clusters:
        lines.append(f"  • {c.pattern} ×{c.count}   [{c.taxonomy_hint}]")
        lines.append(f"      cases: {', '.join(c.case_ids)}")
    lines.append(
        "  ↳ each failing case rejoins the eval set — an attack today becomes a "
        "test forever."
    )
    return "\n".join(lines)
