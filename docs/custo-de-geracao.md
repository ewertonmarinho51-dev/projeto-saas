# Custo de geração dos documentos — diagnóstico, alterações e medição

*30/09/2026 · branch `claude/reducao-custo-geracao` · produção não tocada*

---

## O que foi pedido e o que este documento entrega

Reduzir o custo de geração de DFD, ETP, Mapa de Riscos e TR sem perder
qualidade, consistência ou completude — medindo antes e depois.

Este documento traz o diagnóstico do consumo atual, as fontes de
desperdício, o que foi alterado, os testes executados, a comparação com
números reais, os riscos encontrados e o que ainda pode ser otimizado.

**Nada foi ligado.** As seis medidas nascem atrás de feature flags
desligadas. Com tudo desligado, o prompt é byte a byte o de hoje, e há
prova disso em cada uma delas.

---

## 1. Como os números foram obtidos, e o que cada um vale

Custo de LLM tem duas metades, e misturá-las é como se produz relatório
de economia que não se sustenta. Este trabalho separa as duas.

### Medido aqui, exato

`scripts/medir_custo.py` percorre três processos inteiros — 1 item, 20
itens e 210 itens — pelo caminho REAL do aplicativo: `llm.gerar_documento`,
o SDK da OpenAI de verdade, a montagem do prompt, o RAG, a injeção da
tabela. As conversas são atendidas por uma fixture no transporte HTTP.

**Chamadas pagas nesta medição: zero.** É o mesmo bloqueio da auditoria
pré-operacional (`scripts/sem_llm.py`), que barra e conta qualquer
tentativa de sair para a rede.

Os tokens de entrada são contados pelo **tokenizador do provedor**
(`o200k_base`, a codificação da família gpt-4o/gpt-5), não por
caractere dividido por quatro.

### Não medido aqui — vem da telemetria de produção

Tokens de **saída** e **duração** só existem com modelo respondendo.
Eles vêm de `public.geracoes`: 168 gerações reais entre 13/07 e
18/09/2026. Estão em `docs/custo/producao.json`.

### O que é simulado, e como

| Item | Como | Por quê |
|---|---|---|
| Resposta do modelo | fixture no transporte | não gastar |
| Tamanho da prosa dos documentos | **medido em produção** (DFD 10.862, ETP 25.096, TR 34.677 caracteres) e distribuído entre as cláusulas | a fixture devolve minuta curta; sem isto a cadeia — o maior item da conta — apareceria dez vezes menor do que é |
| Trechos do RAG | sintéticos, com **tamanho medido na base real** (5.595 chunks, média 1.328 caracteres) e assuntos distintos entre si | não há base de conhecimento neste ambiente; medir o RAG como zero esconderia justamente o que mais cresce |
| Tamanho do Mapa de Riscos | **arbitrado** no patamar do DFD | é o único número não medido: o Mapa nunca chegou a gerar em produção (era o P0 corrigido na auditoria anterior) |

Os trechos do RAG terem **assuntos distintos** não é detalhe: a primeira
versão gerava todos do mesmo molde, o deduplicador enxergava dez cópias
e descartava nove, e a "economia de RAG" media 79% — quase toda ela a
fixture se auto-deduplicando. Corrigido, o número caiu para 47%, que é
o que o orçamento de tamanho de fato entrega.

---

## 2. Diagnóstico do consumo atual

### 2.1 Linha de base medida (`docs/custo/antes.json`)

Tokens de **entrada** por processo completo (DFD + ETP + Mapa + TR;
edital e ARP não passam por modelo nenhum):

| Processo | Total | Instruções | Formulário | RAG | Cadeia anterior | System prompt |
|---|---:|---:|---:|---:|---:|---:|
| 1 item | 52.825 | 5.153 | 2.059 | 15.277 | 21.219 | 9.117 |
| 20 itens | 57.276 | 5.153 | 2.467 | 15.313 | 25.226 | 9.117 |
| **210 itens** | **116.538** | 5.153 | 2.251 | 15.176 | **84.841** | 9.117 |

### 2.2 Saída e duração reais, de produção

| Documento | n | Entrada média | Saída média | Saída máxima | Duração |
|---|---:|---:|---:|---:|---:|
| DFD | 5 | 6.337 | 3.453 | 4.152 | 39 s |
| ETP | 7 | 36.803 | 7.586 | 8.421 | 99 s |
| TR | 6 | 26.690 | 9.495 | 10.101 | 121 s |
| Mapa de Riscos | **0** | — | — | — | — |
| auditor | 18 | 23.728 | 2.346 | 2.747 | 32 s |
| corretor | **47** | 23.571 | 4.755 | 14.905 | 61 s |

Um processo real inteiro, o mais limpo dos quatro: **10 chamadas,
177.867 tokens de entrada, 57.529 de saída, 877 segundos**. O pior:
**70 chamadas e 1.952.533 tokens de entrada** — num processo só.

### 2.3 As fontes de desperdício, em ordem de tamanho

**1. A cadeia de documentos anteriores — 42% a 73% da entrada.**
`state.contexto_para_documento` mandava ao modelo a cadeia inteira de
documentos aprovados, texto integral, **incluindo a tabela de itens que
o próprio sistema injeta por código**. Num processo de 210 itens são
84.841 dos 116.538 tokens de entrada, e a maior parte disso é a mesma
tabela viajando três vezes. O modelo não pode alterá-la, e os números
que ele pode citar já chegam calculados no bloco do formulário.

**2. O bloco do RAG — 26% a 29% da entrada.** O teto existente era de
CONTAGEM (dez trechos), e contagem não controla tamanho: dez trechos de
1.500 caracteres custam dez vezes mais que dez de 150, e o teto aceitava
os dois igualmente. A produção usava em média 2,9 a 4,0 referências; o
pior caso era o dobro disso e chegava sem ninguém decidir.

**3. Chamada repetida por clique, rerun, reload e "tentar de novo".**
Não havia cache algum. Quatro caminhos levavam à mesma chamada paga
acontecer de novo sem nada ter mudado no processo — e o quarto (timeout
depois de o provedor já ter gerado) cobrava duas vezes por um documento
que existia do lado de lá.

**4. Um campo do formulário descartava os cinco documentos.**
`invalidar_a_partir_de("formulario")` apagava tudo. Corrigir a data
pretendida custava a geração inteira do processo.

**5. A auditoria e a correção são o maior consumidor, e ninguém sabia.**
Em produção, **65 das 90 chamadas bem-sucedidas** eram de `auditor` e
`corretor`, não de redação de documento — e a tabela `geracoes` guardava
as duas coisas na mesma coluna `documento`, de modo que o custo por
documento não podia ser apurado.

**6. Um teto e um modelo para tudo.** `max_completion_tokens=16384` para
um DFD de 3.453 tokens de saída e para uma resposta JSON de auditoria de
2.346. O modelo configurado corria tanto a redação do TR quanto a
extração de JSON.

**7. Retentativa que repetia o irrecuperável.** Qualquer falha que não
fosse de modelo era repetida três vezes, com espera de 2s e 4s entre
elas. Chave inválida, três vezes. Crédito esgotado, três vezes.
Requisição malformada, três vezes. Um clique com os três motores
configurados dispara **9 requisições e prende a tela por 19 segundos** —
medido, não estimado.

---

## 3. Alterações realizadas

Seis medidas, seis flags, todas OFF. Painel do administrador → Revisão →
**Custo de geração**.

### 3.1 `contexto_canonico` — o próximo documento recebe as decisões, não o documento

`src/resumo_processo.py`. Um mapa **declarado cláusula a cláusula** diz
o que cada documento herda do anterior. As tabelas saem (com um aviso no
lugar, para o modelo não concluir que o quantitativo não existe), e saem
também as cláusulas que o documento seguinte refaz por conta própria.

A maior economia isolada do mapa: a cláusula 5 do ETP (LEVANTAMENTO DE
SOLUÇÕES, de 10 a 35 blocos) não vai para o TR. É a comparação entre
alternativas que levou à escolha — e o TR não reabre a escolha, herda a
decisão da cláusula 6. Reabri-la seria o defeito que a própria instrução
do TR proíbe.

**A defesa:** documento que não segue a estrutura dos perfis — importado,
renumerado, editado à mão — **vai inteiro**. O módulo não adivinha
recorte, e o cabeçalho diz qual dos dois caminhos foi tomado, para o
rastro registrar por que aquele processo pagou o dobro.

### 3.2 `cache_geracao` — a mesma pergunta não se paga duas vezes

`src/cache_geracao.py`. Duas camadas: sessão (clique duplo, rerun) e
banco (reload, sessão nova), com escopo por tenant e processo.

A chave é o **hash dos dois prompts já montados**. Formulário, planilha
calculada, cadeia aprovada, RAG recuperado e diretrizes já estão dentro
deles — o que torna impossível por construção o erro clássico deste tipo
de cache: alguém acrescenta uma fonte ao prompt, esquece de somá-la à
chave, e o sistema passa a servir documento montado com contexto velho.

Somado a isso, **`Idempotency-Key` no pedido ao provedor**, derivada do
próprio pedido. Fecha o caso que o cache local não alcança: a resposta
que o provedor gerou, cobrou, e que não chegou até aqui.

### 3.3 `regeneracao_parcial` — mudar o prazo não reescreve o Termo inteiro

`src/regeneracao.py`. Compara o formulário antigo com o novo, e um
`MAPA_DE_IMPACTO` declarado diz quais cláusulas cada campo alcança. O
documento fica, com um plano pendente; a tela oferece **"Atualizar só
estas cláusulas"** ao lado de **"Elaborar o documento inteiro de novo"** —
e a mais barata não é automática, porque reescrever duas cláusulas e
manter quinze é decisão sobre o documento.

**A defesa, em três camadas:**

1. o mapa é conservador. `prazo` no TR alcança **sete** cláusulas, porque
   prazo aparece em execução, formalização, recebimento, pagamento,
   liquidação e sanção. Cláusula esquecida contradiz a nova sem levantar
   erro nenhum;
2. `objeto` e `itens` atravessam o documento todo → documento inteiro,
   sempre. Campo sem regra declarada → documento inteiro. Alteração que
   alcance metade das cláusulas → documento inteiro;
3. a resposta é **conferida**: cláusula a mais, a menos, ou alteração
   fora do escopo **rejeita tudo**, e o caminho volta a ser a geração
   inteira. Documento pela metade não sai daqui.

### 3.4 `rag_enxuto` — deduplicar e limitar por tamanho

`src/rag.py`. Orçamento de 6.000 caracteres (a produção usava 4.000 a
5.300) e remoção de trechos que dizem a mesma coisa — Jaccard sobre
janelas de 5 palavras. A base tem o mesmo dispositivo em fontes
diferentes: a lei, o manual que a transcreve, o acórdão que a cita.
Três vagas, uma informação.

A ordem das duas operações importa: deduplicar **antes** de cortar, senão
as cópias consomem o orçamento e a evidência nova que vinha atrás delas
fica de fora. O corte é sempre o de menor relevância, depois de a reserva
por tema já ter garantido uma vaga para cada tema prioritário.

### 3.5 `clausulas_deterministicas` — a equipe de planejamento vem do cadastro

`src/clausulas_deterministicas.py`. A cláusula de EQUIPE DE PLANEJAMENTO
(DFD 9, ETP 16) deixa de ser escrita pelo modelo. O modelo emite
`[[EQUIPE_PLANEJAMENTO]]`, o código substitui pela portaria cadastrada —
a mesma resolução que o bloco de assinaturas já usa, com a data de
criação do processo como referência.

Isto economiza a saída da cláusula **e melhora o documento**: o modelo
não tem acesso ao cadastro, então a única coisa que ele podia escrever
ali era `[PREENCHER: nome e matrícula do agente]` — uma pendência
inventada nas instalações em que o dado existe. Sem portaria cadastrada,
a pendência continua visível e a emissão continua bloqueada.

### 3.6 `politica_de_modelo` — teto e modelo por tarefa

`src/politica_ia.py`. Duas classes:

- **redação** (DFD, ETP, Mapa, TR): o modelo principal, sempre. Nenhum
  documento da fase preparatória está na classe econômica, e há prova
  disso — mover um para lá é uma alteração deliberada e visível no diff;
- **estruturada** (auditoria, correção, extração, classificação,
  resposta curta do GovBot): pode correr no modelo econômico.

O modelo econômico fica **vazio por padrão**: sem ele a política só
ajusta o teto, e nenhuma tarefa troca de modelo sem que alguém tenha
escolhido qual. Se o econômico não existir na conta, a troca de modelo
já existente cai de volta para o principal e a tarefa não falha.

Tetos calibrados pela maior saída observada em produção, com folga:

| Tarefa | Maior saída medida | Teto (modelo comum) | Teto (raciocínio) |
|---|---:|---:|---:|
| DFD | 4.152 | 6.000 | 9.000 |
| ETP | 8.421 | 11.000 | 16.384 |
| TR | 10.101 | 13.000 | 16.384 |
| Mapa de Riscos | *sem medida* | 8.000 | 12.000 |
| auditor | 2.747 | 4.000 | 6.000 |
| corretor | 14.905 | 16.384 | 16.384 |

**Honestidade sobre o que o teto faz:** ele **não reduz a fatura por si
só** — os provedores cobram os tokens gerados, não os reservados. O teto
é guarda contra um modelo em laço, e torna explícito o tamanho esperado
de cada saída. A redução real de saída vem do cache e da regeneração por
cláusula.

### 3.7 Retentativa classificada (sem flag — é correção, não otimização)

`llm.classificar_erro`. Sete classes; só três justificam repetir a mesma
requisição no mesmo modelo: limite de ritmo, rede e desconhecida.

Falha desconhecida **continua** com direito a retentativa, deliberadamente:
classificar tudo que não se reconhece como irrecuperável tiraria a
retentativa de falhas transitórias que ninguém catalogou ainda, e uma
indisponibilidade de dois segundos viraria documento não gerado.

`insufficient_quota` também carrega "429" na mensagem. Tratá-lo como
limite de ritmo faria o sistema esperar e repetir três vezes uma conta
sem crédito — que só volta a funcionar quando alguém pagar.

### 3.8 Controle de consumo (ETAPA 10)

`geracoes` passa a registrar, em toda chamada de IA: tenant, secretaria,
usuário, processo, documento, **operação**, modelo, provedor, tokens de
entrada e saída, fallback, **cache hit**, tokens evitados e **custo**.

`operacao` separa `documento` de `auditoria`, `correcao`, `revisao`,
`parecer`, `assistente` e `pesquisa_precos` — sem ela, o custo por
documento não podia ser apurado.

O **custo** vem do preço configurado em `config_app`
(`PRECO_<MODELO>_ENTRADA` / `_SAIDA`, em reais por milhão de tokens).
Sem preço configurado o custo fica **NULO**, nunca um número presumido
pelo código: preço de modelo muda sem avisar e varia por contrato, e um
número embutido envelheceria em silêncio e apareceria num relatório de
economia como se tivesse sido medido.

Ponto único: toda chamada passa por `registrar_geracao`, inclusive o
acerto de cache (que registra custo 0,0 — e zero é medida).

---

## 4. Comparação antes/depois

Mesmo roteiro, mesmos três processos, mesma régua.

```
GOVDOCS_IA_SIMULADA=coerente .venv/bin/python scripts/medir_custo.py \
    --rotulo antes  --saida docs/custo/antes.json
GOVDOCS_IA_SIMULADA=coerente .venv/bin/python scripts/medir_custo.py \
    --rotulo depois --flags todas --saida docs/custo/depois.json
```

### 4.1 Tokens de entrada por processo

| Processo | Antes | Depois | Redução |
|---|---:|---:|---:|
| 1 item | 52.825 | 40.709 | **−23%** |
| 20 itens | 57.276 | 41.173 | **−28%** |
| 210 itens | 116.538 | 40.843 | **−65%** |

O processo de 210 itens passou a custar praticamente o mesmo que o de 1
item. É o efeito de a tabela deixar de viajar na cadeia: o custo de
entrada parou de crescer com o tamanho da planilha.

### 4.2 Por origem do token (somando os três processos)

| Origem | Antes | Depois | Redução |
|---|---:|---:|---:|
| Cadeia de documentos anteriores | 131.286 | 48.431 | **−63%** |
| Bloco do RAG | 45.766 | 24.107 | **−47%** |
| Instruções + formulário + system prompt | 49.587 | 49.587 | 0% |

### 4.3 Chamadas

| Situação | Antes | Depois |
|---|---:|---:|
| Mesmo documento pedido duas vezes | **2 chamadas**, 16.144 tokens | **1 chamada**, 6.036 tokens |
| Um campo do formulário muda | **4 documentos descartados**, 100% das cláusulas reescritas | **1 documento descartado**, **25%** das cláusulas reescritas |
| Um clique quando os 3 motores falham | 9 requisições, 19 s | 9 requisições, 19 s *(inalterado: falha de rede É retentável)* |

Sobre a última linha: a tempestade medida usa uma falha de **rede**, que
continua merecendo as três tentativas. A economia da classificação
aparece nas falhas que **não** merecem — chave inválida, crédito
esgotado, requisição malformada —, que passaram de 3 requisições por
motor para 1. Isso está medido em `tests/test_custo_de_geracao.py`, por
classe de erro, e não no roteiro de tempestade.

### 4.4 Tokens de saída

**Não medidos diretamente**, porque saída só existe com modelo real
respondendo e esta bateria não chamou modelo nenhum. O que se pode
afirmar, e como:

| Efeito | Base | Consequência |
|---|---|---|
| Acerto de cache | **medido**: 1 chamada evitada em 2 | saída **zero** na chamada evitada |
| Atualização por cláusula | **medido**: 25% das cláusulas reescritas | proporcionalmente, ~25% da saída daquele documento |
| Cláusula de equipe por código | **medido**: 1 cláusula de 9 (DFD) e de 18 (ETP) | pequeno, e o ganho principal é de qualidade |
| Teto por tarefa | — | **nenhum**: o provedor cobra o gerado, não o reservado |

Aplicar 25% à saída real do TR em produção (9.495 tokens) daria ~2.400
tokens em vez de 9.495 numa alteração de prazo. **Isso é uma projeção
aritmética sobre a fração de cláusulas, não uma medição de saída** — e
está escrito assim de propósito.

### 4.5 Custo em reais

Não calculado, e não por descuido: **não há preço configurado**. A coluna
`custo` fica NULA até o administrador informar
`PRECO_<MODELO>_ENTRADA/SAIDA`. A partir daí, o custo de cada chamada
passa a ser registrado e a economia em reais sai da própria tabela, sem
depender de nenhuma suposição minha sobre a tabela de preços do
provedor.

Em **tokens**, que é o que se pode afirmar: −23% a −65% de entrada por
processo, −50% de chamadas na repetição, −75% de documentos descartados
numa alteração de campo.

---

## 5. Testes executados

| Suíte | Resultado |
|---|---|
| Suíte completa do projeto | **2.720 passaram, 133 puladas, 0 falhas** (8m56s) |
| `test_resumo_processo.py` (novo, 22) | cada cláusula declarada atravessa; tabela não viaja; documento fora do padrão vai inteiro |
| `test_regeneracao_por_clausula.py` (novo, 16) | recusa de cláusula a mais/a menos/fora do escopo; todo campo do formulário tem decisão declarada |
| `test_custo_de_geracao.py` (novo, 33) | chave de cache por eixo; idempotência; tetos ≥ maior saída medida; classificação de erro por classe |
| `test_rag_enxuto.py` (novo, 7) | orçamento respeitado; melhor evidência sobrevive; dedup antes do corte |
| `test_clausulas_deterministicas.py` (novo, 13) | membro inativo fora; pendência visível sem portaria; falha de cadastro não derruba a geração |
| `test_migracao_0028.py` (novo, 14) | a 0028 **aplicada** num PostgreSQL local descartável |

### Três defeitos encontrados pelas próprias provas, durante a implementação

1. **`sem_tabelas` fechava a tabela em qualquer linha em branco.** Um
   documento com a tabela espaçada ganhava um aviso de omissão **por
   linha**, e o contexto "reduzido" saía **maior** que o original. O modo
   de falha era o oposto do objetivo e não levantava erro nenhum.
2. **O campo `alinhamento` não tinha regra declarada no mapa do TR.**
   Pego por `test_todo_campo_do_formulario_tem_decisao_declarada`.
3. **A folga de raciocínio contava o raciocínio duas vezes.** Os tetos
   são calibrados por `tokens_saida`, que é `completion_tokens` — e esse
   número **já inclui** os tokens de raciocínio. Multiplicar por 2,5 dava
   um teto que não guardava nada; corrigido para 1,5.

### A migração

`0028_controle_de_consumo_e_cache.sql.NAO_APLICAR` — sete colunas
NULLABLE em `geracoes` e a tabela `cache_geracoes`. **Aplicada e
conferida num PostgreSQL local descartável**, nunca em produção: RLS
ligada e forçada, três políticas nominais, nenhuma irrestrita, `anon` sem
grant, índice único da chave, cascade do processo, idempotência da
própria migração.

O sufixo `.NAO_APLICAR` é a trava, o mesmo mecanismo das 0018/0019/0020.
Enquanto ele existir, `cache_geracoes` fica fora do inventário de tabelas
em produção — que é a verdade.

---

## 6. Riscos encontrados

**1. O contexto canônico é a mudança com o pior modo de falha do
trabalho.** Um TR que não souber qual solução o ETP escolheu vai escolher
outra, e a cadeia passa a mentir — sem erro na tela, sem achado, sem
aviso. Mitigado por mapa declarado, recusa de recortar documento fora do
padrão, e uma prova por cláusula declarada. **Continua sendo o item que
mais merece observação no primeiro processo real.**

**2. A atualização por cláusula pode produzir contradição interna.** A
cláusula nova diz 30 dias e a vizinha, que ninguém regenerou, continua
dizendo 15. Mitigado pelo mapa conservador, pela conferência que rejeita
tudo em qualquer desvio, e por o documento vigente viajar como referência
de coerência. **O risco residual não é zero:** o modelo pode escrever uma
cláusula coerente com o texto que leu e incoerente com o que o processo
passou a afirmar. A revisão humana continua sendo a última linha.

**3. A perda de aprovação ao alterar o formulário.** Um documento com
plano de atualização pendente **deixa de estar aprovado**. É deliberado:
manter a aprovação faria o documento seguinte herdar como decidido algo
desatualizado. O efeito colateral é que o servidor precisa reaprovar,
mesmo que escolha a atualização parcial.

**4. `openai` continua sem pin em `requirements.txt`** (`>=1.40.0`). A CI
já instala a 3.19.2, que migrou de `httpx` para `httpx2`. Não é deste
trabalho, mas é o risco que mais pode surpreender numa próxima
implantação.

**5. O cache guarda o texto do documento no banco.** É dado do processo,
na mesma base, sob as mesmas políticas — mas é uma **segunda cópia** do
documento, e uma cópia a mais é uma superfície a mais. Apagada em
cascata com o processo.

---

## 7. O que ainda pode ser otimizado

**1. A auditoria e a correção — o maior alvo que sobrou.** São 65 das 90
chamadas bem-sucedidas de produção, e este trabalho só lhes deu teto de
saída e acesso ao modelo econômico. O corretor manda o bundle inteiro de
blocos a cada tentativa, e o ciclo pode rodar três vezes com uma
reauditoria completa entre elas. Reduzir o escopo enviado ao corretor
para os blocos do finding é a maior economia ainda disponível.

**2. Cláusulas jurídicas padronizadas do TR** (sanções, liquidação, prazo
e forma de pagamento). Parecem candidatas óbvias à montagem por código e
**não foram feitas de propósito**: o texto delas precisa vir de documento
APROVADO pela Administração, como veio o catálogo do edital. Redigi-las
aqui seria escolher a redação de um ato administrativo. O mecanismo está
pronto (`templates_gov.CLAUSULAS_BASE`); falta a fonte aprovada.

**3. Cache de prefixo do provedor.** O system prompt (2.280 tokens) é
idêntico em toda chamada, e as instruções por documento são estáveis. A
OpenAI desconta o prefixo repetido automaticamente a partir de 1.024
tokens — o prompt já está ordenado de modo a aproveitar isso, mas **não
foi medido**, porque a medição sem chamada real não enxerga o desconto.
Vale conferir na primeira rodada paga.

**4. O Mapa de Riscos vai para o TR inteiro.** Ele não segue a estrutura
dos perfis, então não há cláusula endereçável para recortar. Dar-lhe uma
estrutura de cláusulas resolveria isso e também destravaria a atualização
parcial nele.

**5. O teto do Mapa de Riscos é o único número arbitrado** deste
trabalho. O primeiro processo real que o gerar ajusta.

---

## 8. Como ligar

Painel do administrador → Revisão → **Custo de geração**. Seis toggles.

Sugestão de ordem, do mais seguro ao que mais merece observação:

1. `cache_geracao` — não muda nenhum texto; só evita repetir chamada;
2. `politica_de_modelo` — sem modelo econômico configurado, só ajusta o
   teto de saída;
3. `rag_enxuto` — muda quais referências o modelo vê, não o que ele deve
   escrever;
4. `clausulas_deterministicas` — melhora a cláusula de equipe; exige
   portaria cadastrada para ter efeito;
5. `contexto_canonico` — muda o que o modelo lê da cadeia. **Acompanhar o
   primeiro processo;**
6. `regeneracao_parcial` — muda o fluxo de trabalho do servidor e o que
   acontece ao alterar o formulário.

A migração 0028 precisa ser aplicada **antes** de `cache_geracao` ter
efeito além da sessão, e antes de o controle de consumo gravar as colunas
novas. Sem ela, os dois degradam em silêncio: o cache funciona só dentro
da sessão e o registro cai para o formato antigo.

**Rollback de qualquer medida = desligar a flag.** Há prova disso em cada
uma.
