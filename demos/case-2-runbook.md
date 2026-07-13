# Runbook — Caso 2 (pré-run + dia da apresentação)

> **Para que serve:** rodar cada parte da demo do Caso 2 **1 dia antes**, deixar o
> ambiente "quente" (trace populada, BQ semeada, engine acordado, incidente pré-disparado)
> e, no dia, **só mostrar os resultados** — o único beat semi-live é o A/B no terminal.
>
> **Estratégia (decidida):** a demo É o **A/B (breaker OFF vs ON)** no terminal, rodado
> ao vivo, com o **vídeo de fallback aberto numa aba** como rede de segurança. Todo o
> resto (trace, BQ, alerta, p95 do engine) é **pré-populado** — você abre a aba e aponta.
>
> **Como usar com o Claude Code:** cada seção tem `Comando`, `O que esperar` e `Se falhar`.
> Peça: *"roda a Seção 3 do runbook do Caso 2 e confere o esperado"*.
>
> **Regra de ouro:** **sempre rodar de dentro de `agent/`** (`cd .../l400-managing-production-agents/agent`).
> O harness `load_test`/`live_drive`/`cost_scale` já força `CASE=2` quando precisa.

Complementa `demos/case-2-demos.md` (o *quê/como*) e `docs/case-2-fundamentos.md`
(narrativa/slides). Numeração: os docs chamam de **Slide 5/6/7**; o **deck real é a
p.9 (Cascade) / p.10 (Contain) / p.11 (Govern)** — reconcilie as speaker notes.

---

## 0. Pré-flight (5 min, roda primeiro) — checklist de ambiente

```bash
cd ~/l400-managing-production-agents/agent

# 1) ADC (metadata server da VM)
uv run python -c "import google.auth; _,p=google.auth.default(); print('ADC ok, project:', p)"

# 2) Chaves do .env
grep -E "^(MODEL|GOOGLE_CLOUD_PROJECT|GOOGLE_CLOUD_LOCATION)=" .env

# 3) Baseline offline verde (rede de segurança + valida o código do Caso 2)
uv run pytest -q
```

**O que esperar:**
- `ADC ok, project: YOUR_PROJECT_ID`
- `MODEL=gemini-3.5-flash`, projeto e região corretos.
- **`86 passed`** (inclui `test_resilience.py` + `test_cost_seed.py`).

**Se falhar:** ver Seção 9. Sem ADC, nada ao vivo funciona.

---

## 1. Warm-up (2 min) — acordar o modelo global

```bash
CASE=2 uv run python -m scripts.live_drive --scenario slow_payment --no-cloud --no-verify
```

**O que esperar:** o agente roda `look_up_customer → transfer → fraud_check → issue_refund`,
o `issue_refund` demora ~15s (o mock lento), resposta sem erro de rede/modelo.

**Se falhar:** modelo global inacessível → conferir `MODEL=gemini-3.5-flash` (split em
`financial_support/model.py`). Ver Seção 9.

---

## 2. Beat 1 — Waterfall (Cloud Trace) · **pré-run** ✅ (validado 2026-07-13)

**Slide/beat:** *Contain the Blast* (deck p.10) — "which dependency? não adivinho, a trace me diz."
**Câmera:** aproxima em UMA trace. ~30s de palco.

```bash
# Pré-rodar (gera 1 trace com o span de 15s + gen_ai.cost.usd). CASE=2 é obrigatório
# (senão o record_cost não roda e o gen_ai.cost.usd não aparece — isso é o Beat 4).
CASE=2 uv run python -m scripts.live_drive --scenario slow_payment \
  --prompt "Refund my \$50 charge TXN-1001."
```

**O que esperar:** imprime a hierarquia + um **trace id** e auto-verifica via Cloud Trace
REST (lag ~1–2 min). O span `execute_tool issue_refund` ≈ **15s**; os `call_llm` curtos.

**Onde mostrar (link da trace já pré-rodada):**
🔗 https://console.cloud.google.com/traces/list?project=YOUR_PROJECT_ID&tid=7d29dce757bc053633c0503d0fc68e56
→ waterfall: aponte a barra **longa `execute_tool issue_refund` (15s)** vs `call_llm`.
*(Se regerar, use o novo trace id que o comando imprime.)*

**Fala de palco:** *"o modelo respondeu rápido; esta tool levou 15s. A observabilidade
não disse só 'foi lento' — disse ONDE. Vou embrulhar exatamente essa dependência."*
**Honestidade:** o `time.sleep(15)` é mock da degradação — dizer.
**Se falhar:** trace não aparece → lag (espere 2 min) ou rode sem `--no-cloud`. Fallback: a trace já pré-rodada acima.

---

## 3. Beats 2–3 — A/B OFF vs ON (terminal) · **semi-live (o coração)** ✅ (validado 2026-07-13)

**Slide/beat:** *Contain the Blast* (deck p.10) — o clímax. ~45s (OFF) + ~60s (ON).
**IMPORTANTE:** isto **não é uma aba do Console** — é a tabela que **imprime no terminal**
(VSCode). É o artefato do palco (a plataforma não dá token/custo → você instrumenta).

```bash
BREAKER_OPEN_AFTER=2 uv run python -m scripts.load_test --ab --scenario slow_payment \
  --n 6 --concurrency 2
```
> O harness já força `CASE=2` e **neutraliza o budget** (`SESSION_BUDGET_USD` alto) para o
> breaker ser a única variável. `--ab` é **local-only** (o breaker do engine é baked).

**O que esperar (imprime no fim, no terminal):**
```
+-------------------------+-------------+------------+
| metric                  | BREAKER OFF | BREAKER ON |
+-------------------------+-------------+------------+
| total tokens            |     ~95,000 |    ~31,000 |
| total cost              |     ~$0.17  |    ~$0.012 |
| p95 latency             |     ~200s   |     ~39s   |
| breaker-open (fallback) |           0 |          4 |
+-------------------------+-------------+------------+
```
Antes de rodar o ON, mostre no VSCode `financial_support/callbacks/resilience.py` →
`circuit_breaker`: destaque o `return {... "instruction": "do not retry; follow fallback"}`.
**Fala:** *"um breaker normal devolve erro e o modelo relê e tenta de novo. Eu injeto um
FATO no contexto."*

**Honestidade:** os números do **OFF variam** (o modelo storma de forma não-determinística);
o **ON é estável**. Chamadas Flash reais = centavos. A **alucinação ("inventa o saldo") NÃO
é determinística** → narre + mostre o **vídeo de fallback** (Seção 7), não confie ao vivo.
**Se falhar:** rede/latência do modelo estoura o A/B → use a tabela pré-capturada + o vídeo.

---

## 4. Beat 4 — cost/span (`gen_ai.cost.usd`) · **pré-run** ✅ (validado 2026-07-13)

**Slide/beat:** *Govern the Cost* (deck p.11) — "o número que a plataforma não te dá." ~30s.

**Onde mostrar:** a **mesma trace do Beat 1** (o `record_cost` roda mesmo com breaker off).
🔗 abrir a trace → clicar num span **`call_llm`** → aba **Attributes** → apontar **`gen_ai.cost.usd`**
(dica: toggle "GenAI attributes only"; confirmado ao vivo — 5 spans com o atributo).

**Fala:** *"a plataforma me deu latência e tokens. O custo fui eu que calculei, no mesmo
hook do Caso 1."* Flash no VSCode: `record_cost` / `budget_guard` em `resilience.py`.
**Se falhar:** atributo não aparece → a trace foi gerada com `CASE=2`? (senão o `record_cost`
não rodou). Regerar com a Seção 2.

---

## 5. Beat 5 — Custo por tenant (BigQuery) + alerta · **pré-semeado** ✅ (validado 2026-07-13)

**Slide/beat:** *Govern the Cost* (deck p.11) — "quem paga?" ~40s.

### 5a. BigQuery — custo por tenant (um projeto ~10×)
```bash
# (offline, sem creds) render da tabela
uv run python -m evals.cost_scale
# (com creds) re-semear + rodar a query real
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID uv run python -m evals.cost_scale --seed
EVAL_LIVE_CONFIRM=1 GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID uv run python -m evals.cost_scale --live
```
**O que esperar:** **proj-runaway $2.52 (~10×)** vs os outros (~$0.12–0.25).
**Onde mostrar:**
🔗 https://console.cloud.google.com/bigquery?project=YOUR_PROJECT_ID → tabela
`agent_eval.cost_spans` → cole `evals/queries/cost_by_tenant.sql` (troque `PROJECT.DATASET`
por `YOUR_PROJECT_ID.agent_eval`) → **Run → Chart/Visualize → bar** (uma barra
gigante). ⚠️ **Verificar antes** que o "Visualize" nativo está habilitado; fallback: tabela ordenada.

### 5b. Alerta de custo (Cloud Monitoring)
🔗 Policy "Case 2 — agent spend spike": https://console.cloud.google.com/monitoring/alerting/policies?project=YOUR_PROJECT_ID
🔗 Incidentes: https://console.cloud.google.com/monitoring/alerting/incidents?project=YOUR_PROJECT_ID
🔗 Métrica log-based `agent_cost_calls`: https://console.cloud.google.com/logs/metrics?project=YOUR_PROJECT_ID

**Fala:** *"o budget por sessão conteve UMA sessão. Isto governa a árvore inteira."*
**Honestidade:** é **custo instrumentado por você** (não o Billing export, que atrasa horas).
O alerta **só notifica** (não é gate). **Ponte C3:** *"resiliente ✓, custo governado ✓ — mas
cada chamada mexe com dinheiro e PII. Resiliente ≠ seguro."*
**Se falhar:** incidente não disparou → precisa de ingestão + volume de cost-logs; ver Seção 6/9 (pré-disparar).

---

## 6. Frota real (Agent Engine CASE=2) · **deployado** ✅ · p95 = coadjuvante ⚠️

**Slide/beat:** substrato "isto é GCP real, sob carga". Mostre só se sobrar tempo.

🔗 Engines: https://console.cloud.google.com/vertex-ai/agents/agent-engines?project=YOUR_PROJECT_ID
→ **`financial-support-agent-c2`** (`…reasoningEngines/ENGINE_ID_CASE2`); o Caso 1
(`…ENGINE_ID_CASE1`) continua separado — **os demos não se afetam**.
🔗 p95 da frota (Metrics Explorer → `reasoning_engine/request_latencies`):
https://console.cloud.google.com/monitoring/metrics-explorer?project=YOUR_PROJECT_ID

```bash
# dirigir a frota (gera traces escopados no engine + cost-logs). Estado atual: BREAKER=on baked.
uv run python -m scripts.load_test --target engine --breaker on --n 4 --concurrency 2 \
  --engine projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID_CASE2
```
**⚠️ Ajuste de narrativa (importante):** o breaker in-process abre **por-instância**; numa
frota multi-instância ele **não achata** o p95 no Console (testado: só tripa esporadicamente).
Então: o **flatten é o A/B LOCAL (Seção 3)**; o **engine deployado mostra a frota sob carga
(storm ~24s)**. NÃO prometa flatten no Monitoring. Ótimo p/ Q&A: *"um breaker fleet-wide precisa
de store compartilhado (Memorystore), não um dict de processo."*

**Para pré-assar uma janela OFF no p95:** redeploy com `BREAKER=off` (`UPDATE_RESOURCE=…4818…`)
e dirigir; hoje o engine está `BREAKER=on`.

---

## 7. Vídeo de fallback (rede de segurança do A/B) · **PENDENTE (capturar no ensaio)** ⚠️

O único asset ainda não gravado. Capture a resposta ON degradada+honesta (~2s) numa aba:
```bash
# 1 sessão, breaker já aberto (open_after=1), cenário lento -> resposta de fallback rápida
BREAKER_OPEN_AFTER=1 uv run python -m scripts.load_test --scenario slow_payment --breaker on --n 2 --concurrency 1
```
Grave a tela mostrando o breaker abrindo + a resposta honesta ("instabilidade; um humano
confirma"). Deixe o vídeo **aberto numa aba** no dia — é o backstop se o A/B ao vivo borrar.

---

## 8. Dia da apresentação — sequência e "o que mostrar"

Ordem de prioridade (se apertar): **A/B (Seção 3) > trace 15s (Seção 2) > cost/span (Seção 4)
> BQ tenant (Seção 5) > engine (Seção 6)**.

1. **Pré-flight** (Seção 0) + **warm-up** (Seção 1). ~5 min antes.
2. **Slide "Cascade" (p.9):** conceito, sem demo. Diga a inoculação do `max_iterations`.
3. **Slide "Contain" (p.10):** Beat 1 (trace 15s, aba já aberta) → Beat 2–3 (A/B no terminal,
   ao vivo; mostre `resilience.py` antes do ON) → vídeo de fallback.
4. **Slide "Govern" (p.11):** Beat 4 (gen_ai.cost.usd na trace) → Beat 5 (BQ tenant + alerta).
5. **Fechar:** "resiliente ✓, custo governado ✓ — resiliente ≠ seguro" → Caso 3.

**O que NÃO fazer ao vivo:** deploy/update do engine; contar com alucinação ao vivo; prometer
flatten no p95 do Console. Pontuado/instrumentado é pré-rodado; o A/B local é o único semi-live.

---

## 9. Troubleshooting — gotchas conhecidos (já resolvidos no código)

| Sintoma | Causa | Ação |
|---|---|---|
| `AttributeError: 'State' object has no attribute 'pop'` | ADK State não tem `.pop()` | já corrigido: `record_outcome` usa `.get()` |
| Alerta nunca dispara | filtro com `resource.type="global"` | já corrigido: cost-logs do engine são `cloud_run_revision` (o filtro usa isso) |
| A/B ON = OFF (sem contraste) no `--target engine` | breaker do engine é baked; flip local não afeta remoto | já corrigido: `--ab` rejeita `--target engine` (é local-only) |
| ON não achata no A/B local | breaker abre tarde com alta concorrência | use `concurrency < n` e `BREAKER_OPEN_AFTER=2` (as primeiras N calls abrem, o resto curto-circuita) |
| p95 do engine não achata | breaker in-process é **por-instância** | esperado; o flatten é o A/B local (Seção 6) |
| `gen_ai.cost.usd` ausente na trace | trace gerada sem `CASE=2` | regerar com `CASE=2` (Seção 2) |
| budget_guard cortando o OFF | `SESSION_BUDGET_USD` baixo | o `load_test` já neutraliza no A/B; para demo do budget, exporte um valor baixo de propósito |
| Nada roda / ADC falha | VM perdeu escopo `cloud-platform` | reautenticar a VM |

---

## Apêndice — valores do ambiente + IDs (Caso 2)

- **Projeto:** `YOUR_PROJECT_ID` (número `YOUR_PROJECT_NUMBER`)
- **Região:** `us-central1` · **Modelo:** `gemini-3.5-flash` (endpoint `global`)
- **Bucket staging:** `gs://YOUR_PROJECT_ID-agent-staging`
- **Trace pré-rodada (Beats 1+4):** `7d29dce757bc053633c0503d0fc68e56`
- **Engine CASE=2:** `projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID_CASE2` (display `financial-support-agent-c2`) — atualmente `BREAKER=on`
- **Engine CASE=1 (intacto):** `…/reasoningEngines/ENGINE_ID_CASE1`
- **BigQuery:** dataset `agent_eval`, tabela `cost_spans`
- **Métrica log-based:** `agent_cost_calls` · **Alert policy:** `13848242807096629668`
- **Deletar o engine C2 após o talk:** `python -c "import vertexai; from vertexai import agent_engines; agent_engines.get('projects/YOUR_PROJECT_NUMBER/locations/us-central1/reasoningEngines/ENGINE_ID_CASE2').delete()"`

Status de validação (2026-07-13): código ✅ (86 testes) · Beat 1 trace ✅ · Beats 2–3 A/B ✅ ·
Beat 4 cost/span ✅ · Beat 5 BQ ✅ · engine deployado ✅ · alerta criado (incidente = ingestão) ·
**vídeo de fallback = PENDENTE** · ensaio corte-a-corte = PENDENTE.
