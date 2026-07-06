# Managing Production Agents at Scale — 1-pager

**Thesis (scale is the whole point).** An agent that works in a demo is just the start. The real problems show up in production — and **change character at scale**. They're universal problems; what scale does is turn them from *quantitative into qualitative*: in a prototype you work around each one by hand (read the log, write 20 tests, add a `max_iterations`), and at scale every manual workaround **breaks** and has to become an **architectural discipline**. This session follows **one agent maturing under that pressure**, and for each fracture delivers the answer: **why it happens at scale**, and **how to solve it on Google Cloud**.

**The mental model (the 10-second version).** A single agent climbs a **maturity journey**, and the *architecture grows with it*:

> **"I'm blind"** (substrate) → **"I don't know if I improved"** (Case 1) → **"I break under load"** (Case 2) → **"I can't scale with control"** (Case 3).

Each stage adds one layer to the same architecture. The final slide is the **complete reference architecture** — the map the audience takes home.

**Audience & format.** Technical **L400** with an **applied / playbook** bias. 30 min. Each case has a **problem** slide (architecture + pain, in red) and a **solution** slide (the same architecture gaining a layer, in green), with **demos** on Google Cloud for credibility. The architecture is **cumulative** — that cumulative diagram *is* the scale story made visible.

---

## The architecture that grows (the spine)

The talk is organized around **one diagram that gains a layer per case**. This is where "managing agents *at scale*" becomes concrete — each layer exists because the previous one broke under load.

| Layer | What the architecture gains | What breaks at scale (why the layer exists) |
|---|---|---|
| **Substrate — Observability** | `User → Agent → {Tools · RAG · LLM}` with **runtime trace** underneath | You can't eyeball logs across thousands of sessions; without capture there's no eval, no diagnosis, no forensics. |
| **+ Case 1 — Quality** | the **evaluation flywheel** wrapped around the lifecycle (capture → evaluate → gate → monitor → feed back) | Non-determinism makes a "green" deploy **false confidence**; regressions hide in the *trajectory* across sessions and go unseen for days. |
| **+ Case 2 — Resilience & cost** | **circuit breaker + fallback ladder** around each tool-call; **per-session budget**; predictable capacity; **cost governance** | One degraded shared dependency, amplified by the **fleet**, becomes a **retry storm**; cost goes **non-linear** (2× traffic → 20× tokens); quota 429. |
| **+ Case 3 — Zero-Trust** | **user-identity delegation → 403 at the data**; deterministic enforcement at the **perimeter**; defense-in-depth; forensic replay | One god-mode service account across **many users** = the *confused deputy*; identity must **propagate across services**; **an injection is an outage**. |
| **= Reference architecture** | the sum of all layers | the map the FDE assembles for a customer. |

**The conceptual spine (two lenses + one flywheel).**
- **Substrate — Observability.** Not a case; the floor. It shows up three times doing different work: **capture** (data for the eval), **diagnosis** (the *waterfall* that finds the dependency that went down), **forensics** (the replay of the attack).
- **Two lenses.** **AgentOps** (build-time: see, measure, version, ship — Case 1) and **ARE — Agent Reliability Engineering** (runtime: survive failure, the adversary, scale — Cases 2–3).
- **The flywheel ties it together.** The eval produces the number; AgentOps consumes it as a *gate* (pre-deploy), ARE as an *error budget* (in production). *(One-line bridge — not a structural beat.)*

---

## The three cases — concept → what breaks at scale → Google Cloud → platform vs. your code

**1. EDD / Continuous Evaluation (AgentOps).**
- *Concept:* in a non-deterministic system, "green build" is **false confidence** — worse than no eval; the agent can reach the right answer via the wrong path.
- *What breaks at scale:* a model swap → 8% of refunds wrong, **3 days** before anyone noticed; hand-written tests and a frozen "golden dataset" rot and never see new attacks.
- *Google Cloud:* generate the eval from the **behavior contract** (**Eval-Driven Development** — "BDD/TDD for agents"), evaluate **trajectory** (not just output) with AutoRaters/Judge LLM, **gate** it in CI (Cloud Build), and monitor in production — the **Quality Flywheel**. **Security payload:** the same eval set, derived from the tools' **API contracts (input/output parameters)**, doubles as a **data-exfiltration check** → the bridge to Case 3.
- *Platform vs. you:* platform gives the Gen AI Evaluation Service, trajectory metrics, Failure Clusters; **you** generate the eval from the contract, build the CI gate (not native), and curate the living set.

**2. Resilience & cost (ARE).**
- *Concept:* the fleet amplifies the *outage* of a shared dependency, with non-linear cost — a **stochastic distributed system, not an `if`**.
- *What breaks at scale:* an account API degrades → *retry storm*; a 2× traffic spike becomes 20× tokens; and the agent, not understanding "network failure," **invents the balance** (silent unavailability).
- *Google Cloud:* a **semantic** *circuit breaker* (inject the degradation back into the context) + **fallback ladder** (never hallucinate) + **per-session budget**; predictable capacity (Provisioned Throughput) and observable cost. **Cost governance across the org:** cost/token per span (your instrumentation) + labels → BigQuery → **cost per user / project / org**.
- *Platform vs. you:* platform gives capacity, caching, billing export; **you** decide the fallback ladder, the budget, and the model routing (there's no managed router).

**3. Zero-Trust (ARE / SecOps).**
- *Concept:* agent security is **identity architecture**, not "a better filter"; **injection = outage**.
- *What breaks at scale:* a malicious prompt leaks another customer's PII — the *confused deputy* (the agent's service account can do everything, for every user).
- *Google Cloud:* propagate the **user's own identity** down to the tool (**Agent Identity / SPIFFE** + **3-legged OAuth / Auth Manager**) → the data is blocked **at the data level** (**IAM + Row-Level Security = a hard 403**). Deterministic enforcement at the **perimeter** — **Agent Gateway + Agent Registry + IAP** (only registered agents/tools talk; mTLS + Context-Aware Access) — as a *light* boundary layer. Guardrails (Model Armor, Semantic Governance) are **defense-in-depth, never the primary control**. **A2A:** the same identity propagation is what extends cleanly to agent-to-agent calls (the natural next step). And each attack becomes a test case in the eval — **the flywheel closes**.
- *Platform vs. you:* platform gives identity, gateway, guardrails, audit logs; **you** impose least-privilege and loop the injection back into the eval. The **403 rides on IAM + RLS (GA)** even where the 3LO flow is Preview — what's shippable today.

---

## L400 coverage map (what this session covers)

| L400 area | Covered in | How |
|---|---|---|
| **Observability** (agent runtime trace) | Substrate — under all 3 cases | capture (data for the eval) · diagnosis (the waterfall) · forensics (the replay) |
| **Agent Identity** (IAM · 3-legged auth · SPIFFE · Auth Manager · A2A) | Case 3 | delegate the user's identity down to the tool → 403 at the data; A2A as the natural extension |
| **Advanced Identity, Security & Networking** (Agent Gateway · Agent Registry · IAP · Semantic Governance) | Case 3 | deterministic enforcement at the perimeter + guardrails as defense-in-depth |
| **Cost estimation & management** (users · projects · orgs) | Case 2 | per-session budget + cost/token per span (your instrumentation) + labels → BigQuery per user/project/org |
| **Evaluation as a security control** | Case 1 ↔ Case 3 | eval sets derived from the API contracts (input/output) test for **data exfiltration**; every attack feeds back as an adversarial case |

---

## Presentation dynamics
- **Cold open** with the disaster (visceral) before any concept.
- **Visual peaks:** the token graph rising and being **cut** by the circuit breaker; and the **side-by-side 403** (same prompt, two users — one gets the data, the other is blocked by the infrastructure: *"the model tried; the infrastructure said no"*).
- **Pre-recorded, pre-warmed demos** that show **parts** of the architecture — mocks are fine and stated honestly; the star is the **operational layer**, the agent is the *subject*. Only the Case 3 **403 stays genuinely real** (the credibility anchor).
- **L400 honesty:** separate what the platform delivers (*plumbing*) from what is your discipline/code; state the GA / Preview status of the products. We use the best available product (including Preview), and where the star is Preview we name the **GA mechanism underneath** (e.g., 403 = IAM + RLS = GA).

## What the audience takes home (Monday morning)
1. Instrument **trajectory + cost per step** (observability as the substrate).
2. **Write the eval before the agent (EDD)** and *gate* every change — and derive exfiltration checks from the API contracts.
3. No production *tool-call* outside a **circuit breaker** with a deterministic fallback; **budget cost** per session and per user/project/org.
4. Remove *god-mode* from service accounts; **delegate the user's identity** down to the tool.
