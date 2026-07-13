# Caso 3 — Plano de implementação da demo pré-rodada ao vivo

> **Fonte da verdade para construir o caminho GCP do Caso 3 (Zero-Trust).** Escrito
> 2026-07-13 para ser retomado numa sessão nova (depois do `/clear`). Complementa
> `demos/case-3-demos.md` (o *quê/como* da demo) e `docs/case-3-fundamentos.md`
> (narrativa/slides) com o *plano de execução* contra um projeto Google Cloud real.
>
> **Como usar numa sessão nova:** leia este doc + `demos/case-3-demos.md` +
> `agent/README.md`. O estado do código está na seção 6. O **código está FEITO e verde**
> (Fase 1/2/4); o que falta é **provisionar o GCP (Fase 0, Owner)** e **validar o 403 ao
> vivo (Fase 2)**. Comece pela Fase 0.
>
> **O beat inegociável:** o **403 lado a lado** é o ÚNICO beat genuinamente real do talk
> inteiro. Todo este plano existe para protegê-lo. Validar end-to-end **antes** de gravar.

Slides do Caso 3 no deck: **S12** (divisor) · **S13** "The Confused Deputy" · **S14/S15**
"The model is not a security boundary" · **S16** "Close the Loop" · **S17** recap.
(Os `*-fundamentos.md` chamam de Slide 8/9/10 — numeração antiga; reconcilie as notes.)

---

## 1. Decisões travadas (não reabrir)

- **403 real = duas service accounts** (SA-A / SA-B). A tool consulta o BigQuery
  **impersonando** cada uma (keyless — casa com o "no long-lived keys" do SPIFFE). 100%
  GA, determinístico. O consentimento **3LO** vira **garnish pré-gravado** (Preview).
- **Entrega = semi-live + vídeo de fallback.** O A/B das duas credenciais roda ao vivo no
  palco (estilo Caso 2), com vídeo de fallback numa aba. (Supersede a decisão antiga
  "100% pré-gravado" do `case-3-demos.md §1.2`.)
- **Modelo de recurso = IAM per-tenant só.** Datasets por-tenant + IAM dão o 403; **RLS é
  narrada** como o row-scoping irmão (0 rows, não 403), **não mostrada**.
- **⚠️ Path A (a mecânica do 403, honestidade central):** RLS puro devolve **0 rows, NÃO
  403**. O 403 vem do **IAM** negando o recurso per-usuário (dataset per-tenant). User B
  **sem `dataViewer`** no dataset do A. O backend **captura o `Forbidden` REAL** — **NUNCA
  sintetiza** um 403 (isso mataria o único beat real). Supersede o `case-3-demos.md §8.2`.
- **`enforce_identity` CARREGA, não bloqueia.** Ele propaga o principal do usuário; quem
  recusa é o IAM no dado. Se o callback barrasse, a fronteira voltaria pra cima do código
  que o atacante manipula — o mesmo erro do "filtro na frente do modelo".
- **Escopo por `CASE=3`** — o registry ativa `invariants` (C1) + `resilience` (C2) +
  `identity` (C3). Um codebase, aditivo, C1/C2 byte-idênticos.
- **3º Agent Engine (CASE=3) = opcional/garnish, PULAR por padrão.** Um engine roda como
  UMA service account → não mostra dois 403 por-usuário. O artefato real é o **driver
  local** `identity_ab.py` (mesmo precedente do A/B local do C2).

---

## 2. Mapa produto → onde vive na demo

| Produto | Slide | Live vs. semeado | GA/Preview | Código |
|---|---|---|---|---|
| **IAM (per-tenant)** — o 403 | S15 | **semi-live** ⭐ | **GA** | `scripts/setup_case3_identity.sh`, `backends/customer_db.py` |
| **BigQuery** — read escopado pela identidade | S15 | **semi-live** | **GA** | `backends/customer_db.py::_read_bigquery`, `scripts/identity_ab.py` |
| **Row-Level Security** — row-scoping (narrada) | S14/S15 | explicado | **GA** | (narração; complemento do IAM) |
| **Cloud Audit Logs** — 2 identidades | S16 | **real (pós-run)** | **GA** | gerado pelas queries do `identity_ab.py` |
| **Agent Identity (SPIFFE) / 3LO / Auth Manager** | S14/S15 | **pré-gravado** | Preview | narração + vídeo do consentimento |
| **Eval flywheel** — o ataque vira caso adversarial | S16 | **live (offline)** | **GA** (Cloud Build) | `evals/data/eval_cases.json`, `evals/run_offline.py` |
| **Model Armor / SGP / Gateway+Registry+IAP** | S14/S16 | **explicado** | Preview | 1-liners ("nomeie muitos, narre um/dois") |

---

## 3. Fase 0 — Provisionamento (USUÁRIO faz antes) · precisa Owner p/ setIamPolicy

Script pronto e idempotente: **`agent/scripts/setup_case3_identity.sh`** (tags `[editor]`
vs `[OWNER]`). Rodar com uma conta **Owner** (as etapas de IAM exigem `setIamPolicy`).

```bash
cd ~/l400-managing-production-agents/agent
# revisar e rodar (Owner). Cria: 2 SAs, token-creator p/ a Compute SA impersonar,
# datasets tenant_cust001/002 + seed, IAM diferencial (jobUser + dataViewer per-tenant).
bash scripts/setup_case3_identity.sh
# habilitar BigQuery Data Access (DATA_READ) audit logs no Console (Owner).
# adicionar ao agent/.env: IDENTITY_SA_USER_A / IDENTITY_SA_USER_B
```

**Checklist de saída da Fase 0** (o pré-check do 403, antes de qualquer gravação):
```bash
bash scripts/setup_case3_identity.sh validate
# -> User A on tenant_cust001: RETORNA a linha (autorizado)
# -> User B on tenant_cust001: 403 Access Denied (o beat) — se NÃO negar, IAM está errado
```

---

## 4. Fases na nuvem (bloqueadas na Fase 0)

### Fase 1 — Código: bundle `identity` + backend BigQuery · ✅ FEITA (2026-07-13)
Tudo aditivo, C1/C2 byte-idênticos. **98 testes verdes** (12 novos em `test_identity.py`).
- `callbacks/identity.py` (novo): `enforce_identity` (carrier `before_tool`; self-guard
  `case<3`; carimba `data_access_principal`; nunca bloqueia).
- `callbacks/registry.py`: `register(CallbackBundle(name="identity", case=3, before_tool=[enforce_identity]))`.
- `backends/customer_db.py`: caminho `_read_bigquery(customer_id, principal)` atrás de
  `CUSTOMER_DB_BACKEND=bigquery`; impersonation keyless; **captura o `Forbidden` real**.
- `tools/customer.py`: passa `data_access_principal` ao backend (mock ignora; BQ usa).
- `config.py`: `customer_db_backend` / `bq_customers_dataset_template` / `bq_customers_table`.
- `prompts.py`: `with_identity_clause()` gated em `case>=3` (envolve as 3 builders).
- `deploy/agent_engine.py`: `google-cloud-bigquery` + env vars C3 (backend default `mock`).

### Fase 2 — O 403 end-to-end (semi-live) · **O GATE INEGOCIÁVEL** · ✅ LIVE-VALIDADO (2026-07-13)
```bash
# o clímax: mesmo prompt, User A autorizado vs User B negado (403 IAM real)
CASE=3 uv run python -m scripts.identity_ab \
  --principal-a sa-user-a@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --principal-b sa-user-b@YOUR_PROJECT_ID.iam.gserviceaccount.com
# (opcional) prefixar a ferida mock do S13: --wound
```
- Imprime a tabela lado a lado (**USER A → linha · USER B → 403 PERMISSION_DENIED**).
- **HONESTY GATE embutido:** o driver sai ≠0 e grita se o User B **não** for negado (403
  falso por IAM mal configurado) ou o User A não for autorizado. **Sem verde aqui, não grava.**
- **Palco:** *"mesmo prompt, identidade diferente, desfecho diferente. O modelo tentou; a
  infraestrutura disse não. Não filtramos a exfiltração — ela virou impossível por arquitetura."*
- **Honestidade:** o que bloqueia (IAM + BigQuery) é **GA**; o 3LO em volta é Preview.

### Fase 3 — Audit Logs, duas identidades (S16 parte 1) · ✅ CONFIRMADO (2026-07-13)
O pass B gera o Data Access log. Verificado: a entry mostra **as duas identidades**
(`principalEmail`=sa-user-b + `serviceAccountDelegationInfo.firstPartyPrincipal`=Compute SA)
+ `status.code=7` (PERMISSION_DENIED). DATA_READ ligado. Paga o "ninguém foi alertado" do S13.
Salvar o filtro/link do Logs Explorer pro dia.

### Fase 4 — O loop fecha (S16 parte 2) · flywheel · ✅ FEITA (2026-07-13)
- `exfil_injection` **adicionado** ao `evals/data/eval_cases.json` (prompt de injeção
  literal do palco). `CASE=3 uv run python -m evals.run_offline` lista os 2 casos
  cross-account (`adversarial_cross_account` + `exfil_injection`), gate **verde**.
- **Honestidade (landmine):** o gate offline é replay mock → prova que o **detetive**
  (`read_targets_session_customer`) dispara e não some. O **403 real (IAM) é a prova
  preventiva** (Fase 2, ao vivo). **NÃO** alegar que o gate offline testa o IAM.

### Fase 5 — Cloud Build gate · pega o caso novo de graça
`deploy/cloudbuild.yaml` já roda `pytest` + `run_offline`; o `exfil_injection` entra no
gate **sem mudança de CI**. Confirmar build verde. (Opcional: variante que o remove →
build vermelho = "a proteção não pode sumir".)

---

## 5. Trabalho SEM creds (feito / paralelizável)

1. ~~**Bundle `identity` + backend + testes.**~~ **✅ FEITO** (Fase 1).
2. ~~**Driver `identity_ab.py`.**~~ **✅ FEITO** (código; validação live precisa Fase 0).
3. ~~**`exfil_injection` no eval set.**~~ **✅ FEITO** (Fase 4).
4. ~~**Script de provisionamento `setup_case3_identity.sh`.**~~ **✅ FEITO** (Fase 0, roda com Owner).
5. **Ensaio corte-a-corte** com o `demos/case-3-runbook.md` (depois da Fase 0) + **vídeo de fallback**.

---

## 6. Estado atual do código (2026-07-13)

- **Fase 1/2/4 FEITAS e verdes (98 testes).** Arquivos novos: `callbacks/identity.py`,
  `scripts/identity_ab.py`, `scripts/setup_case3_identity.sh`, `tests/test_identity.py`.
  Alterados: `registry.py`, `customer_db.py`, `tools/customer.py`, `config.py`, `prompts.py`,
  `agent.py`, `sub_agents/*.py`, `deploy/agent_engine.py`, `evals/data/eval_cases.json`
  (+ 4 testes de seed reconciliados para 6 casos).
- **`case-3-demos.md` corrigido:** §8.2 (403 sintético morto), §8.1, §3.1, §1 e §8.6
  (conflações RLS↔403 → Path A honesto).
- **LIVE-VALIDADO (2026-07-13):** Fase 0 provisionada; 403 pela agente (A→linha / B→403 real
  do IAM); audit log com 2 identidades (status.code=7). Flywheel + 98 testes verdes.
- **PENDENTE (não-código):** gravar vídeo de fallback (o A/B) + 3LO consent · ensaio corte-a-corte.

---

## 7. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| **Fabricar o 403** (o antigo §8.2) mata o beat real | Backend captura o `Forbidden` REAL; `identity_ab.py` sai ≠0 se B não for negado. Validar Fase 0 antes de codar/gravar. |
| Over-claim "gate offline prova o 403" | Framing de 2 camadas: eval = detetive (mock); IAM = preventivo (live). Fixado no eval_cases.json e no §8.6. |
| Semi-live falha (rede/console) | Vídeo de fallback do A/B; o A/B é determinístico (2 queries BQ, sem storm). |
| IAM/dataset/token-creator exige Owner | Fase 0 = one-time pelo Owner (mesmo padrão da Fase 4 do C1). |
| Fidelidade ao slide "IAM + RLS" sem mostrar RLS | Narrar: 403 = IAM negando o recurso per-tenant; RLS = row-scoping irmão (0 rows). Mesma fronteira GA no dado. |
| 3LO/Auth Manager (Preview) não habilita | Já é garnish pré-gravado; o beat real (IAM+BQ) é GA e independe. Fallback GA = IAP+OIDC (blueprint). |
| Row errada ≠ campo errado (Q&A) | 403/IAM cobre **linha** (cross-account); PII demais numa linha autorizada → column-level/SDP/Model Armor egress (defesa em profundidade S16, NÃO o 403). |

---

## Referências
- `demos/case-3-demos.md` — spec da demo (cortes S8–S10-B, §8.1–8.9, honestidade).
- `docs/case-3-fundamentos.md` — slides + speaker notes + Q&A (Slide 8/9/10).
- `demos/case-3-runbook.md` — o dia da apresentação (corte a corte).
- `agent/scripts/setup_case3_identity.sh` — provisionamento (Fase 0).
- `agent/scripts/identity_ab.py` — o driver do 403 lado a lado (Fase 2).
- Memória: `l400-presentation` (Path A), `gcp-live-environment`, `edd-agentflux-narrative`,
  `demo-fidelity-not-100-match`.
