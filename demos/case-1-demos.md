# Caso 1 — Demonstração L400 (Continuous Evaluation & EDD)

> Documento de referência da demonstração do **Caso 1** (âncora do talk "Managing
> Production Agents at Scale"). Consolida a análise dos componentes do **Gemini
> Enterprise Agent Platform** (seção *Optimize* — Evaluation + Observability), as
> decisões de design, a arquitetura da demo e o roteiro de palco.
>
> **Escopo:** este doc é a fonte da verdade para **construir o agente + as demos**.
> Diagramas/slides do Caso 1 estão em `docs/eval-agentes-fundamentos.md §15`.
> Última atualização: 2026-07-07.

---

## 0. Objetivo e princípios

- **Objetivo:** provar, em código real e em produtos reais do Google Cloud, a tese
  do Caso 1 — *"o placar verde mente"* — e mostrar o **Quality Flywheel** fechando
  o loop (EDD → produção → EDD).
- **Público:** FDEs (são SWEs), Nooglers, parceiros (Accenture). Nível **L400**,
  máximo técnico, **pouco tempo** (~8 min o caso inteiro; demo tecida, ~3–4 min).
- **Meio:** **código ADK real no VSCode** (sem Colab) + **Cloud Console** como prova
  de "isto é Google Cloud real". Tela dividida: VSCode à esquerda, Console à direita.
- **Princípio anti-vitrine:** cada componente responde a uma pergunta que o beat
  anterior deixou no ar. Nada aparece por aparecer.
- **Princípio de credibilidade:** o **substrato GA carrega o peso**; o **Preview é
  acelerador declarado** (transparência GA/Preview no palco). A **disciplina (EDD) é
  portável** — os invariantes rodam como pytest, sem a plataforma.

---

## 1. Decisões travadas (esta sessão, 2026-07-07)

1. **Onde entra a demo:** **tecida** nos slides — corte no S2 (console), S3 (código
   real) e S4 (clímax). Não é bloco monolítico (mata energia em L400).
2. **Meio:** **código ADK real no VSCode**, ambiente real. **Sem Colab/notebook.**
   Consequência: `.show()` (renderer de notebook) não serve → resultados aparecem na
   **aba Evaluation do Console** (reforça "dentro do Google Cloud").
3. **Real vs. staged:** S3 (autoria + geração + eval) **roda de verdade**; S4
   (flywheel: run+fail+clusters+monitor) = **formato a DECIDIR** (gravado OU ambiente
   pré-rodado mostrado ao vivo — decisão 2026-07-08; construir funcional 1º, escolher
   depois). Componentes reais, tudo já preparado. **Fala neutra até decidir** (nem
   "ao vivo" nem "gravação"). Só o 403 do Caso 3 é genuinamente ao vivo.
4. **Preview liberado:** usar **tudo que existe hoje**, mesmo em Preview, com
   **transparência no palco** (dizer o que é GA e o que é Preview).
5. **BigQuery entra no Caso 1** como a peça de **"escala"** (onde vivem milhões de
   traces pontuados; drift ao longo de meses). Ponte de **1 frase** para o Caso 3
   (mesmo BQ ganha Row-Level Security lá). **Não abrir** o assunto aqui.
6. **Usar todas as páginas da plataforma** (Agent evaluation, Evaluate your agents,
   Run offline evaluations, Simulate agent behaviour, Continuous eval / Online
   Monitors, Manage eval metrics, Analyze results / failure clusters, Configure
   quality alerts, Optimize agent prompts, Observability: overview/traces/topology) —
   cada uma com casa definida (ver §5, tabela de cobertura).
7. **Honestidade firme:** (a) o **gate de CI/CD não é nativo** — quem barra é o
   **Cloud Build** rodando o eval; as Quality Alerts **só notificam**. (b) `adk
   optimize` (GEPA) fica **gravado**, nunca ao vivo (é o mais frágil/mágico).

---

## 2. A ideia que costura tudo: *um invariante, seis superfícies*

O `refund ≤ charge` **não é "um teste que mora num lugar"**. É **uma função**,
escrita **uma vez** e derivada do **contrato** (isto é EDD), ligada a **seis
superfícies** do Google Cloud. É o que faz os componentes pararem de parecer soltos.

```
              def refund_within_charge(trace) -> verdict     ← EDD: 1 função, do contrato
                                  │
   ┌──────────┬─────────┬────────┼─────────┬──────────────┬───────────────┐
   ▼          ▼         ▼        ▼         ▼              ▼               ▼
[OBSERV.]  [AUTORAR]  [OFFLINE] [GATE]   [PRODUÇÃO]    [FLYWHEEL]      [ESCALA]
 S2         S3         S3        S3        S4            S4              S4 (chão)
 OTel+      Manage     Run       Cloud     Online        Loss           BigQuery
 Trace+     Metrics    Offline   Build     Monitors      Clusters       (corpus +
 Topology              Eval +              + Quality     + Optimize      drift no
                       Simulate            Alerts        (GEPA)          tempo)
```

**A mesma função** aparece como: guarda de runtime (callback), métrica de teste,
gate de merge, monitor de produção, e semente do próximo teste. Esse é o
*"one object, three jobs"* do roteiro dos slides — agora com **superfície de Google
Cloud concreta em cada nó** e provável em código.

### "Onde roda o teste `refund ≤ charge`?" — Cloud Build **e** Evaluation Service

Duas formas do **mesmo código**, com papéis diferentes — e isso é o ponto:

- **Runtime:** um **ADK `after_tool_callback`** no `issue_refund`. O mesmo hook que
  emite o span OTel também checa o invariante.
- **Teste (eval):** a mesma lógica embrulhada em `types.CodeExecutionMetric`
  (`evaluate(instance) -> float` lê `instance['agent_eval_data']['turns']`, acha a
  chamada `issue_refund` e compara com o `charge`).
- **Inner loop (dev):** **Evaluation Service** — `client.evals.evaluate(...)` do
  terminal do VSCode; resultado na aba **Evaluation** do Console.
- **Gate (merge):** **Cloud Build** roda o **mesmo** script no PR; score < threshold
  ⇒ build vermelho ⇒ merge barrado. ⚠️ **Não é nativo** — o gate é o Cloud Build.

Punchline: *"o mesmo teste é o seu loop de dev E o seu gate de merge E o seu alarme
de produção — porque é a mesma função em superfícies diferentes."*

---

## 3. Inventário real dos componentes (nível código)

Extraído da doc pública (`docs.cloud.google.com/gemini-enterprise-agent-platform/optimize`,
Evaluation + Observability, 12 subpáginas, + guia OTel do ADK). Nomes de API/CLI
**verbatim**.

### 3.1 Confirmações que validam o Caso 1
- ✅ `generate_loss_clusters` **existe** — `client.evals.generate_loss_clusters(eval_result=...)`.
- ✅ **Taxonomia de falhas oficial e nomeada.** `"Incorrect Tool Selection"` é um
  *loss pattern* real da taxonomia `multi_turn_task_success_v1`. (Slide 4 correto.)
- ✅ **Custo NÃO é capturado**; **token É** (agregado, input vs output por modelo).
  Confirma a divisão C1/C2 (custo/token por span = instrumentação sua, Caso 2).
- ✅ **EDD ≠ User Simulation** (a fronteira mais importante — ver §4).
- ✅ A **"seam" é literal:** as métricas online **leem os traces OTel**. Os atributos
  obrigatórios do span são exatamente o que o eval consome → *um substrato, três
  disciplinas*, provável em código.
- ✅ As **duas métricas custom mapeiam 1:1 nas cores do Slide 2:** verde (invariante
  duro) = `CodeExecutionMetric`; âmbar (subjetivo) = `LLMMetric`. São **classes reais**.

### 3.2 Mapa de componentes

| Componente | O que faz (real) | Managed vs. **seu código** | Status |
|---|---|---|---|
| **OpenTelemetry (ADK ≥1.17)** | Substrato. `adk web --otel_to_cloud`; convenções `gen_ai.*`; span `call_llm` | Managed (built-in) | Padrão/estável |
| **Cloud Trace** | Waterfall de 1 request; spans = latência/status/estrutura | Managed | GA |
| **Cloud Storage** | Prompts/respostas **não ficam no span** — vão pro GCS (multimodal, sem truncar) | Managed | GA |
| **Cloud Logging** | Logs do agente; sink → BigQuery | Managed | GA |
| **Topology** | Grafo A2A + MCP a partir de traces agregados | Managed | **Preview** |
| **Gen AI Evaluation Service** (`client.evals`) | `generate_conversation_scenarios` · `run_inference` · `evaluate` · `generate_loss_clusters` | Managed | **Preview** |
| **Metric Registry** | Managed: `types.RubricMetric.*`. **Seus:** `types.CodeExecutionMetric` + `types.LLMMetric` | **Metade sua** | **Preview** |
| **Online Monitors** (`OnlineEvaluator`) | Amostra traces de produção (~10 min) → Logging + Monitoring | Managed | **Preview** |
| **Cloud Monitoring** | Alert policy `online_evaluator/scores < threshold` → Slack/email/PubSub (**só notifica**) | Managed | GA |
| **Cloud Build** | Roda o eval no PR; gate de merge (**não nativo**) | Managed | GA |
| **BigQuery** | Corpus de traces pontuados; drift ao longo de meses; ponte C3 (RLS) | Managed | GA |
| **`adk optimize` (GEPA)** | Reescreve system instructions contra o test suite (hill-climbing) | Managed | **Preview / WIP** |

### 3.3 API surface verbatim (referência de build)

```python
# Setup
pip install google-cloud-aiplatform[adk,evaluation]
import vertexai
from vertexai import Client, evals, types
client = Client(project="YOUR_PROJECT_ID", location="YOUR_LOCATION")

# 1) Simulate agent behaviour — gera INPUTS (user simulation, NÃO EDD)
travel_agent_info = types.evals.AgentInfo.load_from_agent(agent=my_agent)
eval_dataset = client.evals.generate_conversation_scenarios(
    agent_info=travel_agent_info,
    config={
        "count": 5,
        "generation_instruction": "Generate scenarios where a user asks for a refund.",
        "environment_context": "Today is Monday. ...",  # apenas grounding, NÃO fault injection
    },
)

# 2) Run inference — user simulator multi-turn → traces
traces = client.evals.run_inference(
    agent=my_agent, src=eval_dataset,
    config={"user_simulator_config": {"max_turn": 5}},
)

# 3) Manage metrics — o "certo" (EDD): invariante duro + juiz + baseline managed
invariant = types.CodeExecutionMetric(name="refund_within_charge", custom_function="""
def evaluate(instance: dict) -> float:
    agent_data = instance.get('agent_eval_data', {})
    for turn in agent_data.get('turns', []):
        ...  # acha issue_refund; retorna 1.0 se refund <= charge, senão 0.0
""")
judge = types.LLMMetric(name="tone_check", prompt_template="...", result_parsing_function="...")
client.evals.create_evaluation_metric(metric=invariant)
client.evals.create_evaluation_metric(metric=judge)

# 4) Run offline evaluation
result = client.evals.evaluate(
    dataset=eval_dataset,
    metrics=[
        types.RubricMetric.FINAL_RESPONSE_QUALITY,   # managed, adaptive rubric
        types.RubricMetric.HALLUCINATION,            # managed, static rubric
        types.RubricMetric.SAFETY,                   # managed (1=safe, 0=unsafe)
        # + invariant + judge (custom, registrados acima)
    ],
)
result.show()  # nota: renderer de notebook — na demo usamos a aba Evaluation do Console

# 5) Analyze — failure/loss clusters (o "porquê")
loss_clusters = client.evals.generate_loss_clusters(eval_result=result)
# Taxonomias: multi_turn_task_success_v1 e multi_turn_tool_use_quality_v1
# Ex. de loss pattern: "Incorrect Tool Selection"
```

**Métricas managed (enums):** single-turn `FINAL_RESPONSE_QUALITY`, `HALLUCINATION`,
`TOOL_USE_QUALITY`, `SAFETY`; multi-turn `MULTI_TURN_TASK_SUCCESS`,
`MULTI_TURN_TOOL_USE_QUALITY`, `MULTI_TURN_TRAJECTORY_QUALITY`.

**Instrumentação OTel (ADK) — env vars verbatim:**
```
OTEL_SERVICE_NAME='...'
OTEL_SEMCONV_STABILITY_OPT_IN='gen_ai_latest_experimental'
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT='EVENT_ONLY'
ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS='false'          # evita PII no span
GOOGLE_CLOUD_AGENT_ENGINE_ENABLE_TELEMETRY='true'
# multimodal → Cloud Storage
OTEL_INSTRUMENTATION_GENAI_UPLOAD_FORMAT='jsonl'
OTEL_INSTRUMENTATION_GENAI_COMPLETION_HOOK='upload'
OTEL_INSTRUMENTATION_GENAI_UPLOAD_BASE_PATH='gs://BUCKET/PATH'
```
Rodar: `uv run --env-file opentelemetry.env adk web --otel_to_cloud`

**Atributos de span obrigatórios (o que o eval lê):** `gen_ai.agent.name`,
`gen_ai.agent.description`, `gen_ai.conversation.id`; evento
`gen_ai.client.inference.operation.details` com `gen_ai.input.messages`,
`gen_ai.output.messages`, `gen_ai.system_instructions`, `gen_ai.tool.definitions`.

**Online Monitor / Alerts:** resource `OnlineEvaluator`; roda ~10 min; escreve em
Cloud Logging + Cloud Monitoring. Alert policy (Cloud Monitoring), metric type
`aiplatform.googleapis.com/online_evaluator/scores`, label
`metric.labels.evaluation_metric_name="task_success"`. **Notify-only** (sem gate).

**Optimize:** `adk optimize` (CLI), algoritmo **GEPA** (github.com/gepa-ai/gepa),
refina root system instructions contra o test suite. Preview/WIP.

---

## 4. A fronteira crítica: EDD ≠ User Simulation

A armadilha mais perigosa da demo. A plataforma:
- `generate_conversation_scenarios` gera **INPUTS** (starting prompt + conversation
  plan). É **user simulation**. **NÃO sabe o que é "certo".** Pressupõe agente rodável.

EDD é o que **você** faz **a montante**: derivar do **contrato** os **invariantes /
`CodeExecutionMetric`** — o critério de "certo". *Essa é a parte que nenhuma
ferramenta te dá.*

**Consequência de palco:** ao mostrar `generate_conversation_scenarios`, **nomear a
fronteira explicitamente** ("a plataforma gera os inputs; o 'certo' fui eu que
derivei do contrato"). Sem isso, um FDE esperto conflacia EDD com o recurso da
plataforma e a diferenciação evapora ao vivo.

**Defesa de Q&A (obrigatória):** *"EDD valida conformidade com o contrato, não
correção do contrato — igual BDD/TDD; por isso anda junto do flywheel de produção,
que corrige a própria spec."*

---

## 5. Detalhamento por superfície + tabela de cobertura

### Superfície 0 — BigQuery: onde "escala" mora *(chão, S4)*
- **Papel:** Cloud Trace retém traces por semanas; "at scale" precisa de meses e de
  milhões de traces pontuados. Sink GA do Cloud Logging → **BigQuery** = corpus do
  flywheel ("eval como memória de produção"). Query SQL de tendência (taxa de falha
  do invariante por semana).
- **Status:** GA. **Ponte C3 (1 frase):** o mesmo BQ ganha Row-Level Security lá.

### Superfície 1 — Observability *(S2)*
- Cobre: overview + **traces** + **topology**.
- Papel: provar que a trace é real e que é *a mesma* que o eval lê; Topology desenha
  o A2A (fraud-check) + sub-agentes (= diagrama do Slide 1).
- Status: GA/padrão. **Âncora de credibilidade.**

### Superfície 2 — Autorar o eval / Manage Metrics *(S3)*
- Cobre: Agent evaluation (conceito) + Manage evaluation metrics.
- Papel: a fronteira EDD. Três métricas, papéis distintos: sua/dura
  (`CodeExecutionMetric`, verde), sua/subjetiva (`LLMMetric`, âmbar, Gemini mais
  recente), managed/baseline (`RubricMetric.*`, cinza).
- Status: Preview. Lógica do invariante = portável (pytest).

### Superfície 3 — Rodar offline + simular + gate *(S3)*
- Cobre: Evaluate your agents + Run offline evaluations + Simulate agent behaviour.
- Papel: inputs da plataforma; "certo" seu. `generate_conversation_scenarios` (happy/
  policy/**adversarial** = ponte C3) → `run_inference` → `evaluate` → aba Evaluation.
- Gate: **Cloud Build** roda o mesmo script no PR (não nativo).
- Status: eval Preview; Cloud Build GA.

### Superfície 4 — Produção contínua *(S4)*
- Cobre: Continuous eval / Online Monitors + Configure quality alerts.
- Papel: o mesmo invariante vira sentinela. `OnlineEvaluator` (~10 min) → Cloud
  Monitoring; alert quando cai do threshold.
- Status: Online Monitor Preview; Cloud Monitoring GA.

### Superfície 5 — Flywheel / análise *(S4)*
- Cobre: Analyze results / failure clusters + Optimize agent prompts.
- Papel: "falhou" → "padrão nomeado". `generate_loss_clusters` → "Incorrect Tool
  Selection ×N". Caso reprovado volta pro dataset. **Opcional/staged:** `adk optimize`
  (GEPA) propõe a correção — **nunca ao vivo**.
- Status: Preview.

### Tabela de cobertura (prova de que usamos tudo)

| Página da plataforma | Onde vive na demo | Superfície |
|---|---|---|
| Observability: overview / traces / topology | S2 | 1 |
| Agent evaluation (conceito) | S3 (framing EDD) | 2 |
| Manage evaluation metrics | S3 (as 3 métricas) | 2 |
| Evaluate your agents | S3 (workflow SDK) | 3 |
| Run offline evaluations | S3 (`evaluate`) | 3 |
| Simulate agent behaviour | S3 (`generate_scenarios`/`run_inference`) | 3 |
| Continuous eval / Online Monitors | S4 | 4 |
| Configure quality alerts | S4 | 4 |
| Analyze results / failure clusters | S4 | 5 |
| Optimize agent prompts | S4 (staged, 1 beat) | 5 |
| *(novo)* BigQuery — escala | S4 (chão) | 0 |

---

## 6. Experiência de palco (VSCode + Console)

**Setup visual:** tela dividida — **VSCode à esquerda, Cloud Console à direita**. O
código é o "como"; o Console é a prova de "isto é Google Cloud real". Âncora
emocional constante: **dinheiro** — reembolso de **$500 sobre cobrança de $50**.
Pergunta viva que atravessa os cortes: *"o placar tá verde. Pode dar deploy?"*

### Corte S2 — "Esta trace é real" *(~40s, console)*
1. **Direita (Cloud Trace):** clica numa trace de reembolso. Waterfall:
   `root → refund specialist → look_up_customer → issue_refund → reply`. Abre
   **Topology** por 5s (A2A do fraud-check + sub-agentes = Slide 1).
2. **Esquerda (VSCode):** flash de `opentelemetry.env` + `adk web --otel_to_cloud`.
   "Três linhas. É OTel padrão."
3. **Fala-chave:** *"Guardem esta trace. O eval vai ler exatamente ela — mesmo substrato."*

### Corte S3 — "O placar verde mente" — pt.1: você escreve o gabarito *(~2 min, real)*
1. **VSCode `contract.py`:** contrato em linguagem simples; seleciona *"nunca
   reembolsar mais que a cobrança"* → vira **3 linhas** de `CodeExecutionMetric`.
   *"Isto é EDD: o teste sai do contrato, antes do agente rodar."*
2. **VSCode:** ao lado, `LLMMetric` (juiz de tom) + lista de `RubricMetric` managed.
   *"Verde = eu provo. Âmbar = precisa de juiz. Cinza = baseline da Google."*
3. **A fronteira (momento intelectual):** roda `generate_conversation_scenarios` →
   inputs happy/policy/**adversarial**. *"A plataforma gera os inputs. Ela NÃO sabe o
   que é certo. O 'certo' fui eu que derivei do contrato."*
4. **Terminal:** `client.evals.evaluate(...)`. **Direita (aba Evaluation):** placar
   sobe **VERDE**; métricas managed passam. **Pausa.** *"Ship it? É aqui que a maioria
   dos times para."*

### Corte S4 — "O placar verde mente" — pt.2: o dinheiro *(~2 min, clímax, formato a decidir)*
1. **O um-dois — A · o barulhento:** clica no caso do dinheiro. `CodeExecutionMetric`
   `refund ≤ charge` **VERMELHO**: o agente reembolsou **$500** numa cobrança de **$50**
   — e o juiz de tom classificou como "prestativa e educada" (**verde**). **O placar verde
   mente — com dinheiro real.** O check duro pega sozinho; o "porquê" é óbvio (refund >
   charge). *(fala neutra sobre o formato; não afirmar "ao vivo" se for gravação.)*
2. **O um-dois — B · o silencioso:** agora um caso **todo verde** (valor ok, output ok,
   todos os scores passam). Só a **trajetória** mostra que ele **pulou o look-up** e
   reembolsou assim mesmo — invisível pra qualquer check de valor. `generate_loss_clusters(...)`
   → **Failure Clusters**: **"Incorrect Tool Selection ×N"**. *"O A o check duro pegou; o B,
   só a trajetória via — e a plataforma deu nome ao padrão."* **É o B que prova por que
   precisamos de trajetória + clusters.**
3. **Fecha o loop:** o caso reprovado entra no dataset. *"Um ataque hoje vira um teste
   pra sempre."* A caixa **"The Green Score Lies"** (Slide 1) volta como **"The Green
   Score — EARNED"**, com as 2 perguntas ganhando ✓.
4. **Escala (BQ):** *"Mas isso foi um caso. E em produção?"* → **BigQuery**: query com
   taxa de falha do invariante **por semana, ao longo de meses**. *"Escala não cabe
   numa trace; cabe no BigQuery."* (1 frase: *"no Caso 3 esse mesmo BQ ganha RLS"*).
5. **A sentinela:** **Online Monitor** já roda o invariante em produção; **Cloud
   Monitoring** dispara o alerta ao cair do threshold. *"O mesmo teste, vigiando 24/7."*
6. **(Opcional, gravado):** `adk optimize` (GEPA) propõe a correção das instruções.
   *"O loop pode até tentar se consertar."* — fronteira, não mágica.

**Arco emocional:** verde ingênuo (S3) → **um-dois** (A: mentira com dinheiro, check duro
pega · B: falha silenciosa, só a trajetória pega + cluster nomeia) → loop fechado (anel) →
escala provada (BQ) → vigilância contínua. Termina no pico, não no detalhe.

---

## 7. Landmines / honestidade (não errar no palco)

- **Gate de CI/CD não é nativo.** Quem barra o merge é o **Cloud Build** rodando o
  eval. As **Quality Alerts só notificam** (Slack/email/PubSub).
- **Custo não é capturado** pela observabilidade; **token é agregado**. Custo/span =
  instrumentação sua (assunto do Caso 2). Não implicar que o dashboard mostra custo.
- **EDD ≠ User Simulation** (ver §4). Nomear a fronteira.
- **`adk optimize` (GEPA)** = gravado, nunca ao vivo.
- **Toda a suíte Eval é Preview.** Dizer no palco; ancorar credibilidade no substrato
  GA (OTel/Trace/Build/BQ) + invariantes portáveis.
- **`.show()` é renderer de notebook** — na demo, resultados na aba Evaluation do Console.
- **Loss clusters precisam de N casos** para formar cluster → dado staged; ser honesto.

---

## 8. Build do agente — CONSTRUÍDO (2026-07-07)

O agente + o harness de eval do Caso 1 estão construídos na pasta **`agent/`** do
repo (ADK 2.3.0, uv, Python 3.12). Roda offline (sem modelo/GCP) para testes e
demo; APIs Preview reais wired e guardadas para rodar contra o projeto real.

- **ADK:** `root` (`financial_support`) → `refund_specialist` + `disputes_specialist`.
- **Tools (mock realista + feature flags):** `look_up_customer` → customer_db
  (BigQuery; hook RLS no C3), `issue_refund` → payment_processor (hook latência/
  retry no C2; é onde mora o `after_tool_callback` do invariante), `fraud_check`
  → local **ou via A2A** (`fraud_check_a2a`, server `to_a2a` + `RemoteA2aAgent`).
- **Fault engine** (`backends/faults.py`) = as feature flags (cenários
  `healthy`/`refund_over_charge`/`wrong_account`/`slow_payment`/`payment_declined`/
  `fraud_unavailable`); encena o caso que reprova sem não-determinismo.
- **Invariant seam:** `callbacks/invariants.py` (`after_tool_callback`) roda o
  invariante do `contract.py` + anota o span; modo `observe` (deixa passar → eval
  pega) vs `block`.
- **Case-scoping via `CASE`** (registry): a demo do Caso 1 roda com só o
  invariante ligado; C2/C3 ficam dormentes no mesmo codebase.

**Estrutura real construída:**
```
agent/
  financial_support/   # ADK: root + sub_agents/ + tools/ + backends/ + callbacks/ + observability/
    contract.py        # contrato → invariantes (verde); "one function, three jobs"
    backends/faults.py # feature flags / fault injection
    callbacks/         # invariants.py (seam) + telemetry.py + registry.py (extensível C2/C3)
  fraud_check_a2a/     # agente externo via A2A (server + client)
  evals/               # metrics · scenarios · record · eval_core · report · clusters
                       # · online_monitor · bigquery_scale · queries/*.sql · live · run_offline
  deploy/opentelemetry.env · cloudbuild.yaml   # substrato + gate (Cloud Build, não nativo)
  scripts/run_local.py # dirige tool+seam offline (sem modelo)
  tests/               # 23 testes verdes
```

**Mapa demo → código (as 6 superfícies):** ver tabela no `agent/README.md`.
Comando-chave da demo offline: `uv run python -m evals.run_offline` (record →
evaluate → report → clusters → gate exit≠0).

**O um-dois do S4 (§6, corte S4) roda de ponta a ponta no `run_offline`:**
- **A · barulhento** (`adversarial_over_refund`): `refund_within_charge` VERMELHO
  ($500 sobre $50) enquanto `tone_check` fica verde. O check duro pega sozinho.
- **B · silencioso** (`silent_skipped_lookup`, add 2026-07-08): refund $50 sobre
  $50, conta certa, resposta educada — **todos os checks de valor verdes**; só o
  invariante de **trajetória** `refund_requires_lookup` fica VERMELHO (o look-up
  foi pulado). O `generate_loss_clusters` (análogo offline) nomeia
  **"Incorrect Tool Selection"**. É o B que prova por que trajetória + clusters
  existem — nenhum check de valor o enxergava.

O invariante de trajetória vive em `contract.py::check_refund_requires_lookup_trace`
(green/gating), é encenado pelo flow `refund_no_lookup` em `evals/record.py`, e tem
o `CodeExecutionMetric` espelhado em `evals/metrics.py` para o caminho `--live`.

---

## Referências
- Doc pública: `docs.cloud.google.com/gemini-enterprise-agent-platform/optimize`
  (Evaluation + Observability) + guia OTel ADK (`stackdriver/docs/instrumentation/ai-agent-adk`).
- Fundamentos conceituais: `docs/eval-agentes-fundamentos.md` (14 seções + §15 slides).
- Slides do Caso 1: `docs/eval-agentes-fundamentos.md §15.1–15.6`.
- Caso 1 (narrativa): `en/cases/case-1.md`.
