"""The resilience seam (Case 2) — semantic circuit breaker + cost/budget.

Case 1 proved the money with an ``after_tool`` invariant. Case 2 reuses the very
same callback seam for two new jobs: it *protects* the money (a semantic circuit
breaker that, when a shared dependency degrades, injects a deterministic fact back
into the model's context instead of letting it retry blindly) and it *measures*
the money (cost per model span + a per-session spend budget). One seam, many jobs.

Everything is dormant under ``CASE=1`` (the registry does not wire this bundle)
and the breaker additionally self-guards on ``BREAKER != "on"`` — so turning the
concern on is a single env flip, and Case 1 is byte-for-byte unaffected.

Why a *semantic* breaker (the L400 twist)
-----------------------------------------
A library breaker returns an error. The consumer here is a reasoning loop: it
reads the error as "I must have called it wrong" and tries again — amplifying the
outage. So instead of returning an error we return a dict, which ADK hands to the
model as the tool result: a fact it can act on ("do not retry; follow fallback").
"""

from __future__ import annotations

import time
from typing import Any, Optional

from google.adk.models import LlmResponse
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from google.genai import types

from ..config import get_settings
from ..observability import cost_log
from . import telemetry

# Per-dependency failure counters. Process-global on purpose: a deployed instance
# serves many concurrent sessions (the "fleet"), and we WANT them to jointly trip
# the breaker for a shared dependency — that is the systemic behaviour the demo
# shows. Honest caveat: counters are per-process, not cross-instance.
_failures: dict[str, int] = {}

# Illustrative Gemini Flash pricing, USD per 1M tokens. Cost is a "scene number"
# for the demo; verify against the current gemini-3.5-flash list price before
# quoting a real figure on stage.
_PRICE = {"in": 0.30, "out": 2.50}


def reset() -> None:
    """Clear the breaker state (tests + the load harness's OFF->ON pass)."""

    _failures.clear()


def _start_key(tool_name: str) -> str:
    return f"_breaker_start_{tool_name}"


def circuit_breaker(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """ADK ``before_tool_callback``: short-circuit a degraded dependency.

    If the tool's circuit is OPEN, return a dict — ADK delivers it to the model
    AS the tool result. That dict is the injection: a deterministic instruction
    the model can follow ("unavailable; do not retry; use cache or hand off").
    Otherwise stamp a per-session start time so :func:`record_outcome` can measure
    latency — the breaker trips on SLOW, not only on hard errors (the shared
    dependency in the demo is *degraded*, not *down*).
    """

    if get_settings().breaker != "on":
        return None

    name = tool.name
    if _failures.get(name, 0) >= get_settings().breaker_open_after:
        telemetry.set_attribute("resilience.breaker.open", name)
        # THE HERO: this dict becomes the tool result the model reads.
        return {
            "status": "unavailable",
            "dependency": name,
            "instruction": (
                "This tool is unavailable right now. Do NOT retry it. Follow the "
                "fallback: if a cached value is provided, relay it and say it may "
                "be out of date; otherwise hand off to a human. Never invent a "
                "value."
            ),
            "cached_last_refund": tool_context.state.get("last_refund"),
        }

    tool_context.state[_start_key(name)] = time.time()
    return None


def record_outcome(
    tool: BaseTool,
    args: dict[str, Any],
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    """ADK ``after_tool_callback``: feed the breaker (trips on SLOW or ERROR).

    ADK runs ``after_tool`` even when ``before_tool`` short-circuited, so we must
    ignore our own injected ``unavailable`` result — otherwise the "success"
    branch would reset the counter, flap the breaker closed, and re-start the
    storm. This is the single most important correctness fix in this module.
    """

    if get_settings().breaker != "on":
        return None
    if not isinstance(tool_response, dict):
        return None

    status = tool_response.get("status")
    if status == "unavailable":
        # Our own injection came back around; do not touch the counter.
        return None

    name = tool.name
    # ADK's State supports get/[]=, but NOT pop/del — read the marker with get().
    # before_tool re-stamps a fresh start before every real (non-open) call, so a
    # stale value never survives to the next measured call.
    started = tool_context.state.get(_start_key(name))
    elapsed = (time.time() - started) if started is not None else 0.0

    if status == "error" or elapsed > get_settings().breaker_timeout_s:
        _failures[name] = _failures.get(name, 0) + 1
    else:
        _failures[name] = 0  # half-open: a fast success closes the circuit
    return None


def record_cost(callback_context, llm_response) -> None:
    """ADK ``after_model_callback``: compute cost from token usage.

    The platform captures I/O and latency per span but NOT cost, and token counts
    arrive aggregated. So we derive cost here (tokens x price), put it on the span
    as ``gen_ai.cost.usd`` (the number the console won't give you), and accumulate
    it on session state so the per-session budget can act on it.
    """

    usage = getattr(llm_response, "usage_metadata", None)
    if not usage:
        return None

    prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
    candidate_tokens = getattr(usage, "candidates_token_count", 0) or 0
    # Context caching (Slide 7) would discount cached_content_token_count on the
    # input side; thoughts_token_count would add to the output side. Kept simple.
    cost = (
        prompt_tokens * _PRICE["in"] + candidate_tokens * _PRICE["out"]
    ) / 1_000_000

    telemetry.set_attribute("gen_ai.cost.usd", cost)

    state = callback_context.state
    state["session_cost_usd"] = state.get("session_cost_usd", 0.0) + cost
    state["session_prompt_tokens"] = (
        state.get("session_prompt_tokens", 0) + prompt_tokens
    )
    state["session_candidate_tokens"] = (
        state.get("session_candidate_tokens", 0) + candidate_tokens
    )

    # Durable side of the seam: mirror cost to Cloud Logging for the Logging->BQ
    # cost corpus (no-op unless enabled). Mirrors invariants -> verdict_log.
    cost_log.emit_cost(callback_context, cost, prompt_tokens, candidate_tokens)
    return None


def budget_guard(callback_context, llm_request) -> Optional[LlmResponse]:
    """ADK ``before_model_callback``: stop a runaway session locally.

    When the accumulated session cost crosses the budget, short-circuit the model
    with a canned, honest hand-off (NOT an empty response) — local containment,
    the same spirit as the breaker but for spend.
    """

    budget = get_settings().session_budget_usd
    if callback_context.state.get("session_cost_usd", 0.0) >= budget:
        telemetry.set_attribute("resilience.budget.exceeded", True)
        return LlmResponse(
            content=types.Content(
                role="model",
                parts=[
                    types.Part(
                        text=(
                            "I've reached this session's spend limit, so I'm "
                            "pausing here. A human agent will follow up to confirm "
                            "and complete this safely."
                        )
                    )
                ],
            )
        )
    return None
