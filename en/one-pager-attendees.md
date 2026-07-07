# Managing Production Agents at Scale

**L400 · 30 min · applied playbook — for engineers running agents in production (or about to).**

---

**The one line.** An agent that works in a demo is the easy part. This session follows *one* real agent — a financial-support agent that reads customer data and issues refunds — as it grows from prototype to production at scale, and shows the engineering discipline each stage forces on you.

**Why scale is the whole point.** The problems aren't new. What scale does is change their *character*: in a prototype you patch each one by hand — read the log, write twenty tests, add a `max_iterations`. At scale every one of those hand-patches breaks, and has to become an **architectural discipline**. We follow one agent maturing under that pressure, and for each fracture we answer two questions: **why it happens at scale**, and **how to solve it on Google Cloud**.

The mental model, in one breath:

> **"I don't know if I improved"** → **"I break under load"** → **"I can't scale with control."**

Each stage adds one layer to the *same* architecture. The final slide is the **complete reference architecture** — the map you take home.

---

## Three failures, three fixes

**1 — "It passed. So why is it wrong in production?"**
With a non-deterministic agent, a green build is *false confidence*: the agent can reach the right answer down the wrong path, and a regression can hide for days. **The fix:** write the eval *from the agent's behavior contract, before the agent* (Eval-Driven Development — think TDD/BDD for agents), score the whole **trajectory** and not just the final answer, gate it in CI, and keep it alive with a **quality flywheel** that feeds production traces back in. You stop shipping on vibes.

**2 — "One slow dependency took the whole fleet down."**
A single degraded API, amplified across thousands of sessions, becomes a **retry storm**; cost goes non-linear (2× traffic → 20× tokens); and an agent that doesn't understand "network error" will happily **invent the answer**. **The fix:** a *semantic* circuit breaker and a **fallback ladder** so the agent degrades honestly instead of hallucinating, a per-session cost budget, and cost you can actually attribute — down to the user, project, and org.

**3 — "A prompt made it leak another customer's data."**
Agent security is **identity architecture**, not a smarter content filter — and a prompt injection is an outage. If the agent runs as one all-powerful service account, it can do anything for anyone (the *confused deputy*). **The fix:** push the **user's own identity** all the way down to the data, so access is denied at the data layer — a real, deterministic **403 from the infrastructure**, not a hopeful guardrail. And every attack we catch becomes a permanent test case back in Case 1 — the loop closes.

---

## What you'll leave with (Monday morning)

1. Instrument **trajectory and cost per step** — observability as the foundation, not an afterthought.
2. **Write the eval before the agent**, and gate every change on it.
3. No production tool-call outside a **circuit breaker** with a deterministic fallback — and a **cost budget** per session and per user/project/org.
4. Take *god-mode* away from service accounts; **delegate the user's identity** down to the data.

## What to expect in the room
- We open with the **disaster**, not the theory.
- Demos run on **Google Cloud** and show real parts of the architecture. We're honest about what's live versus mocked — and the **Case 3 403 is genuinely real** (it's hard to fake infrastructure saying no).
- Technical and applied. You leave with the reference architecture and the disciplines to build it — not a product tour.
