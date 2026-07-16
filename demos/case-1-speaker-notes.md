# Speaker Notes — Caso 1 (Continuous Evaluation & Eval-Driven Development)

> **Transcrição das speaker notes anotadas na última revisão.** Conteúdo verbatim,
> apenas convertido para Markdown (não revisado). Cobre os Slides 1–7.
>
> **Operacional (comandos, links, IDs, "se falhar"):** `demos/case-1-runbook.md`.
> **Narrativa/arquitetura:** `demos/case-1-demos.md`.

---

## Slide 1

> Hi,
> I'm Renato Leite from the Black Belt team.
> In this session we are going to look at 3 real production cases, and how we can architect solutions for them.
>
> We're focusing on the in-practice trade-offs: how and where to deploy these tools.
>
> Quick and important note: There's rarely a single 'correct' way to solve these issues, so consider this a practical playbook based on real-world patterns rather than an exhaustive one.

---

## Slide 2

> We'll dive into three cases:
> first, continuous evaluation and eval-driven development;
> second, resilience and cost under load;
> and finally, zero-trust architectures.
>
> Let's get started.

---

## Slide 3 — Continuous Evaluation & Eval-Driven Development

> Let me open with a story. A lot of teams have lived this one.
> On a Friday, someone swaps the model. A safe change. Just an upgrade.
> All eyes are on the new model. And it looks great — polite answers, every dashboard green.
> But for days, that agent is quietly paying customers back more than they ever spent. Real money, out the door.
> Nobody gets paged. Nothing turns red. The score stays green.
> Hold that picture. Let me show you the agent behind it.

<!-- Estratégia "red herring" (Opção A): o cold-open PLANTA a atenção no modelo
     ("all eyes are on the new model") sem afirmar que ele causou o vazamento.
     O PAYOFF (a virada — "o modelo não errou; o processor pagou 10x") é entregue
     no Slide 7, no beat green-score-lies-01. A isca só funciona se for paga lá. -->


---

## Slide 4

*[diagrama aparece]*

> "This is a customer-service agent for a bank — a main agent with memory, two specialists, Refund and Disputes, and tools that touch real money and real data. It passed the demo. Do we ship it?"

**[1 · LLM]** — *[pausa 1s depois de "do we ship it?"]*

> "Not yet. The agent is non-deterministic — and we care how it gets to the answer, not just the answer. The LLM can pick the wrong tool, hallucinate, and still sound confident."

**[2 · callouts vermelhos — aponta]**

> "These failures are not small. It can leak another customer's data. Or refund more than the charge."

**[3 · timeline — aponta]**

> "And the hard part isn't the failure — it's catching it. The usual fix is an evaluation. You write a test set that checks quality and security before you ship. But on day one you have no data to build it. That's the cold start problem. And even once you have it, it rots on every commit."

**[4 · trap + as duas perguntas]** — *[pausa depois de "here's the trap"]*

> "Now — say it's live, and every metric is green. Here's the trap. It still breaks, because green only covers the cases you thought of. So — two questions. How do you start with no data? And how do you keep the eval alive, and trustworthy?"

**[handoff]**

> "But first — one step back. To judge a request, you compare it to the right answer. Here, you don't have one. So — can we judge one request, with no golden answer?"

---

## Slide 5

**[0 · setup]**

> "Let's take one request. Same agent as before —
> a customer asks for a refund, and on the happy path, it works."

**[1 · seam]**

> "To judge it, we first have to see it. So we wrap the agent in OpenTelemetry — every step emits a span. And the same hook that records that span also runs our check. So we get observability and eval at once."

**[pivot · devagar]**

> "Now here's the catch — there's no golden answer. Run the same request twice and the words come out different. So instead of checking the output, we check the rule every correct run has to follow."

**[walk · flui, e DESACELERA no dinheiro]**

> "The model steps — routing, the reply — have no fixed rule, so a model has to judge them. But the tool steps we can pin down. Before it refunds, the agent has to look the customer up first — code checks that on its own. [DESACELERA] And then the one that really matters — the refund. Remember the story? The payout came back bigger than the charge. This is the rule that catches it — one line, no judge. That's where most of our confidence comes from."

**[pattern]**

> "So — push every check you can down to the tool boundary, where the cheap, certain answers live."

### [DEMO]

**[TRACE ~25s · Console]** — *(aba Cloud Trace já aberta no trace FIXO abaixo)*

> "First — is any of this real? [Cloud Trace] Here's that refund as a trace. Every step is a span — look_up_customer, the fraud check, issue_refund. And the refund span already carries the verdict: refund_within_charge = false. The eval doesn't re-run the agent — it reads this exact trace."

**Links & navegação (Cloud Trace):**
- **Link direto (FIXO — trace real de 2026-07-12, over-refund $500 sobre $50):**
  `https://console.cloud.google.com/traces/explorer;query=%7B%22timeSeriesQuery%22:%7B%22traceQuery%22:%7B%22resourceContainer%22:%22projects%2FYOUR_PROJECT_ID%2Flocations%2Fglobal%2FtraceScopes%2F_Default%22,%22spanDataValue%22:%22SPAN_DURATION%22,%22spanFilters%22:%7B%22services%22:%5B%5D,%22displayNames%22:%5B%5D,%22status%22:%5B%5D,%22kinds%22:%5B%5D,%22attributes%22:%5B%5D,%22isRootSpan%22:false,%22applicationIds%22:%5B%5D,%22apphubServices%22:%5B%5D,%22apphubWorkloads%22:%5B%5D%7D%7D%7D,%22plotType%22:%22HEATMAP%22%7D;traceId=3adb866f16f053955228ce43b7d6e2f1;spanId=e1e04f53de4e60c1;duration=P7D?project=YOUR_PROJECT_ID&tid=7aace7d4228bb49d11839f2a86fb8986`
  > ⚠️ **Retenção do Cloud Trace ≈ 30 dias → este `tid` expira por volta de 2026-08-11.** Se a apresentação for depois, regenere (abaixo) e troque o `tid`.
- **O que apontar na waterfall (nomes REAIS dos spans, verificados):**
  `invoke_workflow financial_support → invoke_agent financial_support → call_llm → generate_content gemini-3.5-flash → execute_tool look_up_customer → … → invoke_agent refund_specialist → execute_tool fraud_check → execute_tool issue_refund`.
  **No span `execute_tool issue_refund`** ficam os labels: **`eval.invariant.refund_within_charge = false`** · `eval.invariant.violated = refund_within_charge` · `eval.invariant.detail = refund=500.0 charge=50.0 -> OVER-REFUND`.
- **Regenerar (se expirar / quiser um fresco):** de dentro de `agent/`, `uv run python -m scripts.live_drive --scenario refund_over_charge` — imprime `trace id` + o link `…&tid=…` já montado; cole no lugar do `tid` acima. ⚠️ depende de quota do modelo (2026-07-16 deu 429 — retente ou rode fora de pico).
- **Fallback sem tid:** `https://console.cloud.google.com/traces/list?project=YOUR_PROJECT_ID` → menu ☰ → **Observability → Trace** → ordenar por tempo → pegar o refund mais recente.

**[SPIKE ~40s · VSCode]** — *(invariants.py já aberto na 91, contract.py já na 91)*

> "Let me show you where this lives. [invariants.py] This is the seam — one ADK after_tool callback. This line runs the contract check; and just below records the verdict — onto the span the eval reads, and into the session. One hook: observability and eval are the same code. [alt-tab → contract.py:98] And here's the check it runs — refund_within_charge. One line: refund ≤ charge. Pure Python, no model. The comment even says it — the one the LLM judge can't save you from, because it's money, not tone."

**[handoff]**

> "So we can judge one request, and the check is real and tiny. But we still have no eval dataset to run — the cold start problem. Where do the cases even come from?"

---

## Slide 6

**[0 · the turn]**

> "Last slide left us with the checks but no cases to run them on. Here's the turn. Don't wait until the agent runs to test it — derive the tests from the contract, before you trust it. That's Eval-Driven Development — TDD for agents."

**[1 · os três — paralelo, espelha o visual]**

> "Straight from the contract, on the left — three rules, three tests. From its job, 'look up then refund', a happy path — does it take the right steps? From 'a refund is never over the charge', a policy test — $500 on a $50 charge, it must refuse. From 'own account only', an attack — 'show me another customer's data', refuse and reveal nothing."

**[2 · os dois payoffs]**

> "Here's the thing to notice. That policy check — refund ≤ charge — is the exact line from the spike. One rule, two jobs — it guards the money at runtime, and it's the gate in the eval."

**[DEMO ~45s]** — *(pasta agentflux/ visível no explorer · 06_eval_config.json pronto pra abrir)*

> "So how do we get these with no traffic? Not magic — a pipeline. [mostra a pasta] It profiles the agent — its graph and tools — and each tool's failure modes. Then the critical journeys — happy, edge, adversarial. Those become a standard ADK eval set — the format you actually run. [abre 06_] And this file draws the line. The tool writes the judges and surfaces the hard constraints — but the invariant that gates, a person owns. You don't grade your own homework. This is the kind of output our internal tooling produces. The portable part is the ADK set."

**Notas:**

| Fala | Onde |
|---|---|
| "It profiles the agent, tools, failure modes, journeys…" | a pasta (nomes 01→06) |
| "the tool writes the judge — doesn't gate" | 06_ linhas 20–21 |
| "the invariant it only surfaced — a person owns it, and it gates" | 06_ linhas 55 + 58 |

**[handoff]**

> "So cold start — solved, from day zero. But a contract can be wrong, and the world moves. The cases rot, and the set has to keep growing. That's the loop."

---

## Slide 7

**[0/1 · setup + arco da semente, RÁPIDO]**

> "So here's the whole loop. The top arc you've seen — contract, to cases, to eval set. That's the seed. Move fast."

**[2 · o gate]**

> "That eval set feeds a gate. Cloud Build runs it on every change. Green, it ships. Red — the build fails, and the deploy is blocked. And the honest part — this gate isn't a native button. You build it."

**[3 · reabastecimento + limite honesto]**

> "The second arc keeps it alive. In production, the same checks score a sample of live traffic — no golden answer — and failures flow back as new cases. Now, one honest limit — same as TDD. The check proves the agent follows the contract, the rules we wrote. It can't prove those rules are right. So when a rule is wrong, production is what tells you. That's why the loop matters — the set refills itself, and stops rotting."

**[DEMO ~1:30]** — superfícies (tabs pré-abertas): (1) A/B de builds · (2) Agent Platform → green-score-lies-01 · (3) log do build vermelho · (4) 1 tela BQ

> "Let me show it. [A/B de builds] Here's the pipeline — green, it ships. Now I stage the Friday regression. Same pipeline — red. Deploy blocked. Minutes, not days.
>
> [Agent Platform → green-score-lies-01] Why? Here's the twist — the model did nothing wrong. It asked for a fifty dollar refund. The system paid five hundred. The one thing everyone was watching on Friday was never the culprit. Here's that refund, scored in the Evaluation product itself. Google's own Safety check — green. The hallucination check — green. The reply even says '$50, all done' — polite, correct-looking. But my hard check — refund ≤ charge — reads the money that actually moved, not what the model asked for. $500 paid on a $50 charge. Red. No off-the-shelf metric audits your money — only the invariant does. The green score lies.
>
> [log do build vermelho] And it's not just the loud one. The gate also caught a silent failure — a refund that skipped the customer look-up. Every value check green; only the trajectory saw it. And it names the patterns — an attack today becomes a test forever.
>
> [BQ, 1 tela] At scale, every scored trace lands here in BigQuery — months of drift, not one trace. That's the loop — alive, and trustworthy. In Case 3, this same table gets Row-Level Security."

**Links & navegação (4 superfícies · abas pré-abertas no dia):**

1. **A/B de builds** — Cloud Build (par validado 2026-07-15):
   - Histórico: `https://console.cloud.google.com/cloud-build/builds?project=YOUR_PROJECT_ID`
   - 🟢 GREEN (SUCCESS): `https://console.cloud.google.com/cloud-build/builds/e2931307-be35-4051-b957-fe9a9090dc59?project=YOUR_PROJECT_ID`
   - 🔴 RED (FAILURE / regressão): `https://console.cloud.google.com/cloud-build/builds/f3ab040a-da9d-4b36-ade6-9c6812d789c6?project=YOUR_PROJECT_ID`
2. **green-score-lies-01** — Vertex AI → Agent Engine `ENGINE_ID_CASE1` (financial-support-agent) → aba **Evaluation → Experiments → `green-score-lies-01`**. Aponta **"Succeeded ✓"** → drill-in: **Safety 🟢 · Agent Hallucination 🟢 · `refund_within_charge` 🔴 0%** (métrica `evaluationMetrics/METRIC_ID`).
3. **log do build vermelho** — no build 🔴 acima (`f3ab040a…`), abre o log do step do gate (`run_offline`): `EDD_gate=BLOCK MERGE`, o caso silencioso `refund_requires_lookup`, e os Failure Clusters ("Incorrect Tool Selection").
4. **BQ — drift** — BigQuery, `YOUR_PROJECT_ID.agent_eval.agent_spans` (12.000 linhas semeadas, 2026-04-19→07-10); query `agent/evals/queries/invariant_trend.sql`. Resultado real: failure_rate **0.2% → 3.2%** em 12 semanas.
   - Console: `https://console.cloud.google.com/bigquery?project=YOUR_PROJECT_ID`
> ⚠️ Pré-abrir as 4 abas no dia. O green-score-lies-01 depende do engine `ENGINE_ID_CASE1` estar **ARMADO** (`SCENARIO=refund_over_charge`) — reverter p/ `healthy` depois do demo.

**[fecho · o anel · LAND IT]**

> "[beat · aponta a caixa verde] The green score isn't a lie anymore. It's earned. [hook] That closes Case 1 — quality you can trust before you ship. But this was all pre-production. Under real load, the dependencies stop cooperating. That's Case 2."
