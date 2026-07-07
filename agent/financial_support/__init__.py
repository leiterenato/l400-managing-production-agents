"""Financial Support Agent — the base agent that matures across the L400 cases.

ADK discovers ``root_agent`` from this package (``adk web`` / ``adk run``).

The package is organised so each case adds capability without breaking the
structure:
  * ``contract.py``      — the behavioural contract + invariants (Case 1 / EDD).
  * ``tools/``           — the agent's tools (mock backends behind them).
  * ``backends/``        — swappable mock external systems + fault injection.
  * ``callbacks/``       — cross-cutting concerns, composed via a registry
                            (Case 2 resilience / Case 3 zero-trust plug in here).
  * ``observability/``   — the OTel substrate (always on).
  * ``sub_agents/``      — the specialists.
"""

from . import agent
from .agent import root_agent

__all__ = ["agent", "root_agent"]
