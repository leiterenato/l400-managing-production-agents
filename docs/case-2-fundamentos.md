# Caso 2 — Resiliência & Custo sob carga · Fundamentos e Slides

> Doc de referência denso do Caso 2 (PT; diagramas e speaker notes em EN, porque os slides são em inglês).
> Espelha `eval-agentes-fundamentos.md` (Caso 1). Resumo estratégico em `../en/cases/case-2.md` e `../en/blueprint-presentation.md`.
> Agente-base: atendimento financeiro (lê PII + emite reembolso), o **mesmo** agente que amadurece pelos 3 casos.

---

## Índice
1. [A tese L400 — é relevante? (discussão honesta)](#1-a-tese-l400)
2. [A ponte de entrada (Caso 1 → Caso 2)](#2-a-ponte-de-entrada)
3. [A câmera / arco emocional](#3-a-câmera)
4. [O arco em 5 atos](#4-o-arco-em-5-atos)
5. [Slide 5 — "The Cascade" (problema)](#5-slide-5--the-cascade)
6. [Slide 6 — "Contain the blast" (clímax)](#6-slide-6--contain-the-blast)
7. [Slide 7 — "Govern the cost" (clímax econômico)](#7-slide-7--govern-the-cost)
8. [Landmines e decisões travadas](#8-landmines-e-decisões-travadas)

---

## 1. A tese L400

**Veredito honesto (não auto-convencimento).**

- **Relevância pra produção: altíssima.** Custo explodindo e retries em cascata são das primeiras dores que todo time bate ao pôr agente em produção — antes de eval, antes de zero-trust. Nesse eixo, o Caso 2 é provavelmente o **mais imediatamente útil** dos três.
- **Novidade L400: condicional, e é o eixo em risco.** Resiliência é campo maduro. Circuit breaker, fallback, backoff-com-jitter, comprar capacidade reservada — um SWE sênior (Accenture) já conhece há 15 anos. Se qualquer beat soar como o mecanismo genérico, rebaixa pra L200. **A linha é fina.** O que salva é *exclusivamente* o twist de agente.

**O que carrega o peso L400 (o que um sênior NÃO traz de microsserviços):**
1. **O modelo relê o erro e retenta na camada de raciocínio** — invisível pro backoff de infra. Retry duplo.
2. **O breaker semântico (injetar no contexto).** Devolver erro pra um loop de raciocínio não funciona — ele reinterpreta. Falar a língua do modelo é a joia.
3. **Alucinação como falha de disponibilidade.** Componente que, ao quebrar, mente com confiança em vez de dar 500. Reenquadrar "hallucination" como *availability* é virada que só existe com agentes.
4. **Economia: custo não-linear + não-capturado.** 2×→20×, e a plataforma não dá custo por span → você instrumenta.

**Onde o caso é FRACO pra L400 (vigiar):**
- **Provisioned Throughput vs DSQ é o elo mais fraco** — é "compre capacidade reservada", conhecimento de produto/procurement, não disciplina. **NÃO fazer disso depth spike.** Reframe: a disciplina é *decidir o comportamento no limite* (spillover vs 429) + combinar com budget por sessão + backoff. O engenheiro leva a **política**, não o SKU.
- **Fallback ladder por si só é óbvio.** A novidade é *degrade, don't invent* + "cada degrau é sua decisão de error budget".
- **O breaker como mecanismo é commodity** → a **injeção no contexto** é o herói. Regra de ferro: **todo beat abre pelo twist, não pelo mecanismo.**

**Litmus test:** *"Um SWE sênior que já construiu microsserviços aprende algo novo?"* Só com breaker/fallback/PT → não (L200). Com os 4 twists acima em primeiro plano → sim (L400). O caso **passa** se os twists estão na frente e os mecanismos ficam de pano de fundo.

**A espinha que blinda o caso (uma frase):**
> Resiliência clássica pressupõe componentes determinísticos que falham alto. Um agente é um componente **estocástico** que falha em silêncio e **amplifica** — reinterpreta erros, retenta invisível, e alucina em vez de errar. Então o playbook inteiro tem que ser **re-derivado para um componente que raciocina.**

Corolário de forma: **cada padrão clássico quebra de um jeito novo com agentes** (tabela abaixo). É o fio que atravessa cada beat.

| Padrão clássico | Por que quebra com agentes |
|---|---|
| Circuit breaker devolve erro | O LLM relê o erro como "errei o parâmetro" e tenta de novo → injetar no **contexto**, não no retorno |
| Retry com backoff na infra | O **modelo também retenta**, na camada de raciocínio, invisível → retry duplo |
| Autoscaling horizontal | Custo de token é **não-linear** → escalar amplifica a conta, e ainda bate no mesmo 429 |
| Fallback devolve erro/cache | O agente pode **alucinar** em vez de falhar honesto → indisponibilidade silenciosa |

---

## 2. A ponte de entrada

Gancho já plantado no Slide 1 do Caso 1: `issue_refund → Payment system`. Frase de transição (honesta com o Caso 1):

> *"O eval provou que a agente está correta. Mas o eval rodou num ambiente simulado, uma sessão por vez. Ele não disse nada sobre o que acontece quando mil dessas agentes batem na mesma API lenta ao mesmo tempo."*

Respeita o Caso 1 (eval é necessário) e motiva o Caso 2 (eval não é suficiente pro comportamento **sistêmico**). Correção ≠ resiliência.

---

## 3. A câmera

Caso 1 = macro→micro→mezzo→macro. Caso 2 tem câmera própria:

**afasta (a frota) → contágio (o vermelho se espalha) → aproxima (um waterfall) → clique (o breaker corta) → afasta (governança/custo na árvore).**

Largo → pânico → diagnóstico → controle → economia sob controle. O ritmo espelha a emoção.

---

## 4. O arco em 5 atos

- **Ato 1 — O sucesso vira o inimigo.** *(câmera afasta)* A câmera puxa pra trás do diagrama-âncora do Caso 1 e revela: aquilo era uma célula. Agora são muitas — a **frota** — dividindo **uma** dependência. Quebra *porque* deu certo (foi adotada).
- **Ato 2 — A cascata (a ferida).** *(contágio)* A dependência degrada (lenta, não caída). O modelo lê timeout como erro próprio → retenta. ×N = **retry storm** → amplifica. Sintomas: 20× tokens, 429/DSQ, saldo inventado, runtime satura. **Herói conceitual:** sistema distribuído estocástico. Não é `max_iterations`.
- **Ato 3 — O diagnóstico.** *(aproxima em UM waterfall)* O waterfall acha o culpado ("modelo 1s, tool 18s"). Observabilidade **motivada**, setup do breaker.
- **Ato 4 — Conter (clímax + herói).** *(clique)* Breaker semântico injeta a degradação **de volta no contexto**. Fallback ladder → *degrade, don't invent*.
- **Ato 5 — Não só sobreviver, governar.** *(afasta pra árvore de custo)* Cost/span (sua instrumentação) → budget por sessão (local) → PT vs DSQ + FinOps na árvore (global). Visibilidade vira gestão.

**Ponte de saída (→ Caso 3):** *"Agora é resiliente. Mas resiliente ≠ segura — e tudo mexe com dinheiro e PII."*

**Forma:** 3 slides (não 2). Cada movimento respira; o custo ganha o espaço que merece.

---

## 5. Slide 5 — "The Cascade"

**Papel:** a ferida. **Câmera:** afasta (frota) → contágio. **Cor:** vermelho. **Sem demo** (conceito puro). **Título:** "The Cascade" (subtítulo opcional: *"one slow dependency, amplified by the fleet"*).

### Arquitetura — motor de loop vicioso com entrada e explosão

Estrutura causal = **entrada → ciclo vicioso → estilhaço.** (Aprendizado de forma: layout radial/hub embola; o certo é fluxo com o **loop girando** no centro.)

```mermaid
flowchart LR
  FLEET["The fleet<br/>one agent × N sessions"]:::fleet

  subgraph LOOP["The vicious cycle"]
    direction TB
    DEP["Shared dependency<br/><b>DEGRADED · slow · 18s</b>"]:::bad
    MODEL["Model misreads timeout<br/>as its OWN error → retries"]:::bad
    DEP -->|timeout| MODEL
    MODEL -->|amplifies| DEP
  end

  BLAST["<b>BLAST RADIUS</b><br/>• Cost — 2× traffic → 20× tokens<br/>• Quota — 429 (Dynamic Shared Quota)<br/>• Hallucination — invents the balance<br/>• Saturation — runtime not elastic"]:::blast

  FLEET ==>|converge on ONE| DEP
  LOOP ==> BLAST

  classDef fleet fill:#f1f3f4,stroke:#5f6368,color:#111
  classDef bad fill:#fce8e6,stroke:#d93025,stroke-width:2px,color:#111
  classDef blast fill:#fff,stroke:#d93025,color:#111
```

**Notas de build (Slides / Nano Banana):**
- **A frota = UM objeto:** carta da frente = a espinha do Caso 1 (`main → refund specialist → look up → issue refund`); atrás, **cartas desbotadas empilhadas** + badge `× N`. Resolve o "azul flutuante" e entrega "uma célula de uma colônia".
- **A dependência = forma de serviço** (retângulo/hexágono), **nunca cilindro/DB**.
- **O ciclo vicioso é o protagonista visual:** duas setas como um **círculo grande girando** (uma "timeout →", a de volta "amplifies →"); anime a rotação no reveal 5. Deixar **as duas sólidas e vermelhas** (não misturar tracejado/sólido — não significa nada).
- **O blast = leque à direita**, vermelho, lido como consequências (saem do loop), não pares.
- **Cor = significado:** vermelho = falha; neutro = saudável. Sem amarelo/azul decorativo.
- Mermaid é só a fonte da verdade de conteúdo/topologia; o visual final é desenhado (Slides) ou gerado (Nano Banana) com texto real por cima.

**Reveals (7):**
1. A frota (baralho + `× N`). *"Mesma agente, muitas sessões."*
2. Convergência numa dependência (funil).
3. Degrada (vermelha, 18s).
4. A sabotagem — modelo lê timeout como erro próprio → retenta.
5. O loop fecha — "amplifies" volta; o círculo gira. Pânico (nomeia retry storm).
6. A explosão — 4 sintomas.
7. Herói conceitual + punchline.

`18s` é número de **cena** (ilustra a dependência lenta), não de impacto — pode ficar.

### Speaker notes (EN)
> *(open — pay off the Case 1 bridge)*
> "In Case 1 we earned the green score. But that eval ran in a simulated environment — one session at a time. It never saw a fleet.
> *(reveal 1)* In production it's never one agent. It's the same agent, running as a fleet — many concurrent sessions.
> *(reveal 2)* And they all share the same dependencies. They converge on one downstream service.
> *(reveal 3)* Now that dependency degrades. Slow, not down — eighteen seconds per call.
> *(reveal 4)* Here's the part that's specific to agents. A normal system sees a network timeout. The model does not. It reads the timeout as *its own mistake* — 'I must have passed the wrong parameter' — so it tries again.
> *(reveal 5)* Multiply that by N sessions, all retrying at once. That's a retry storm. And the storm amplifies the very outage it's reacting to. The cycle feeds itself.
> *(reveal 6)* Four things happen together. Cost: a two-times traffic spike becomes twenty-times the tokens. Quota: the model endpoint hits its shared limit and returns 429s. Hallucination: when the tool stalls, the agent doesn't say 'I don't know' — it invents the balance. And the runtime itself saturates — it is not infinitely elastic.
> *(reveal 7)* So the real problem is not one agent stuck in a loop. It's a stochastic distributed system — a fleet amplifying one dependency's outage, with non-linear cost. One dependency went down, and it took your agent — and your bill — with it.
> *(trivial-twin inoculation — say it, don't slide it)* And to be clear: this is not something you fix with a `max_iterations` cap. That limits one agent. It does nothing for a fleet amplifying a shared dependency.
> *(hand off to Slide 6)* So the first question is: which dependency? Let's open the trace."

Timing ~75–90s. Inegociável: reveal 7. `max_iterations` pode virar resposta de Q&A se apertar.

### Defesas de Q&A (Slide 5)
- **"Não é só thundering herd clássico?"** → Na infra, sim. O amplificador novo é o **modelo**: repete na camada de raciocínio (invisível pro backoff) e **alucina** em vez de falhar.
- **"Por que não escalar horizontal?"** → Custo de token é **não-linear**; escalar multiplica a conta e ainda bate no **mesmo 429 do DSQ**.
- **"`max_iterations` não resolve?"** → Limita **uma** agente. Nada faz por uma **frota** amplificando dependência compartilhada. Altitude errada.

---

## 6. Slide 6 — "Contain the blast"

**Papel:** o vira-jogo. **Câmera:** aproxima em UM waterfall → clique (breaker corta). **Cor:** vermelho vira verde. **Demo tecida** (3 beats). **Título:** "Contain the blast" (ou "Cut the loop").

### Arquitetura — duas movimentações: (A) diagnóstico + (B) contenção

**Parte A — o waterfall (diagnóstico · demo beat 1).** Barra de tempo (Gantt), não flowchart:
```
DIAGNOSIS — one trace, where did the 18s go?
  Model      ▐█▌ 1s                                  (green)
  Look-up    ▐███████████████████████▌ 18s   ← culprit (red)
  ───────────────────────────────────────────► time
  "The model is fine. The dependency degraded."
```
Observabilidade **motivada** — 1 beat rápido, emenda no breaker. Não é tour de tracing.

**Parte B — contenção (breaker semântico + fallback ladder):**
```mermaid
flowchart LR
  AGENT["Agent"]:::ok
  CB["CIRCUIT BREAKER<br/>opens after N failures"]:::breaker
  DEP["Shared dependency<br/>DEGRADED · 18s"]:::bad
  INJ["Inject into context<br/><b>'tool unavailable · do not retry · follow fallback'</b>"]:::inject

  subgraph LADDER["Fallback ladder — degrade, don't invent"]
    direction LR
    L1["Gemini Pro"]:::rung --> L2["Flash"]:::rung --> L3["Cached answer"]:::rung --> L4["Human handoff"]:::rung
  end

  AGENT --> CB
  CB -. "cuts the blind call" .-x DEP
  CB ==> INJ
  INJ ==> LADDER

  classDef ok fill:#e6f4ea,stroke:#188038,color:#111
  classDef breaker fill:#fff,stroke:#1a73e8,stroke-width:3px,color:#111
  classDef bad fill:#fce8e6,stroke:#d93025,stroke-width:2px,color:#111
  classDef inject fill:#e8f0fe,stroke:#1a73e8,stroke-width:3px,color:#111
  classDef rung fill:#f1f3f4,stroke:#5f6368,color:#111
```

**O herói do slide é a seta grossa `CB ==> INJECT`.** Um breaker normal só faz a parte fina tracejada (`cuts the call ✕`) — e o modelo relê o erro e tenta de novo. O **semântico** injeta o fato **de volta no contexto**. Erro de infra vira **fato determinístico**. Essa é a diferença L400.

**Notas de build:**
- **A seta de injeção é a maior/mais forte** (azul, grossa). A seta pro dependency é **fina, tracejada, ✕** (o familiar). Contraste visual = a mensagem.
- **O waterfall = duas barras horizontais** (escala de tempo real): modelo curto/verde, tool longa/vermelha, callout "18s". Fica em cima/à esquerda como lead-in.
- **A fallback ladder desce/degrada** — Pro → Flash → cache → humano; cada degrau mais apagado. Rótulo: *degrade, don't invent* (NÃO "never hallucinate" — ver §8).
- **Cor = significado:** vermelho = degradado/corte cego; azul = a intervenção; verde = desfecho gracioso.
- **Continuidade:** a "Shared dependency · 18s" é a **mesma** do Slide 5; o breaker aparece *em cima* dela.

**Reveals (6 + 3 demo beats tecidos):**
1. Diagnóstico — o waterfall (modelo 1s vs tool 18s). **[DEMO beat 1: abre a trace real no console]**
2. Embrulha o culpado — breaker na frente da dependência que a trace apontou.
3. Abre e corta — após N falhas o breaker abre; a seta cega vira ✕. **[DEMO beat 2: gráfico de tokens/latência subindo → o breaker corta]** — deixa respirar.
4. **O HERÓI — injeta no contexto** — *"tool unavailable · do not retry · follow fallback."* Fala o contraste com o breaker normal.
5. Fallback ladder — Pro → Flash → cache → humano. *Degrade, don't invent.* Cada degrau é *sua* decisão.
6. Desfecho + ponte — **[DEMO beat 3: fallback responde em ~2s, degradação graciosa em vez de saldo inventado]**. Fecha: *"contivemos o incidente. Mas ainda não governamos o custo."* → Slide 7.

### Speaker notes (EN)
> *(pick up from Slide 5's last line: "which dependency?")*
> "So — which dependency? We don't guess. We open the trace.
> *(reveal 1 · demo beat 1)* Here is one request, broken down by step. The model responded in one second. This look-up tool took eighteen. The fault is not the model — it's the external dependency. Observability didn't just tell me it was slow; it told me *where*.
> *(reveal 2)* Now I contain it. And I wrap exactly the dependency the trace pointed at — not blindly, everywhere. I put a circuit breaker in front of it.
> *(reveal 3 · demo beat 2)* After N failures, the breaker opens and stops calling the dead dependency. Watch the dashboard — the tokens and latency are climbing… and the breaker cuts it off. *(let it breathe)*
> *(reveal 4 — the hero)* But here is the part that matters for agents. A normal circuit breaker just returns an error. The model would read that error, reinterpret it, and try again. So I don't return an error — I **inject the fact back into the context**, in language the model understands: 'this tool is unavailable; do not retry; follow the fallback.' That turns an infrastructure error into a deterministic instruction.
> *(reveal 5)* And then the fallback ladder. What do you do when the tool is down? Degrade — don't invent. Try a cheaper model, then a cached answer, then hand off to a human. Each rung is your decision — the platform does not decide this for you.
> *(reveal 6 · demo beat 3)* The result: the agent responds in about two seconds with honest, degraded service — instead of inventing a balance. We turned a silent, expensive outage into a controlled, cheap failure.
> *(bridge to Slide 7)* We contained the incident. But surviving is not the same as governing. We still haven't answered: what did this cost — and who pays for it?"

Timing ~2 min (com os 3 beats). Inegociável: **reveal 4** (injeção no contexto) — o único conceito que separa isto de "circuit breaker de microsserviço".

### Defesas de Q&A (Slide 6)
- **"Circuit breaker não é padrão antigo?"** → O padrão sim; o **twist** é injetar no contexto porque o consumidor é um raciocinador que reinterpreta erro. Devolver 500 pra um loop de raciocínio não contém — realimenta.
- **"E se o próprio fallback (Flash) alucinar?"** → Por isso a escada **termina** em degraus determinísticos (cache/humano). O objetivo é *degrade, don't invent*, não "modelo nunca erra".

---

## 7. Slide 7 — "Govern the cost"

**Papel:** amadurecimento final — de conter um incidente pra governar a economia. **Câmera:** afasta (uma sessão → a árvore da org). **Cor:** verde/controle (com callout vermelho no "porquê"). **Demo tecida** (leve). **Título:** "Govern the cost" (alt: "Who pays for it?", paga a deixa do Slide 6). **Deep spike:** *one instrumented number, three altitudes of control.*

### A ideia que faz ser L400 (não "ligue o billing dashboard")
> A economia do agente é **não-linear**, e a plataforma **não te dá o número** que você precisa pra governá-la. Custo não escala com tráfego — ele *compõe*: fan-out (sub-agentes) × contexto crescendo (cada turno reenvia o histórico) × retries. E a plataforma captura I/O e latência por span, mas **não captura custo**, e token vem **agregado**. Então você instrumenta **custo por span** — e esse número, uma vez que existe, faz **três trabalhos em três altitudes**: sessão (local), time/projeto (médio), org (global).

Rima de propósito com o Caso 1 ("um invariante, seis superfícies") e reusa o **mesmo seam** (o callback que emitiu o span, rodou o invariante no C1 e injetou o breaker no S6 — agora acumula custo e aplica o budget). **Um seam, muitos trabalhos** = o fio arquitetural do talk inteiro.

### Arquitetura — um número, três escopos (leque paralelo; WHY = banner)
> **Correção de geometria (2026-07-08):** a v1 desenhava `SESSION → PROJECT → ORG` encadeados (sugeria fluxo/sequência falso — mesmo bug do S5) e `WHY -.-> SEAM` (sugeria que o "porquê" flui pra dentro do seam). O conceito real é **uma fonte → três consumidores PARALELOS**, em escopo crescente. WHY é motivação (banner), não nó de fluxo.

```mermaid
flowchart LR
  WHY["<b>WHY it's non-linear</b> — fan-out × context growth × retries · <i>2× traffic → 20× tokens (Slide 5)</i>"]:::why

  SEAM["<b>cost per span</b><br/>you instrument it<br/><i>platform gives I/O + latency, not cost</i>"]:::seam

  ORG["<b>ORG</b> · global<br/>Billing→BigQuery + labels<br/>chargeback · quotas per tenant"]:::ctrl
  PROJ["<b>PROJECT / TEAM</b> · mid<br/>cost-aware routing (Flash/Pro)<br/>reserved-capacity sizing"]:::ctrl
  SESS["<b>SESSION</b> · local<br/>per-session budget<br/>kill a runaway session"]:::ctrl

  SEAM ==> ORG
  SEAM ==> PROJ
  SEAM ==> SESS

  classDef why fill:#fce8e6,stroke:#d93025,color:#111
  classDef seam fill:#e8f0fe,stroke:#1a73e8,stroke-width:3px,color:#111
  classDef ctrl fill:#e6f4ea,stroke:#188038,color:#111
```
**Herói visual:** UMA fonte (`cost per span`) → **três lanes paralelas** (session/project/org). Lê na hora como "o mesmo número, três usos". Distinção afiada: **budget por sessão = contenção local** (mata *uma* sessão descontrolada, o espírito do breaker); **FinOps na org = governança global** (atribui e cobra por tenant). Visibilidade de custo ≠ gestão de custo.

**Notas de build:**
- **WHY = faixa vermelha no topo, largura cheia, SEM seta** — é o "porquê nos importamos" (reveal 1), depois fica de pano de fundo. Nunca ligar por seta ao seam.
- **Leque paralelo, não cadeia:** as três lanes saem da mesma fonte; **nenhuma seta entre elas** (session não "vira" project). Ordem = escopo: SESSION embaixo → ORG em cima, com um eixo lateral discreto **"scope: local → global ↑"** (dá a sensação de câmera afastando sem seta causal).
- **Cor = significado (consistente com S6):** vermelho = a ferida (economia não-linear); **azul = sua instrumentação** (o seam/cost-per-span, mesma cor da injeção do S6); verde = os controles/governança.
- **O seam é o MESMO elemento visual** do C1 (span + invariante) e do S6 (injeta breaker) — mostre-o recorrente ("um seam, muitos trabalhos"). Continuidade barata e poderosa.
- **Reserved capacity (Provisioned Throughput) fica como sub-item pequeno** da lane PROJECT, tag "*capacity, not the star*" — sem destaque de depth spike.
- **Alternativa premium (build manual):** anéis concêntricos (cost/span no centro → SESSION → PROJECT → ORG) — mostra "mesmo número, escopo se abrindo" e faz callback do *blast radius* do S5/S6. Mais elegante, um tico mais de carga cognitiva. Mermaid não desenha.

**Reveals (7 + demo leve tecida):**
1. **O porquê (vermelho)** — custo é não-linear: fan-out × contexto × retries. *"O 2×→20× do Slide 5 não foi azar."*
2. **Beat de honestidade + o enabler (azul)** — cost per span. A plataforma dá I/O e latência, **não** custo; token agregado → você instrumenta, no **mesmo seam** do C1/S6. **[DEMO: abre a trace, mostra o atributo de custo por span — o número que a plataforma não deu]**
3. **Altitude 1 — SESSION** — budget por sessão, contém *uma* sessão descontrolada, localmente.
4. **Altitude 2 — PROJECT/TEAM** — modela gasto: routing cost-aware (seu código, não há router gerenciado) + reserved-capacity (Provisioned Throughput) sizing (1 frase).
5. **Altitude 3 — ORG** — FinOps: Billing→BigQuery + labels → chargeback/alerts/quotas por tenant. **[DEMO: BigQuery — custo por projeto/tenant; um time dispara → alerta]**
6. **Payoff do deep spike** — *"um número instrumentado, três altitudes: sessão, time, org. A diferença entre receber uma conta assustadora e governar o gasto."*
7. **Ponte pro Caso 3** — *"resiliente ✓, custo governado ✓ — mas cada chamada mexe com dinheiro e PII. Resiliente ≠ seguro."*

### Speaker notes (EN)
> *(pick up from Slide 6's last line: "what did this cost — and who pays for it?")*
> "We survived the incident. Now — what did it cost, and who pays?
> *(reveal 1 — the why)* First, why cost is even a problem. For a normal service, cost scales with traffic — double the traffic, double the bill. For an agent it compounds: one request fans out into sub-agents and tool calls; every turn re-sends the growing context; and retries multiply all of it. That's why, back in Slide 5, a two-times traffic spike became twenty-times the tokens. It's not bad luck — it's how agent economics behave.
> *(reveal 2 — honesty beat · demo)* Now here's the catch. To govern cost, you need the cost of each decision. And the platform does not give it to you. It captures inputs, outputs, and latency per step — but not cost, and token counts come aggregated, per session or per model. So you instrument cost per span yourself — on the *same* callback that already emits the trace and runs the invariant from Case 1. One seam, many jobs. *(show the cost attribute in the trace)*
> *(reveal 3 — session)* Once you have that number, it does three jobs, at three altitudes. First, the session: a per-session token and step budget. This kills one runaway session in flight — the same idea as the breaker, but for spend. Local containment.
> *(reveal 4 — project)* Second, the team or project: now that you can see which decision is expensive, you route — Flash for the easy calls, Pro for the hard ones. That routing is your code; there is no managed router. And this is where you size reserved capacity — Provisioned Throughput — if you need predictable latency. But capacity is a purchase; the engineering is the policy around it.
> *(reveal 5 — org · demo)* Third, the org: you tag every call with a label hierarchy — user, project, org — stream it to BigQuery, and now you can attribute and govern. Chargeback per tenant, alerts and quotas per project. *(show cost per tenant; one team spikes, an alert fires.)*
> *(reveal 6 — payoff)* One instrumented number, three altitudes: session, team, org. That is the difference between getting a scary bill at the end of the month and governing spend as it happens. Visibility is not management.
> *(reveal 7 — bridge to Case 3)* So now the agent is resilient, and its cost is governed. But look at what we've been moving around this whole time — refunds, balances, customer accounts. Every one of these calls touches money and PII. Resilient is not the same as secure. That's Case 3."

Timing ~2 min (2 beats leves de demo). Inegociáveis: **reveal 2** (custo não é capturado — "liguei tracing" vs "governo gasto") e **reveal 6** (payoff das três altitudes). Se apertar, o tier PROJECT (reveal 4) vira 1 frase.

### Defesas de Q&A (Slide 7)
- **"A plataforma não dá custo?"** → Dá I/O e latência por span; **custo não**, e token vem agregado (sessão/modelo/agente). Custo por span é instrumentação sua.
- **"Não é só tag + dashboard no BigQuery?"** → O dashboard é a parte fácil. A disciplina é instrumentar no nível da *decisão*, aplicar budget em *runtime* (local) e atribuir numa *hierarquia de labels* (global) — custo vira loop de controle, não autópsia mensal.
- **"Por que não só uma quota de projeto?"** → Quota de projeto é teto global cego; não para *uma* sessão descontrolada no meio do voo, nem atribui por tenant. Precisa das duas altitudes.
- **"Reserved capacity (PT) é obrigatório?"** → Não — é escolha de capacidade pra latência previsível e evitar 429. A engenharia é a política de spillover + budget + backoff, não comprar o SKU.

**Lente travada (§1):** protagonista é a **economia** (custo não-linear, cost/span, FinOps na árvore) — muito mais L400 e raro de ver bem-feito do que "compre capacidade reservada". Reserved capacity (PT) é coadjuvante.

---

## 8. Landmines e decisões travadas
- **"never hallucinate" → RECUSADO.** Absoluto atacável e nem mecanicamente verdadeiro (Flash na escada pode alucinar). Frase oficial: **"Degrade, don't invent"** (a escada termina em degrau determinístico: cache/humano). O objetivo é trocar "inventa o saldo" por degradação honesta, não zerar alucinação.
- **Provisioned Throughput NÃO é depth spike** — é procurement. A disciplina é a **política** (spillover vs 429 + budget + backoff), não o SKU.
- **Todo beat abre pelo twist, não pelo mecanismo** (senão vira L200).
- **Waterfall não é tour de tracing** — entra como diagnóstico motivado, 1 beat, emenda no breaker.
- **Custo NÃO é capturado pela plataforma; token vem agregado** → cost/span é instrumentação sua. Dizer no palco.
- **Não há router gerenciado**; Pub/Sub/Cloud Tasks é sua arquitetura. Dizer.
- **Impacto em ordem de grandeza**, nunca falso-preciso ("dezenas de seg → poucos seg"; "spike de tokens, não explosão 20× como número de impacto"). `18s`/`2×→20×` são números de **cena**, ficam.
- **Só o 403 do Caso 3 é genuinamente real**; demos do Caso 2 demonstram *partes* (mock honesto; tool lenta = `time.sleep(15)`). O Caso 2 é o único candidato a "live" controlado, com vídeo de fallback aberto.
- **Forma de diagrama:** loop vicioso NÃO em layout radial/hub (embola). Fluxo com o loop girando no centro. Cor só carrega significado.
