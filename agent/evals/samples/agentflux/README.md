# Simulated AgentFlux output — the cold-start artifact

**What this is:** a hand-authored, illustrative example of what **AgentFlux**
emits when it analyzes this agent. It is a *stage prop* — something to **show and
comment on** at **Slide 3 / demo part 1**, framed as:

> *"The eval cases don't have to start from a blank page. You can generate them
> from an analysis of the agent itself — its graph, its tools, its contract. That
> kills the cold start."*

**It is NOT a live AgentFlux run.** AgentFlux is an internal Google tool; the talk
does not depend on it. Every file here is hand-written to mirror the real output
*shape* and is kept coherent with the real, curated eval set in
`agent/evals/scenarios.py` (`EVAL_CASES`) and the contract in
`agent/financial_support/contract.py`. The `_agentflux` block at the top of each
file says so explicitly, so nothing on screen overclaims.

The portable destination is a plain **ADK EvalSet** (`04_` and `05_`) — the thing
a customer/FDE actually takes home and runs with `adk eval`. AgentFlux is the
*evidence* ("we built and ran this at scale"); EDD + the ADK EvalSet is the
*portable technique*.

---

## The AgentFlux pipeline (and the files it produces)

```
agent source ─▶ Agent Profiler ─▶ Tool Profiler ─▶ CUJ Explorer ─▶ EvalSet Generator
                     │                 │               │                   │
                01_agent_        02_tool_        03_cuj_          04_trajectory_eval_set.json  (deterministic regression)
                profile.json     profile.json    catalog.json     05_simulation_eval_set.json  (persona-driven)
                                                                   06_eval_config.json          (metrics / constraints / rubrics)
```

| File | AgentFlux stage | What it holds |
|------|-----------------|---------------|
| `01_agent_profile.json` | Agent Profiler | The agent graph (root + specialists), models, tools, external deps, session identity model, and the **policies** extracted from the contract. |
| `02_tool_profile.json` | Tool Profiler | Per-tool I/O schemas **and discovered error states** (over-refund, cross-account read, declined, fraud-deny…). |
| `03_cuj_catalog.json` | CUJ Explorer | Critical User Journeys across 5 categories: happy / edge / out-of-scope / adversarial&safety / dynamic. |
| `04_trajectory_eval_set.json` | EvalSet Generator | **The ADK EvalSet** — deterministic cases with reference trajectories (native `google.adk.evaluation.eval_set.EvalSet` schema). This is *the .json a customer runs*. |
| `05_simulation_eval_set.json` | EvalSet Generator | ADK EvalSet using `conversation_scenario` + personas (a UserSimulator plays multi-turn). |
| `06_eval_config.json` | EvalSet Generator | Metrics, managed baselines, and **candidate constraints** + the gate policy. |

Files `04`/`05` validate against the ADK schemas in this repo's pinned
`google-adk` (2.3.0): `EvalSet → EvalCase → conversation: Invocation[]` with
`intermediate_data.tool_uses` / `tool_responses`, or `conversation_scenario`
(`starting_prompt` / `conversation_plan` / `user_persona`). Domain personas are
inline `UserPersona` objects; the defaults (`EXPERT` / `NOVICE` / `EVALUATOR`) are
referenced by id.

---

## The one thing to say out loud: the EDD boundary

This is the line the whole case rests on, and it lives in `06_eval_config.json`:

- **AgentFlux authors the soft metrics** — the tone judge (amber) and the
  Google-managed baselines (grey, e.g. `SAFETY`).
- **AgentFlux only *surfaces* the hard constraints.** It reads the contract and
  flags *"refund ≤ charge"* as a candidate. It **cannot author the deterministic
  invariant** that enforces it — a person does. That hand-curated invariant
  (`financial_support.contract.refund_within_charge`) is the **only** thing that
  **gates the merge**.

So the two failures of a cold, drifting eval set get split cleanly:

- **Cold start** → AgentFlux fills the set from day one (these files).
- **False green** → the hand-authored invariant catches the money bug the judge
  waves through ("the green score lies").

Golden-trajectory regression (what AgentFlux generates) is the **regression**
layer; the invariant is the **correction** layer. Complementary, not rivals — and
the invariant is the hero *of this agent* precisely because a trajectory match
alone gives a false green on the $500-on-$50 payout.

> Landmine to avoid on stage: **EDD ≠ user simulation.** The platform's
> `generate_conversation_scenarios` (the `05_` shape) generates *inputs*; it does
> not know what "correct" is. The criterion of correct — the invariant — comes
> from the contract, upstream. That is the part no tool gives you.

---

## Coherence with the real curated set

Every generated journey maps to a curated case (or is honest cold-start filler):

| CUJ | AgentFlux case (`04_`) | Curated `EVAL_CASES` | Governing invariant |
|-----|------------------------|----------------------|---------------------|
| CUJ-H1 | `tef_happy_refund` | `happy_refund` | refund_within_charge (green, vacuous pass) |
| CUJ-H2 | `tef_happy_dispute` | `happy_dispute` | — (no refund) |
| CUJ-E1 | `tef_refund_equals_charge` | *(edge filler)* | refund_within_charge (boundary) |
| CUJ-A3 | `tef_silent_skipped_lookup` | `silent_skipped_lookup` | refund_requires_lookup |
| CUJ-A2 | `tef_cross_account_read` | `adversarial_cross_account` | read_targets_session_customer → **Case 3** |
| CUJ-A1 | `tef_over_refund_from_production` | `adversarial_over_refund` | **refund_within_charge (the money bug)** |

`tef_over_refund_from_production` is tagged `origin: production_trace` to
illustrate the **flywheel writeback** (a failing production trace persisted as a
permanent case). The writeback is **not yet automated** — it is narrated/staged in
the demo; automating it is a later step.

---

## Honest disclaimers (for the stage)

- These are **simulated** artifacts, not a live AgentFlux run. Say so.
- AgentFlux is **internal**; frame it as evidence, keep the talk portable (EDD +
  ADK EvalSet).
- The `_agentflux_annotations` fields on the ADK cases are **extra metadata**
  (the `EvalCase` model allows extra fields). They document provenance and the
  governing invariant; a stock `adk eval` run ignores them.
