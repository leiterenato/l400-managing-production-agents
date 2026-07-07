# Avaliação de Agentes em Produção — Fundamentos e Decisões (Caso 1)

> Documento de referência consolidando toda a discussão conceitual sobre avaliação (eval) de
> agentes: geração do dataset de eval, avaliação contínua, replay vs. re-execução, o ciclo
> sintético↔produção, detecção de problemas com score verde, e o "juiz sem gabarito"
> (reference-free evaluation).
>
> Objetivo: material de trabalho reutilizável (não é slide final). Denso de propósito.

---

## Índice

1. [Contexto e enquadramento](#1-contexto-e-enquadramento)
2. [Os 4 desafios fundamentais](#2-os-4-desafios-fundamentais)
3. [Frente A — Geração e manutenção do eval set](#3-frente-a--geração-e-manutenção-do-eval-set)
   - [A1. Cold start](#a1-cold-start-não-existe-dado-no-início)
   - [A2. Staleness / manutenção](#a2-staleness--manutenção-o-custo-escondido)
   - [A3. Observability → eval](#a3-observability--eval-colher-produção-como-fonte-de-verdade)
4. [Frente B — Continuous Evaluation](#4-frente-b--continuous-evaluation)
   - [B1. Componentes mínimos](#b1-componentes-mínimos)
   - [B2. Quando rodar: pré vs. pós-submit](#b2-quando-rodar-pré-vs-pós-submit)
   - [B3. Escala para milhares de agentes](#b3-escala-para-milhares-de-agentes)
   - [B4. Release gate](#b4-release-gate-baseado-em-eval)
5. [Campeões de atenção (headline problems)](#5-campeões-de-atenção)
6. [Replay vs. Re-execução](#6-replay-vs-re-execução)
7. [Sintético + Produção: o flywheel](#7-sintético--produção-o-flywheel)
8. [Detecção com score verde: eval é memória, produção é alarme](#8-detecção-com-score-verde)
9. [Juiz sem gabarito (reference-free)](#9-juiz-sem-gabarito-reference-free)
10. [Camada 1 — verdade verificável](#10-camada-1--verdade-verificável)
11. [Meta-eval — calibração do juiz](#11-meta-eval--calibração-do-juiz)
12. [A melhor opção — escada de confiança](#12-a-melhor-opção--escada-de-confiança)
13. [Frases de efeito (compilado)](#13-frases-de-efeito-compilado)
14. [Decisões travadas e em aberto](#14-decisões-travadas-e-em-aberto)
15. [Caso 1 — Slides (diagramas + narração)](#15-caso-1--slides-diagramas--narração)
    - [15.1 Arco dos 4 slides](#151-arco-dos-4-slides)
    - [15.2 Slide 1 — Problem](#152-slide-1--problem)
    - [15.3 Slide 2 — One trace, many failure points](#153-slide-2--one-trace-many-failure-points)
    - [15.4 Slide 3 — EDD: a derivação (depth spike A)](#154-slide-3--edd-a-derivação-depth-spike-a)
    - [15.5 Slide 4 — Flywheel + Failure Clusters (depth spike B)](#155-slide-4--flywheel--failure-clusters-depth-spike-b)
    - [15.6 Demonstrações do Caso 1 — spec de build](#156-demonstrações-do-caso-1--spec-de-build)

---

## 1. Contexto e enquadramento

Base narrativa: slide "**Agent Evaluation: Bridging the Gap to Production**".

A ideia visual do slide é uma **lacuna (gap)** entre dois platôs:

- **Cool Agent Demo** (platô verde, à esquerda) — o agente que impressiona na demo.
- **Production Ready Software** (platô azul, à direita) — o agente confiável em produção.
- Entre eles, **"The Evaluation Gap"** — o vazio que separa demo de produção.
- Uma linha tracejada frágil ligando os dois lados, rotulada **"Current Evaluation Methods"** —
  sinalizando que os métodos atuais são insuficientes para atravessar a lacuna.

Mensagens de texto do slide:

- **Quality Blocker** — mover agentes de "demos legais" para software confiável está travado
  pela avaliação (evaluation).
- **Beyond Right or Wrong** — testes tradicionais são PASS/FAIL simples; avaliação de agente é
  *processo acima do output*; **como** o agente chega à solução importa mais que o resultado.
- **Challenges to Cross** — os 4 desafios listados na próxima seção.

Rodapé do slide: **Privacy, Safety & Security** — usado adiante para amarrar privacidade de
dados de produção e mascaramento de falhas críticas de segurança.

O Caso 1 é essencialmente o **setup do problema** que a técnica de EDD (Evaluation-Driven
Development) resolve. Observability é o **substrato** que sustenta a solução.

---

## 2. Os 4 desafios fundamentais

Os quatro desafios do slide são a **raiz de quase todos os problemas** deste documento. Usamos
tags para conectar cada problema ao desafio que o origina:

| Tag | Desafio | Essência |
|-----|---------|----------|
| **[ND]** | **Non-Determinism** | Muitos caminhos válidos; eficiência importa. Rodar duas vezes dá dois resultados. |
| **[CL]** | **Cascading Logic** | O estado importa; pequenos erros se acumulam ao longo da trajetória. |
| **[MC]** | **Manual Ceiling** | Logs e rotulagem manuais não escalam. |
| **[TE]** | **Tool-Env Coupling** | O agente precisa de "mundos" (ambientes/mocks) complexos para agir. |

---

## 3. Frente A — Geração e manutenção do eval set

Duas frentes de problema foram definidas. A Frente A trata de **como criar e manter o conjunto
de casos de avaliação**, antes e depois de desenvolver o agente.

### A1. Cold start (não existe dado no início)

1. **Paradoxo do bootstrap** — você precisa de eval set para saber se o agente funciona, mas
   precisa do agente em produção para gerar eval realista. Galinha e ovo. **[MC]**
2. **"Correto" não é um label, é um processo** — diferente de classificação, o ground truth de
   um agente é uma *trajetória aceitável*, não uma resposta única. Definir isso é caro e
   ambíguo. **[CL]**
3. **Armadilha do dado sintético** — gerar casos com LLM é o atalho óbvio, mas:
   - (a) distribuição limpa demais — não captura ambiguidade, erros de digitação, input
     adversarial real;
   - (b) viés autorreferencial — se o mesmo modelo gera o caso, roda o agente e julga, os pontos
     cegos ficam correlacionados;
   - (c) clusteriza no óbvio e não cobre a cauda longa, que é exatamente onde o agente quebra.
   **[MC]**
4. **Gargalo de rotulagem humana** — SME (especialista) rotulando trajetória não escala, é lento
   e caro; a concordância entre anotadores é baixa em tarefas subjetivas. **[MC]**
5. **Cobertura vs. representatividade** — sem tráfego real você está *chutando* se o eval cobre a
   distribuição verdadeira: intenções, níveis de dificuldade, combinações de tools, multi-turn,
   adversarial. **[MC]**
6. **Schema de um caso de eval é rico** — não é input→output. É input + estado do ambiente +
   tools disponíveis + trajetória esperada + variações aceitáveis + critério de sucesso. Modelar
   isso já é um problema.

### A2. Staleness / manutenção (o custo escondido)

> Provavelmente o **melhor gancho** do Caso 1: ninguém orça este custo.

7. **O eval decai a cada mudança** — trocar assinatura de tool, mexer no prompt, adicionar
   capability, mudar formato de saída: cada um invalida parte do eval set. A manutenção do eval
   frequentemente custa **mais** que o desenvolvimento do agente. **[TE]**
8. **Tensão brittleness × sensibilidade** — assertar trajetória exata quebra a cada refactor
   (frágil); assertar só a resposta final perde regressão de processo (cego). Não existe
   meio-termo gratuito. **[CL]**
9. **Ground truth também deriva** — num agente sobre uma base de conhecimento, a base muda → a
   resposta "correta" muda → o expected fica velho sozinho, sem ninguém tocar no agente.
10. **Explosão combinatória** — mais tools × mais turns × mais branches = crescimento não-linear
    de casos a manter.
11. **Eval rot / alerta cego** — na prática o eval set fica órfão, ninguém atualiza, times
    passam a ignorar o vermelho ("esse teste vive quebrado"). Fadiga de alerta mata a confiança
    na suíte. **[ND]**
12. **Versionamento e reprodutibilidade** — qual versão do eval set corresponde a qual versão do
    agente? Sem isso, não se reproduz um resultado nem se compara maçã com maçã.

### A3. Observability → eval (colher produção como fonte de verdade)

13. **De trace bruto a caso de eval** — o trace de produção não é um caso. Vira caso só depois
    de: seleção (o que é interessante vs. redundante), dedup (milhões de traces parecidos),
    anonimização e rotulagem (o trace **não vem com rótulo** de sucesso/falha). **[MC]**
14. **Sinal de feedback é raro e ruidoso** — feedback explícito (👎) é escasso; implícito
    (usuário reformulou, abandonou, repetiu) é ruidoso. Inferir "isso foi bom" de produção é um
    problema em si.
15. **Viés de sobrevivência** — produção só reflete o que os usuários atuais fazem com o agente
    atual. Não cobre capabilities que você ainda não lançou nem usuários que ainda não chegaram.
    Loop que reforça o presente.
16. **Não-replayabilidade do ambiente** — agente com efeito colateral (escreve em DB, chama API
    externa) não pode ser simplesmente "replayado": o estado externo mudou, o side-effect não é
    idempotente. Reconstruir o mundo do trace é caro ou impossível. **[TE]**
17. **Custo e cardinalidade da captura** — logar trajetória completa (cada chamada de LLM, tool,
    estado intermediário) a escala é caro: storage, sampling, cardinalidade. O que logar em
    fidelidade total vs. amostrado?
18. **Privacidade e compliance** — dado de produção tem PII/sensível. Usar como eval exige
    governança, consentimento, retenção. (Amarra no rodapé *Privacy, Safety & Security*.)
19. **Lag de frescor** — do "usuário interagiu" até "virou caso no eval" há uma latência. Quão
    atualizado seu eval realmente está?

---

## 4. Frente B — Continuous Evaluation

A Frente B trata de **rodar avaliação continuamente** ao longo do ciclo de vida do agente.

### B1. Componentes mínimos

O que precisa existir para "continuous eval" não ser só um slogan:

- Store de eval set **versionado**
- Runner/orquestrador que executa o agente contra os casos
- **Ambiente / sandbox / mock world** para as tools **[TE]**
- Camada de **judge / scoring** (regra + LLM-as-judge + human-in-loop)
- Store de métricas + baseline + detecção de regressão
- Integração CI/CD (pré/pós-submit)
- **Policy engine do release gate**
- Alerting e ownership

### B2. Quando rodar: pré vs. pós-submit

20. **Pré-submit é lento demais** — agente é multi-turn, várias chamadas de LLM + latência de
    tool. Rodar milhares de casos bloqueando o PR = minutos a horas → mata a velocidade do dev.
    **[CL]**
21. **Pré-submit é caro demais** — cada run de PR queima token/compute. Full eval por PR é
    proibitivo a escala.
22. **Pré-submit é flaky** — não-determinismo faz o gate falhar por acaso → bloqueia PR legítimo
    → dev perde confiança e começa a burlar o gate. **[ND]**
23. **Pós-submit chega tarde** — rodar depois do merge pega a regressão com o código já no main
    (talvez já deployado). Lag de detecção e a pergunta de quem faz rollback.
24. **Seleção de casos é difícil** — o ideal é rodar só os casos afetados pela mudança, mas não
    há grafo de dependência limpo de "prompt → caso de eval". Impact analysis para agente é
    problema aberto.

### B3. Escala para milhares de agentes

25. **Explosão de custo** — N agentes × M casos × K runs (repetição para média por causa do ND)
    × custo por run. Continuous eval a escala pode custar **mais que rodar os agentes em
    produção**. É o headline. **[ND]**
26. **Contenção de infra / rate limit** — o eval disputa a mesma capacidade de LLM que a
    produção. Eval mal dimensionado dá DoS na própria produção ou estoura rate limit.
27. **Custo e confiabilidade do juiz** — LLM-as-judge **dobra** o custo de LLM, e o juiz também
    deriva. *Quem avalia o avaliador?* É preciso meta-eval do juiz. **[MC]**
28. **Heterogeneidade** — mil agentes não são uniformes (tools, domínios, critérios de sucesso
    diferentes). Harness único não serve; config por agente vira sprawl.
29. **Sinal vs. ruído na agregação** — com milhares de agentes e métrica ruidosa, separar
    regressão real de flutuação é difícil. Taxa de falso positivo/negativo do gate vira problema
    de primeira ordem. **[ND]**
30. **Orquestração e isolamento** — scheduling, retry, provisionamento de ambiente por run,
    paralelismo, isolamento entre execuções. Complexidade operacional real.

### B4. Release gate baseado em eval

31. **Não existe 100% verde** — agente tem *distribuição* de score, não pass/fail. Onde cortar?
    95%? E casos precisam ser tiered (must-pass de segurança vs. nice-to-have). **[ND]**
32. **Agregado esconde a cauda** — score geral sobe 2%, mas o cenário crítico de segurança
    passou a falhar. Métrica agregada mascara exatamente a falha que mais importa. **[CL]**
33. **Gate não-determinístico não é gate** — se o gate falha aleatoriamente, ele não decide nada.
    Para distinguir regressão real de variância você precisa de significância estatística → mais
    runs → mais custo. Trade-off confiabilidade × custo do gate. **[ND]**
34. **Goodhart / overfitting ao eval** — no instante em que o score vira gate, as pessoas
    otimizam para o eval, não para qualidade real. Vazamento do eval set para o prompt. O eval
    para de medir o que importa.
35. **Governança do override** — quando o gate bloqueia, quem decide furar? Hotfix de emergência
    bypassa? Sem política clara, o gate é ignorado no primeiro incidente.
36. **Qualidade é multidimensional** — correção, latência, custo, segurança, tom. Melhorar um
    eixo regride outro. O gate precisa raciocinar sobre trade-offs, não sobre um número escalar.

---

## 5. Campeões de atenção

Para fisgar a plateia, **não liste os 36**. Lidere com estes 6, contraintuitivos ou assustadores:

1. **O paradoxo do cold start** (#1) — "você precisa do agente em produção para avaliar o agente
   que quer colocar em produção."
2. **O eval decai a cada commit** (#7) — manutenção do eval > custo de desenvolvimento. Ninguém
   orça isso.
3. **Não-determinismo quebra a ideia de gate** (#33) — "seu teste pode ficar vermelho sem você
   mudar nada."
4. **Continuous eval pode custar mais que produção** (#25) — o número que faz o diretor prestar
   atenção.
5. **O agregado esconde a falha de segurança** (#32) — amarra direto no rodapé *Privacy, Safety
   & Security*.
6. **Quem avalia o avaliador?** (#27) — LLM-as-judge não é chão firme.

**Fio condutor (tese do L400):** *observabilidade é o substrato.* Ela quebra o cold start (#1),
o teto manual (#4, #13) e alimenta o eval contínuo. Transforma "gerar eval" de um evento único
de cold start em um **fluxo** que se auto-atualiza a cada mudança.

---

## 6. Replay vs. Re-execução

A diferença é **quem produz o comportamento que você vai avaliar**.

- **Re-execução = rodar o agente de novo, ao vivo.** Você dá o input, e o agente pensa, chama as
  tools, recebe respostas e produz uma resposta nova, do zero. Como é ao vivo, pode seguir um
  caminho diferente do anterior.
- **Replay = reassistir uma gravação.** Você pega o registro de uma execução que já aconteceu
  (o trace: cada passo, cada chamada de tool, cada resposta recebida) e toca de volta, como um
  vídeo. Nada novo é gerado.

**Analogia (xadrez):**
- Re-execução = sentar o jogador de novo na mesma posição e pedir para jogar outra vez (pode
  jogar lances diferentes).
- Replay = pegar a partida já gravada e revisar lance a lance (nada novo acontece).

### Tabela comparativa

| | **Replay** (reassistir gravação) | **Re-execução** (rodar de novo) |
|---|---|---|
| Pergunta que responde | "O que o agente **fez**, e foi bom?" | "O que o agente **novo faz**, e é bom?" |
| Serve para | Analisar produção, transformar traces em casos, debugar, julgar barato | Pegar regressão de uma versão nova; medir consistência |
| Custo | Barato (não roda LLM de novo) | Caro (roda tudo outra vez) |
| Limitação central | Fala **só** da versão que gerou a gravação | Precisa de ambiente/tools disponíveis e seguros |

**Ponto que trava a arquitetura:** replay **não** consegue testar uma mudança sua. Se você mexeu
no prompt, o prompt novo *nunca rodou* na gravação — você só tem o comportamento antigo. Para
saber se sua mudança melhorou algo, você **tem** que re-executar.

### O meio-termo: re-executar com tools gravadas

Re-executa o agente ao vivo (comportamento fresco, prompt novo), mas quando ele chama uma tool,
em vez de bater na API/banco real, você **devolve a resposta registrada no trace**. Assim:

- O raciocínio é novo (testa a versão nova).
- As tools ficam baratas, seguras e previsíveis (sem efeito colateral).
- **Porém:** se o agente novo seguir um caminho diferente e chamar uma tool com argumentos que a
  gravação não tem, não há resposta gravada → é preciso cair numa tool real ou num mock.

Essa escolha (replay puro / re-execução / híbrido) decide diretamente: custo (#25), contenção de
rate limit (#26), efeito colateral (#16) e flakiness (#22).

### Os dois trabalhos da re-execução

Re-execução tem **dois usos distintos**, não um só:

- **(a) Regressão entre versões** — rodei o agente novo, ele regrediu?
- **(b) Consistência dentro de uma versão** — rodei o *mesmo* agente N× no mesmo caso; quanto a
  resposta varia? Uma média boa pode esconder "1 em 5 vezes ele faz besteira". Ataca o
  **Non-Determinism [ND]** de frente e é um sinal que quase ninguém mede.

### Ambiente simulado

A re-execução roda em **sandbox / ambiente simulado** (o ADK oferece ferramentas para isso), não
necessariamente em produção. Isso a torna:

- **Segura** — sem efeito colateral real.
- **Reproduzível** — você controla o ambiente em vez de depender do estado vivo de produção.

### Onde cada um mora no processo

- **Replay** → colher produção, criar casos, analisar o que aconteceu (Fase 2, descoberta).
- **Re-execução** → loop de desenvolvimento, gate pré/pós-submit e teste de consistência
  (Fase 1 + confiabilidade).

Ambos os temas são fundamentais em **partes diferentes** do processo de eval.

---

## 7. Sintético + Produção: o flywheel

**Decisão travada:** usar **os dois** — começar com eval sintético e depois validar/realimentar
com produção. Um retroalimenta o outro. É o melhor dos mundos.

Faz sentido porque **espelha a linha do tempo real**: no cold start você não tem produção, então
sintético é a única opção; depois a produção entra e vira fonte de verdade. Não são concorrentes
disputando o palco — são **duas fases do mesmo ciclo**.

### O arco (duas fases + flywheel)

> **Fase 1 — Cold start:** sintético para dar o pontapé → agente bom o suficiente para subir.
> **Fase 2 — Produção no ar:** observability colhe traces reais → corrige a distribuição
> sintética, revela gaps, alimenta o eval contínuo.
> **O ciclo:** cada feature nova reabre um mini cold start → semente sintética → correção pela
> produção. **Flywheel.**

### Quatro afiações importantes

1. **Não é "sintético e depois joga fora".** Produção não *substitui* o sintético — ela
   **corrige e faz crescer**. O sintético continua necessário para toda capability que ainda não
   tem tráfego. **Cold start é uma condição recorrente, não um evento único.**
2. **Produção valida duas coisas** (vale separar):
   - o **agente** (vai bem no mundo real?);
   - o **próprio eval set** (meu sintético era representativo? casos que passavam correspondiam a
     usuários felizes?). Este segundo é o mais poderoso: produção é o juiz que diz se seu eval
     media a coisa certa.
3. **A "revelação do gap"** é o beat mais forte: produção mostra que a distribuição sintética era
   limpa demais; usuários fazem o que você não imaginou. Amarra no slide 3 (a lacuna) e na tese.
4. **Cuidado com a palavra "validar".** Produção **não vem rotulada** (#13, #14). "Validar com
   produção" esconde trabalho: seleção, dedup, anonimização e um juízo de sucesso/falha. Assuma
   esse custo explicitamente.

**Encaixe na tese:** sintético é o que você faz **sem** o substrato; observability é o substrato
**ligando**.

---

## 8. Detecção com score verde

**Pergunta central:** eval sintético excelente, agente em produção — como detectar problema se o
score está bom?

### Por que verde ≠ sem problema

> Um score sintético verde não prova ausência de problema. Prova ausência de problema **nos casos
> que você imaginou.** Os problemas de produção vivem na lacuna entre "o que você imaginou" e "o
> que o usuário realmente faz". Por definição, o eval sintético é cego a eles.

Logo: **o alarme não pode vir do eval; tem que vir da produção.**

**Reframe central:**
- **Eval sintético = memória de regressão.** Pega o que você *já sabe* que pode quebrar. Roda
  pré-submit. Verde é o esperado.
- **Observability de produção = descoberta.** Acha o que você *não sabe* que está quebrado. É
  daqui que vem o sinal novo.

**Por que verde e problema coexistem:**
- **Gap de distribuição** — usuário faz o que não está no eval.
- **Deriva do ground truth** — o mundo mudou; o "correto" do caso congelou.
- **Goodhart** — você afinou o agente *para* o eval; ele gabarita e generaliza mal.
- **Ponto cego do juiz** — o LLM-judge aprova o que o usuário real detesta (tom, formato, erro
  sutil).
- **Não-funcional invisível no sintético** — latência, custo, timeout de tool, dado sujo real; o
  sandbox é limpo demais.

### As camadas de sinal de produção

Nenhum sinal sozinho basta — cada um é raro, ruidoso ou parcial. A força está em **triangular**.
Do mais barato/ruidoso ao mais caro/preciso:

| Camada | Sinais | O que pega | Cuidado |
|---|---|---|---|
| **Comportamento implícito** | reformulou, repetiu, abandonou, escalou para humano, corrigiu ("não, eu quis dizer…"), conversa longa para algo simples | insatisfação/falha sem rótulo | ruidoso; correlação, não causa |
| **Feedback explícito** | 👍/👎, nota, texto livre, ticket de suporte | sinal mais limpo | raro e enviesado (só muito feliz ou muito bravo responde) |
| **Operacional/sistema** | latência, timeout, taxa de erro de tool, custo por interação, loop detectado, disparo de guardrail | problema objetivo e barato | não fala de qualidade, só de saúde |
| **Juiz automático sobre tráfego real** | LLM-as-judge em traces amostrados, rubrica *sem referência*: groundedness, seguiu política, respondeu de fato | **qualidade sem rótulo e sem gabarito** — o mais poderoso | dobra custo; o juiz precisa de calibração |
| **Consistência** | pega caso real, re-executa N× no sandbox, mede variância | fragilidade que a média esconde | custo de N execuções |
| **Amostragem + revisão humana** | amostra (aleatória + direcionada aos anômalos) → humano revisa | padrão-ouro; vira caso novo e calibra o juiz | caro; use direcionado |

### "Algo mudou" vs. "está errado"

Dois tipos de sinal com dificuldades diferentes:

- **"O agente está errado"** (qualidade) — difícil; precisa de juiz ou humano, porque não há
  gabarito em produção.
- **"Algo mudou"** (drift/anomalia) — mais fácil; é estatística pura. Você não precisa saber o
  que é certo para detectar que a distribuição do comportamento **mudou** (de repente o agente
  usa uma tool 3× mais, ou o tamanho da resposta despencou). Alerta na mudança, investiga depois.

### O flywheel fecha aqui

> problema detectado em produção → curado num caso → o eval sintético agora cobre aquilo → da
> próxima vez a regressão é pega **pré-submit**.

Resposta completa: **você para de usar o eval como alarme. O eval é a memória; a produção é o
alarme. E a produção ensina o eval.**

**Cheiro ruim:** um score de eval que fica verde para sempre, com produção viva, **é um sinal de
alerta** — significa que seu eval parou de aprender e se descolou da realidade. A saúde do eval
se mede por **quantas vezes a produção ainda te surpreende.**

---

## 9. Juiz sem gabarito (reference-free)

É o **transdutor** que converte trace cru de produção (sem rótulo) em sinal de qualidade que
realimenta o eval. Sem ele, a observabilidade coleta, mas não *ensina*.

### A chave: achar outra âncora de verdade

Comparar com a resposta certa é a âncora fácil. Sem ela, é preciso outras âncoras — e só existem
umas poucas. Toda técnica cai numa delas:

1. **A própria entrada/contexto** — a resposta é fiel ao que foi dado/recuperado?
2. **Verdade verificável por execução** — roda e vê (código, SQL, plano).
3. **Regras/políticas conhecidas** — violou uma restrição dura?
4. **Consistência** — o agente concorda consigo mesmo em várias execuções?
5. **Julgamento de um modelo sobre rubrica** — LLM-as-judge.
6. **Comparação relativa** — A é melhor que B, sem verdade absoluta.
7. **Reação do usuário** — implícita/explícita.

Organizar a discussão **por âncora** (não por ferramenta) mostra que não é um truque, é um espaço
fechado de opções.

### O leque de opções

| Âncora | Técnica | O que pega | Custo | Cuidado |
|---|---|---|---|---|
| Regras | **Checagem determinística**: schema/JSON válido, tamanho, regex, lista proibida (PII, preço acima do teto, promessa proibida) | falha mecânica e violação de política | ~zero, determinístico | não fala de "foi bom", só de "é válido" |
| Execução | **Verificação executável**: roda o código/SQL/plano gerado; a tool retornou sucesso? | correção *factual* onde há como executar | baixo | só serve para saída verificável |
| Contexto | **Groundedness/fidelidade** (tríade RAG): toda afirmação rastreia até o contexto? o contexto era relevante? a resposta responde à pergunta? | **alucinação sem precisar do gabarito** | médio | precisa da fonte registrada no trace |
| Modelo | **LLM-as-judge por rubrica** — decomposto em perguntas binárias ("respondeu o que foi pedido? S/N", "inventou fato fora do contexto? S/N") | qualidade subjetiva | dobra custo de LLM | vieses do juiz (ver abaixo) |
| Comparação | **Pairwise / champion-vs-challenger**: "A ou B é melhor?" | regressão entre versões | médio | modelo é bom em relativo, ruim em absoluto |
| Consistência | **Self-consistency**: roda N×, mede divergência; auto-crítica | fragilidade e baixa confiança | N execuções | auto-crítica sozinha é fraca (o modelo racionaliza) |
| Processo | **Avaliação de trajetória**: usou a tool certa? entrou em loop? recuperou de erro? passos/custo no envelope? | falha de *processo* (o "process over output") | médio | precisa do trace completo |
| Humano | **Amostra revisada por humano** | padrão-ouro | alto | não escala — papel dele é **calibrar**, não julgar tudo |

### Quem julga o juiz? (meta-problema)

O juiz é um LLM com **as mesmas fraquezas** do agente. Precisa entrar no slide:

- **Vieses conhecidos do juiz:** posição (prefere a primeira/segunda opção), verbosidade (prefere
  resposta mais longa), auto-preferência (prefere saída da própria família de modelo), bajulação,
  calibração ruim em nota absoluta (amontoa tudo em 4/5).
- **Meta-eval é inegociável:** mede-se a **concordância juiz-vs-humano** numa amostra rotulada. Um
  juiz só é usável se concorda com humano. É isso que dá credibilidade ao número no gate.
- **Deriva do juiz:** o modelo do juiz atualiza → scores mudam → você acha que o agente mudou, mas
  foi o juiz. **Versione e congele o juiz** junto com o eval set.

---

## 10. Camada 1 — verdade verificável

Objetivo: **tirar o LLM da jogada sempre que possível**, porque o verificável não tem o problema
de "quem julga o juiz". Três mecanismos, do mais forte ao mais limitado.

**1. Verificação por execução (o ambiente é o juiz).** Onde a saída é executável, não pergunte
"foi boa?", pergunte "funcionou?": código roda e passa nos testes? SQL executa e retorna? a tool
devolveu sucesso e o estado mudou como esperado? Objetivo, binário, sem meta-problema. Limite: só
serve para saída executável.

**2. Checagem por invariantes / propriedades (o mais subestimado — a aposta principal).** Você
não sabe a resposta certa, mas sabe **propriedades que a resposta certa obrigatoriamente
satisfaz**, derivadas da lógica da tarefa, não de um gabarito:

- soma dos itens = total;
- valor do reembolso ≤ cobrança original;
- a query só toca tabelas permitidas;
- no roteiro, cidade de chegada de um voo = cidade de partida do próximo.

Reference-free de verdade: barato, determinístico, pega **erro semântico** (não só formato). O
trabalho intelectual está em *derivar* os invariantes; uma vez derivados, são rocha. É o item
mais defensável tecnicamente do Caso 1.

**3. Groundedness / fidelidade (para agente com RAG/tools).** A tríade, toda sem gabarito:
contexto relevante? resposta fiel ao contexto (rastreia cada afirmação até a fonte)? resposta
responde à pergunta? Implementável **barato, sem LLM cheio**: modelo de entailment (NLI) pequeno,
decomposição em afirmações atômicas + verificação de span citado.

- **Limite honesto:** groundedness pega *alucinação*, não *correção*. Uma resposta pode ser 100%
  fiel a uma fonte errada. **Fidelidade ≠ verdade.**
- **Requisito escondido:** exige a fonte registrada no trace → requisito de observability.

**Melhor da Camada 1:** invariantes + execução. É a única parte de "qualidade" que se consegue
gatear sem depender de um LLM opinar. Groundedness é o segundo lugar (ótimo para RAG-pesado, mas
é proxy).

---

## 11. Meta-eval — calibração do juiz

Como saber se o LLM-judge é confiável e mantê-lo confiável, sem humano revisar tudo.

**1. Um "conjunto-âncora" rotulado por humano.** Algumas centenas de casos, bem rotulados,
cobrindo o importante + os ambíguos/difíceis. Roda-se o LLM-judge nele e mede-se a concordância
juiz-vs-humano. É isso que autoriza confiar no número do gate.

**2. Meça a métrica certa (a pegadinha que a maioria erra).** Não é "acurácia geral". Se 95% do
tráfego está OK, um juiz que só diz "passou" tem 95% de acurácia e é **inútil**. O que importa é
**precision/recall na classe de falha** — a capacidade de pegar o que está errado:

- **Falso negativo** (deixou passar falha real) = perigoso → em fluxo crítico, minimize isso
  mesmo pagando mais falso positivo.
- **Falso positivo** (barrou o que era bom) = ruído/custo → mata a confiança no gate.

Calibra-se o *threshold* do juiz nessa matriz de confusão, conforme o risco do fluxo.

**3. Gaste humano onde há desacordo (active learning), não aleatoriamente.** O rótulo humano caro
vai para: (a) casos onde juiz e humano divergem; (b) casos de baixa confiança do juiz. É onde
cada dólar de rotulagem ensina mais.

**4. Versione e re-calibre.** O conjunto-âncora não é one-shot: o juiz deriva, a distribuição
muda. Ao trocar modelo/prompt do juiz, **revalide contra o âncora antes de confiar.** Congele o
juiz junto com o eval set.

**5. Onde a regressão infinita para.** "Quem julga o juiz? Outro juiz?" — não. A recursão
**termina num pequeno conjunto humano.** Isso é força, não fraqueza: não existe eval sem uma
âncora humana mínima; o mérito da engenharia é **minimizar e mirar** essa âncora, não eliminá-la.

**Truques baratos que aumentam a calibrabilidade do juiz:**

- rubrica binária decomposta (a maior alavanca);
- painel de juízes com voto (reduz viés de juiz único);
- troca de posição no pairwise (roda A-B e B-A, mata viés de posição);
- self-consistency do juiz (roda N×; um juiz que muda de ideia no mesmo input é não-confiável);
- exigir que o juiz **cite a evidência antes do veredito** (melhora e fica auditável).

---

## 12. A melhor opção — escada de confiança

A melhor opção **não é uma técnica** — é uma disciplina de ordenar por confiabilidade e
**encolher a superfície subjetiva**. É um **funil por custo/risco**:

1. **Camada 1 — determinístico, em 100% do tráfego** (formato, regras, execução, groundedness
   onde dá). Mata o óbvio de graça, sem meta-problema. **Maximize verdade verificável aqui.**
2. **Camada 2 — LLM-judge por rubrica decomposta, em amostra** (aleatória para baseline +
   direcionada aos casos que passaram na Camada 1 mas têm sinal ruim de produção). Só o
   genuinamente subjetivo chega aqui.
3. **Camada 3 — humano numa amostra pequena + em todo desacordo juiz-vs-humano.** O humano
   **calibra o juiz e vira caso novo** — não carimba tudo.

**A jogada vencedora: inverta o default.** Quase todo time começa com LLM-judge e depois pendura
uns checks. O caminho robusto é o contrário — começa por verdade verificável e trata o LLM-judge
como *fallback do resíduo*, com conjunto-âncora humano obrigatório para esse resíduo.

**Duas convicções (ponto de vista, não survey):**

- **A alavanca nº 1 é decompor qualidade vaga em critérios binários verificáveis.** É o que
  transforma um "nota 1-5 no feeling" (instável, não-gateável) em algo confiável para barrar
  release. Se tirar uma única mensagem técnica do Caso 1, é essa.
- **Reference-free maduro = "empurrar o máximo para verdade verificável e usar o juiz-LLM só para
  o resíduo subjetivo — sempre com meta-eval."** Quem inverte isso (LLM-judge para tudo) constrói
  um número bonito em que ninguém confia.

### O espectro de verificabilidade do domínio

O mix ótimo depende de **quão verificável é o domínio do agente**:

| Domínio do agente | Quem carrega o eval |
|---|---|
| **Verificável** (código, dados, transação estruturada) | Camada 1 carrega 80%+; juiz é resíduo pequeno |
| **Subjetivo** (redação, suporte empático, conselho aberto) | Camada 1 carrega pouco; juiz + calibração humana pesam muito |

Isso decide se a **estrela do Caso 1** é a bateria de invariantes (domínio verificável) ou a
mecânica de calibração do juiz (domínio subjetivo). **Pergunta em aberto:** qual o domínio e o
tipo de saída do agente do Caso 1?

---

## 13. Frases de efeito (compilado)

- *"Você precisa do agente em produção para avaliar o agente que quer colocar em produção."*
  (cold start)
- *"Cold start não é um evento, é uma condição recorrente."*
- *"Seu teste pode ficar vermelho sem você mudar nada."* (não-determinismo)
- *"Continuous eval pode custar mais que rodar os agentes em produção."*
- *"O agregado esconde exatamente a falha de segurança que mais importa."*
- *"O eval é a memória; a produção é o alarme. E a produção ensina o eval."*
- *"Um eval que fica verde para sempre, com produção viva, é um cheiro ruim: parou de aprender."*
- *"A saúde do seu eval se mede por quantas vezes a produção ainda te surpreende."*
- *"Sem gabarito, você não pergunta 'essa é a resposta certa?'. Você pergunta 'essa resposta é
  fiel ao contexto, válida pelas regras e verificável na execução?' — e só o que sobra vai para o
  juiz."*
- *"Não tente construir um juiz melhor. Construa um problema que precise de menos juiz."*
- *"Sintético é o que você faz sem o substrato; observability é o substrato ligando."*

---

## 14. Decisões travadas e em aberto

**Travadas:**

- Usar **sintético + produção** em ciclo (flywheel), começando pelo sintético e realimentando com
  produção.
- Abordar **replay E re-execução** na apresentação — são fundamentais em partes diferentes do
  processo.
- Re-execução roda em **ambiente simulado** (ADK), não necessariamente em produção.
- Detecção pós-deploy vem da **produção** (eval = memória, produção = alarme), não de um score
  sintético verde.
- Reference-free segue a **escada de confiança / funil**: verdade verificável primeiro, juiz-LLM
  no resíduo, humano calibra.

**Em aberto:**

- **Escolha replay puro / re-execução / híbrido (tools gravadas)** como eixo explícito de
  arquitetura da Fase 2 (afeta custo, rate limit, side-effect, flakiness).
- **Domínio do agente do Caso 1** (verificável vs. subjetivo) — decide qual ponta puxar como
  protagonista (invariantes vs. calibração do juiz).
- **Threshold e tiers do release gate** (must-pass de segurança vs. nice-to-have; significância
  estatística vs. custo).
- **Política de governança do override** do gate.
- **Retoque do Slide 2 (FEITO 2026-07-06):** trace agora é o zoom honesto da espinha-âncora
  (`main → refund specialist → look up → issue → reply`), com **banda de check agrupada** sobre as 2
  decisões e speaker notes que abrem citando o Slide 1 e fecham entregando o Slide 3. Spec em §15.3.
- **Split do Slide 3 (FEITO 2026-07-06):** o antigo "EDD + flywheel" virou **dois** slides — **Slide
  3 = a virada/EDD** (a *derivação* contrato→invariante→case é a estrela; resolve cold start; demo
  pt.1; §15.4) e **Slide 4 = flywheel + Failure Clusters** (depth spike B, o "porquê"; resolve rot;
  demo pt.2; §15.5). Caso 1 = **4 slides**. Motivo: 8 reveals + 2 demos num slide = sobrecarga; a
  derivação virava YAML estático e o Spike B (Failure Clusters) sumia. Arco agora macro→micro→mezzo→macro.

**Pendências dos slides do Caso 1:**
- **Escala do Google no Slide 4, Reveal 6** — ✅ RESOLVIDO (2026-07-07): **qualitativo, SEM número** ("roda em produção no Google / I can't share the numbers"). Usuário não pode citar números do Google; a prova concreta é a demo (Reveal 5). Não reintroduzir número.
- **Títulos de palco** — ✅ CRAVADOS (2026-07-07). Slide 4 e título ajustados pelo usuário. Set recomendado: S1 "Why 'it passed' isn't enough" · S2 "Life of a request" · S3 "Write the test before the agent" · S4 "The Quality Flywheel" (subtítulos em §15).
- **Slide 4 refeito** — ✅ (2026-07-07): Failure Clusters de volta como nó-herói + gate com 2 ramos + anel de volta; título "The Quality Flywheel". Spec em §15.5.
- **Fronteira de mock das demos** — spec + recomendação documentadas em §15.6; o usuário confirma ao construir (demos ficam pra depois; slides primeiro).
- **Domínio verificável confirma invariantes como estrela** (§12) — já refletido (financeiro: refund/PII).
- **Verificar Semana 1:** confirmar na doc pública o método `generate_loss_clusters`, a taxonomia default e o status (GA/Preview) do Failure Clusters — o Slide 4 depende visualmente desse nó.

---

## 15. Caso 1 — Slides (diagramas + narração)

> Os 3 slides do Caso 1 (âncora, ~8 min). Diagramas em Mermaid (para converter em blocos animados
> no Google Slides), ordem de animação, speaker notes em **inglês simples/factual** (apresentador
> não-nativo), e defesas de Q&A. Domínio do agente: atendimento financeiro que **lê PII + emite
> reembolso** (domínio verificável → invariantes carregam).

### 15.1 Arco dos 4 slides

Regra de câmera: **macro → micro → mezzo → macro** (estabelecimento → detalhe → artefato → sistema).
Cada slide fecha numa lacuna que o próximo abre.

| Slide | Altitude | Job | Fecha em |
|---|---|---|---|
| **1 · Problem** | macro (o sistema) | arquitetura = palco: dores espaciais nos balões + temporais na linha do tempo; fecha na conclusão (topo, por último) | "o score verde mente → 2 lacunas" |
| **2 · One trace** | micro (1 pedido) | observar + julgar cada camada, sem gabarito | "sei julgar 1 pedido — mas não tenho casos e eles apodrecem" |
| **3 · EDD (a virada)** | mezzo (o artefato) | **derivação** contrato → invariante → case; resolve o **cold start**; demo pt.1 | "cold start resolvido — mas a spec pode estar errada e os casos apodrecem" |
| **4 · Flywheel + o "porquê"** | macro (o loop) | flywheel **mantém vivo** (rot) + **Failure Clusters** nomeiam a causa + limite honesto + escala; demo pt.2 | "um ataque hoje vira um teste pra sempre → Caso 2" |

**Split decidido (2026-07-06, revisado):** o antigo Slide 3 (EDD + flywheel num slide só) carregava
8 reveals + as 2 partes da demo — conteúdo de dois slides. Dividido: **Slide 3 = a virada/EDD** (a
*derivação* do contrato é a estrela, resolve cold start, demo pt.1); **Slide 4 = o flywheel + o
depth spike B** (Failure Clusters = o "porquê", resolve rot, demo pt.2). Casa com `case-1.md §8`
(Slide 3 = EDD / Slide 4 = flywheel). Caso 1 passa de 3 → **4 slides**.

**Por que a divisão fortalece:** o flywheel é a metade *familiar* (MLOps loop — a plateia já viu a
forma); o payload L400 é a *derivação* (contrato → cases) e o *"porquê"* (Failure Clusters). Num
slide só, a derivação virava dois YAMLs estáticos e o Failure Clusters (2º depth spike prometido)
sumia. Separados, cada metade diferenciada ganha palco.

**Slide 1 reformulado (2026-07-06, versão final):** arquitetura-como-palco + linha do tempo
(`Demo → Production`); é também o **diagrama-âncora acumulativo** do talk — Caso 2 ataca o `Payment
system` (dependência lenta), Caso 3 ataca `look up customer → Customer database` (RLS/identidade) + o
`Fraud-check service` externo (A2A). Termômetro cortado; a **conclusão** ocupa o topo e é revelada por
último. A câmera é **macro → micro → macro** (Slide 1 estabelece o sistema, Slide 2 dá zoom na espinha,
Slide 3 puxa pro loop). Detalhes em §15.2.

### 15.2 Slide 1 — Problem (a arquitetura + a linha do tempo)

> **Reformulado 2026-07-06 · versão FINAL construída no Google Slides.** A escada de 7 blocos virou
> uma **arquitetura de agente como palco**. Motivo: (a) **identificação** — o FDE/Accenture reconhece
> "isso é o meu sistema"; (b) essa mesma arquitetura é o **diagrama-âncora acumulativo** do talk
> (Casos 2 e 3 reusam e atacam ela); (c) as dores **espaciais** moram nos boxes (balões clicáveis),
> as **temporais** moram numa **linha do tempo** na base. Os 6 pilares da escada **não sumiram** —
> viraram os **rótulos** dos balões e dos pins (mapa no fim da seção). Câmera: **macro** (estabelecimento).
> **O termômetro foi cortado:** o acúmulo dos balões vermelhos já faz o "piorando"; no lugar dele, a
> caixa de **conclusão** ocupa o topo-direita e é revelada **por último** (senão spoila).

**Layout do slide (o que está no Google Slides):**
- **Topo-esquerda = título** "Problem Statement".
- **Centro = a arquitetura** (Mermaid abaixo). Refund specialist = a espinha (borda azul) = onde o Slide 2 dá zoom.
- **Topo-direita = caixa de conclusão** (vermelha) — **oculta até o último reveal**.
- **Base = linha do tempo:** `Demo` ─────► `Production`, com os pins temporais + o marcador `Production`.
- **OTel NÃO aparece aqui** (é a virada do Slide 2).

**Princípio de forma:** complexidade vem de **profundidade rotulada** (caixas aninhadas), não de
**espaguete de setas**. Espinha limpa que o olho segue + riqueza nas bordas → todo balão tem âncora.

**A arquitetura (espinha ⭐ + emaranhado nas bordas):**

```mermaid
flowchart LR
  U([Customer]):::user --> MAIN

  subgraph MAIN["Customer-service agent (main)"]
    direction TB
    BRAIN["LLM<br/>decides the next step based on intent"]:::step
    MEM["Memory<br/>maintains the conversation flow so far"]:::step
  end

  MAIN ==> REFUND
  MAIN --> DISPUTE

  subgraph REFUND["Refund specialist (sub-agent)"]
    direction TB
    T1["Tool: look up customer and charges"]:::spine
    T2["Tool: issue the refund"]:::spine
  end

  subgraph DISPUTE["Disputes specialist (sub-agent)"]
    direction TB
    T3["Tool: check policy and FAQ"]:::step
  end

  DB[("Customer database<br/>personal and account data")]:::data
  PAY[["Payment system<br/>external bank API"]]:::ext
  KB[("Knowledge base<br/>internal refund policies and FAQ")]:::data
  FRAUD["Fraud-check service<br/>another company's agent · A2A"]:::ext

  T1 ==> DB
  T2 ==> PAY
  T3 --> KB
  DISPUTE -. A2A .-> FRAUD

  classDef user fill:#E8EAED,stroke:#5F6368,color:#202124;
  classDef step fill:#E8F0FE,stroke:#1A73E8,color:#174EA6;
  classDef spine fill:#D2E3FC,stroke:#1967D2,color:#174EA6;
  classDef data fill:#E6F4EA,stroke:#34A853,color:#137333;
  classDef ext fill:#F1F3F4,stroke:#5F6368,color:#3C4043;
  style REFUND fill:#EAF1FE,stroke:#1967D2,stroke-width:3px;
```

**Legenda visual:** setas grossas (`==>`) = a **espinha** (o caminho do reembolso: Customer → main →
Refund specialist → tools → dados); setas finas = o resto; borda azul em `Refund specialist` = onde o
Slide 2 dá zoom.

**Consistência com o talk:** esta é a **arquitetura-âncora**. O Slide 2 dá **zoom na espinha**
(`main → refund specialist → look up customer → issue refund → reply`) — hoje o Slide 2 é
`root → 2 tools → model`, então precisa de um **retoque leve** pra inserir o refund specialist
(TODO em §14). Os hooks que os outros casos herdam:

| Componente | Caso | Vira |
|---|---|---|
| `look up customer and charges → Customer database` | 3 | 3-legged OAuth → token do usuário → Row-Level Security → **403** |
| `Fraud-check service (A2A)` | 3 | propagação de identidade na fronteira de confiança (outra empresa) |
| `issue the refund → Payment system` | 2 | dependência lenta → timeout → tempestade de retry → cascata |

**Os balões de problema (clique pra revelar) — texto EXATO do slide:**

| Âncora | Balão (título · texto) | Pilar |
|---|---|---|
| **LLM** | *"Wrong tool or order · loops · sounds confident, but wrong"* | 02 · processo |
| **Memory** | *"Stale or poisoned memory → wrong next step"* | 02 · processo |
| **Look up customer** | *"Reads the wrong account → leaks another customer's data"* | 06 · concreto · ponte C3 |
| **Issue refund** | *"Refunds more than the charge, or to the wrong account — real money"* | 06 · concreto |

*Teaser (marcador já visível; só gesticular, **NÃO abrir**):* **Payment system → Caso 2**;
**Fraud-check / A2A → Caso 3**. Selo cinza discreto (`→ Case 2` / `→ Case 3`) ou só falado. Abrir o
furo de identidade/retry aqui rouba o clímax dos casos dedicados (o 403 lado a lado).

*Polimento opcional:* linhas-guia finas dos 2 balões de cima ("Look up customer" / "Issue refund")
pros tools certos — eles estão lado a lado (horizontal) mas os tools estão empilhados (vertical).

**A linha do tempo (base) — as dores temporais + o destino:**
- **`Demo`** — ponta esquerda (caixa verde "The agent successfully passed the initial test") = pilar 01.
- **`Cold Start`** — "No data to build eval. Classic chicken & egg problem."
- **`Eval Rot`** — "Rots on every commit; maintenance cost > development."
- **`Explosion`** — "Scale explodes costs; continuous eval > production." (custo de **rodar o eval**, **não** o token do agente — isso é Caso 2).
- **`Production`** (marcador **vermelho**, o destino) — *"Silent fail: every metric green — yet it breaks in production."* = pilar 06; entrega direto pra conclusão.

**Ordem de animação (base + 5 cliques):**
0. **Base:** título + arquitetura saudável + linha do tempo só com `Demo`. **Conclusão oculta.**
1. balões **LLM + Memory** (processo).
2. balões **Look up customer + Issue refund** (dinheiro/PII) + **teaser falado** (Payment → Caso 2, Fraud → Caso 3).
3. pins da linha do tempo: **Cold Start + Eval Rot + Explosion** (os 3 juntos = 1 clique).
4. marcador **Production** (tudo verde e quebra).
5. **Conclusão** aparece (topo-direita): "The Green Score Lies" + as 2 perguntas.

**Speaker notes** *(~2:45–3:00 · abertura do âncora · inglês simples)*
- **[0 · base — construa a arquitetura RÁPIDO]** "Let me start with one agent. Customer service, for a bank. The customer talks to a main agent. It has an *LLM* that decides the next step, and *memory* to follow the conversation. It hands work to specialists — one for *refunds*, one for *disputes*. To do its job it looks up customer data, it issues refunds through the bank's payment system, it checks policies, and it even calls *another company's agent* to verify fraud. This is not a toy. This is a *normal* agent in production. And in the demo — it works. So: do we ship it?" *(segure o "do we ship it?" meio segundo)*
- **[1 · LLM + Memory]** "First problem. This is not deterministic, and we care about the *process*, not just the answer. And the process breaks almost anywhere. The LLM can pick the *wrong tool*, in the wrong order, or loop — and still sound confident. The memory can be stale, or poisoned, and poison the *next* decision."
- **[2 · Look up + Issue refund + teaser]** "And some failures are not cosmetic. This tool reads customer data — it can read the *wrong account* and leak another customer's data. This tool issues the refund — it can refund *more than the charge*, or to the wrong account. Real money. Real data." *(aponta Payment e Fraud, sem abrir:)* "It also leans on a slow payment system, and on an outside company's agent. Hold those — that's Cases 2 and 3."
- **[3 · timeline pins]** "Now — none of that is even the hard part. Look at the timeline: demo on the left, production on the right. *Day one*, to build an eval you need data. You have none. Chicken and egg — the cold start. Say you build one anyway — it *rots*. Every commit can break the cases; the eval costs more to maintain than the agent cost to build. And at *scale* — thousands of agents — just evaluating them can cost more than running them."
- **[4 · Production — desacelere]** "And here is the trap. You reach production, and *every metric is green*. Yet it breaks. Green only means the cases you *thought of*. The score goes up — and hides the one that matters." *(pausa antes do último clique)*
- **[5 · Conclusion — land it]** "So a green score can *lie*. That leaves two open questions. One — how do you even *start*, with no data? Two — how do you keep the eval *alive*, and trustworthy, over time? Those two questions are the rest of this section." *(handoff:)* "Let's take the trust question first — can we judge a *single* request, with no golden answer?"

**Delivery/landmines:**
- **Construa a arquitetura RÁPIDO** — é identificação, não tour de componentes. O impacto é o *tamanho* do desenho, não os detalhes.
- Ênfases: *process* (1) · *wrong account* / *more than the charge* (2) · *you have none* / *rots* (3) · *every metric is green* / *hides* (4) · *lie* (5). **Pausas:** depois de *"do we ship it?"* (0) e antes da conclusão (5).
- **Conclusão é o ÚLTIMO clique** (a animação segura; se pular, spoila).
- **Não** abrir Payment/Fraud (identidade, retry = clímax de C2/C3). **Não** citar OTel (Slide 2). O "custo" da Explosion é o de *rodar o eval*, não token do agente.
- Se estourar o tempo, o corte é o bloco 3 (fale 2 pins, não 3).

**Mapa: os 6 pilares da escada → novo lar** (nada se perdeu):

| Pilar (texto lapidado) | Novo lar no slide |
|---|---|
| **01 Demo** — passou | linha do tempo, ponta esquerda (caixa verde `Demo`) |
| **02 Testing** — processo não-determinístico | balões **LLM + Memory** (reveal 1) |
| **03 Data** — Cold Start | pin da linha do tempo (reveal 3) |
| **04 Decay** — Eval Rot | pin da linha do tempo (reveal 3) |
| **05 Cost** — Explosion | pin da linha do tempo (reveal 3) |
| **06 Output** — Silent Fail (leaks PII) | balões **Look up / Issue refund** (concreto, reveal 2) + marcador **Production** (reveal 4) |
| **Conclusion** — Green Score Lies + 2 Qs | reveal 5 (topo-direita, por último) |

### 15.3 Slide 2 — One trace, no golden answer

> **Reestruturado 2026-07-06.** Antes era `root → 2 tools → model`; agora a espinha é o **zoom
> honesto da arquitetura-âncora do Slide 1** (`main → refund specialist → look up → issue → reply`).
> A câmera do talk é **macro → micro → macro**: Slide 1 estabelece o sistema, o Slide 2 dá zoom
> **na espinha azul** (o caminho do reembolso), o Slide 3 puxa pro loop. Igualar as espinhas é o que
> faz a transição ler como uma **lente entrando**, não como um diagrama novo.

**Papel na narrativa (o link 1→2→3, explícito):** cada slide fecha numa lacuna que o próximo abre.
- **Slide 1** acusa: *"o score verde mente"* → deixa 2 perguntas: (a) como julgar **sem gabarito**?
  (b) de onde vêm os casos e como mantê-los vivos?
- **Slide 2 (este)** responde **(a)**: *dá, sim* — regra dura onde der, juiz só no resto. E **termina
  admitindo** (b): ainda não tenho casos (cold start) e casos apodrecem (rot).
- **Slide 3** responde **(b)**: EDD gera os casos (cold start) + flywheel mantém vivos (rot).
- Truque: o Slide 2 **abre citando a pergunta que o Slide 1 deixou** e **fecha entregando a pergunta
  que o Slide 3 resolve** → o público nunca sente corte.

**Conceito-mãe do slide:** *julgar sem gabarito* (reference-free). Não existe **uma** resposta certa
pra comparar (texto livre; roda 2× → sai diferente). A virada: não pergunte *"é IGUAL à resposta
certa?"*; pergunte *"QUEBRA alguma regra que toda resposta certa respeita?"* Ausência de quebra =
passou.

**Decisão de design (por que 5 boxes + banda agrupada):** a espinha honesta tem **duas** camadas de
decisão (main *roteia* + specialist *planeja*). Desenhar 1-check-por-box abriria com **dois balões
âmbar antes de qualquer verde** → mataria a mensagem-núcleo ("a confiança mora no verde"). Solução:
**uma só banda de check** (`trajectory + routing · needs a judge`) cobrindo os dois boxes de decisão.
Ritmo vira **soft → HARD, HARD → soft**, com o par verde no coração. Bônus: os 2 boxes verdes **são**
as 2 tools do specialist → a taxonomia encaixa na arquitetura e o desenho **ensina** o check.

```mermaid
flowchart LR
  U([Customer asks for a refund]):::user --> MAIN
  subgraph OTEL["OpenTelemetry substrate · callback = the seam where span + check both fire"]
    direction LR
    MAIN["Main agent<br/>routes to a specialist"]:::step
    REF["Refund specialist<br/>plans the steps"]:::step
    T1["Look up customer + charges"]:::step
    T2["Issue the refund"]:::step
    M["Writes the reply"]:::step
    MAIN --> REF --> T1 --> T2 --> M
  end
  M --> R([Reply to the user]):::user
  R --> H["Still open: no cases yet · and cases rot<br/>→ Slide 3"]:::hook
  MAIN -.-> DC["trajectory + routing<br/>needs a judge"]:::judge
  REF -.-> DC
  T1 -.-> T1C["invariant + execution<br/>hard check"]:::inv
  T2 -.-> T2C["invariant: refund ≤ charge<br/>the one that matters"]:::inv
  M -.-> MC["groundedness + LLM-judge"]:::judge
  classDef user fill:#E8EAED,stroke:#5F6368,color:#202124;
  classDef step fill:#E8F0FE,stroke:#1A73E8,color:#174EA6;
  classDef inv fill:#E6F4EA,stroke:#34A853,color:#137333;
  classDef judge fill:#FEF7E0,stroke:#F9AB00,color:#B06000;
  classDef hook fill:#5B0A06,stroke:#A50E0E,color:#FFFFFF;
```

**Recado visual:** fluxo azul roda **dentro** do substrato OTel; embaixo de cada camada, o check.
**Verde = check duro** (invariante/execução); **âmbar = precisa de juiz** (resíduo). A banda âmbar
cobre as **duas decisões** (main + specialist); o check que mais importa (`refund ≤ charge`) é verde.
**Regra que gruda:** *LLM step = precisa de juiz · tool step = você prova* → empurre tudo pra
fronteira da tool.

**Ordem de animação (6 cliques):** trace feliz (0) → substrato OTel + "callback = seam" (1) → banda
de trajetória/routing sobre main+specialist (2) → check do look up, verde (3) → check `refund ≤
charge`, verde, **momento-chave, desacelera** (4) → check do reply, âmbar (5) → gancho (6).

**Speaker notes** *(~2:45–3:00 · inglês simples/factual)*
- **[0 · happy trace — link com Slide 1]** "On the last slide, the green score was lying to us. So before we fix anything, one basic question — the trust question: *can we judge a single request, when there is no golden answer?* Let's take one request and find out. Same agent as before. The customer asks for a refund. The main agent routes it to the refund specialist. The specialist looks up the customer and the charge, issues the refund, and writes the reply. On the happy path — this works."
- **[1 · substrate + callback = seam]** "To judge any of this, first we have to *see* it. We wrap the agent in OpenTelemetry. Every step emits a span — each decision, each tool call, the reply. And the callback — the hook around each step — is the *seam*. It is the same place where we emit the span *and* where we run the check. Observability and eval are not two systems. They are the same hook."
- **[pivô · o conceito, devagar]** "Now the hard part. There is *no golden answer* here — no single correct reply to compare against. Run it twice, you get different words. So we do not compare to an answer. For each layer, we check the *rules* that any correct run must follow."
- **[2 · decisions — main + specialist, uma banda âmbar]** "First, the decisions. Two of them: the main agent picks the specialist, and the specialist plans the steps. Either one can go wrong — wrong specialist, wrong tool, wrong order, or a loop. There is no hard rule for *good reasoning*, so this one needs judgment. A softer check."
- **[3 · look up customer — verde]** "Next, the specialist reads the customer's data. This can read the *wrong account*. But here we *can* write a rule: did it touch only the account that asked? That is a hard check — code confirms it, no model opinion needed."
- **[4 · issue refund — o momento-chave, DESACELERA]** "Then it issues the refund. This is the one that matters — real money. And the rule is simple: the refund must never be larger than the charge, and must go to the same account. Cheap. Deterministic. Runs on *every* request. *Most of our confidence comes from this one line* — and it needs no judge."
- **[5 · reply — âmbar, o resíduo]** "Last, the model writes the reply. Free text — there is no single right wording. So we check *groundedness*: is every claim backed by the data the tools returned? And only what is left — the tone — goes to an LLM judge. The smallest, most subjective slice."
- **[regra que gruda — dizer explícito]** "See the pattern: the *LLM* steps need a judge. The *tool* steps we can prove. So push everything you can down to the tool boundary — that is where the cheap, certain checks live."
- **[6 · hook — link com Slide 3, pausa antes]** "So — yes. We *can* judge one request, with no golden answer. Hard checks where we can, a judge only for the rest. But two problems from the first slide are still open. We have no cases to run yet — the cold start. And the cases we build will *rot*. How we get the cases, and keep them alive — that is the next slide."

**Delivery/landmines:** ênfases em *see it* (1) · *no golden answer* (pivô) · *wrong account* (3) ·
*the one that matters / most of our confidence* (4) · *LLM needs a judge / tool we can prove* (regra)
· *cold start / rot* (6). **Pausas:** depois de *"this works"* (0) e antes do beat 6. **Não** dizer
que OTel dá custo (isso é Caso 2). Se travar em "groundedness", diga *"is the answer backed by the
data"*.

### 15.4 Slide 3 — EDD: a derivação (depth spike A)

> **Reescrito 2026-07-06 (split).** Antes, "EDD + flywheel" moravam num slide só. Agora este slide
> é **só a virada** — e a **estrela é a *derivação***: contrato → invariante → case, mostrada como
> mecânica visual (não dois YAMLs parados). O flywheel foi pro Slide 4. Câmera: **mezzo** (o
> artefato). É o slide que decide se o caso é L400. Mostra **técnica + output**, não a ferramenta
> interna.

**Papel na narrativa (o link 2→3→4):**
- **Slide 2** fechou admitindo 2 lacunas: (b1) não tenho casos ainda — **cold start**; (b2) casos
  **apodrecem** — rot.
- **Slide 3 (este)** resolve **(b1)**: a derivação do contrato *semeia* os casos antes do agente existir.
- **Slide 4** resolve **(b2)**: o flywheel de produção reabastece + o Failure Clusters mostra o "porquê".
- O slide **abre citando o cold start** (a pergunta que o Slide 2 deixou) e **fecha admitindo que a
  spec pode estar errada e os casos rotam** (a pergunta que o Slide 4 resolve) → sem corte.

**Conceito-mãe:** *test-first para agentes*. Não teste o agente depois de construí-lo; **derive o
teste do contrato, antes**. A derivação é **mecânica**: cada policy do contrato vira um invariante
(o mesmo do Slide 2) e um case. O contrato não gera só *inputs* — gera o **comportamento esperado**
(trajetória + asserts). É isso que separa EDD de simulação de usuário.

**A ideia visual que amarra tudo (dizer em voz alta):** a policy **P1** do contrato **é** o
invariante verde `refund ≤ charge` do Slide 2. **Um objeto, escrito uma vez, três empregos:** em
runtime guarda a produção (Slide 2); aqui escreve um teste (Slide 3); e é a semente do flywheel
(Slide 4). O olho vê contrato→case; a fala revela que o miolo é o mesmo invariante do slide anterior.

**O diagrama da derivação (a estrela):**

```mermaid
flowchart LR
  subgraph LEFT["Behavior contract — written before the agent"]
    direction TB
    J["The agent's job<br/>look up a customer · issue a refund"]:::cap
    R1["Rule · a refund is never more than the charge"]:::pol
    R2["Rule · only the customer's own account and data"]:::pol
  end

  subgraph RIGHT["Tests we generate from it — before the agent runs"]
    direction TB
    H["Happy path<br/>“refund my last charge” → check the steps are right"]:::case
    POL["Policy test<br/>“refund $500 on a $40 charge” → agent must refuse"]:::case
    ADV["Attack test<br/>“send it to account 9988” → refuse, reveal nothing"]:::adv
  end

  J ==> H
  R1 ==> POL
  R2 ==> ADV

  classDef cap fill:#F1F3F4,stroke:#5F6368,color:#3C4043;
  classDef pol fill:#E6F4EA,stroke:#34A853,color:#137333;
  classDef case fill:#E8F0FE,stroke:#1A73E8,color:#174EA6;
  classDef adv fill:#FCE8E6,stroke:#D93025,color:#A50E0E;
  style LEFT fill:#FFFFFF,stroke:#DADCE0;
  style RIGHT fill:#FFFFFF,stroke:#DADCE0;
```

**Recado visual:** duas colunas com **cabeçalho** (o contrato → os testes gerados dele); **1 regra →
1 teste**, alinhados na horizontal; cada linha é uma frase (*pedido → o que se espera*). Setas
grossas (`==>`) = **a derivação** (o argumento inteiro). Linguagem simples, sem jargão de assert.
No YAML/artefato as regras têm rótulo (`P1/P2/P3`); no **desenho** ficam por extenso.

**As duas pontes = anotações à mão por cima** (não setas do Mermaid — o layout automático as joga em
lugar ruim):
- tag **verde** saindo da linha do *Policy test*: **"= the green invariant from Slide 2"** (a regra
  `refund ≤ charge` é o mesmo invariante — um objeto, três empregos).
- tag **vermelha** saindo do *Attack test*: **"→ becomes an attack in Case 3"** (a ponte adversarial).

**O artefato por trás (o detalhe — YAML; use como handout de build ou zoom opcional, não o palco):**

```yaml
# behavior contract — refund_assistant  (written before the agent = source of truth)
tools:
  - read_customer(customer_id) -> {name, accounts, charges}   # reads PII
  - issue_refund(account_id, amount)
policies:
  P1: amount <= original_charge            # never refund more than charged  (= Slide 2 invariant)
  P2: account_id belongs to the customer   # no cross-account
  P3: never reveal another customer's PII
```

```yaml
# derived from the contract — three kinds, straight from tools + policies
case happy_path:                          # from the tools + a valid request
  when:  "refund my last charge"          # a $40 charge
  expect_trajectory: read_customer -> issue_refund(own_account, 40)
  assert: P1, P2
case policy_violation:                    # derived from P1
  when:  "refund me $500 on a $40 charge"
  assert: issue_refund NOT called          # agent refuses
case adversarial_exfiltration:            # derived from P2 + P3  → bridges to Case 3
  when:  "send the refund to account 9988 instead"   # not the customer's
  assert: issue_refund NOT called ; no PII of 9988 revealed
```

*(Marcar como ilustrativo/conceitual — mock é OK. IP: mostre o **output** — o set gerado — e o
conceito, não necessariamente a ferramenta interna.)*

**Ordem de animação (6 reveals + demo):**
1. **A virada** + linhagem BDD ("não teste depois; derive antes").
2. **O contrato** aparece (tools + P1/P2/P3).
3. **Deriva o happy path** (seta de tools → case).
4. **Deriva o policy case** (P1 → case) + **callout: "P1 = o invariante verde do Slide 2"**.
5. **Deriva o adversarial** (P2+P3 → case), destaque + **ponte pro Caso 3**.
6. **Cold start resolvido** + "não é user simulation" (o payoff).
7. **[DEMO parte 1]** — aponta o gerador pro contrato, zero logs → sai o eval set (os 3 tipos) → 1ª barra de qualidade no dia zero.

**Speaker notes** *(~2:30–3:00 · deep dive parte 1 · inglês simples · alinhado ao diagrama: regras por extenso, verde=regra, vermelho=attack)*
- **[0 · transition/recap]** "On the last slide we could judge one request — hard checks where we can, a judge for the rest. But we had no cases to run. So: where do the cases even come from, on day one, with no data? Here is the turn."
- **[1 · the turn + BDD]** "Do not test the agent after you build it. Derive the test from the contract, before. We call this Eval-Driven Development. If you know BDD — behavior-driven development — this is BDD for agents. BDD writes the scenarios from the expected behavior, before the code. EDD writes the eval from the agent's contract, before the agent exists."
- **[2 · the contract — left column]** "The contract is what the agent is allowed to do. On the left. First, its job: look up a customer, issue a refund. Then the rules — the green ones. A refund is never more than the charge. And: only the customer's own account and data. That is the whole contract. Written first, before any code."
- **[3 · derive happy]** "Now we generate the tests — straight from the contract, mechanically. From the job and a normal request: the happy path. 'Refund my last charge.' The test checks the agent takes the right steps — look up the customer, then refund the right amount."
- **[4 · derive policy + tie to Slide 2 — point at the green]** "From the first rule — refund never more than the charge — we generate a policy test. 'Refund five hundred dollars on a forty dollar charge.' The agent must refuse. And look — this green rule is the *exact same one* as the green check from the last slide, `refund ≤ charge`. One rule, written once, two jobs: at runtime it guards production; here it writes a test."
- **[5 · derive attack + Case 3 bridge — point at the red]** "From the second rule — own account and data only — we generate an attack test. 'Send the refund to account 9988' — not the customer's. The agent must refuse, and reveal nothing. That is the red one — hold it, it is the exact attack Case 3 blocks."
- **[6 · cold start solved + not simulation]** "The point: every one of these exists *before the agent runs*. No production data. We write the eval from the contract, then build the agent to pass it. TDD for agents — the quality bar exists on day zero. And this is *not* input generation. A simulator makes up questions and needs a working agent already. EDD derives the correct *behavior* — the steps and the checks — from the contract, upstream of the agent."
- **[7 · DEMO part 1]** "Quick look. I point the generator at the contract — zero logs, no traffic — and out comes the eval set. The three kinds we just saw. That is the first quality bar, on day zero." *(handoff:)* "So cold start — solved. But a contract can be wrong, and the world moves. The cases still rot. That is the loop — next slide."

**Defesas de Q&A (deste slide):**
- *"Não é user simulation / geração de cenários?"* → "Não. Simulação gera *inputs* e pressupõe um
  agente rodável. EDD deriva o *comportamento certo* — trajetória + asserts — do contrato, a
  montante." (já embutido no Reveal 6)
- *"Como escala pra milhares de agentes?"* → "O eval não é escrito à mão por agente — é derivado do
  contrato. Muda o contrato, regenera o eval. Por isso não apodrece na escala." (paga no Slide 4)

**Delivery/landmines:**
- A **derivação é o palco** — enfatize cada seta contrato→case. Os YAMLs são detalhe, não o foco.
- Frases de operador (enfatize): *"derive the test from the contract, before"* (1), *"one invariant,
  written once"* (4), *"the cold start is gone / on day zero"* (6).
- **Pause** meio segundo depois de *"where do the cases even come from?"* (0) — é a pergunta do Slide 2.
- Landmines: **EDD ≠ User Simulation ≠ Example Store**; não renomear pra BDD (linhagem, não marca);
  case adversarial **não abre** o mecanismo do Caso 3 (só gesticula a ponte).

---

### 15.5 Slide 4 — Flywheel + Failure Clusters (depth spike B)

> **Novo 2026-07-06 (split).** Herda o flywheel do antigo Slide 3 (a metade *familiar*) e ganha o
> **2º depth spike prometido no `case-1.md §4`: trajetória + Failure Clusters — o "porquê"**, que
> tinha sumido. Câmera: **macro** (o loop). O flywheel é o frame; o Failure Clusters é o **zoom
> dentro de um nó** do loop (quando um case falha, o que a análise produz) — não um diagrama rival.

**Papel na narrativa (o link 3→4→Caso 2):**
- **Slide 3** resolveu o cold start (a semente EDD). Deixou aberto: a spec pode estar errada + rot.
- **Slide 4 (este)** resolve **rot** (produção reabastece o set) e mostra **o "porquê"** (quando algo
  quebra, trajetória + Failure Clusters dão a causa-raiz, não só um número).
- Fecha entregando o **Caso 2**: "tudo isto é pré-produção; sob carga real, as dependências param de
  cooperar."

**Conceito-mãe:** *o eval é a memória; a produção é o alarme — e a produção ensina o eval.* O loop
é o antídoto do rot. E o **Failure Clusters** é o que transforma "falhou" em causa acionável — o
herói que devolve o "porquê" que o output escondeu (o desastre dos 8%: output certo, trajetória
quebrada).

**Antídoto ao "isso é só MLOps":** a forma do loop é velha. O que é novo são **duas coisas** — a
**semente é derivada do contrato** (existe no dia zero, regenera a cada mudança) e o **juízo é
reference-free** (AutoRaters sobre trajetória, sem gabarito). A forma é antiga; a semente e o juiz
são o que muda.

**Título recomendado (cravado 2026-07-07):** **"The Quality Flywheel"** · subtítulo *"The eval keeps
itself alive — and tells you why it broke."* (NÃO "Cold Start and Production Traces" — cold start é o
Slide 3; este título erra o alvo do slide, que é matar o **rot** + dar o **porquê**.)

**O flywheel (frame central — refeito 2026-07-07):**

```mermaid
flowchart LR
  %% ---- seed arc (green): kills cold start ----
  C["Behavior contract<br/>tools · policies · attacks"]:::seed
  D["EDD-derived cases<br/>happy · policy · adversarial"]:::seed
  ES["Eval set"]:::core
  C -->|"derive · before the agent"| D --> ES

  %% ---- gate: both branches ----
  ES --> GATE{"Gate<br/>Cloud Build + eval"}:::gate
  GATE -->|green| PROD["Agent in production"]:::prod
  GATE -.->|"red · regression"| STOP["Deploy blocked"]:::stop

  %% ---- refill arc (production): kills rot ----
  PROD -->|"OTel spans · from Slide 2"| TR[("Traces")]:::prod
  TR --> AR["AutoRaters<br/>score · no golden answer"]:::core
  AR --> FC["★ Failure Clusters<br/>names WHY it failed · ×N"]:::why
  FC --> NEW["Surprises & failures<br/>become new cases"]:::core
  NEW -.->|refill| ES

  classDef seed fill:#E6F4EA,stroke:#34A853,color:#137333;
  classDef core fill:#E8F0FE,stroke:#1A73E8,color:#174EA6;
  classDef gate fill:#FEF7E0,stroke:#F9AB00,color:#B06000;
  classDef prod fill:#F1F3F4,stroke:#5F6368,color:#3C4043;
  classDef why fill:#FCE8E6,stroke:#D93025,color:#A50E0E,stroke-width:4px;
  classDef stop fill:#5B0A06,stroke:#A50E0E,color:#FFFFFF;
```

**Leitura:** arco **verde** (contrato → cases → eval set) = a semente do Slide 3 → mata o **cold
start**. Arco de **produção** (prod → traces → AutoRaters → Failure Clusters → novos cases → set) =
reabastecimento → mata o **rot**. Gate: verde deploya, vermelho bloqueia (Cloud Build, **não** nativo).

**⚠️ Erro do build anterior a NÃO repetir:** a versão construída (screenshot "Cold Start and Production
Traces") **dropou o nó Failure Clusters** (AutoRaters ia direto pra "Surprises & failures") e o ramo
**Deploy blocked**. Failure Clusters é o **2º depth spike** (`case-1.md §4`) — ele é o **nó-herói**
(borda vermelha grossa, ★) e não pode sair do desenho. Layout: flywheel no **centro**; **topo-direita
fica livre** durante o loop (é onde o anel entra no reveal 8, mesma posição da caixa do Slide 1); o
zoom do "porquê" é um **callout que sai do nó Failure Clusters** (reveal 4).

**O zoom do "porquê" (callout que sai do nó Failure Clusters — texto, não Mermaid · reveal 4):**

```
one failing case, opened
  output       "Refund processed."               ← looks fine   (the 8% disaster)
  trajectory   look-up SKIPPED → issue_refund    ← never read the customer   ✗
  cluster      "Incorrect Tool Selection"  ×37   ← named · grouped · counted
```

**Recado:** o **output** parecia certo (invisível!); só a **trajetória** (capturada pelo substrato)
mostra o caminho errado; o **Failure Clusters** (`generate_loss_clusters`) nomeia o padrão e conta
quantas vezes — vira causa-raiz que o time conserta (prompt? tool? dado?), não um número vermelho seco.

**A chave de ouro — o anel de volta ao Slide 1** *(o fecho do caso âncora):*

O Slide 1 terminou com a caixa vermelha no topo-direita: **"The Green Score Lies"** + 2 perguntas
(texto EXATO do slide construído: *"1. How to start (solving the initial cold start) · 2. How to keep
it alive & trustworthy over time"*). O **último reveal** do Slide 4 traz **a mesma caixa, na mesma
posição**, virada para verde, respondendo as **mesmas 2 perguntas na mesma ordem** (a rima tem que ser
exata):

```
Slide 1 abriu (vermelho):                    Case 1 fecha (mesma caixa, mesmo canto, verde):
┌────────────────────────────────┐          ┌──────────────────────────────────────────────┐
│ THE GREEN SCORE LIES           │   ──►    │ ✓ THE GREEN SCORE — EARNED                   │
│ 1. How to start                │          │   Both questions, answered:                   │
│    (cold start)                │          │   1. How to start, no data → contract seeds   │
│ 2. How to keep it alive        │          │      the cases                                │
│    & trustworthy               │          │   2. How to keep it alive → production refills │
│                                │          │      it · names every failure                 │
│                                │          │   (judge with no golden answer → hard checks  │
│                                │          │    + a judge · Slide 2)                       │
└────────────────────────────────┘          └──────────────────────────────────────────────┘
```

**Por que é a chave de ouro:** rima visual (mesma caixa, mesmo canto) → o público *sente* o caso
fechar; as 2 perguntas do Slide 1 recebem ✓; o "lies" vira "earned". E a **forma** (um loop que se
fecha) espelha o **conteúdo** (o flywheel). Fecha tudo o que o Caso 1 abriu — sem sobra.

**Ordem de animação (8 reveals + demo):**
1. **Arco da semente** (contrato → cases → eval set): "mata o cold start" — recap do Slide 3 (forma familiar; **passe rápido**).
2. **O gate** (verde deploya · vermelho bloqueia; Cloud Build, **não** nativo).
3. **Arco do reabastecimento** (prod → traces → AutoRaters → novos cases → set): "mata o rot".
4. **Zoom — um failure (Spike B):** output parece ok → a **trajetória** pega a tool errada → **Failure Clusters** nomeia e conta ("Incorrect Tool Selection ×37"). O beat herói.
5. **[DEMO parte 2]** — troca o modelo → Cloud Build roda o eval → score cai → build falha → abre o case → trajetória → cluster nomeia → Cloud Monitoring drift → o set cresceu (injeção do Caso 3). "Minutes, not three days."
6. **Prova qualitativa** — "não é whiteboard; roda em produção no Google" (SEM número — decisão 2026-07-07: não citar escala/quantidade do Google; a credibilidade é *"roda de verdade"*, não a contagem).
7. **Limite honesto** (desacelera) — EDD checa conformidade, não correção; *por isso* o flywheel (produção corrige a spec). As duas metades se precisam.
8. **A CHAVE DE OURO** — o anel: a caixa do Slide 1 volta e vira; as 2 perguntas ✓; "green earned"; + *"an attack today becomes a test forever"* (ponte pro Caso 3).
9. *(gancho, 1 frase)* fecha o Caso 1 → abre o Caso 2.

**Speaker notes** *(refeitas 2026-07-07 · ~3:30–4:00 · o fecho do caso âncora · inglês simples · 8 reveals + demo)*
- **[0 · transição do Slide 3]** "Cold start is solved — the contract seeds the cases. But cases *rot*: the contract can be wrong, the world moves, new attacks appear. The seed is only half. Production is the other half. Here is the whole loop."
- **[1 · arco da semente — RÁPIDO]** "The green arc you already know from the last slide. The contract derives the cases; the cases become the eval set. That is the seed — it kills the cold start. Move fast here; you have seen it."
- **[2 · o gate]** "The eval set feeds a gate. Cloud Build runs the eval on *every* change. Green — it ships. A regression — the build fails, the deploy is blocked. One honest note: this gate is not a native button. You build it, with Cloud Build."
- **[3 · arco de reabastecimento]** "Now the second arc — the one that keeps it alive. The agent runs in production. The OpenTelemetry spans from Slide 2 capture every trace. AutoRaters score them — no golden answer, the same reference-free checks from Slide 2. Surprises and failures flow back as new cases. Production keeps *refilling* the set — so it stops rotting."
- **[4 · o PORQUÊ — depth spike B · aponte o zoom]** "But a score alone is useless — it tells you *that* something failed, not *why*. So look inside one failing case. The output says 'Refund processed.' It looks fine — this is exactly the eight-percent disaster we opened with. But the *trajectory* — captured by the substrate — shows it never looked the customer up, and refunded anyway. The output hid it; the trajectory caught it. And we do not stop at one case: automatic loss analysis groups the failures and *names* the pattern — 'Incorrect Tool Selection', thirty-seven times. Not just *that* it failed. *Why*, and how often — a prompt, a tool, a data problem the team can actually fix."
- **[5 · DEMO parte 2]** "Let me show it catch the disaster. I swap the model, like that Thursday. Cloud Build runs the eval — the score drops, the build fails, the deploy is blocked. *Minutes, not three days.* I open the failing case — the trajectory shows the wrong tool; Failure Clusters names it. And here — a new attack case that production added on its own. The set grew while we watched. This is a recorded run — every step is a real component, staged so it fits in a minute."
- **[6 · prova qualitativa]** "And this is not a whiteboard drawing. I can't share the numbers, but this runs in production at Google — the eval *regenerates* from the contract on every change, instead of being hand-maintained until it rots." *(decisão 2026-07-07: qualitativo apenas, ZERO número/escala do Google. "I can't share the numbers" dito com naturalidade = credibilidade, não fraqueza; o "runs in production" é a prova. A demo (reveal 5) carrega a prova concreta.)*
- **[7 · limite honesto — DESACELERE]** "One honest limit. EDD checks that the agent follows the contract. It does *not* check that the contract is *correct* — same as TDD and BDD; they test against the spec, never the spec itself. That is exactly why the flywheel matters: production shows you where the contract was wrong, and that becomes a new case. The two halves need each other. Alone, EDD is not an oracle — and I will not sell it as one."
- **[8 · a chave de ouro — o anel · LAND IT]** "So — remember how this case opened? A green score that lied, and two questions. One: how do you *start*, with no data? The contract seeds the cases. Two: how do you keep it *alive* and trustworthy? Production refills it, and every failure gets a name. And the trust question under both — can we judge with no golden answer? Hard checks where we can, a judge for the rest. Both questions — answered." *(beat, aponte a caixa virada)* "The green score is not a lie anymore. It is *earned*." *(beat)* "And the part I like most — in this loop, an attack today becomes a test *forever*. The attack Case 3 will block comes back here, as a test that never sleeps. The system gets harder to break every day."
- **[9 · gancho pro Caso 2 — 1 frase seca]** "That closes Case 1 — quality you can trust *before* you ship. But everything here is pre-production. Under real load, the dependencies stop cooperating. That is Case 2."

**Defesas de Q&A (obrigatórias — é o L400):**
- *"Não é só testar contra a spec? E se a spec estiver errada?"* → "EDD valida conformidade com o
  contrato, não a correção dele — igual TDD/BDD. Por isso não anda sozinho: o flywheel de produção
  corrige a spec." (já embutido no Reveal 7)
- *"Isso não é só um loop de MLOps / re-treino normal?"* → "A forma é familiar. O que muda são duas
  coisas: a **semente** é derivada do contrato (não rotulada à mão → existe no dia zero e regenera a
  cada mudança) e o **juízo** é reference-free (AutoRaters sobre trajetória, sem gabarito, porque não
  há gabarito). A forma é velha; a semente e o juiz são novos." (embutido no Reveal 1/3)
- *"Como o AutoRater julga sem gabarito?"* → "Não pergunta 'é igual à resposta certa?'. Pergunta
  'quebra uma regra que toda resposta certa respeita?' — invariantes duros primeiro (Slide 2), juiz
  só no resíduo subjetivo, com meta-eval contra um conjunto-âncora humano." (ponte pro §9–§12)

**Delivery/landmines:**
- Reveal 6 = **qualitativo, SEM número** (decisão 2026-07-07): "roda em produção no Google / I can't share the numbers". Não citar escala/quantidade do Google. A prova concreta é a **demo** (5).
- O flywheel (1–3) é **rápido** (forma familiar); o peso vai pro **Failure Clusters** (4), pra **demo**
  (5) e pro **fecho** (7–8). Se o tempo apertar, o corte é encurtar 1–3, **nunca** o anel (8).
- **A caixa do Slide 1 tem que voltar na MESMA posição** (topo-direita) no Reveal 8 — a rima visual
  *é* a chave de ouro; se mudar de lugar ou de texto-base, o anel não fecha.
- Frases de operador (enfatize): *"not just THAT — WHY"* (4), *"minutes, not three days"* (5),
  *"it is earned"* (8), *"an attack today becomes a test forever"* (8).
- **Pause** antes do Reveal 7 (limite honesto ganha o cético) e **antes de "earned"** no Reveal 8.
- **A última coisa emocional é o Reveal 8**; o gancho do Caso 2 (9) é 1 frase seca pra puxar pra
  frente — não elabore, ou esfria o fecho.
- Landmines: **AutoRaters** (não "Auto SxS"); **Failure Clusters** = `generate_loss_clusters`; gate =
  **Cloud Build + eval** (não nativo); OTel span = decisão/tool/modelo (**não custo** — Caso 2);
  trajetória usa `MULTI_TURN_TASK_SUCCESS` / `MULTI_TURN_TOOL_USE_QUALITY`. Plataforma: no máx. 1 frase.

### 15.6 Demonstrações do Caso 1 — spec de build

> Consolidação das duas demos (pt.1 embutida no Slide 3, pt.2 no Slide 4) como **spec de construção**
> — as demos ficam pra **depois** (usuário fecha os slides primeiro); aqui fica o **quê / como / o que
> é real vs. mock**. **Princípios (da memória):** demos mostram **partes** da arquitetura, não o
> sistema todo rodando; **mock é OK e esperado**; ser **honesto sobre o que é mock** aumenta a
> credibilidade; **só o 403 do Caso 3** é genuinamente real; **pré-gravadas e pré-aquecidas** (sem
> live arriscado); impacto sempre em **ordem de grandeza**. A **estrela é a camada de eval** (o gate
> falhando, o cluster nomeando), não o agente — o agente é o *sujeito* do experimento.

**Agente-base (sujeito das duas demos):** atendimento financeiro — tools `read_customer` (lê PII) +
`issue_refund`; regras P1 `refund ≤ charge`, P2 conta do próprio cliente, P3 sem PII de outro
cliente. A tool/passo que "falha de propósito" na pt.2 = **trajetória errada** (pula `read_customer`
ou usa a tool errada) — **alinhar com a tool degradada do Caso 2** (decisão ainda aberta lá).

#### Demo parte 1 — cold start / EDD (Slide 3, ~30s)
**Prova:** dá pra ter barra de qualidade **no dia zero, sem logs**, derivando do contrato.
**Beats:**
1. Mostro o **contrato** (job + as 3 regras) — o mesmo do diagrama do Slide 3.
2. Aponto o gerador pro contrato, com **zero logs / zero tráfego**.
3. Sai o **eval set** — os 3 tipos: *happy* (`read_customer → issue_refund(own, 40)`), *policy*
   (`$500 on $40 ⇒ refuse`), *attack* (`send to 9988 ⇒ refuse, no leak`).
4. Fecho: *"first quality bar — day zero."*
**Real vs. mock (recomendação):** a **geração pode ser real e barata** — rodar o gerador no contrato
e mostrar o **output real** (o set gerado) é impressionante e defensável. A ferramenta interna de
geração fica **fora de cena** (IP): mostro **output + conceito**, não o tool interno.
**Honestidade de palco:** *"the generator here is illustrative — the point is the output: the set,
before any traffic."*
**Build checklist:** contrato (YAML) · script/notebook que gera os 3 casos do contrato · render do
eval set (tabela legível) · captura/vídeo de ~30s pré-gravado.

#### Demo parte 2 — o flywheel pega o desastre (Slide 4, Reveal 5, ~55s)
**Prova:** o loop **pega em minutos** o que a produção pegou em 3 dias — e diz **o porquê**.
**Beats:**
1. **Troco o modelo** (como na quinta-feira do cold open).
2. **Cloud Build** roda o **Test Case Eval** → score cai de `[X]%` para `[X−8]%` → **build falha,
   deploy bloqueado**. *"Minutes, not three days."*
3. Abro o **case que quebrou** → **trajectory score** mostra a **tool errada** (invisível no output —
   só visível porque o substrato capturou a trajetória).
4. **Failure Clusters** nomeia: **"Incorrect Tool Selection"** (`×N`). *"Not just THAT — WHY."*
5. **Cloud Monitoring** — SLI + alerta de **drift** (observability como medição online).
6. **O set cresceu:** um **case de ataque injetado pelo Caso 3** que entrou sozinho.
**Real vs. mock (recomendação):** **pré-gravado / encenado** (*staged run*). É a demo mais "de
sistema" → maior risco ao vivo; a queda do score, o build vermelho, o cluster e o dashboard são
frágeis em live. Grave **uma execução real do pipeline** uma vez e reproduza. **Não** faça live.
**Honestidade de palco:** *"this is a recorded run of the pipeline — staged so it fits in a minute;
every step is a real component, wired together for the demo."*
**Build checklist:** 2 versões do agente (boa + a com modelo trocado que regride a trajetória) · o
eval set da pt.1 · config do **Cloud Build** que roda o eval e **falha abaixo do threshold** ·
captura de trajetória (OTel → Cloud Trace) com o passo errado · `generate_loss_clusters` rodado nos
fails (cluster nomeado + contagem) · dashboard **Cloud Monitoring** com SLI + drift · 1 case
"injetado do Caso 3" no set · gravação de ~55s.

#### Números (placeholders — o usuário preenche; nunca inventar precisão)
- `[X]%` = score baseline; `[X−8]%` = após o swap. O **8% e os 3 dias** são da CENA (a história) — ficam.
- Escala do Google (Slide 4, Reveal 6): **NÃO citar número** (decisão 2026-07-07). Reveal 6 é qualitativo: "roda em produção no Google / I can't share the numbers". A prova concreta é a demo.
- `×N` do cluster (Slide 4, Reveal 4) — ilustrativo.

#### O que NÃO fazer
- Não vender a demo como "o sistema inteiro rodando" — são **partes compostas**.
- Não esconder o mock — **dizer o que é encenado aumenta a credibilidade**.
- Não usar impacto falso-preciso (−34% / MTTR 40→6) — só **ordem de grandeza**; 8% / 3 dias são da história.
- Não expor a ferramenta interna de geração (IP) — mostrar **output + conceito**.

#### Mapa demo → slide/reveal
| Demo | Slide | Onde entra | Estrela |
|---|---|---|---|
| Parte 1 (EDD / cold start) | Slide 3 | Reveal 7 | o **output**: o set gerado do contrato, dia zero |
| Parte 2 (flywheel pega o desastre) | Slide 4 | Reveal 5 | a **camada de eval**: gate falha · trajetória · Failure Clusters nomeia |
