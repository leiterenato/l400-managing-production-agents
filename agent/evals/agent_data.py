"""Adapter: Evaluation Service instance -> the contract's ``turns`` shape.

The Gen AI Evaluation Service hands a custom metric an ``instance`` dict whose
agent conversation lives at::

    instance["agent_data"]["turns"][*]["events"][*]["content"]["parts"][*]

where each part is either a ``function_call`` ({name, args}) or a
``function_response`` ({name, response}). Our contract invariants
(:mod:`financial_support.contract`) instead read the normalized shape
``turns[*]["tool_calls"][*] = {name, args, response}``.

This module is the ONE place that bridges the two. Because the invariants
themselves come straight from :mod:`financial_support.contract` (the single
source of truth used by the runtime callback and pytest), the live metric adds
no second copy of the logic — only this format adapter.

**Fail-loud contract:** if an instance carries no usable ``agent_data`` (for
example a placeholder left behind by a failed inference run), we raise. The
Evaluation Service turns that into a metric *error* (``num_cases_error``), which
is visible — never a silent ``1.0``. A metric that can't read its input must not
report green. That is the whole point of Case 1.
"""

from __future__ import annotations

from typing import Any


def platform_instance_to_turns(instance: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert a platform ``instance`` into contract ``turns`` with tool_calls.

    Raises:
        ValueError: if the instance has no ``agent_data`` with turns (a failed /
            placeholder run) — so the metric errors loudly instead of passing.
    """

    agent_data = instance.get("agent_data")
    if not isinstance(agent_data, dict) or not agent_data.get("turns"):
        raise ValueError(
            "instance has no agent_data.turns — cannot evaluate the trajectory "
            "(likely a failed/placeholder inference run). Refusing to score."
        )

    tool_calls: list[dict[str, Any]] = []
    pending_args: dict[str, list[dict[str, Any]]] = {}

    for turn in agent_data["turns"]:
        for event in turn.get("events", []) or []:
            parts = (event.get("content") or {}).get("parts") or []
            for part in parts:
                fc = part.get("function_call")
                fr = part.get("function_response")
                if fc:
                    name = fc.get("name")
                    pending_args.setdefault(name, []).append(fc.get("args") or {})
                elif fr:
                    name = fr.get("name")
                    args_queue = pending_args.get(name) or []
                    args = args_queue.pop(0) if args_queue else {}
                    tool_calls.append(
                        {
                            "name": name,
                            "args": args,
                            "response": fr.get("response") or {},
                        }
                    )

    # One synthetic turn carrying the ordered tool calls — exactly what the
    # contract's iter_tool_calls / trace checks consume.
    return [{"tool_calls": tool_calls}]
