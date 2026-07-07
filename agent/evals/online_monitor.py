"""Online monitor — the same invariant, watching production 24/7 (S4).

Offline simulation of the platform's continuous eval: the ``OnlineEvaluator``
samples a fraction of production traces (~every 10 min), scores them with the
*same* invariant, writes to Cloud Logging + Cloud Monitoring, and a Cloud
Monitoring alert policy fires when the score drops below a threshold.

Honesty for the stage: the alert **notifies only** (Slack / email / PubSub). It
does not gate — the gate is Cloud Build at merge time. Here we simulate a stream
whose quality drifts, and show the rolling invariant pass-rate tripping the
alert. Deterministic (index-driven, no randomness) so the demo repeats exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import local_invariant_score
from .scenarios import staged_instance


def synth_stream(n: int = 60, drift_at: int = 40, bad_every: int = 2):
    """Yield production-like instances; after ``drift_at`` some over-refund.

    Before the drift point every refund is clean ($50 on $50). After it, one in
    every ``bad_every`` is the $500-on-$50 bug — a regression creeping in.
    """

    for i in range(n):
        if i >= drift_at and i % bad_every == 0:
            yield staged_instance(refund_amount=500.0, charge_amount=50.0)
        else:
            yield staged_instance(refund_amount=50.0, charge_amount=50.0)


@dataclass
class MonitorEvent:
    index: int
    pass_rate: float
    alert: bool


def run_monitor(
    threshold: float = 0.9,
    window: int = 10,
    n: int = 60,
    drift_at: int = 40,
) -> list[MonitorEvent]:
    """Slide a window over the stream; flag when pass-rate falls below threshold."""

    scores: list[float] = []
    events: list[MonitorEvent] = []
    alerted = False
    for i, inst in enumerate(synth_stream(n=n, drift_at=drift_at)):
        scores.append(local_invariant_score(inst))
        window_scores = scores[-window:]
        rate = sum(window_scores) / len(window_scores)
        fired = False
        if rate < threshold and not alerted:
            alerted = True
            fired = True
        events.append(MonitorEvent(index=i, pass_rate=rate, alert=fired))
    return events


def render(events: list[MonitorEvent], threshold: float = 0.9) -> str:
    lines = [
        "Online monitor — refund_within_charge over a production stream",
        f"(sampling window; alert threshold = {threshold:.0%}, notify-only)",
        "=" * 64,
    ]
    for e in events:
        bar = "#" * int(round(e.pass_rate * 20))
        tag = "   <== ALERT: quality below threshold (notify Slack/email)" if e.alert else ""
        # Print every 5th sample plus any alert, to keep it readable.
        if e.index % 5 == 0 or e.alert:
            lines.append(f"  t={e.index:>3}  {e.pass_rate:5.0%} |{bar:<20}|{tag}")
    fired = [e for e in events if e.alert]
    lines.append("-" * 64)
    if fired:
        lines.append(
            f"Alert fired at t={fired[0].index}: the same invariant that gated the "
            "merge now watches production."
        )
    else:
        lines.append("No alert — production stayed healthy.")
    return "\n".join(lines)


def main() -> int:
    events = run_monitor()
    print(render(events))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
