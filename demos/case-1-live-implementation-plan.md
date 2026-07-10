# Caso 1 — Plano de implementação da demo pré-rodada ao vivo

> **Fonte da verdade para construir o caminho GCP do Caso 1.** Escrito 2026-07-09
> para ser retomado numa sessão nova (depois do `/clear`). Complementa
> `demos/case-1-demos.md` (o *quê/como* da demo) com o *plano de execução* contra
> um projeto Google Cloud real.
>
> **Como usar numa sessão nova:** leia este doc + `demos/case-1-demos.md` +
> `agent/README.md`. O estado do código está na seção 6. Comece pela seção 5
> (tarefas sem-creds) ou pela Fase 0 (provisionamento) conforme o que estiver pronto.

---

## 1. Decisões travadas (não reabrir)

- **Formato do S4:** **ambiente pré-rodado ao vivo** (não gravado). O apresentador
  roda contra um projeto GCP real preparado antes do talk. Fala de palco:
  *"this is a real environment I ran just before we started"* — nunca "ao vivo agora"
  para os passos pré-rodados. (Usuário pode voltar atrás e gravar se não ficar
  confortável — não muda o build.)
- **Escopo do S4 = HÍBRIDO:**
  - **LIVE de verdade:** deploy no Agent Runtime, S2 (trace + topology), S3 (eval).
  - **PRÉ-SEMEADO:** Online Monitor (janelas de ~10min) e BigQuery (meses de drift)
    — impossível gerar ao vivo; semeado com histórico numa tabela/stream real.
- **Produtos no escopo do Caso 1 (usar SÓ estes):**
  **Observability** (S2/S4) · **Evaluation** (S3/S4) · **Agent Runtime** (substrato
  de "produção").
- **Fora do Caso 1 (deixar para C2/C3):** **Model Armor** e **Agent Gateway** são do
  eixo *govern* → **Caso 3** (borda de identidade, SPIFFE/mTLS/IAP/IAM). Entram lá
  como **menção**, não beat — Model Armor é probabilístico e enfraqueceria o clímax
  determinístico do C3 (IAM+RLS→403). **Não abrir na demo do C1.** Foco.

---

## 2. Mapa produto → onde vive na demo (só os 3 do C1)

| Produto | Slide | Live vs. semeado | GA/Preview | Código |
|---|---|---|---|---|
| **Observability** — Cloud Trace + Agent Topology | S2 | **live** | Trace/Log/Monitoring **GA**; Topology **Preview** | `financial_support/observability/`, `deploy/opentelemetry.env` |
| **Evaluation** — Gen AI Evaluation Service (`client.evals`) | S3 | **live** | **Preview** | `evals/live.py`, `evals/metrics.py` |
| **Evaluation** — Online Monitor + Cloud Monitoring alert | S4 | **pré-semeado** | Online Monitor **Preview**; Monitoring **GA** | `evals/online_monitor.py` |
| **Evaluation** — Failure Clusters (`generate_loss_clusters`) | S4 | live (via S3) | **Preview** | `evals/clusters.py` (offline), `evals/live.py` (live) |
| **BigQuery** — corpus de traces pontuados + trend | S4 | **pré-semeado** | **GA** | `evals/bigquery_scale.py`, `evals/queries/invariant_trend.sql` |
| **Agent Runtime** — deploy da "produção" (`ReasoningEngine`) | substrato S4 | **live** | core **GA**; Quality/Identity/Gateway **Preview** | `deploy/agent_engine.py` |
| **Cloud Build** — o gate de merge (não nativo) | S3/S4 | live | **GA** | `deploy/cloudbuild.yaml` |

---

## 3. Fase 0 — Provisionamento (USUÁRIO faz antes)

```bash
# 1) Projeto + região + billing (assume projeto já criado)
export GOOGLE_CLOUD_PROJECT=<seu-projeto>
export GOOGLE_CLOUD_LOCATION=us-central1

# 2) Habilitar APIs
gcloud services enable \
  aiplatform.googleapis.com \
  cloudtrace.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  bigquery.googleapis.com \
  cloudbuild.googleapis.com

# 3) Credenciais (ADC) — rodar interativamente na sessão com `! gcloud ...`
gcloud auth application-default login

# 4) Staging bucket para o Agent Runtime
gsutil mb -l $GOOGLE_CLOUD_LOCATION gs://<seu-bucket>

# 5) Confirmar acesso a AMBOS os modelos no Vertex:
#    - gemini-3.5-flash @ global  -> o AGENTE (run_inference; global-only, por isso
#      allow_cross_region_model=True no eval que roda em us-central1)
#    - gemini-2.5-flash @ us-central1 -> o JUIZ (LLMMetric autorater)

# 6) Preencher agent/.env a partir do .env.example
```

**Checklist de saída da Fase 0:** ADC ok · APIs on · bucket criado · **ambos** os
modelos acessíveis (agente `gemini-3.5-flash@global` + juiz `gemini-2.5-flash@us-central1`)
· `agent/.env` preenchido.

---

## 4. Fases na nuvem (bloqueadas na Fase 0)

### Fase 1 — S2 live (Observability) · precisa creds
```bash
uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud
# (opcional, para a aresta A2A na Topology — 2 terminais)
uv run python -m fraud_check_a2a                  # terminal 1 (porta 8001)
USE_A2A_FRAUD=true uv run --env-file deploy/opentelemetry.env adk web --otel_to_cloud
```
- Dirigir o fluxo de refund → confirmar **waterfall no Cloud Trace**
  (`root → refund specialist → look_up_customer → issue_refund → reply`).
- Abrir **Agent Topology** → refund specialist + sub-agentes + **aresta A2A** do fraud-check.
- **Validar:** os atributos de span que o eval lê aparecem de fato (ver
  `demos/case-1-demos.md §3.3`, "Atributos de span obrigatórios").
- **Palco:** declarar Topology = Preview.

### Fase 2 — S3 live eval (Evaluation Preview) · ✅ FEITA (2026-07-10)
```bash
EVAL_LIVE_CONFIRM=1 uv run python -m evals.run_offline --live
```
- **Payoff PROVADO ao vivo.** Scoreboard real (2 casos determinísticos):
  `refund_within_charge mean=0.50` (dispute verde, refund **0.0 → OVER-REFUND
  $500 sobre $50**) enquanto `tone_check=1.00` e `safety=1.00`
  passam. "The green score lies", determinístico e repetível.
- **Decisão-chave (desacoplar do simulador):** o simulador de usuário é
  não-determinístico e às vezes nunca dispara o over-refund → invariante ficava
  vacuamente 1.00. Agora o `run_inference` roda sobre um **dataset determinístico
  EDD** (single-turn, SEM `user_simulator_config`) — o bug do dinheiro dispara em
  TODA rodada. `generate_conversation_scenarios` continua no palco (mostrar
  "plataforma gera inputs"), mas **desacoplado** do caminho pontuado.
- **Gotcha #1 — o pedido tem que ser em-política:** um prompt "give me $500"
  tropeça no `fraud_check` do próprio agente (review em amount≥200) → nunca emite
  refund. O caso pontuado pede **$50** (em-política) e o **fault** (`over_charge_
  multiplier`) é quem over-paga. O bug está no *mundo*, não no pedido — e é esse o
  ponto. Guardado por `tests/test_live_metrics.py::test_live_inference_prompts_are_in_policy`.
- **Gotcha #2 — cache de settings antes do `.env`:** `import evals.run_offline`
  toca `get_settings()` e cacheia `SCENARIO=healthy` (shell) ANTES do `load_dotenv`
  → o fault não aplicava. Fix: `reload_settings()` no `live.py` após o load.
  Guardado por `...::test_over_charge_fault_triggers_money_bug_end_to_end`.
- **Gotcha #3 — juiz (`LLMMetric`):** `judge_model` exige **resource name
  completo** (`projects/…/locations/…/publishers/google/models/gemini-2.5-flash`);
  nome nu dá 400 "Invalid autorater model resource name". Ver
  `evals/metrics.py::_judge_model_resource_name`.
- **Managed single-turn** — cinza = **`SAFETY`** (estável 1.00/1.00/1.00 num probe de
  3 evaluates; `scripts/managed_probe.py`), deixa o bug passar = evidência honesta do
  "green lies", e o beat fica limpo (*safe ≠ correto*). **`FINAL_RESPONSE_QUALITY` E
  `HALLUCINATION` foram REMOVIDAS** (revisão Fase 2): autoraters não-determinísticos
  (FRQ 0.33/0.67/1.00, dinga o caso *correto* por não narrar transfer; HALLUCINATION
  0.76–0.92) → oscilam o pass_rate e quebrariam o "tudo verde → ship it?". Cinza
  estável > cinza que treme. (`TOOL_USE_QUALITY` quase serviu mas deu 0.80 numa rodada.)
- **loss_clusters:** ainda "no response" com 2 casos — experimental, é beat de S4;
  best-effort, não bloqueia.
- **Fallback:** o **gate offline** (`run_offline` sem `--live`) continua o artefato
  determinístico/verde se a API Preview quebrar no dia. 46 testes verdes.
- **Fronteira EDD (dizer no palco):** a plataforma gera os *inputs*; o *critério de
  certo* (o invariante) veio do contrato. Determinismo deixa isso ainda mais nítido:
  o input adversarial também sai do contrato. Ver `demos/case-1-demos.md §4`.

### Fase 3 — Agent Runtime deploy (a "produção") · ✅ FEITA (2026-07-10)
```bash
# .env NÃO é auto-carregado por este script — passar as vars no comando:
GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID GOOGLE_CLOUD_LOCATION=us-central1 \
  GOOGLE_CLOUD_STAGING_BUCKET=gs://YOUR_PROJECT_ID-agent-staging \
  GOOGLE_GENAI_USE_VERTEXAI=true MODEL=gemini-3.5-flash CASE=1 \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```
- **PROVADO ao vivo:** `ReasoningEngine` deployado e **servindo tráfego** (via
  `eng.stream_query`), com a trajetória multi-agente real em produção. **Traces do
  agente deployado aparecem no Cloud Trace de PROJETO E na aba Traces escopada ao
  agente** (Trace Explorer / `ListTraces` / console tab), com a seam EDD:
  `invoke_workflow → invoke_agent → call_llm → execute_tool {look_up_customer,
  transfer_to_agent, fraud_check, issue_refund} → refund_specialist`, labels
  `eval.invariant.refund_within_charge / refund_after_fraud_decision /
  read_targets_session_customer`.
- **Superfície de palco:** a aba Traces do agente OU o Trace Explorer de projeto (ambos
  têm a seam; ver #5). **NÃO demonstrar o deploy ao vivo** (cold start) — pré-deployar e
  mostrar o Console.

**5 fixes reais (em `deploy/agent_engine.py` + `pyproject.toml`):**
1. **`cloudpickle` faltando** → extra `agent-engines`:
   `google-cloud-aiplatform[evaluation,agent-engines]` no `pyproject.toml` (+`uv sync`).
2. **`No module named 'financial_support'`** no startup → `extra_packages=["financial_support"]`
   no `create()` (o pickle referencia código que não era enviado).
3. **`enable_tracing=True` deprecado** → `AdkApp(agent=...)` + env vars documentadas:
   `GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY=true`,
   `OTEL_SEMCONV_STABILITY_OPT_IN=gen_ai_latest_experimental`,
   `OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=EVENT_ONLY` (NÃO `true`),
   `ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`.
4. **Só as 3 env vars documentadas de tracing são necessárias** (ver #3). NÃO setar
   `OTEL_RESOURCE_ATTRIBUTES=gcp.project_id` — é desnecessário (o template resolve
   número→id do projeto via Resource Manager no `set_up`, então `gcp.project_id` sai certo)
   e foi um workaround para um `400` cuja causa real era outra (ver #5).
5. **CAUSA RAIZ da aba vazia (RESOLVIDO — não era Preview):** era o NOSSO
   `financial_support/observability/otel.py::init_telemetry()` chamado **no import** do
   agente (`agent.py`), que fazia `set_tracer_provider()` com um Resource pobre
   (`service.name="financial-support-agent"`, sem `cloud.resource_id`). O import roda
   ANTES do `set_up()` do runtime → nosso provider ganhava a corrida; o template então só
   adicionava o exporter ao provider errado. Spans exportavam com `service.name=display_name`
   → a aba (que filtra por `service.name=<engine id>`/`cloud.resource_id`) ficava vazia.
   **Fix:** removido o `init_telemetry()` automático no import + guard de runtime gerenciado
   em `otel.py`. **Provado ao vivo:** pós-fix os spans têm `service.name=<engine id>` +
   `cloud.resource_id=//aiplatform.../reasoningEngines/<id>` e a aba popula.

**Superfície de palco:** com a aba do agente FUNCIONANDO, dá pra mostrar a aba Traces
escopada ao agente OU o Trace Explorer de projeto (ambos têm a seam). Local do S2 continua
como fallback (decisão travada).

- **Verdades-base do probe (custom engine que dumpa `os.environ`+Resource; já deletado):**
  `GOOGLE_CLOUD_AGENT_ENGINE_ID` **está presente no `set_up`** (só `None` no `__init__` —
  a teoria "não populado a tempo" era falsa); plataforma **não injeta `OTEL_SERVICE_NAME`**;
  `OTEL_RESOURCE_ATTRIBUTES=gcp.project_id` **não** sobrescreve `service.name`. Diagnóstico
  do 400: replicar `google/adk/telemetry/google_cloud.py::_get_gcp_span_exporter` + POST à
  mão (`AuthorizedSession`+`encode_spans().SerializeToString()`).
- **Honestidade:** Runtime dá as superfícies de observabilidade (mesmo OTel→Trace),
  **não** dá métricas de qualidade nem custo de graça. Os invariantes são SUA
  instrumentação — é o ponto do EDD.

### Fase 4 — S4 pré-semeado (híbrido) · construção + creds
- **BigQuery (o item de build real):** — **✅ schema + seeder RECONCILIADOS sem creds (2026-07-09).**
  1. ~~Reconciliar o schema~~ **FEITO.** Raiz descoberta: spans OTel vão pro Cloud
     Trace, que **não tem export nativo p/ BQ** → caminho GA = **Cloud Logging → BQ
     sink** de uma **log entry estruturada** espelhando o verdict. A query foi
     reescrita p/ o schema **LogEntry/jsonPayload** real (`jsonPayload.invariant_passed`,
     `jsonPayload.tool_name`), não mais o atributo pontuado inexistente. Schema da
     tabela em `evals/queries/agent_spans_schema.json` (validado contra o SDK real do
     BQ, `SchemaField.from_api_repr`).
  2. ~~Escrever o seeder~~ **FEITO.** `bigquery_scale.py` ganhou `synthetic_rows()`
     (corpus expandido em linhas LogEntry, semanas alinhadas ao domingo p/ casar com
     `DATE_TRUNC(..,WEEK)`), `weekly_from_rows()` (re-agrega igual à SQL) e
     `seed_bigquery()` (cria dataset+tabela particionada e faz `load_table_from_json`,
     guardado). +7 testes (34 verdes à época; 46 hoje) provam que o corpus re-agrega no
     `weekly_failure_rate()`. Inspeção offline: `python -m evals.bigquery_scale --dump`.
  3. **Com creds (falta):** criar o **sink Cloud Logging → BigQuery** de verdade
     (ou usar o seeder), **semear** e validar. Só o passo que precisa de GCP.
  4. Semear: `EVAL_LIVE_CONFIRM=1 python -m evals.bigquery_scale --seed` (anchor=hoje);
     conferir: `EVAL_LIVE_CONFIRM=1 python -m evals.bigquery_scale --live`.
- **Online Monitor:** manter `evals/online_monitor.py` como a view **semeada** (janela
  deslizante + alerta), com framing honesto ("stream semeado de um ambiente real").
  Opcional: apontar para a aba Evaluation (online monitors) do agente deployado se
  existir. Cloud Monitoring alert policy é GA (ver `demos/case-1-demos.md §3.3`).
- **Ponte C3 (1 frase):** o mesmo BQ ganha Row-Level Security no Caso 3.

### Fase 5 — Cloud Build gate · usuário conecta o repo
```bash
gcloud builds submit --config deploy/cloudbuild.yaml
```
- Mostra o gate: `run_offline` sai ≠0 → build vermelho → merge barrado.
- Opcional: wire como required check no branch do PR.
- **Honestidade:** o gate **não é nativo** — quem barra é o Cloud Build. Quality
  Alerts só notificam. (Existe `agents-cli eval` com Cloud Build CI/CD oficial, mas
  o barrador continua sendo o Cloud Build.)

---

## 5. Trabalho SEM creds (pode começar já, em paralelo ao provisionamento)

Ordenado por valor:

1. ~~**Reconciliar o schema BigQuery (maior valor).**~~ **✅ FEITO (2026-07-09).** Ver
   Fase 4 acima: query reescrita p/ LogEntry/jsonPayload, schema em
   `agent_spans_schema.json`, seeder + testes no `bigquery_scale.py`. Falta só o passo
   com creds (criar o sink / semear a tabela real).
2. **Endurecer `evals/live.py`** contra o drift de API Preview mais provável (revisão
   contra as assinaturas documentadas; deixar mensagens de erro claras para o dia da
   validação com creds).
3. **Ajustar o framing** de `evals/online_monitor.py` para a narrativa "ambiente
   semeado" (comentários/labels), sem mudar a lógica determinística.

---

## 6. Estado atual do código (2026-07-09)

- **Beat B do S4 FEITO** (esta sessão): invariante de trajetória
  `refund_requires_lookup` (`contract.py`, green/gating, sem runtime guard), case
  `silent_skipped_lookup` + flow `refund_no_lookup` (`evals/record.py`), cluster
  **"Incorrect Tool Selection"** (`evals/clusters.py`), métrica custom (`types.Metric`
  com `custom_function` local) espelhada no `--live` (`evals/metrics.py`). O um-dois A/B roda em `run_offline`.
- **Schema BQ + seeder RECONCILIADOS (2026-07-09):** query em LogEntry/jsonPayload,
  `agent_spans_schema.json`, `synthetic_rows`/`weekly_from_rows`/`seed_bigquery` +
  `--dump`/`--seed` no `bigquery_scale.py`. (Tarefa sem-creds #1 concluída.)
- **Offline tudo verde:** `run_offline` (5 casos, 3 falham, gate BLOCK),
  `online_monitor` (alerta t=42), `bigquery_scale` (drift semana 7→12), **46 testes**.
- **Gaps offline ainda abertos (fora deste plano, opcionais):** gerador
  contrato→cases da demo pt.1 (hoje `EVAL_CASES` é lista à mão); caso "policy/recusa";
  grey (RubricMetric) só no `--live`. Ver `case-1-demo-review` na memória.

---

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| Drift de API Preview (Evaluation) na Fase 2 | Fallback no gate offline (determinístico); validar cedo, antes de investir no resto |
| Schema Logging→BQ ≠ o que a query assume | Tarefa sem-creds #1 reconcilia antes de precisar de creds |
| Agent Runtime cold start / falha no deploy ao vivo | Pré-deployar; nunca demonstrar o deploy ao vivo |
| Topology/Online Monitor/Eval são Preview | Declarar no palco; credibilidade no substrato GA (Trace/Build/BQ) + invariantes portáveis (pytest) |
| Tempo apertado no palco | Ordem de prioridade: A/B do S4 > trace S2 > eval S3 > BQ/monitor |

---

## Referências
- `demos/case-1-demos.md` — spec da demo (o quê/como, roteiro de palco, API verbatim).
- `agent/README.md` — quickstart, mapa das 6 superfícies, cenários.
- `docs/eval-agentes-fundamentos.md §15` — slides + speaker notes.
- Memória: `case-1-demo-review`, `demo-fidelity-not-100-match`, `l400-presentation`.
