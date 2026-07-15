"""Console report for an :class:`~evals.eval_core.EvalResult`.

Plain-text table (no deps). In the real demo the same numbers show up in the
Evaluation tab of the Cloud Console; this is the offline / CI view.
"""

from __future__ import annotations

from .eval_core import EvalResult
from .metrics import GATING_METRICS, METRIC_KIND

_COLOUR_TAG = {"green": "[green]", "amber": "[amber]", "grey": "[grey]"}


def _fmt_score(name: str, score: float, expected_failing: list[str]) -> str:
    """One metric line. A red score is only a FAIL when it is UNEXPECTED.

    The seed set carries adversarial cases whose invariant is SUPPOSED to read
    red — so a red that matches the case's expected set is the check doing its job
    ("RED (expected)"), not a build failure. A red that is NOT expected is the
    thing that blocks the merge ("FAIL <- REGRESSION"). This keeps the log honest:
    on a green build you never see the word FAIL.
    """
    tag = _COLOUR_TAG.get(METRIC_KIND.get(name, ""), "")
    if score >= 1.0:
        mark = "ok"
    elif name not in GATING_METRICS:
        mark = "flag (judge — non-gating)"
    elif name in expected_failing:
        mark = "RED (expected — the invariant fired)"
    else:
        mark = "FAIL <- REGRESSION (blocks merge)"
    return f"{name}{tag}={score:.1f} {mark}"


def _case_status(c) -> str:
    """EDD status: does the case's verdict match the contract's expectation?"""

    if c.regressed:
        return "REGRESSION <-- verdict changed from what the contract expects"
    if c.expected_failing_invariants:
        # A red invariant that was SUPPOSED to fire — the check doing its job.
        return f"caught (expected: {', '.join(c.expected_failing_invariants)})"
    return "PASS"


def render(result: EvalResult) -> str:
    lines: list[str] = []
    lines.append("Offline evaluation — one function, three jobs (this is the test job)")
    lines.append("=" * 72)
    for c in result.cases:
        lines.append(
            f"\n{c.id}  ({c.kind} / scenario={c.scenario})  [{_case_status(c)}]"
        )
        for name, score in c.scores.items():
            lines.append(f"    {_fmt_score(name, score, c.expected_failing_invariants)}")
        if c.note:
            lines.append(f"    · {c.note}")
    lines.append("\n" + "-" * 72)
    # The bottom line is the EDD gate: block on a *regression*, not on the seed
    # set's expected adversarial reds. Break the red count into expected catches
    # (adversarial cases doing their job) vs regressions (a verdict that diverged
    # from the contract) so "why did it block?" reads clean on screen.
    regression_ids = {c.id for c in result.regressions}
    expected_catches = sum(1 for c in result.failing if c.id not in regression_ids)
    n_reg = len(result.regressions)
    red_breakdown = f"{expected_catches} expected catch{'es' if expected_catches != 1 else ''}"
    if n_reg:
        red_breakdown += f" + {n_reg} regression{'s' if n_reg != 1 else ''}"
    lines.append(
        f"cases={result.total}  red={len(result.failing)} ({red_breakdown})  "
        f"EDD_gate={'OK' if result.edd_gate_ok else 'BLOCK MERGE'}"
    )
    lines.append(
        "  (a red invariant is the check doing its job; the gate blocks only on a "
        "REGRESSION — a verdict that diverged from the contract's expectation.)"
    )
    return "\n".join(lines)


def render_regressions(cases) -> str:
    """Explain each regression: which case, which invariant, which direction."""

    lines = ["REGRESSIONS — the merge gate is blocking:"]
    for c in cases:
        if c.unexpected_failures:
            lines.append(
                f"  • {c.id}: NEW failure(s) {c.unexpected_failures} — a bug this "
                "case did not have before (an invariant now reads red)."
            )
        if c.missed_failures:
            lines.append(
                f"  • {c.id}: invariant(s) {c.missed_failures} STOPPED firing — the "
                "check was weakened; a bug it used to catch would now slip through."
            )
    lines.append(
        "  ↳ fix the code (or, if the contract truly changed, update the case's "
        "expected_failing_invariants in evals/data/eval_cases.json)."
    )
    return "\n".join(lines)


def print_report(result: EvalResult) -> None:
    print(render(result))
