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

# 5) Confirmar acesso ao modelo gemini-2.5-flash no Vertex (região us-central1)

# 6) Preencher agent/.env a partir do .env.example
```

**Checklist de saída da Fase 0:** ADC ok · APIs on · bucket criado · modelo acessível
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

### Fase 2 — S3 live eval (Evaluation Preview) · precisa creds · ⚠️ MAIOR RISCO
```bash
EVAL_LIVE_CONFIRM=1 uv run python -m evals.run_offline --live
```
- Valida a pipeline Preview: `generate_conversation_scenarios` → `run_inference` →
  `evaluate` → `generate_loss_clusters`. Resultados na **aba Evaluation** do Console.
- **Risco:** drift de assinatura das APIs Preview (o SDK muda). A investigação de
  2026-07-09 não confirmou os nomes exatos direto da página de overview — validar
  contra as subpáginas do SDK ("Manage evaluation metrics", "Continuous evaluation").
- **Fallback:** se a API live quebrar, o **gate offline** (`run_offline` sem `--live`)
  é o artefato mostrado — já é determinístico e verde. Não bloqueia a demo.
- **Fronteira EDD (dizer no palco):** a plataforma gera os *inputs*; o *critério de
  certo* (o invariante) veio do contrato. Ver `demos/case-1-demos.md §4`.

### Fase 3 — Agent Runtime deploy (a "produção") · precisa creds + bucket
```bash
GOOGLE_CLOUD_STAGING_BUCKET=gs://<seu-bucket> \
  DEPLOY_CONFIRM=1 uv run python deploy/agent_engine.py
```
- Cria o `ReasoningEngine` (Agent Runtime). Confirmar traces fluindo para Cloud Trace.
- É a "produção" que o S4 aponta. **NÃO demonstrar o deploy ao vivo** (cold start) —
  pré-deployar e mostrar o Console.
- **Honestidade:** Runtime dá as superfícies de observabilidade (mesmo OTel→Trace),
  **não** dá métricas de qualidade nem custo de graça. Os invariantes são SUA
  instrumentação — é o ponto do EDD.

### Fase 4 — S4 pré-semeado (híbrido) · construção + creds
- **BigQuery (o item de build real):**
  1. Criar dataset + **sink Cloud Logging → BigQuery** dos spans do agente.
  2. **Reconciliar o schema:** `evals/queries/invariant_trend.sql` hoje assume
     `attributes.eval.invariant.refund_within_charge` e `attributes.gen_ai.tool.name`
     — o schema real do sink Logging→BQ **não** produz esse formato. Ajustar a query
     ao schema real (campos aninhados do LogEntry / jsonPayload).
  3. **Semear histórico** (meses de drift) na tabela real, para a trend query retornar
     dados de verdade. Ver `weekly_failure_rate()` em `bigquery_scale.py` como o shape
     alvo dos dados.
  4. Rodar `EVAL_LIVE_CONFIRM=1 python -m evals.bigquery_scale --live`.
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

1. **Reconciliar o schema BigQuery (maior valor).** Descobrir o schema real do sink
   Cloud Logging→BQ para spans OTel do ADK, corrigir `invariant_trend.sql`, e escrever
   um *seeder* que popula a tabela `agent_spans` com o corpus histórico (meses de
   drift, shape de `weekly_failure_rate()`). Sem isso a Fase 4/BQ não roda.
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
  **"Incorrect Tool Selection"** (`evals/clusters.py`), `CodeExecutionMetric`
  espelhado no `--live` (`evals/metrics.py`). O um-dois A/B roda em `run_offline`.
- **Offline tudo verde:** `run_offline` (5 casos, 3 falham, gate BLOCK),
  `online_monitor` (alerta t=42), `bigquery_scale` (drift semana 7→12), **27 testes**.
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
