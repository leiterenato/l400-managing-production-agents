# Managing Production Agents at Scale — from Chaos to Reliability
**L400 session · 30 min · (pre-recorded) demos on Google Cloud**

An agent that works in a demo is just the start. The real problems show up in production — and **explode at scale**. This session shows the **three problems** almost every team hits when running real agents, and **how to solve each one on Google Cloud** — with working demos.

**The three problems:**

- **You change the agent and can't tell if you made it worse.** A prompt tweak or a model swap passes the "green" deploy, and days later you find the agent has been quietly getting things wrong. The fix: **Eval-Driven Development (EDD)** — test the agent's behavior *before* it ships and keep testing in production (it's TDD for agents).

- **One slow dependency takes the whole fleet down — and the bill with it.** Under real traffic the agent retries blindly, cost spikes (a small bump becomes a blowout), and it "makes up an answer" instead of failing honestly. The fix: resilience — circuit breakers, graceful degradation, and per-session cost budgets.

- **One malicious message turns your agent against you.** An attacker tricks it into leaking data or taking an action it shouldn't. The fix: zero-trust — make the infrastructure itself refuse the access (a hard "no" at the data), instead of relying on a filter that can be bypassed.
