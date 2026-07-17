# Speaker Notes — Caso 2 (Resilience & Cost Under Load)

> **Fonte única da verdade das speaker notes do Caso 2.** Deck final = 4 slides
> (p.8 divider · p.9 Cascade · p.10 Contain · p.11 Govern).
>
> **Convenção deste doc:** cada slide separa **🎤 O que você FALA** (narração, o
> que sai da sua boca) de **🎬 O que você FAZ** (ações de demo, alinhadas à fala).
> Nunca misture os dois no mesmo parágrafo — foi o que confundiu na v1.
>
> **Numeração:** os docs antigos (`case-2-demos.md`, `case-2-fundamentos.md`)
> chamam de Slide 5/6/7. O **deck real é p.9/10/11**. Este doc usa o deck real.
>
> **Operacional (comandos, links, IDs, "se falhar"):** `demos/case-2-runbook.md`.
> **Narrativa/arquitetura:** `demos/case-2-demos.md`.
>
> **Latência do mock = 15s** (código `faults.py` + trace pré-rodada + slide). Se o
> slide mudar, atualize as 2 menções de "fifteen seconds / 15s" abaixo.

---

## Slide 8 — Section divider ("02 — Resilience & Cost Under Load")

### 🎤 O que você FALA
> *(transição curta, ~10s, sem demo)*
> "Case 1 was about **truth** — proving the agent does the right thing. Case 2 is
> what happens when that *same* agent hits **production**. Now it runs as a fleet.
> Its dependencies degrade. And every call costs money. Resilience and cost, under
> load."

---

## Slide 9 — The Cascade *(conceito, sem demo)*

### 🎤 O que você FALA
> **(open — pay off the Case 1 bridge)**
> "In Case 1 we earned the green score. But that eval ran in a simulated
> environment — one session at a time. It never saw a fleet.
>
> **(reveal 1 — the fleet)** In production it's never one agent. It's the same
> agent, running as a fleet — many sessions running side by side.
>
> **(reveal 2 — converge)** And they all share the same dependencies. They
> converge on one downstream service.
>
> **(reveal 3 — degraded)** Then that shared dependency starts to degrade. Not
> down — just slow. Fifteen seconds per call.
>
> **(reveal 4 — model misreads)** Here's the part that's specific to agents. A
> normal system sees a network timeout. The model does not. It reads the timeout
> as *its own* mistake — it assumes it passed the wrong parameter — so it tries
> again.
>
> **(reveal 5 — the loop closes)** Now multiply that across the fleet — every
> session retrying at once. That's a retry storm. And the storm amplifies the very outage it's
> reacting to. The cycle feeds itself.
>
> **(reveal 6 — blast radius)** Four things happen at once. In this case, twice the
> traffic becomes twenty times the tokens — the cost explodes. The model endpoint
> hits its shared quota and starts returning 429s. The agent, instead of admitting it doesn't
> know, invents the balance. And the runtime itself saturates — it was never
> infinitely elastic.
>
> **(reveal 7 — the hero + punchline)** So the real problem is not one agent stuck
> in a loop. It's a **stochastic distributed system** — a fleet amplifying one
> dependency's outage, with non-linear cost. One dependency went slow, and it took
> your agent — and your bill — with it.
>
> **(trivial-twin inoculation — say it, don't slide it)** And to be clear, this is
> not something you fix with a `max_iterations` cap. That limits *one* agent. It
> does nothing for a fleet amplifying a shared dependency.
>
> **(hand off to Slide 10)** So the first question is, **which** dependency? Let's
> open the trace."

### ⚠️ Honestidade / Q&A
- DSQ (429) e saturação de runtime = **explicados, não disparados ao vivo** (não dá
  pra estourar quota compartilhada real com segurança).
- O gêmeo trivial (`max_iterations`) é inoculado **na fala**, não no slide — de
  propósito.

---

## Slide 10 — Contain the Blast *(o slide-herói — demo do A/B)*

### 🎤 O que você FALA *(estrutura invertida: incidente ao vivo no dashboard)*
> **(open — the fleet, healthy · dashboard baseline)**
> "This is the same agent from Case 1. But now it's in production — running as a
> fleet, many sessions at once. Right now it's healthy. Every request comes back in
> about eight seconds.
>
> **(the incident — the storm · dashboard incident)** Then a shared dependency
> degrades. Not down — just slow. And watch what it does to the fleet. Latency
> jumps past **fifty seconds**. Throughput collapses — we go from twenty-four
> interactions a minute down to three. The fleet is stalling. And worse — while
> it's stuck, the agent doesn't admit it's slow. It **invents the balance**.
>
> **(which dependency? · Cloud Trace)** So which one is it? I don't guess. The
> trace tells me. The model call is fast — about a second. This one tool took
> **fifteen seconds**. That's what I'm going to wrap.
>
> **(the twist — inject, don't error · VSCode)** And here's the twist that makes
> this an *agent* problem. A normal circuit breaker returns an **error**. The
> model reads that error and just tries again. So mine works differently. After a
> couple of failures, it opens. Instead of an error, it **injects a fact into the
> context**. It tells the model the tool is unavailable, and to follow the fallback
> rather than retry.
>
> **(the fix — watch it recover · dashboard recovery)** Now watch the same fleet
> with the breaker on. Latency falls back to eight seconds. The breaker starts
> firing — that's the breaker cutting the blind calls. And throughput climbs all the
> way back. Same seam from Case 1 — new job.
>
> **(optional — the alert)** And that breaker signal isn't just a graph. It's a log
> line you can page on. The breaker contains the damage in real time. And an alert on
> it gets a human to fix the dependency itself.
>
> **(the fallback ladder · slide)** And that fallback isn't vague. It's a ladder,
> organized by the type of failure. If the problem is the model or the quota — a
> 429 — you route down, from Pro to Flash. If the data or a dependency is down, you
> serve a **cached** answer. And if there's nothing cached, you **hand off to a
> human**. The rule at every rung is the same — **degrade, don't invent.**
>
> **(payoff + bridge)** So expensive chaos became a **cheap, honest failure**. We
> survived the incident. Now the next question — what did it **cost**, and **who
> pays** for it?"

### 🎬 O que você FAZ (choreografia — segue a fala, da esquerda pra direita no dashboard)
| # | Fala | Ação | Onde |
|---|---|---|---|
| 1 | "…healthy… about eight seconds" | Apontar o trecho **BASELINE** (p50 ~8s, sessões ~24/min) | **Dashboard** |
| 2 | "watch what it does… stalling… invents the balance" | Apontar o trecho **INCIDENTE** (latência → ~50s, sessões → ~3/min) | **Dashboard** |
| 3 | "which one is it?… fifteen seconds" | Cortar pra trace: `issue_refund` ~15s vs `call_llm` ~1s | **Cloud Trace** |
| 4 | "injects a fact… do not retry" | Cortar pro código: `circuit_breaker` → o `return {...}` | **VSCode** |
| 5 | "watch the same fleet… climbs all the way back" | Voltar pro dashboard: trecho **RECUPERAÇÃO** (p50 → ~8s, breaker-open sobe, sessões → ~24) | **Dashboard** |
| 5b · opcional | "a log line you can page on" | Cortar pro Logs Explorer: linha **WARNING** `breaker_open` (`issue_refund`, `elapsed≈15s`) | **Cloud Logging** |
| 6 | "it's a ladder, organized by the type of failure" | Apontar o painel direito do slide | o próprio slide |

**Sequência de janelas:** Dashboard → Cloud Trace → VSCode → Dashboard → Slide.
Tudo **pré-gravado** — você narra por cima da linha do tempo, nada roda ao vivo.

**🔗 Links (deixar as abas abertas antes de subir ao palco):**
- **Dashboard (3 atos):** https://console.cloud.google.com/monitoring/dashboards/builder/7111cbc0-edcc-40e7-8b69-c13106afdb34?project=YOUR_PROJECT_ID
  → tiles: latência **p50** (herói, V limpo 8→53→8), breaker-open/min, sessões/min.
  → janela do run `case2-final` (gravado **2026-07-15**): **~21:17–21:40 (UTC do VM)** — no console (UTC-3)
    aparece **~18:17–18:40**. Ajuste o time-range pra essa faixa.
- **Cloud Trace (15s):** https://console.cloud.google.com/traces/list?project=YOUR_PROJECT_ID&tid=c129273cbcd5934d60f9473535c036a5
  → ⚠️ **a view filtra pela última hora** — se a trace for antiga aparece vazia.
    **Gere fresca no dia** (fica na janela recente e o link abre direto):
    `CASE=2 uv run python -m scripts.live_drive --scenario slow_payment --prompt "Refund my \$50 charge TXN-1001."`
    (imprime a nova `tid` — troque no link). Ou expanda o time-range no Cloud Trace.
- **Código:** `agent/financial_support/callbacks/resilience.py` → `circuit_breaker`
- **Cloud Logging (breaker aberto):** Logs Explorer com a query
  ```
  logName="projects/YOUR_PROJECT_ID/logs/breaker_events_live"
  jsonPayload.event="breaker_open"
  ```
  → uma linha **WARNING** por vez que o circuito abre (`tool=issue_refund`,
  `reason=slow`, `elapsed_s≈15`). É o *"you page on it"* literal — sinal **real**;
  **nenhuma alert policy presa** nele (por escolha; dá pra prender em 1 passo). Só
  emite se o run tiver `BREAKER_AUDIT_LOG=on`. Emitido pelo callback `record_outcome`
  → `observability/breaker_log.py`.

**Honestidade do dashboard:** são **custom metrics instrumentadas por você**, medidas
do agente REAL sob carga simulada — **não** as métricas nativas do engine. Isso é
on-thesis ("você instrumenta o número que o console não te dá"); diga se perguntarem.

**Re-gravar mais perto do dia (~25–30 min, tokens reais):** precisa do
`BREAKER_AUDIT_LOG=on` pra emitir a linha de log do breaker na mesma rodada.
```bash
BREAKER_AUDIT_LOG=on BREAKER_OPEN_AFTER=2 uv run python -m scripts.monitoring_demo \
  --act-seconds 480 --tick-seconds 30 --session-timeout 90 --window-seconds 120 \
  --concurrency 2 --run-label case2-final
```
⚠️ **429 (cota):** em 2026-07-17 a rodada com `--concurrency 3` tomou `429
RESOURCE_EXHAUSTED` e **sujou o baseline** (os retries do 429 travaram sessões
"healthy" no cap → mean/p95 estouraram; o p50 sobreviveu). Use `--concurrency 2`. Se
ainda tomar 429, **use a janela limpa de 07-15** — a série `case2-final` guarda as
duas rodadas, é só escolher o time-range. Depois valide o log com a query do Logs
Explorer acima (uma linha `breaker_open` no ato recovery).

**Rede (backup se o dashboard falhar):** a tabela A/B no terminal —
`BREAKER_OPEN_AFTER=2 uv run python -m scripts.load_test --ab --scenario slow_payment --n 6 --concurrency 2`
— pré-rodada, + o vídeo de fallback aberto numa aba.

### ⚠️ Honestidade / Q&A
- O atraso é um **mock** (`time.sleep`) da degradação — dizer.
- A alucinação do incidente **não é determinística** → narrar + ter o **vídeo de
  fallback** aberto (não confiar ao vivo).
- O roteamento Pro→Flash é **seu código** — não há router gerenciado.
- O dashboard é **pré-gravado** e as métricas são **instrumentadas por você** (não
  nativas do engine) — on-thesis, dizer se perguntarem.
- O **log do breaker** (`breaker_events_live`) é **instrumentação sua** via callback
  (`BREAKER_AUDIT_LOG=on`) — a plataforma não te dá esse evento; mesma tese do custo/span.

**Perguntas prováveis (respostas prontas):**
- **"O que o breaker faz quando aciona?"** Dois tempos: (1) *in-band* — degrada com
  a fallback ladder e responde honesto (salva a requisição agora); (2) *out-of-band*
  — ao abrir, emite uma linha **WARNING** no Cloud Logging (`breaker_events_live`,
  `event=breaker_open`) que você **pode** paginar pra tirar um humano e consertar a
  **causa raiz** (a dependência). Honesto no palco: o sinal (log) é **real**; **não há
  alert policy presa** nele hoje — é 1 passo, mas de propósito não montei. E **não há
  probe half-open automático**: o breaker reseta num sucesso rápido *se* uma chamada
  passar, mas enquanto a dependência fica lenta ele **fica aberto contendo** — a cura
  da dependência é trabalho do humano via alerta, não automática.
- **"Sessões/min é rejeição de cliente?"** Não. É **throughput** (interações que
  completam/min). No incidente cai (22→3) porque **cada sessão demora ~50s** e engasga
  — a frota **trava**. Cliente OFF: lento + às vezes **errado** (saldo inventado); e
  sob saturação sustentada, eventualmente timeout/recusa. Cliente ON: **rápido (~8s) e
  honesto** ("não consigo confirmar agora; um humano confirma").
- **"Isso não é só um circuit breaker de biblioteca?"** Não — biblioteca devolve
  *erro* e o modelo relê e **retenta** (amplifica). Este injeta um **fato** no contexto
  (fala a língua do modelo). E `max_iterations` limita UMA agente, não uma frota.
- **Depth:** o breaker é in-process → numa frota multi-instância abre por-instância; o
  flatten que mostro é local (processo único). Fleet-wide precisa de store
  compartilhado (Memorystore/Redis), não um dict de processo.

---

## Slide 11 — Govern the Cost

### 🎤 O que você FALA
> **(pick up from Slide 10's last line: "what did this cost — and who pays?")**
> "So — what did it cost? And who pays?
>
> **(reveal 1 — the why)** Why is cost even a problem to begin with? For a normal
> service, cost scales with traffic — double the traffic, double the bill. For an
> agent it **compounds**. One request fans out into sub-agents and tool calls.
> Every turn re-sends the growing context. And retries multiply all of it. That's
> why the storm turned twice the traffic into twenty times the tokens. It's
> not bad luck — it's how agent economics behave.
>
> **(reveal 2 — honesty beat)** Now the catch. To govern cost, you need the cost
> of each **decision**. And the platform does not give it to you. It captures
> inputs, outputs, and latency per step — but **not cost**. And the token counts
> come **aggregated** — per session, or per model. So you instrument cost per span
> **yourself**. It's the same callback that already emits the trace and runs the
> Case 1 invariant. One seam, many jobs.
>
> **(reveal 3 — session · local)** Once you have that number, it does three jobs
> at three altitudes. First, the **session**. You set a per-session token and step
> budget. This kills one runaway session in flight — same idea as the breaker, but
> for spend.
>
> **(reveal 4 — project/team · shape spend)** Second, the **team or project**. Now
> that you can see which decision is expensive, you **route** — Flash for the easy
> calls, Pro for the hard ones. That routing is your code. There is no managed
> router. And this is also where you size reserved capacity — **Provisioned
> Throughput**. That's for when you need predictable latency. But capacity is just a
> *purchase*. The engineering is the policy around it.
>
> **(reveal 5 — org · global)** Third, the **org**. You tag every call with a
> label hierarchy — user, project, org. You stream it to BigQuery. And now you can
> attribute and govern. Chargeback per tenant. Alerts and quotas per project.
>
> **(reveal 6 — payoff)** One instrumented number, three altitudes — session,
> team, org. Without it, you get a scary bill at the end of the month. With it, you
> **govern spend as it happens**. Visibility is not management.
>
> **(reveal 7 — bridge to Case 3)** So now the agent is resilient, and its cost is
> governed. But look at what we've been moving this whole time — refunds,
> balances, customer accounts. Every one of these calls touches **money and PII**.
> Resilient is not the same as **secure**. That's Case 3."

### 🎬 O que você FAZ (alinhado à fala)
| # | Quando (na fala) | Ação | Onde |
|---|---|---|---|
| 1 | reveal 2 ("instrument cost per span yourself") | Span `call_llm` → aba Attributes → apontar `gen_ai.cost.usd` | Cloud Trace (mesma trace do Slide 10) |
| 2 | reveal 5 ("chargeback per tenant… alerts") | Query `cost_by_tenant` → uma barra ~10× (proj-runaway); alerta | BigQuery + Cloud Monitoring |

### ⚠️ Honestidade / Q&A
- `gen_ai.cost.usd` é **seu atributo** — a plataforma dá I/O + latência, **não**
  custo; token vem agregado.
- A tabela do BQ que mostro é o custo que **eu instrumentei** (`cost_spans`),
  **não** o Billing export — esse atrasa horas. Não implicar que é o billing real.
- O alerta **só notifica** — não é gate (mesma honestidade do Caso 1).
- Provisioned Throughput: se citar GSU/spillover verbatim, conferir na doc pública
  antes.

---

## Ordem de prioridade da demo (se o tempo apertar)
A/B (Slide 10) > trace 15s (Slide 10) > cost/span (Slide 11) > BQ tenant (Slide 11)
> engine deployado (garnish).

## O que NÃO fazer ao vivo
Deploy/update do engine · contar com a alucinação ao vivo · prometer flatten no p95
do Console. Pré-rodado é pré-rodado; o A/B local é o único semi-live.
