# Caso 2 — Demonstração L400 (Resilience & Cost under Load)

> Documento de referência da demonstração do **Caso 2** do talk "Managing
> Production Agents at Scale". Consolida a arquitetura da demo, o mapeamento
> demo↔slide, o inventário de componentes do Google Cloud (real vs. seu código),
> e — no maior detalhe — **o que construir no codebase `agent/`** (os concerns do
> C2 já estão *plantados e dormentes* lá; aqui está como ativá-los).
>
> **Escopo:** fonte da verdade para **construir as demos do Caso 2**.
> Narrativa/slides do Caso 2 estão em `docs/case-2-fundamentos.md`.
> Agente-base: `agent/` (ADK 2.3.0, uv, py3.12) — o **mesmo** agente do Caso 1.
> Última atualização: 2026-07-08.

---

## 0. Objetivo e princípios

- **Objetivo:** provar, em código real e produtos reais do Google Cloud, a tese do
  Caso 2 — *"resiliência clássica não basta para um componente que raciocina"* — e
  mostrar o **A/B ao vivo** (breaker OFF vs ON) que transforma um caos caro numa
  falha barata e honesta.
- **Público / nível:** FDEs (SWEs), Nooglers, Accenture. **L400**, ~7 min, demo
  **tecida** nos 3 slides (não bloco monolítico).
- **Meio:** **VSCode à esquerda** (o código: breaker/budget/cost são *seu* código) +
  **Cloud Console à direita** (Cloud Trace, Cloud Monitoring, BigQuery = prova de
  "isto é GCP real"). Um terminal com o **gerador de carga**.
- **Princípio anti-vitrine (o que mata o "bla bla"):** o beat que carrega o caso é o
  **contraste A/B nos dashboards reais**, não "olha minha trace bonita". A waterfall
  entra como **diagnóstico motivado** (achar a dependência), 1 beat, e emenda no breaker.
- **Princípio de credibilidade:** o substrato é **GA** (Cloud Trace, Cloud
  Monitoring, BigQuery, Cloud Build, Provisioned Throughput, Context caching); o
  **breaker semântico, o cost/span e o budget são SEU código** — a disciplina, não
  uma feature. Isso é exatamente o que o FDE leva pra casa.

---

## 1. Decisões travadas

1. **A demo é o A/B.** Mesma carga, **breaker OFF vs ON**, lado a lado nos dashboards
   reais. OFF = latência/tokens subindo + saldo inventado. ON = breaker abre +
   fallback em ~2s + custo achatado. **Sem o contraste, é tour de tracing.**
2. **Único candidato a "live" controlado do talk** — e mesmo assim **com vídeo de
   fallback aberto numa aba**. O resto pré-aquecido/pré-populado.
3. **Real vs. staged (honestidade firme):**
   - **Real, roda:** a waterfall (Cloud Trace), o código do breaker/budget/cost
     (callbacks ADK que executam), o cost/span, a query de custo-por-tenant (BigQuery),
     a alert policy (Cloud Monitoring).
   - **Semi-live (com rede):** a carga que produz a retry storm (gerador de carga real,
     mas você dispara; latência do modelo varia → vídeo de fallback aberto).
   - **Explicado, NÃO disparado ao vivo:** **429/DSQ** (não dá pra estourar quota
     compartilhada real com segurança) e o **billing export** (tem latência de horas →
     o nível org usa dados **instrumentados por você** no BQ, não o billing real).
4. **`time.sleep(15)` é a dependência degradada** — mock honesto (dizer no palco).
5. **Escopo por caso via `CASE=2`** — o registry ativa `invariants` (C1) **+**
   `resilience` (C2); o C3 fica dormente. Um codebase, runtime limpo por caso.
6. **Provisioned Throughput / Context caching = coadjuvantes** (Slide 7), não depth
   spike. **Verificar na doc pública, Semana 1:** header de spillover do PT, % de
   desconto do context caching, definição de GSU (não inventar verbatim).

---

## 2. A ideia que costura tudo: *um seam, muitos trabalhos*

O mesmo `callback seam` do Caso 1 é o fio arquitetural do talk inteiro. **Um ponto de
costura, papéis diferentes por caso:**

```
        ADK callbacks (registry.CallbackBundle)  ← um seam
                          │
   ┌──────────────┬───────┴────────┬───────────────────┐
   ▼              ▼                ▼                    ▼
[C1: after_tool] [C2: before_tool] [C2: after_model]   [C3: before_tool]
 invariante       CIRCUIT BREAKER   record_cost          enforce_identity
 refund≤charge    injeta no contexto  (cost/span +        (403, próximo caso)
 (Slide 2)        (Slide 6, herói)    budget) (Slide 7)
```

O **breaker semântico é literal no ADK**: um `before_tool_callback` que **retorna um
dict** *curto-circuita a tool* e entrega esse dict ao modelo como se fosse o resultado
da tool. **Retornar `{"status": "unavailable", "instruction": "do not retry; follow
fallback"}` É a injeção no contexto.** Não é metáfora — é o mecanismo do framework.

O **cost/span** reusa o mesmo padrão de `telemetry.set_attribute` do Caso 1
(`eval.invariant.*` → agora `gen_ai.cost.usd`). O **budget por sessão** lê o custo
acumulado em `tool_context.state` (mesmo lugar onde o C1 guarda `invariant_violations`).

**Punchline de palco:** *"É o mesmo hook. No Caso 1 ele provava o dinheiro; aqui ele
protege o dinheiro e mede o dinheiro. Um seam, muitos trabalhos."*

---

## 3. Inventário real dos componentes (nível código)

### 3.1 Superfícies do Google Cloud

| Componente | O que faz na demo (real) | Managed vs. **seu código** | Status |
|---|---|---|---|
| **OpenTelemetry (ADK)** | Substrato: spans `gen_ai.*` de cada model/tool call; base da waterfall e do cost/span | Managed (built-in) | Padrão |
| **Cloud Trace** | **Waterfall** de 1 request: model ~1s vs tool 18s → diagnóstico (Slide 6 beat 1) | Managed | GA |
| **Cloud Monitoring** | Dashboards do **A/B**: latência/token subindo (OFF) vs achatado (ON); **alert policy** de custo/latência | Managed | GA |
| **Provisioned Throughput** | Capacidade reservada (GSU) — a alavanca contra o 429 (Slide 7, coadjuvante) | Managed | GA · *verificar GSU/spillover* |
| **Context caching** | Desconto no prefixo reusado (system prompt/schemas) | Managed | GA · *verificar % desconto* |
| **BigQuery** | Corpus de cost/span → **custo por user/project/org** (Slide 7); alerta por tenant | Managed | GA |
| **Cloud Build** | (herdado do C1) roda eval no PR; aqui pode rodar o teste de resiliência | Managed | GA |
| **Agent Runtime** | Hosting do agente deployado (a "frota"); mesmo substrato OTel | Managed | *verificar GA do runtime-base* |
| **Circuit breaker semântico** | `before_tool_callback`: abre após N falhas, injeta no contexto | **Seu código** | — |
| **Fallback ladder** | Pro → Flash → cache → humano (model routing = seu código) | **Seu código** | — |
| **Cost per span** | Atributo custom no span (token × preço); a plataforma **não** captura custo | **Seu código** | — |
| **Per-session budget** | Callback que soma custo e aborta a sessão descontrolada | **Seu código** | — |
| **Cost attribution (labels)** | Hierarquia user/project/org → chargeback/quotas | **Seu código** (+ Billing→BQ) | — |
| **Load generator** | Reproduz a retry storm (frota = N sessões concorrentes) | **Seu código** | — |

### 3.2 Landmines de honestidade (dizer no palco)
- **Custo NÃO é capturado** pela observabilidade; **token vem agregado** → cost/span é
  instrumentação sua. (Confirmado na análise do C1.)
- **Não há router gerenciado** — o model routing (Flash/Pro) é seu código.
- **Pub/Sub / Cloud Tasks** (desacoplar tool lenta) é sua arquitetura, não primitiva.
- **Gate de CI/CD não é nativo** (herdado do C1) — Cloud Build roda; alerts só notificam.
- **429/DSQ e billing export** não são disparados ao vivo (ver §1.3).

---

## 4. A fronteira crítica: o gêmeo trivial (`max_iterations`)

A armadilha do Caso 2. Um FDE pode reduzir tudo a *"é só pôr `max_iterations` ou um
circuit breaker de biblioteca"*. **Nomear a fronteira no palco:**

- Um breaker de biblioteca **devolve erro** → o modelo **relê e tenta de novo**. Por
  isso o breaker aqui **injeta no contexto** (fala a língua do modelo). Esse é o twist.
- `max_iterations` limita **uma** agente. O problema é uma **frota amplificando** uma
  dependência. Altitude errada.
- **Regra de ferro da demo:** todo beat **abre pelo twist** (o modelo raciocina), não
  pelo mecanismo (breaker existe há 20 anos). Senão vira L200.

---

## 5. Mapa demo → slide (o que roda em cada beat)

| Slide | Beat da demo | Superfície GCP | Real / staged |
|---|---|---|---|
| **5 — The Cascade** | *(sem demo)* — setup conceitual do loop vicioso | — | conceito |
| **6 — Contain the blast** | **1. Waterfall**: abre trace, aponta 18s | Cloud Trace | **real** (pré-populado) |
| | **2. A/B OFF**: dispara carga → latência/token sobem, saldo inventado | Cloud Monitoring + load gen | **semi-live** (+ vídeo) |
| | **3. A/B ON**: breaker abre (log da injeção) → fallback ~2s, custo achata | callbacks + Monitoring | **semi-live** (+ vídeo) |
| **7 — Govern the cost** | **4. cost/span** na trace (o número que a plataforma não dá) | Cloud Trace | **real** |
| | **5. custo por tenant** + alerta dispara | BigQuery + Monitoring alert | **real** (dados instrumentados) |

---

## 6. Experiência de palco (o A/B, corte a corte)

**Setup visual:** VSCode (esquerda) · Cloud Console (direita) · terminal com o gerador
de carga (rodapé). Âncora emocional: **dinheiro + a frota** ("uma dependência lenta,
mil sessões"). Pergunta viva: *"a dependência caiu — quem cai junto?"*

### Corte S6-A — "Which dependency?" *(~30s, real, Cloud Trace)*
1. **Direita (Cloud Trace):** abre uma trace pré-populada do reembolso. Waterfall:
   `root → refund specialist → look_up → issue_refund`. O span do `issue_refund` está
   **vermelho, 18s**; o `call_llm` está verde, ~1s.
2. **Fala-chave:** *"O modelo respondeu em 1 segundo. Esta tool levou 18. Não adivinho —
   a observabilidade me disse ONDE. Vou embrulhar exatamente essa dependência."*

### Corte S6-B — A/B **OFF** *(~45s, semi-live, dashboard + terminal)*
1. **Terminal:** `CASE=2 SCENARIO=slow_payment BREAKER=off python -m scripts.load_test`
   dispara **N sessões concorrentes**.
2. **Direita (Cloud Monitoring):** o gráfico de **tokens/latência sobe** (a retry storm
   real). **VSCode (logs):** o modelo **retenta** — "let me try that again".
3. **O soco:** uma resposta ao usuário aparece com o **saldo inventado** (a alucinação
   como indisponibilidade). *"A dependência não caiu. Mas a agente caiu — e mentiu."*

### Corte S6-C — A/B **ON** (o clímax) *(~60s, semi-live)*
1. **VSCode `callbacks/resilience.py`:** mostra as ~15 linhas do `circuit_breaker`
   (before_tool). Destaca o `return {... "instruction": "do not retry; follow fallback"}`.
   *"Um breaker normal devolveria erro. Eu injeto um FATO no contexto."*
2. **Terminal:** mesma carga, `BREAKER=on`.
3. **Direita (Monitoring):** após N falhas o **breaker abre** — latência/token
   **achatam** (deixa o gráfico respirar). **VSCode (logs):** a linha da **injeção** +
   o modelo seguindo a **fallback ladder** (Flash → cache).
4. **Desfecho:** a resposta ao usuário chega em **~2s**, degradada e **honesta**
   ("estamos com uma instabilidade; um agente humano vai confirmar seu saldo"). *"Caos
   caro virou falha barata e honesta."*

### Corte S7-A — "What did it cost?" *(~30s, real, Cloud Trace)*
1. **Direita (Trace):** clica num span e mostra o atributo **`gen_ai.cost.usd`** — o
   número que **você** instrumentou. *"A plataforma me deu latência e tokens. O custo
   fui eu que calculei, no mesmo hook."*
2. **VSCode:** flash do `record_cost` (after_model) + do `budget_guard` (before_model).

### Corte S7-B — "Who pays?" *(~40s, real, BigQuery + alert)*
1. **Direita (BigQuery):** query de **custo por tenant** sobre a tabela de cost/span.
   Um `project_id` está **10× acima** dos outros.
2. **Monitoring:** a **alert policy** por tenant **dispara** (Slack/email). *"Budget por
   sessão conteve UMA sessão. Isto governa a árvore inteira — qual time está queimando."*
3. **Ponte C3:** *"Resiliente ✓, custo governado ✓. Mas cada chamada mexe com dinheiro e
   PII. Resiliente ≠ seguro."*

**Arco emocional:** diagnóstico (achei) → caos com dinheiro real (OFF) → corte + fallback
honesto (ON) → o número que ninguém te dá (cost/span) → governança da árvore (tenant).
Termina no controle, entregando o C3.

---

## 7. Landmines / honestidade (não errar no palco)
- **Abrir pelo twist, não pelo mecanismo** (§4). O gêmeo trivial é `max_iterations`.
- **Custo não é capturado; token agregado** → cost/span é seu. Não implicar que o
  dashboard mostra custo nativo.
- **429/DSQ e billing export:** explicados, não disparados (§1.3).
- **`time.sleep(15)`** é mock da degradação — dizer.
- **PT/Context caching:** coadjuvantes; verificar verbatim (GSU/spillover/%) Semana 1.
- **Live tem rede:** vídeo de fallback aberto; a variância de latência do modelo pode
  atrapalhar o A/B ao vivo.
- **"Degrade, don't invent"** (não "never hallucinate") — a escada termina em degrau
  determinístico (cache/humano).

---

## 8. Build — o que adicionar ao `agent/` (os concerns do C2 já estão plantados)

O codebase foi construído para isto: `registry.py` traz o **exemplo exato** do bundle,
`faults.py` já tem os cenários do C2, `payment_processor.py` honra `latency_s`/`fail`,
e `refund.py` marca onde o breaker entra. Ativar o C2 é **aditivo** — sem tocar no C1.

### 8.1 Novo módulo `callbacks/resilience.py`
O coração. Grounded nas assinaturas ADK reais e no padrão do `invariants.py`.

```python
"""Case 2 resilience concern: semantic circuit breaker + cost/budget."""
from __future__ import annotations
from typing import Any, Optional
from google.adk.tools import ToolContext
from google.adk.tools.base_tool import BaseTool
from ..config import get_settings
from . import telemetry

# Per-dependency failure counters (process-local; a fleet shares the process
# per instance — good enough for the demo, honest about it).
_failures: dict[str, int] = {}
_OPEN_AFTER = 3  # N failures -> open

def circuit_breaker(
    tool: BaseTool, args: dict[str, Any], tool_context: ToolContext
) -> Optional[dict]:
    """before_tool_callback: if the dependency's circuit is OPEN, short-circuit
    the tool and INJECT a deterministic fact into the context (returning a dict
    hands it to the model as the tool result)."""
    if get_settings().breaker != "on":
        return None
    name = tool.name
    if _failures.get(name, 0) >= _OPEN_AFTER:
        telemetry.set_attribute("resilience.breaker.open", name)
        # THE HERO: this dict becomes the tool result the model reads.
        return {
            "status": "unavailable",
            "dependency": name,
            "instruction": "This tool is unavailable right now. Do NOT retry. "
                           "Follow the fallback: use a cached balance if present, "
                           "otherwise hand off to a human. Never invent a value.",
        }
    return None

def record_outcome(
    tool: BaseTool, args: dict[str, Any],
    tool_context: ToolContext, tool_response: dict,
) -> Optional[dict]:
    """after_tool_callback: feed the breaker. Count hard failures/timeouts."""
    if isinstance(tool_response, dict) and tool_response.get("status") == "error":
        _failures[tool.name] = _failures.get(tool.name, 0) + 1
    else:
        _failures[tool.name] = 0  # half-open: a success closes it
    return None
```

### 8.2 Cost/span + budget (reusa `telemetry` + `state`)
Custo mora no **model call** (é onde vive o token). Use `after_model` + `before_model`.

```python
# in resilience.py (or a cost.py sibling)
_PRICE = {"in": 0.30, "out": 2.50}  # USD / 1M tokens (gemini-2.5-flash; verify)

def record_cost(callback_context, llm_response):
    """after_model_callback: compute cost from usage, put on span + session."""
    usage = getattr(llm_response, "usage_metadata", None)
    if not usage:
        return None
    cost = (usage.prompt_token_count * _PRICE["in"]
            + usage.candidates_token_count * _PRICE["out"]) / 1_000_000
    telemetry.set_attribute("gen_ai.cost.usd", cost)      # the number the platform won't give you
    state = callback_context.state
    state["session_cost_usd"] = state.get("session_cost_usd", 0.0) + cost
    return None

def budget_guard(callback_context, llm_request):
    """before_model_callback: stop a runaway session locally."""
    budget = get_settings().session_budget_usd
    if callback_context.state.get("session_cost_usd", 0.0) >= budget:
        telemetry.set_attribute("resilience.budget.exceeded", True)
        from google.adk.models import LlmResponse   # graceful stop
        return LlmResponse(content=None)  # or a canned "handing off to a human" content
    return None
```
> ⚠️ **Verificar assinaturas exatas** de `before/after_model_callback` e do
> `LlmResponse`/`usage_metadata` na versão do ADK instalada, Semana 1. O padrão
> (retornar objeto curto-circuita; `state` persiste) está correto; os nomes de campo
> podem variar.

### 8.3 Registrar o bundle (a linha que ativa o C2 — igual o comentário do `registry.py`)
```python
# em callbacks/registry.py (ou num resilience module importado por ele)
register(CallbackBundle(
    name="resilience", case=2,
    before_tool=[circuit_breaker],
    after_tool=[record_outcome],
    before_model=[budget_guard],
    after_model=[record_cost],
))
```
Com `CASE=2`, `assemble()` já monta esses callbacks no chain junto do invariante do C1.
Com `CASE=1`, ficam dormentes. **Zero mudança no C1.**

### 8.4 Config novo (`config.py` → `Settings`)
Adicionar campos lidos do env (mesmo padrão `_env_str`/`_env_bool`):
```python
breaker: str            # "on" | "off"        (BREAKER, default "off")
session_budget_usd: float  # (SESSION_BUDGET_USD, default 0.50)
```

### 8.5 Cenários de falha (já existem — talvez 1 novo)
`faults.py` já tem `slow_payment` (latency 15s), `payment_declined` (fail), e
`fraud_unavailable`. Para a retry storm mais nítida, opcional:
```python
"retry_storm": {"issue_refund": {"fail": "timeout", "latency_s": 8.0}},
```

### 8.6 Fallback ladder (model routing = seu código)
No `refund_agent`/root: ao ver `status == "unavailable"` no resultado da tool, o prompt
instrui a **degradar** — tentar cache em `tool_context.state["last_refund"]`, senão
handoff. Opcional: rota Pro→Flash trocando `model` por dificuldade (seu código; **não há
router gerenciado**). Manter simples: a injeção do breaker já guia o modelo.

### 8.7 Gerador de carga `scripts/load_test.py` (a "frota")
```python
# asyncio: dispara N sessões concorrentes contra o agente (local adk api_server
# ou o Agent Runtime deployado), sob SCENARIO/BREAKER do env. Coleta latência p50/p95
# e tokens totais -> imprime a tabela do A/B. Real concurrency, você dispara.
```
Recomendação: `hey`/`locust` contra `adk api_server`, ou asyncio + o runner do ADK.
**Usar Flash + carga pequena** (a carga real gasta tokens reais = $).

### 8.8 BigQuery — custo por tenant (estende o padrão do C1)
O C1 já tem `evals/bigquery_scale.py` + `queries/*.sql`. Adicionar:
- tabela `cost_spans(ts, session_id, user_id, project_id, org_id, tool, cost_usd)`
  populada a partir dos atributos `gen_ai.cost.usd` (sink do Logging → BQ, ou dump do
  harness).
- `queries/cost_by_tenant.sql`: `SUM(cost_usd) GROUP BY project_id ORDER BY ... DESC`
  (um tenant 10× acima).
- alert policy no Cloud Monitoring sobre a métrica de custo por label.

### 8.9 Dashboards + alert (Cloud Monitoring)
- Dashboard do A/B: latência p95 e tokens/min (duas séries: OFF vs ON).
- Alert policy: custo por tenant acima do threshold → notify (Slack/email). **Só
  notifica** (mesma honestidade do C1: alerta não é gate).

### 8.10 Checklist de build
- [ ] `callbacks/resilience.py` (breaker + record_outcome + record_cost + budget_guard)
- [ ] `register(CallbackBundle(name="resilience", case=2, ...))`
- [ ] `config.py`: `breaker`, `session_budget_usd`
- [ ] `faults.py`: (opcional) `retry_storm`
- [ ] fallback no prompt do refund/root (degrade, don't invent)
- [ ] `scripts/load_test.py` (a frota + tabela A/B)
- [ ] BQ `cost_spans` + `queries/cost_by_tenant.sql`
- [ ] Cloud Monitoring dashboard (A/B) + alert policy (tenant)
- [ ] testes: breaker abre após N falhas; cost acumula; budget aborta; `CASE=1` dorme
- [ ] validar `before/after_model_callback` + `usage_metadata` na versão do ADK
- [ ] pré-popular: 1 trace com 18s + `gen_ai.cost.usd`; BQ com tenants; vídeo de fallback

---

## Referências
- Narrativa/slides do Caso 2: `docs/case-2-fundamentos.md`.
- Padrão de demo (Caso 1): `demos/case-1-demos.md`.
- Código-base: `agent/` — `callbacks/registry.py` (extensão), `callbacks/invariants.py`
  (padrão do seam), `callbacks/telemetry.py` (set_attribute), `backends/faults.py`
  (cenários C2), `backends/payment_processor.py` (latency/fail), `config.py` (Settings).
- Landmines de plataforma (custo/router/gate): `en/cases/case-2.md §9` + `blueprint`.
