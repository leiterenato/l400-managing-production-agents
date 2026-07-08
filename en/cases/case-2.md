# Case 2 — Resilience & Cost under Load
*(visual showpiece)*

> Standardized execution doc. Strategic summary in `../blueprint-presentation.md`.
> **Slide-by-slide narrative, architecture (Mermaid), reveals, speaker notes, and the L400-relevance discussion live in `../../docs/case-2-fundamentos.md`.**
> Platform: **Gemini Enterprise Agent Platform** → **Scale** pillar (Agent Runtime · Sessions · Memory Bank) + model consumption options (Provisioned Throughput · Context caching).
>
> **Observability absorbed here (substrate):** this case owns **two** functions of observability —
> **(a) diagnosis** (the trace **waterfall** — *which* dependency degraded, where the 18s went) and
> **(b) cost/token per span** (**your** instrumentation, because the platform does not capture cost; it is what **enables the per-session budget**). The waterfall becomes the **setup** for the circuit breaker; cost/span becomes the **enabler** of the budget.

---

## 1. Summary

| Field | Value |
|---|---|
| **Lens** | ARE |
| **Maturity** | *"I break under load"* |
| **Depth spikes (2)** | **A)** **semantic** circuit breaker + fallback ladder (your code) · **B)** **Provisioned Throughput** vs. on-demand/DSQ (the lever against the 429) |
| **End-to-end** | the fleet + shared dependency → **diagnosis (waterfall)** → contain the cascade + capacity/cost |
| **Time** | ~7 min · 2 slides |
| **Demo** | 3 beats: **waterfall** (diagnosis) → the tokens/latency chart **climbing and being cut off** → graceful fallback |

> **Pacing note:** this is the **highest visual energy** of the talk. Keep the vocabulary at the **systemic** level: *fleet · shared dependency · retry storm · blast radius*. That keeps you at L400.

---

## 2. The problem (the wound)

**The scene:** real volume arrived. The agent runs as a **fleet** — many concurrent sessions sharing the **same dependencies** (the account API, the model endpoint).

**The cascade (*cascading failure*):** the account API **degraded** — it got slow, it did not go down. The model **does not understand "network failure"**: it treats a timeout/500 as *"oh, I got the parameter wrong"* and tries again. Multiply by N sessions at the same time = **retry storm**: the fleet **amplifies** the dependency's problem and **saturates the runtime's concurrency**. And the **Agent Runtime is not infinitely elastic** (`min_instances` goes up to 10; `container_concurrency` is finite) — the fleet truly saturates.

**The 3 symptoms that come together:**
- **Non-linear cost:** fan-out + growing context + retries → a **2× traffic spike turned into 20× tokens**.
- **Quota (429):** the model endpoint hits the limit (**Dynamic Shared Quota**) → half the sessions fail.
- **Hallucination as an availability failure:** when the tool stalls, the agent **does not say "I don't know" — it invents the balance**. Silent unavailability, worse than an honest 500.

**The L400 insight (the hero):** this is a **stochastic distributed system**, not an `if`. The problem is **not ONE agent in a loop** — it is a **fleet amplifying the outage of a shared dependency**, with non-linear cost.

**⚠️ Trivial twin to avoid (dangerous):** "just add `max_iterations` / a circuit breaker." Frameworks already cap recursion. **That is not the problem.**

**Punchline:** the outage of **one** dependency became the outage of **your agent** — and the bill exploded along with it.

---

## 3. The end-to-end solution with Google Cloud (we are the heroes)

Most of this is **your discipline and code**; the platform provides the **plumbing**. Present it as **discipline**, not as a product feature.

### Front 0 — Diagnosis: find the degraded dependency *(observability absorbed)*
- Before containing, you need to **know what broke**. I open the trace **waterfall**: *"the model responded in 1s; this legacy tool took 18s. The fault is not the model — it's the external infra."*
- This is the substrate doing **diagnosis** work: in an agent, the span carries the **semantic content** (which tool, which args, latency per step), and that is what turns *"it took 20s"* into *"the account tool degraded."* **The waterfall is the setup for the circuit breaker** — you don't wrap blindly; you wrap the dependency the trace pointed at.

### Front 1 — Contain the cascade (your code)
- **Semantic circuit breaker** (half-open): after N failures on a dependency, it opens the circuit and **deterministically injects into the context** *"this tool is unavailable"* — instead of letting the model retry blindly.
- **Deterministic fallback ladder:** Gemini **Pro → Flash → cached response → human handoff**. Degrades gracefully, **never hallucinates**.
- **Per-session token/step budget** → contains the cost **blast radius**. **Enabled by cost/token per span** (see Front 2).

### Front 2 — Capacity and cost (Cloud plumbing + your policy)
- **Cost/token per span is *your* instrumentation (honesty beat):** observability captures I/O and latency per span natively, **but cost is not captured** and **token appears aggregated** (session/model/agent), not per span. To budget per session, **you instrument cost/token per span**. That is what separates *"I turned on tracing"* from *"I know how much each agent decision cost"* — and it is the raw material of the budget and of FinOps.
- **Provisioned Throughput** (reserved capacity in **GSU**, predictable latency) vs **PayGo / Dynamic Shared Quota** (on-demand, subject to 429).
- **Context caching** — a discount on the reused prefix (system prompt, schemas, RAG). *(Cuts input cost; the output blow-up of the retry storm is contained by the per-session budget.)*
- **Model routing** (Flash for easy / Pro for hard) — **your code, there is no managed router**.
- **Batch inference** — async/cheap for bulk; **Pub/Sub / Cloud Tasks** for slow tools (**your architecture**, not a platform primitive).
- **SLO + error budget** in **Cloud Monitoring** (consumes the signal/SLI born in the substrate and in Case 1).
- **FinOps across the org — cost per user / project / org:** Billing → BigQuery + **labels** + `usageMetadata`. The per-session budget contains the blast radius **locally** (one runaway session); the **label hierarchy** is how you **attribute and govern cost up the tree** — which *user*, *team/project*, or *org* is burning tokens. That's the difference between cost *visibility* and cost *management*: alerts and quotas per project/org, chargeback per tenant, not just a bill after the fact.

**Cumulative diagram — the agent gains "resilience" (on top of the substrate's "eyes"):**
```
   Fleet of sessions ──► [ Agent ] ──► Account tool (DEGRADED: slow)
                            │                 │  ◄── waterfall (substrate) flags the 18s
                            │            ┌─────┴─────┐
                            │            │ CIRCUIT   │  opens after N failures
                            │            │ BREAKER   │  and injects into context:
                            │            └─────┬─────┘  "tool unavailable"
                            ▼                  ▼
                   Fallback ladder:   Pro → Flash → cache → human   (never hallucinates)
   Capacity:  Provisioned Throughput (GSU, predictable) | on-demand/DSQ → 429
   Guard:     per-session token budget (← cost/span) · SLO+error budget · Billing→BigQuery
```

---

## 4. Strategic deep dive (2 depth spikes)

### Spike A — The SEMANTIC circuit breaker + fallback ladder (the heart, and it's your code)
- **The problem it solves:** a normal circuit breaker **just cuts the call**. But the agent is a **reasoning loop** — if you only return an error, the model reinterprets it and **tries again**. The turning point is to **inject the degradation back into the context**, in language the model understands: *"the account tool is unavailable right now; do not try again; follow the fallback."* This turns an **infra error** (which the model treats as its own error) into a **deterministic fact** that guides the next step.
- **The fallback ladder:** what to do when the tool goes down? **Never hallucinate.** Degrade: try a cheaper model, then a cached response, then hand off to a human. Each rung is **your decision**.
- **Why it's the hero:** the platform gives you quota, caching, billing — but **does not decide your fallback ladder or your error budget**. That is the discipline you bring.

### Spike B — Predictable capacity: Provisioned Throughput vs. on-demand
- **The problem it solves:** the **429**. On-demand, Gemini runs under **Dynamic Shared Quota** — **shared** capacity; under contention, you take a 429 and half the sessions fail. **There is no fixed RPM that is "yours."**
- **The solution:** **Provisioned Throughput** = **reserved** capacity, measured in **GSU** (Generative AI Scale Units), predictable latency, isolated from the shared pool. You configure what happens **beyond** the reserved amount (spills over to on-demand **or** gets a 429).
- **The discipline:** combine **PT** (predictable base capacity) + **backoff with jitter** (the doc's *"Retry strategy"*) + **per-session budget**. The platform says **how** to back off; **when to stop retrying** is your decision.

---

## 5. Demonstration (pre-recorded · candidate for controlled "live")

**3 beats — diagnosis → intervention → outcome:**
1. **Diagnosis (waterfall):** I open the pre-populated trace and point at the **18s** tool — *"this is the dependency that degraded."*
2. **Intervention:** I trigger the scenario → the dashboard shows the **tokens/latency spike climbing** → the **circuit breaker cuts in**.
3. **Outcome:** the **fallback responds in ~2s** with **graceful degradation**, instead of an invented balance.

**Principle:** the highest visual energy of the talk — the chart climbing and **being cut off**. Let that moment **breathe**. It is the **only candidate for a controlled "live"** in the talk — and even so, with the **fallback video open in a tab**.

---

## 6. Portable takeaway (Monday-morning)
> Wrap **every tool-call in a circuit breaker** and inject the deterministic fallback **back into the context**. **Never** let the model retry blindly. **Budget tokens/steps per session** — and for that, **instrument cost per span** (the platform does not give it to you for free). **Govern cost up the tree** (labels → BigQuery → per user / project / org), not just per session.

---

## 7. Technologies (the "lego": platform vs. your code)
> **Status & enablement:** almost everything here is **GA** (Provisioned Throughput, Context caching, Batch inference, Agent Runtime knobs, Cloud Monitoring, Billing→BigQuery, Pub/Sub/Cloud Tasks, Cloud Trace). **Memory Bank is Preview** (optional). See §4.6 of the blueprint.

**Platform (plumbing):** Cloud Trace (waterfall — substrate) · Provisioned Throughput (GSU) · Context caching · Batch inference · Sessions + Memory Bank · Agent Runtime knobs (`min_instances`, `container_concurrency`) · Retry strategy (backoff+jitter) · Cloud Monitoring (SLO/error budget) · Billing→BigQuery + `usageMetadata`.
**Your code (the discipline):** **semantic circuit breaker** · **fallback ladder** · **per-session token/step budget** · **cost/token per span** (instrumentation) · **cost attribution/governance across users/projects/orgs** (the label hierarchy) · model routing · async decoupling (Pub/Sub/Cloud Tasks) · "when to stop retrying".

---

## 8. Slide outline (2 — beats)
- **Slide 5 — Problem "The cascade and the bill":** the fleet + degraded dependency + retry storm + 2×→20× + 429 + hallucination as unavailability. Red.
- **Slide 6 — Solution:** waterfall (diagnosis) → semantic circuit breaker + fallback ladder + budget (← cost/span) + PT vs DSQ + caching + **cost governance up the tree (per user/project/org)**. **[DEMO: waterfall → cut-off chart → fallback]** · *hook into Case 3: "resilient ≠ secure — and it touches money and PII."*

---

## 9. Risks · trivial twin · TODO
- **Trivial twin:** "`max_iterations`". Stay at the **systemic** level (fleet / dependency / retry storm / blast radius).
- **Honesty:** **there is no managed router**; Pub/Sub is **your** architecture; **cost is not captured** (token aggregated) → cost/span is yours. Say this explicitly.
- **Don't let the waterfall become a "tracing tour":** it enters as **motivated diagnosis** (find the dependency), not as "look at my pretty trace." 1 beat, fast, and segue into the breaker.
- **Confirm live (numbers for later):** Provisioned Throughput spillover header · context caching discount % · GSU definition.
- **TODO:** state impact in **orders of magnitude** ("tens of seconds → low single digits" for p95; "a token spike, not a 20× blow-up" for cost; "zero invented answers") — **no false-precise %** · the demo's "slow tool" is a `time.sleep(15)` in the build (mock is fine — be honest about it; we demonstrate *parts* of the architecture) · confirm `gen_ai.*`/cost attributes in the span instrumentation.
