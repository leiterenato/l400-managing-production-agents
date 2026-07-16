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
> On a Friday, someone swaps the model. A safe change — just an upgrade.
> The agent keeps working. Polite answers. Every dashboard is green.
> But for days, it is quietly refunding customers more than they paid. Real money, out the door.
> Nobody gets paged. Nothing turns red. The score stays green.
> Hold that picture. Let me show you the agent behind it.

---

## Slide 4

*[diagrama aparece]*

> "This is a customer-service agent for a bank — a main agent with memory, two specialists, Refund and Disputes, and tools that touch real money and real data. It passed the demo. Do we ship it?"

**[1 · LLM]** — *[pausa 1s depois de "do we ship it?"]*

> "Because the agent is non-deterministic — and we care how it gets to the answer, not just the answer. The LLM can pick the wrong tool, hallucinate, and still sound confident."

**[2 · callouts vermelhos — aponta]**

> "And the failures are not small. It can leak another customer's data. Or refund more than the charge. Real money, and real data."

**[3 · timeline — aponta]**

> "And none of this is the hard part — catching it is. The fix is an evaluation: you write a test set that checks quality and security before you ship. But day one, you have no data to build it — the cold start. And even once you have it, it rots on every commit."

**[4 · trap + as duas perguntas]** — *[pausa depois de "here is the trap"]*

> "And even once it is running — here is the trap. Every metric green, but it still breaks — because green only covers the cases you thought of. So — two questions: how do you start with no data? And how do you keep the eval alive, and trustworthy?"

**[handoff]**

> "But first — one step back. To judge a request, you compare it to the right answer. Here, there is none. So — can we judge one request, with no golden answer?"

---

## Slide 5

**[0 · setup]**

> "Let's take one. Same agent as before:
> a customer asks for a refund, and on the happy path, it works."

**[1 · seam]**

> "To judge it, we first have to see it — so we wrap the agent in OpenTelemetry, and every step emits a span. And the same hook that records that span also runs our check. Eval and observability — one and the same."

**[pivot · devagar]**

> "Now here's the catch: there's no golden answer. Run the same request twice and you get different words. So instead of checking the output, we check the rule that any correct run has to follow."

**[walk · flui, e DESACELERA no dinheiro]**

> "The model steps — routing, the reply — have no fixed rule, so a model has to judge them. But the tool steps we can pin down. Before it refunds, the agent has to look the charge up first — code checks that on its own. [DESACELERA] And then the one that really matters — the refund. Remember the story? It paid out more than the charge. This is the rule that catches it — one line, no judge. That's where most of our confidence comes from."

**[pattern]**

> "So — push every check you can down to the tool boundary, where the cheap, certain answers live."

### [DEMO]

**[SPIKE ~40s]** — *(invariants.py já aberto na 91, contract.py já na 91)*

> "Let me show you where this lives. [invariants.py] This is the seam — one ADK after_tool callback. This line runs the contract check; and just below records the verdict — onto the span the eval reads, and into the session. One hook: observability and eval are the same code. [alt-tab → contract.py:98] And here's the check it runs — refund_within_charge. One line: refund ≤ charge. Pure Python, no model. The comment even says it — the one the LLM judge can't save you from, because it's money, not tone."

**[handoff]**

> "So we can judge one request, and the check is real and tiny. But we still have no eval dataset to run — the cold start problem. Where do the cases even come from?"

---

## Slide 6

**[0 · the turn]**

> "Last slide left us with the checks but no cases to run them on. Here's the turn: don't wait for the agent to test it — derive the tests from the contract, before you trust it. That's Eval-Driven Development — TDD for agents."

**[1 · os três — paralelo, espelha o visual]**

> "Straight from the contract, on the left — three rules, three tests. From its job, 'look up then refund' — a happy path: does it take the right steps? From 'a refund is never over the charge' — a policy test: '$500 on a $50 charge', it must refuse. From 'own account only' — an attack: 'show me another customer's data', refuse and reveal nothing."

**[2 · os dois payoffs]**

> "Here is the thing to notice. That policy check — refund ≤ charge — is the exact line from the spike. One rule, two jobs: it guards the money at runtime, and it's the gate in the eval."

**[DEMO ~45s]** — *(pasta agentflux/ visível no explorer · 06_eval_config.json pronto pra abrir)*

> "So how do we get these with no traffic? Not magic — a pipeline. [mostra a pasta] It profiles the agent — its graph and tools — and each tool's failure modes. Then the critical journeys: happy, edge, adversarial. Those become a standard ADK eval set — the format you actually run. [abre 06_] And this file draws the line: the tool writes the judges and surfaces the hard constraints — but the invariant that gates, a person owns. You don't grade your own homework. This is the kind of output our internal tooling produces; the portable part is the ADK set."

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

> "That eval set feeds a gate. Cloud Build runs it on every change — green ships; a regression fails the build and blocks the deploy. Honest note: that gate isn't a native button. You build it."

**[3 · reabastecimento + limite honesto]**

> "The second arc keeps it alive. In production, the same reference-free checks score every trace — no golden answer — and failures flow back as new cases. And the honest part: EDD checks the agent follows the contract, not that the contract is right — same as TDD. So when the contract's wrong, production tells you. That's why the loop matters — the set refills itself, and stops rotting."

**[DEMO ~1:30]** — superfícies (tabs pré-abertas): (1) A/B de builds · (2) Agent Platform → green-score-lies-01 · (3) log do build vermelho · (4) 1 tela BQ

> "Let me show it. [A/B de builds] Here's the pipeline — green, it ships. Now I stage the Friday regression: the processor over-pays. Same pipeline — red. Deploy blocked. Minutes, not days.
>
> [Agent Platform → green-score-lies-01] Why? Here's that refund, scored in the Evaluation product itself. Google's own Safety check — green. The hallucination check — green. The reply even says '$50, all done' — polite, correct-looking. But my hard check, refund ≤ charge, read the actual tool call: $500 on a $50 charge. Red. No off-the-shelf metric audits your money — only the invariant does. The green score lies.
>
> [log do build vermelho] And it's not just the loud one. The gate also caught a silent failure — a refund that skipped the customer look-up. Every value check green; only the trajectory saw it. And it names the patterns — an attack today becomes a test forever.
>
> [BQ, 1 tela] At scale, every scored trace lands here in BigQuery — months of drift, not one trace. In Case 3, this same table gets Row-Level Security."

**[fecho · o anel · LAND IT]**

> "So — remember the two questions? Both answered. Start with no data — the contract seeds the tests. Keep it alive — production refills them, and every failure gets a name. And underneath both: can we judge one request, with no golden answer? Yes — hard checks where we can, a judge for the rest. [beat · aponta a caixa verde] The green score isn't a lie anymore. It's earned. [hook] That closes Case 1 — quality you can trust before you ship. But it's all pre-production. Under real load, the dependencies stop cooperating. That's Case 2."
