"""Run the fraud-check agent as an A2A server.

    uv run python -m fraud_check_a2a            # serves on http://localhost:8001

Then point the main agent at it:

    USE_A2A_FRAUD=true FRAUD_AGENT_URL=http://localhost:8001 uv run adk web

The agent card is published at
``http://localhost:8001/.well-known/agent-card.json``.
"""

from __future__ import annotations

import os

import uvicorn
from google.adk.a2a.utils.agent_to_a2a import to_a2a

from .agent import root_agent

HOST = os.environ.get("FRAUD_AGENT_HOST", "localhost")
PORT = int(os.environ.get("FRAUD_AGENT_PORT", "8001"))

# Starlette app implementing the A2A protocol for `root_agent`.
a2a_app = to_a2a(root_agent, host=HOST, port=PORT)


def main() -> None:
    uvicorn.run(a2a_app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()
