"""Console report for an :class:`~evals.eval_core.EvalResult`.

Plain-text table (no deps). In the real demo the same numbers show up in the
Evaluation tab of the Cloud Console; this is the offline / CI view.
"""

from __future__ import annotations

from .eval_core import EvalResult
from .metrics import METRIC_KIND

_COLOUR_TAG = {"green": "[green]", "amber": "[amber]", "grey": "[grey]"}


def _fmt_score(name: str, score: float) -> str:
    tag = _COLOUR_TAG.get(METRIC_KIND.get(name, ""), "")
    mark = "ok " if score >= 1.0 else "FAIL"
    return f"{name}{tag}={score:.1f} {mark}"


def render(result: EvalResult) -> str:
    lines: list[str] = []
    lines.append("Offline evaluation — one function, three jobs (this is the test job)")
    lines.append("=" * 72)
    for c in result.cases:
        status = "PASS" if not c.gate_failed else "FAIL <-- green score would have lied"
        lines.append(f"\n{c.id}  ({c.kind} / scenario={c.scenario})  [{status}]")
        for name, score in c.scores.items():
            lines.append(f"    {_fmt_score(name, score)}")
        if c.note:
            lines.append(f"    · {c.note}")
    lines.append("\n" + "-" * 72)
    lines.append(
        f"cases={result.total}  pass_rate={result.pass_rate:.0%}  "
        f"failing={len(result.failing)}  "
        f"gate={'OK' if result.gate_ok else 'BLOCK MERGE'}"
    )
    return "\n".join(lines)


def print_report(result: EvalResult) -> None:
    print(render(result))
