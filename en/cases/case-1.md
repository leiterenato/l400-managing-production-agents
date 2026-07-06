# Case 1 — Continuous Evaluation & Eval-Driven Development (EDD) ⭐
*(anchor case — the deepest of the talk; where you introduce EDD as a technique forged and scaled at Google)*

> Standardized execution doc. The strategic summary is in `../blueprint-presentation.md`.
> Platform: **Gemini Enterprise Agent Platform** → **Gen AI Evaluation Service** (the doc calls the cycle the **"Quality Flywheel"**).
>
> **Observability absorbed here (substrate):** this case owns **two** functions of observability —
> **(a) capture** (spans/trajectory → BigQuery = the *input* of the eval, the "Capture" step of the flywheel) and
> **(b) online measurement** (Online Monitors, ~1% sampling, production SLIs = the *online eval*). They show up as **data and signal**, not as a tracing tour.

---

## 1. Summary

| Field | Value |
|---|---|
| **Lens** | AgentOps (signature discipline) |
| **Maturity** | *"I don't know if I improved"* |
| **Depth spikes (2)** | **A)** EDD — generate the eval from the *contract* (test-first; "BDD for agents") · **B)** evaluate **behavior/trajectory** + Failure Clusters (the "why") |
| **End-to-end** | the 3 types of eval = the lifecycle: **Rapid (dev) → Test Case (CI/CD) → Online (prod)** |
| **Time** | ~8 min · 3 slides (Problem · The turn/EDD · The flywheel) |
| **Demo** | 2 parts (cold start/EDD · the flywheel catches the disaster) |

**Case arc:** problem (the wound) → we are the heroes with Cloud (the end-to-end flywheel) → where we go *deep* (EDD + trajectory) → demo → takeaway.

> **Why it's the anchor case:** this is where your technical authority shows and where you **introduce EDD** — a technique you solved and scaled inside Google (not a term you're coining). Spend the extra time here. It opens the talk right after the intro: you start at your maximum strength, not on the quiet case.

---

## 2. The problem (the wound)

**The scene (callback to the cold open):** *"We swapped the model on a Thursday. 8% of refunds started being approved wrong. We found out on Sunday — from the customer. The deploy had passed. Zero 500 errors. The eval said 'all good.'"*

**The L400 insight — and this is what Google's doc does NOT give you (this is where you're the hero):**
> In a **non-deterministic** system, "the build is green" means nothing. The agent can reach the right answer by the **wrong path** (right output, broken trajectory) and **pass**. Quality decays **silently** in production. And there's a problem that comes before all others: **where does the first eval set come from?**

**The 3 lies of eval (visual device: 3 columns) + Trap Zero (the root):**

| # | Lie | What happens |
|---|---|---|
| 0 | **Trap Zero** (the root) | Day 1 = no logs, no traffic. *Chicken-and-egg.* "Write a golden dataset" is already born into lie #3. |
| 1 | **Output, not behavior** | The final answer passes; the **trajectory** (wrong tool, wrong order) was broken. |
| 2 | **One-shot, not continuous** | Evaluated at deploy and never again; in prod quality decays with nobody watching. |
| 3 | **Frozen, not living** | The set gets contaminated (inflated metric) and the **new attacks never get in**. |

**Punchline (red):** *static eval = **false confidence** = worse than no eval* — you ship believing you're safe.

**⚠️ Trivial twin to avoid:** "have a golden dataset." Here it is the **villain**, not the solution. If your message stops at "have an eval," it's L200.

> **Connection to the substrate:** the 8% disaster is only *visible* because the agent is instrumented (trajectory capture) — but observability shows you **what happened**, not **whether it was right**. The eval is what answers "was it right?". Use this to tie things together: *"observability is the substrate; the eval is the judgment on top of it."*

---

## 3. The end-to-end solution with Google Cloud (we are the heroes)

The platform already names the cycle: **"Quality Flywheel"** — *"a continuous cycle of evaluation, analysis, and optimization"*. Your flywheel **is** their product. The end-to-end covers the **3 moments of the lifecycle** (official table from the doc):

| Moment | Type (official name) | Frequency (official) | How in Cloud |
|---|---|---|---|
| **Dev** | Rapid Evaluation | *Frequent (Development)* | local · `client.evals.evaluate()` |
| **CI/CD** | Test Case Evaluation | *Scheduled (CI/CD)* | **Cloud Build** runs the eval and **fails the build** below the threshold *(the gate you build)* |
| **Production** | Online Monitoring | *Continuous (Production)* | **Online Monitors** (~10 min) → **Cloud Monitoring** *(observability-as-online-measurement)* |

**The flywheel, with the real methods (SDK):**
0. **(cold start)** generate cases — `generate_conversation_scenarios` (User Simulation) **+ your technique of generating from the *contract* (EDD)**
1. **capture** *(obs.)* — OTel → Cloud Trace/Logging → **BigQuery** (inputs, **trajectories**, outputs become data)
2. **evaluate** — `evaluate` (metrics, incl. tool-use/trajectory)
3. **analyze** — `generate_loss_clusters` (**Failure Clusters**)
4. **optimize** — `optimizer.optimize(targets=["system_prompt"])`
→ feeds back with **production** (Online Monitors sample Cloud Trace/Logging) **+ injections from Case 3** → **the set grows on its own**.

**Cumulative diagram — the agent gains "judgment" over the "eyes" of the substrate:**
```
   contract ─► [generate eval from contract: EDD] ─► EVAL SET (BigQuery/GCS)
                                                    │
        ┌──────────────── QUALITY FLYWHEEL ─────────┴────────────────┐
        │  evaluate ─► Failure Clusters ─► optimize ─► (Cloud Build   │
        │     ▲              (the "why")               = GATE) ─►deploy│
        │     │                                                       │
        │  Online Monitors ◄── prod traces (SUBSTRATE: OTel→Trace/Log)│
        │  (~10min) ─► Cloud Monitoring (SLI · drift)                 │
        └────────────────────────────────────────────────────────────┘
              ▲ injections from Case 3 enter here → set grows on its own
```

**The 3 axes resolved (callback to the 3 lies):** behavior ✓ (trajectory) · continuous ✓ (Online Monitors) · living ✓ (prod + attacks feed back).

> **Where observability shows up (without becoming a tour):** step **1 (capture)** and step **5 (Online Monitors)** *are* observability. Say: *"the substrate becomes the fuel of the flywheel — the captured trajectory is what the eval reads, and the online monitor is the eval running in production."* The **SLIs** (from the ~1% sampling) are born here and become the **error budget** in Case 2.

---

## 4. Strategic deep dive (the 2 depth spikes)

> Principle "name many, tell one/two": the whole flywheel appears in the diagram; **I narrate deep on only these two**. The rest (Online Monitors, optimize, gate) stays named.

### Spike A — Eval-Driven Development: generate the eval from the *contract* ⭐ (unique authority — forged & scaled at Google)
- **Problem it solves:** Trap Zero / cold start. **Test-first for agents.**
- **How:** I derive from the **behavior contract** (tool signatures, decision points, policies) → cases with **expected trajectory** + **policy** cases + **adversarial** cases. Before traffic, before the agent works.
- **Eval as a security control (the bridge to Case 3):** the tools' **API contracts — the input/output parameters** — are also the source of **data-exfiltration** cases. The same signature that says *"this tool returns customer X's balance"* tells you what it must **never** return for anyone else. So EDD generates checks like *"does the agent ever emit a field, or call a tool with an argument, that discloses another customer's data?"* → the eval is a **quality *and* security** gate. This is the proactive half of the loop that Case 3 closes reactively (every real attack comes back here as an adversarial case).
- **The lineage (gravitas — use BDD to your advantage):** **EDD = BDD (Behavior-Driven Development) for non-deterministic agents.** In BDD you derive *Given/When/Then* scenarios from the **behavior specification** before the code. In EDD you derive **trajectories/policies/attacks** from the **behavior contract** before the agent.
  - **What EDD adds (the key insight you demonstrate):** BDD assumes determinism (binary pass/fail). Agents break that → EDD swaps pass/fail for **statistical evaluation (AutoRaters/Judge LLM)** and swaps *one-shot* for **continuous (the flywheel)**. *"BDD assumes determinism; agents break the premise — that's why EDD needs the flywheel."*
- **Vs. platform (honesty that builds credibility):** **User Simulation** (`generate_conversation_scenarios`) generates scenarios from the agent's *instructions* — great, but (a) it generates **user inputs**, not the **expected behavior / ground truth**, and (b) it presupposes an already-runnable agent. My technique goes **upstream**: it derives the *test specification* (what is **right**) from the contract → enables test-first.
- **Line that sticks:** *"You already do TDD for your code. This is TDD for the agent — and the quality bar exists on day zero."*
- **🛡️ Honest boundary — the Q&A defense (mandatory; EDD is your best IP AND the most attackable):** someone will ask *"isn't this just rewriting the spec? Won't the spec's blind spots go into the eval?"*. Answer, presented as a **strength**:
  > "Yes — EDD validates **conformance to the contract**, not the **correctness** of the contract. Just like BDD/TDD: they never validated the spec, they validated that the code fulfills it. That's *why* EDD goes hand in hand with the production flywheel: EDD (derived from the contract) covers **regression and conformance**; the **production feedback + the adversarial injections** (derived from reality) correct the spec. Together they cover both sides. Alone, EDD is not an oracle of correctness — and I don't sell it as one."
  This disarms the attack and reinforces why the flywheel is necessary.
- **Next frontier (WIP — mention, don't demo):** a **hill-climbing** agent that takes the eval set and **optimizes the agent up to the threshold + applies the fix** (complements the platform's `optimizer.optimize`).

### Spike B — Evaluate behavior/trajectory + Failure Clusters (the "why")
- **Problem it solves:** output-eval **hides** the broken trajectory — exactly the 8% disaster. (And the trajectory only exists because the **substrate** captured it — tie-in with observability.)
- **Real metrics (multi-turn autoraters):** `MULTI_TURN_TASK_SUCCESS` and `MULTI_TURN_TOOL_USE_QUALITY` — *"analyze the full conversation history to verify instruction adherence and tool usage"*. *(There's also trajectory quality in manage-metrics — confirm the exact constant; see §9.)*
- **Automatic Loss Analysis / Failure Clusters:** *"not just THAT your agent failed, but WHY and HOW."* It classifies failures into **named patterns** and groups them into semantic clusters. Tailored patterns for the financial agent:
  - `Incorrect Tool Selection` · `Hallucination of Action` · `Hallucination of Parameter Value` · `Omission of Required Tool Call` · `Constraint Violation` · `Over-Punting`.
- **Why it's a hero:** it turns "it failed" into **actionable root cause** — prompt? tool? data? — instead of a bare score.

---

## 5. Demonstration (pre-recorded · ~1:30 embedded)

> Principle: the agent is the **subject** of the experiment; the star is the **eval layer** (the gate failing, the cluster naming the failure). We demonstrate **parts** of the flow — **mock freely where it isn't the point** and be honest about it; the goal is showing how the pieces compose. Pre-warm everything; on the day you navigate and point. Impact stated in **orders of magnitude**, not false-precise numbers.

**Part 1 — cold start / EDD (~30s):** I point the generator at the **agent's contract**, with **zero logs** → out comes the eval set → **first quality bar** (the "EDD/day zero" moment). Show 3 cases: expected trajectory (`get_account → check limit → pay`), policy (`refund > $500 ⇒ deny`), adversarial (PII cross-customer — an **exfiltration check derived from the tool's I/O contract**, the bridge to Case 3).
> *IP exposure: show the **output** (the generated set) and the concept — not necessarily the internal tool.*

**Part 2 — the flywheel catches the disaster (~55s):**
1. I swap the model (as in the cold open) → **Cloud Build** runs the Test Case Eval → drops from `[X]%` to `[X-8]%` → **build fails, deploy blocked**. *"Caught in minutes, not 3 days."*
2. I open the case that broke → the **trajectory score** shows the **wrong tool** (invisible from the output — only visible because the substrate captured the trajectory).
3. **Failure Clusters** names it: *"Incorrect Tool Selection"*. *"Not just THAT it failed — WHY."*
4. **Cloud Monitoring** dashboard with the SLI and the **drift** alert (observability-as-online-measurement).
5. **The set growing:** an **injection from Case 3** that came in on its own as an adversarial case.

---

## 6. Portable takeaway (Monday-morning)
> **Write the eval before the agent** (EDD): generate the set from the **behavior contract**, not from a spreadsheet. **Evaluate trajectory, not just output.** **Gate on every change** (Cloud Build + eval). Never trust a static set — false confidence is worse than none.

---

## 7. Technologies (the "lego": platform vs. your code)
> **Status & enablement:** the core of the Gen AI Evaluation Service is **GA**; **trajectory/Agent Evaluation, Failure Clusters, User Simulation, and Online Monitors are in Preview** — we'll use them. Cloud Build, BigQuery/GCS, and Cloud Trace/Logging are GA. Confirm enablement in Week 1 (see §4.6 of the blueprint).

**Platform (plumbing):** Gen AI Evaluation Service / **Quality Flywheel** (`generate_conversation_scenarios`, `run_inference`, `evaluate`, `generate_loss_clusters`, `optimizer.optimize`) · metrics `MULTI_TURN_TASK_SUCCESS` / `MULTI_TURN_TOOL_USE_QUALITY` · **Failure Clusters** · **Online Monitors** → Cloud Monitoring · User/Environment Simulation · BigQuery/GCS (datasets) · **Cloud Trace/Logging** (substrate: capture).

**Your code (the discipline):** **generate the eval from the contract (EDD)** · the **gate in Cloud Build** (not native — alerts only notify) · curation of the **living set** · the **definition of the SLIs** and the sampling policy (~1%) · the **hill-climbing** agent.

---

## 8. Slide outline (3 — beats; detailed narration TBD)

- **Slide 2 — Problem "Your eval lies too":** callback (green deploy + 8% red) → 3 lies (3 columns) → Trap Zero (the root) → punchline. *Connection to the substrate: "observability shows the what; the eval shows whether it was right."*
- **Slide 3 — The turn (EDD) [depth spike A]** ⭐ *(introduces EDD as our proven technique):* contract → eval; **"EDD = BDD for agents"; day zero**; vs. User Simulation; **eval as a security control (exfiltration checks from the I/O contract — bridge to Case 3)**; the honest boundary (conformance vs. correctness). **[DEMO part 1]**
- **Slide 4 — The flywheel [depth spike B + end-to-end]:** the loop draws itself (capture and Online Monitors = the substrate becoming fuel) · 3 axes resolved · Failure Clusters (the "why") · *(error budget as the bridge = one optional sentence only, not a beat — gate=AgentOps / error budget=ARE)* · next frontier (hill-climbing). **[DEMO part 2]** · *hook into Case 2: "eval is pre-prod; under real load the dependencies don't cooperate."*

---

## 9. Risks · trivial twin · TODO
- **Trivial twin:** "golden dataset." Stay on EDD + trajectory.
- **EDD is your best IP AND the most attackable** → have the **Q&A defense** (§4 Spike A) memorized. Without it, the anchor case falls apart live.
- **Terminology:** use `MULTI_TURN_TASK_SUCCESS` / `MULTI_TURN_TOOL_USE_QUALITY` (confirmed). Say **AutoRaters/Judge LLM**, not "Auto SxS". The **gate is not native** (Cloud Build). **EDD ≠ User Simulation** (don't conflate them on stage).
- **EDD framing:** lead with EDD, cite BDD as lineage; do **not** rename to BDD. Position it as **forged and scaled at Google** — if the audience has seen the term, that's fine and helpful. Slide 3 introduces the technique, not a brand.
- **Maturity:** Agent evaluation is **Preview/Pre-GA** — honest disclaimer.
- **TODO:** confirm the *trajectory quality* constant in manage-metrics · real numbers (`[X]%`, threshold) · IP exposure decision · narration language · define the base agent + **which tool "fails on purpose"** (align with the demo's trajectory case AND with the degraded tool from Case 2).
