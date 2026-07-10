# Runbook — Caso 1 (pré-run + dia da apresentação)

> **Para que serve:** rodar cada parte da demo **1 dia antes**, deixar o ambiente
> "quente" (endpoints acordados, abas do Console populadas com resultados reais) e,
> no dia, **só mostrar os resultados** — sem gerar nada ao vivo no caminho crítico.
>
> **Estratégia (decidida):** o payoff do S3 é **pré-rodado ao vivo**. Fala de palco:
> *"this is a real environment I ran shortly before we started"* — nunca "gerando
> agora" para o caso pontuado. A rede de segurança é o **gate offline**
> (determinístico, sempre verde/vermelho igual).
>
> **Como usar com o Claude Code:** cada seção tem `Comando`, `O que esperar` (o
> "verde" de sucesso) e `Se falhar`. Peça ao Claude: *"roda a Seção 3 do runbook e
> confere o esperado"*. Ele roda o bloco e compara com o esperado.
>
> **Regra de ouro:** **sempre rodar de dentro de `agent/`** (o `uv` gerencia o venv).
> Toda seção assume `cd .../l400-managing-production-agents/agent`.

Complementa `demos/case-1-demos.md` (o *quê/como* da demo) e
`demos/case-1-live-implementation-plan.md` (plano por fases). Status de validação de
cada parte está marcado em cada seção.

---

## 0. Pré-flight (5 min, roda primeiro) — checklist de ambiente

**Objetivo:** garantir creds, projeto e `.env` antes de qualquer coisa.

```bash
cd ~/l400-managing-production-agents/agent

# 1) ADC (via metadata server da VM — não precisa de login interativo)
uv run python -c "import google.auth; _,p=google.auth.default(); print('ADC ok, project:', p)"

# 2) Conferir as chaves do .env que a demo usa
grep -E "^(MODEL|GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_LOCATION|CASE|SCENARIO|INVARIANT_ENFORCEMENT)=" .env

# 3) Baseline offline verde (rede de segurança + valida o código)
uv run pytest -q
```

**O que esperar:**
- `ADC ok, project: YOUR_PROJECT_ID`
- `.env`: `MODEL=gemini-3.5-flash`, `GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID`,
  `GOOGLE_CLOUD_LOCATION=us-central1`, `CASE=1`, `SCENARIO=refund_over_charge`,
  `INVARIANT_ENFORCEMENT=observe`.
- `40 passed`.

**Se falhar:** ver Seção 9 (Troubleshooting). Se o ADC falhar, a VM perdeu o escopo
`cloud-platform` — nada roda ao vivo até resolver.

---

## 1. Warm-up dos endpoints (2 min) — aquecer o modelo global

**Objetivo:** a primeira chamada ao `gemini-3.5-flash@global` é mais lenta (cold).
Dispara uma execução do agente **sem exportar nada** só para acordar o endpoint.

```bash
uv run python -m scripts.live_drive --no-cloud --no-verify
```

**O que esperar:** o agente roda o fluxo de refund e imprime a trajetória
(`look_up_customer → transfer → fraud_check → issue_refund`) + a seam do invariante
marcando o over-refund. Sem erro de rede/modelo.

**Se falhar:** modelo global inacessível → conferir `MODEL=gemini-3.5-flash` e a
região `global` (o split está em `financial_support/model.py`). Ver Seção 9.

---

## 2. S2 — Observability (trace + topology) · **LIVE ok** ✅ (validado Fase 1)

**Slide/beat:** S2 — "a trace é real e é *a mesma* que o eval lê".
**Quando:** pode ser ao vivo no dia (rápido) OU pré-rodado. Recomendo pré-rodar para
já ter a waterfall aberta no Console.

```bash
# Dirige o agente REAL e EXPORTA o trace para o Cloud Trace (idêntico ao adk web --otel_to_cloud)
uv run python -m scripts.live_drive --scenario refund_over_charge
```

**O que esperar:**
- Imprime a hierarquia de spans e um **trace id**.
- Verificação por Cloud Trace v1 confirma o trace (lag ~1–2 min).
- A seam literal aparece no span do `issue_refund`: labels
  `eval.invariant.refund_within_charge=false / violated / detail`.

**Onde mostrar no Console:** Cloud Trace → o trace pelo id → **waterfall**
`invocation → invoke_agent → call_llm → generate_content (gemini-3.5-flash) →
execute_tool {look_up_customer, transfer_to_agent, fraud_check, issue_refund}`.
Depois **Agent Topology** (Vertex AI, **Preview** — declarar no palco).

**Aresta A2A (opcional, dá o fraud-check como serviço externo na Topology):** precisa
de 2 terminais.
```bash
# terminal 1: sobe o agente de fraude A2A (porta 8001)
uv run python -m fraud_check_a2a
# terminal 2: dirige com o fraud externo ligado
USE_A2A_FRAUD=true uv run python -m scripts.live_drive --scenario refund_over_charge
```

**Fala de palco:** Trace/Log/Monitoring são **GA**; **Topology é Preview**.
**Se falhar:** o trace não aparece → é lag (espere 2 min) ou o export não montou
(rode sem `--no-cloud`). Fallback: mostrar uma trace pré-gravada.

---

## 3. S3 — Evaluation: "o placar verde mente" · **LIVE ok** ✅ (validado 6/6)

> **Este é o núcleo. PRÉ-RODAR no dia anterior e mostrar a aba Evaluation no dia.**

**Slide/beat:** S3 (placar sobe verde, "ship it?") + S4-A (o dinheiro: invariante
vermelho, juiz verde).

```bash
EVAL_LIVE_CONFIRM=1 uv run python -m evals.run_offline --live
```

**O que esperar (scoreboard — confira valor por valor):**
```
=== Evaluation summary (live) ===
  refund_within_charge      mean=0.50   valid=2 err=0     <- o caso do dinheiro dá 0.0
  refund_requires_lookup    mean=1.00   valid=2 err=0
  tone_check                mean=1.00   valid=2 err=0     <- o juiz DEIXA passar
  final_response_quality_v1 mean=1.00   pass_rate=100%    <- managed REAL tb deixa passar
```
> **HALLUCINATION foi removida do set live de propósito** (revisão Fase 2): é um
> autorater não-determinístico (0.76–0.92) que marca até o caso *correto* (dispute
> ~0.67) e cujo pass_rate oscila (0%/50%). Isso quebraria o "tudo verde → ship it?"
> e embaralharia a mensagem. O "cinza" fica só na `final_response_quality` (estável
> 1.00). NÃO reintroduza sem querer.

Por caso (em `/tmp/eval_result.json`):
- `happy_refund` → `refund_within_charge: 0.0 | refund=500.0 charge=50.0 -> OVER-REFUND`
- `happy_dispute` → `refund_within_charge: 1.0 | no refund issued`

**Onde mostrar no Console:** Vertex AI → **Evaluation** → a última run. É a superfície
do palco (NÃO o `.show()`, que é renderer de notebook).

**Confirmar consistência antes do dia (opcional, recomendado):** rode a checagem de
flakiness — reproduz o over-refund N vezes e mostra a trajetória.
```bash
EVAL_LIVE_CONFIRM=1 uv run python -m scripts.flaky_check 6
# esperado: "MONEY BUG reproduced: 6/6 runs", trajetória idêntica em todas
```

**Fronteira EDD (dizer no palco):** a plataforma gera os *inputs*
(`generate_conversation_scenarios`); o *critério de certo* (o invariante) veio do
**contrato**. O input pontuado é **determinístico e derivado do contrato** — não é o
que o simulador gerou (isso é mostrado, mas desacoplado do placar).

**Honestidade (não errar no palco):**
- O over-refund é um **fault injetado** (`SCENARIO=refund_over_charge`, o processor
  paga a mais). Dizer *"injetei uma falha onde o processador paga a mais"* — nunca
  "olha o que o agente fez". O agente pede $50 certinho; o **mundo** quebra.
- Liderar o "green lies" com a **`final_response_quality` (managed da Google)**
  passando, não só com o juiz de tom (que só avalia tom — evita o strawman).

**Se falhar:**
- Invariante deu `1.00` (não pegou) → o fault não aplicou. Quase sempre é cache de
  settings (Seção 9). O `live.py` já faz `reload_settings()`; se persistir, confira
  `SCENARIO=refund_over_charge` no `.env`.
- `tone_check err=2` → `judge_model` precisa de resource name completo (já corrigido
  em `_judge_model_resource_name`). Ver Seção 9.
- Qualquer quebra da API Preview → **fallback: gate offline** (Seção 5).

---

## 4. S4 — Escala + sentinela (BigQuery + Online Monitor) · **pré-semeado**

**Slide/beat:** S4 — "escala não cabe numa trace; cabe no BigQuery" + a sentinela
(online monitor + alerta).

### 4a. BigQuery — corpus de traces pontuados (tendência por semana)
> ⚠️ **Ainda não rodado com creds** — a **primeira** execução cria o dataset/tabela e
> semeia. Reserve tempo para depurar. Inspeção offline não precisa de creds.

```bash
# (sem creds) inspecionar o corpus sintético e a agregação semanal
uv run python -m evals.bigquery_scale            # tabela de taxa de falha por semana
uv run python -m evals.bigquery_scale --dump     # linhas LogEntry cru (NDJSON)

# (com creds) semear a tabela real e depois conferir
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --seed
EVAL_LIVE_CONFIRM=1 uv run python -m evals.bigquery_scale --live
```

**O que esperar:** offline, uma tabela com a taxa de falha do invariante subindo da
semana ~7 à ~12 (o drift). Com creds, `--seed` cria `agent_eval.agent_spans`
(particionada) e `--live` roda a query real e imprime as mesmas semanas.

**Onde mostrar:** BigQuery → dataset `agent_eval` → a query de tendência
(`evals/queries/invariant_trend.sql`).
**Ponte C3 (1 frase):** esse mesmo BQ ganha Row-Level Security no Caso 3.

### 4b. Online Monitor — a sentinela (semeado)
```bash
uv run python -m evals.online_monitor
```
**O que esperar:** janela deslizante + **"Alert fired at t=42"** (o mesmo invariante
que barrou o merge agora vigia produção). É uma **view semeada** — framing honesto:
*"stream semeado de um ambiente real"*. Cloud Monitoring alert policy é GA.

**Se falhar (4a com creds):** schema Logging→BQ ≠ o que a query assume → o schema já
foi reconciliado (`evals/queries/agent_spans_schema.json`); se der erro de schema,
recriar a tabela pelo `--seed`. Ver `case-1-live-implementation-plan.md §Fase 4`.

---

## 5. Gate offline (rede de segurança / fallback do S3) · **sempre verde** ✅

**Objetivo:** o artefato determinístico. Se a API Preview vacilar no dia, é **este**
que você mostra — mesma mensagem, zero dependência de rede.

```bash
uv run python -m evals.run_offline        # sai !=0 (gate BLOCK) com clusters
echo "exit=$?"                            # esperado: exit=1
```

**O que esperar:** 5 casos, 3 falham, o report imprime o gate BLOCK e os **Failure
Clusters** (inclui "Incorrect Tool Selection" do beat B). `exit=1`.

> **Nota S4/clusters:** o `generate_loss_clusters` **live** retorna "no response"
> (Preview, experimental). **Use os clusters do gate offline** (aqui) para o beat de
> Failure Clusters — funcionam de verdade.

---

## 6. (Opcional) Agent Runtime deploy — a "produção" · **não validado ainda** ⚠️

**Slide/beat:** substrato do S4 ("a produção que o S4 aponta"). Introdução/menção, não
métricas-grátis.
> ⚠️ **Primeira execução com creds — cold start lento. NUNCA demonstrar o deploy ao
> vivo.** Pré-deployar dias antes e mostrar o Console.

```bash
GOOGLE_CLOUD_STAGING_BUCKET=gs://YOUR_PROJECT_ID-agent-staging \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```

**O que esperar:** cria o `ReasoningEngine` (Agent Runtime); traces fluindo para o
Cloud Trace. **Honestidade:** o Runtime dá as superfícies de observabilidade (mesmo
OTel→Trace), **não** dá qualidade nem custo de graça — os invariantes são SUA
instrumentação (o ponto do EDD).

---

## 7. (Opcional) Cloud Build gate — o barrador do merge · **não validado ainda** ⚠️

**Slide/beat:** S3/S4 — o gate de CI/CD (não é nativo; quem barra é o Cloud Build).

```bash
gcloud builds submit --config deploy/cloudbuild.yaml
```

**O que esperar:** o build roda `run_offline`; sai `!=0` → **build vermelho** → merge
barrado. **Honestidade:** o gate **não é nativo** — Quality Alerts só notificam.

---

## 8. Dia da apresentação — sequência e "o que mostrar"

Ordem de prioridade (se o tempo apertar): **S4-A (o dinheiro) > trace S2 > eval S3 >
BQ/monitor**.

1. **Pré-flight rápido** (Seção 0, itens 1–2) + **warm-up** (Seção 1). ~5 min antes.
2. **S2:** abrir a waterfall + Topology já populadas do pré-run (Seção 2).
3. **S3/S4-A:** abrir a aba **Evaluation** com o scoreboard do pré-run (Seção 3).
   Contar a história: verde ingênuo → o um-dois (invariante vermelho no dinheiro,
   juiz/managed verdes).
4. **S4-B:** o caso silencioso + **Failure Clusters** — usar o **gate offline**
   (Seção 5), que tem os clusters de verdade.
5. **S4-escala:** BigQuery (tendência por semana) + Online Monitor (Seção 4).
6. **Fechar o loop:** o caso reprovado vira teste; "The Green Score — EARNED".

**O que NÃO fazer ao vivo:** deploy do Agent Runtime; gerar o eval no caminho crítico
("gerando agora"). Tudo pontuado é pré-rodado.

---

## 9. Troubleshooting — gotchas conhecidos (todos já resolvidos no código)

| Sintoma | Causa | Ação |
|---|---|---|
| Invariante `1.00` ao vivo (não pega o dinheiro) | (a) prompt pedindo >$200 tropeça no fraud review; (b) `SCENARIO` cacheado como `healthy` antes do `.env` | (a) usar prompt em-política ($50) — já é o default; (b) `reload_settings()` já está no `live.py`; confira `SCENARIO=refund_over_charge` no `.env` |
| `tone_check err=2` — "Invalid autorater model resource name" | `judge_model` como nome nu | já corrigido: `_judge_model_resource_name` monta `projects/.../publishers/google/models/gemini-2.5-flash` |
| 404 no modelo / "only available in global" | Gemini 3.x só resolve no endpoint `global` | split já feito em `model.py`; `allow_cross_region_model=True` no eval. Não mudar |
| `result.model_dump()` quebra (pandas) | `evaluation_dataset` carrega DataFrame | já usa `exclude={"evaluation_dataset"}` |
| `generate_loss_clusters` "no response" ao vivo | Preview experimental | usar clusters do **gate offline** (Seção 5) |
| Um caso vira `num_cases_error` | SDK `parts[0]["text"]` quebra se o turno termina sem texto | é fail-loud (visível, não verde falso); re-rodar; em 6/6 não ocorreu com o prompt em-política |
| `SERVICE_DISABLED` em projeto novo | Service Usage / Resource Manager off | habilitar as 2 APIs pelo Console (conta Owner), 1x — ver memória `gcp-live-environment` |
| Nada roda / ADC falha | VM perdeu escopo `cloud-platform` | recriar/reautenticar a VM; sem ADC nada ao vivo funciona |

**Diagnósticos reutilizáveis** (se algo ao vivo surpreender):
- `EVAL_LIVE_CONFIRM=1 uv run python -m scripts.infer_probe` — dumpa quais tools o
  agente chamou por prompt (revelou as 2 causas-raiz do invariante 1.00).
- `EVAL_LIVE_CONFIRM=1 uv run python -m scripts.eval_probe` — dumpa o `instance` que o
  metric recebe (útil se o schema da plataforma mudar).
- `EVAL_LIVE_CONFIRM=1 uv run python -m scripts.flaky_check N` — mede reprodutibilidade.

---

## Apêndice — valores do ambiente (Fase 0)

- **Projeto:** `YOUR_PROJECT_ID` (número `YOUR_PROJECT_NUMBER`)
- **Região:** `us-central1` (plataforma) · **`global`** (modelo Gemini 3.x)
- **Modelo:** `gemini-3.5-flash`
- **Bucket de staging:** `gs://YOUR_PROJECT_ID-agent-staging`
- **Identidade runtime:** SA do Compute da VM (`...-compute@developer.gserviceaccount.com`),
  `roles/editor` — cobre tudo do Caso 1
- **ADC:** metadata server (escopo `cloud-platform`) — sem arquivo de credencial

Status de validação: Fase 0 ✅ · Fase 1 (S2) ✅ · Fase 2 (S3) ✅ (payoff 6/6) ·
Fase 3 (Runtime) / 4 (BQ seed) / 5 (Cloud Build) = **primeira execução com creds
pendente** (reserve tempo para depurar no pré-run).
