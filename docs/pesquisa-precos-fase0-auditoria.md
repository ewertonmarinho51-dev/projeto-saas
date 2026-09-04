# Pesquisa de Preços — Fase 0: auditoria de arquitetura

Branch: `feature/pesquisa-precos`, criada de `main` em `75e325f`.
Data: 04/09/2026. **Nenhum código de produto foi escrito nesta fase.**

Tudo o que está aqui foi verificado no repositório ou contra as APIs
oficiais. Onde não consegui verificar, digo que não consegui.

---

## A. ARQUITETURA ATUAL ENCONTRADA

23.086 linhas em 38 módulos de `src/` mais 10 de `src/ui/`. O que
importa para este módulo:

| módulo | o que já resolve | o módulo de preços deve |
|---|---|---|
| `planilha.py` | estrutura canônica do item, cálculo, importação XLSX, injeção determinística da tabela | **consumir e devolver**, nunca criar segundo formato |
| `llm.py` | OpenAI → Gemini com fallback avisado, `registrar_geracao`, `rag_trace` | **usar como está** para a camada semântica |
| `govbot.py` | `hash_canonico`, `origin_hash`/`post_hash`, allowlist de intenções, system prompt que trata texto externo como dado | **reusar a filosofia e as funções** |
| `rag.py` | embeddings, chunks, recuperação | candidato a matching semântico |
| `fatos.py` | fatos canônicos versionados do processo | destino do fato "valor estimado" |
| `state.py` | `invalidar_a_partir_de`, `INSTRUMENTOS_DERIVADOS` | **ponto de invalidação** ao aplicar preços |
| `db.py` | `_cliente()`/`cliente_do_usuario()`, `flag_ativa`, `tenant_atual`, `registrar_incidente` | persistência e flag |
| `export.py` | DOCX institucional → LibreOffice → PDF, larguras proporcionais | **motor único** de relatório |
| `validacao.py` | `_BLOQUEANTES`, achados, gravidade | validação do relatório |
| `trilha.py` | vocabulário fechado de eventos de governança | trilha da pesquisa |

### Estrutura canônica do item (verificada)

```python
CAMPOS_ITEM      = ["codigo", "descricao", "unidade", "quantidade", "valor_unitario"]
CAMPO_FONTE      = "fonte"          # link da origem do preço — JÁ EXISTE
CAMPOS_DERIVADOS = {"valor_total"}  # derivado, não editável
```

O campo `fonte` já existe e já é exportado como link compacto. **O módulo
de preços é o preenchedor natural desse campo** — não é preciso inventar
coluna nova para proveniência do preço unitário.

### Feature flags

Convenção verificada em `governanca.py`: constante `FLAG_*` com valor em
snake_case inglês (`canonical_facts`, `process_consistency`,
`confidence_emission_gate`…), lida por `db.flag_ativa()`, default OFF.
A flag do módulo deve seguir isso — sugiro `FLAG_PESQUISA_PRECOS =
"price_research"` em `governanca.py`, e não uma string solta.

---

## B. COMO O MÓDULO ENTRA NO SISTEMA

```
Formulário Matriz (steps.render_formulario)
   └─ editor de itens (planilha)   ← ENTRADA A: "Pesquisar preços"
Dashboard                          ← ENTRADA B: pesquisa autônoma
Importação XLSX (planilha.importar_de_xlsx) ← ENTRADA C: já existe
        ↓
   pesquisa_precos (novo)
        ↓  aplica
   dados["itens"]  →  planilha.calcular  →  valor_global
        ↓
   state.invalidar_a_partir_de("formulario")   ← já existe, já testado
        ↓
   DFD / ETP / TR consomem só o FATO da estimativa
```

Três pontos de enxerto, todos já existentes — nenhum exige refatoração.

---

## C. DIAGRAMA DE DADOS

Schema atual: **28 tabelas**, todas com RLS habilitado. Nenhuma serve
para pesquisa de preços; a mais próxima (`geracoes`) é registro técnico
de geração de documento.

Proposta mínima — **4 tabelas**, justificadas uma a uma:

| tabela | por que não dá para reaproveitar |
|---|---|
| `pesquisas_preco` | cabeçalho com estado, perfil normativo, vínculo com processo e versão — não existe equivalente |
| `pesquisa_preco_itens` | um item pode ter estado próprio (`incomplete`) independente do processo; `processos.dados` é JSON e não indexa nem versiona por item |
| `pesquisa_preco_referencias` | **o volume mora aqui**: 210 itens × ~30 referências = ~6.300 linhas por pesquisa. JSON aninhado inviabilizaria filtro, exclusão auditável e reprodutibilidade |
| `pesquisa_preco_eventos` | trilha própria da pesquisa (inclusão/exclusão manual, mudança de método) |

Se a auditoria preferir menos, `pesquisa_preco_eventos` pode ser
substituída por `governanca_eventos` + vocabulário novo em `trilha.py`.
As outras três eu não consigo eliminar sem perder auditabilidade.

---

## D. FLUXO UX

Sem cópia do sistema de referência; usa os componentes GovConnect que já
existem (`render_page_header`, `render_stepper`, `render_section_heading`,
`render_summary_strip`).

```
Lista de pesquisas → Nova pesquisa
  Etapa 1 Identificação (nome, processo, objeto, responsável, local,
          data-base, perfil normativo)
  Etapa 2 Itens (importa do processo/XLSX; reusa o editor da planilha)
  Etapa 3 [Pesquisar automaticamente]  → progresso por item
  Etapa 4 Revisão por item (candidatos, filtros, score explicado,
          painel estatístico, anomalias)
  Etapa 5 Resumo global + relatórios
  Etapa 6 [Aplicar preços ao processo] → diff antes/depois → confirmação
```

---

## E. FONTES E APIS — **CONFIRMADAS CONTRA O SERVIDOR REAL**

Não confiei na documentação: chamei os endpoints deste ambiente.

### Compras.gov.br — Dados Abertos

`GET https://dadosabertos.compras.gov.br/v3/api-docs` → **77 endpoints**.
O módulo de pesquisa de preço existe e tem 4 endpoints (+ variantes CSV):

```
/modulo-pesquisa-preco/1_consultarMaterial
/modulo-pesquisa-preco/2_consultarMaterialDetalhe
/modulo-pesquisa-preco/3_consultarServico
/modulo-pesquisa-preco/4_consultarServicoDetalhe
```

**Contrato real de `1_consultarMaterial`:**

- obrigatórios: `tipo` (enum: `codigoItemCatalogo` | `codigoPdm`), `codigo`
- opcionais úteis: `estado`, `codigoMunicipio`, `codigoUasg`, `poder`,
  `esfera`, `codigoClasse`, `dataCompraInicio`, `dataCompraFim`,
  `dataResultado`, `pagina`, `tamanhoPagina`
- `tamanhoPagina` **precisa estar entre 10 e 500** (a API recusa 1 a 9)
- envelope: `{resultado[], totalRegistros, totalPaginas, paginasRestantes}`

**Consulta real executada** (CATMAT 236168, alicate wattímetro):
30 referências. Campos que a fonte devolve por referência — verificados,
não presumidos:

```
idCompra  idItemCompra  idCompraItem  numeroItemCompra
dataCompra  dataResultado  modalidade  forma  criterioJulgamento
precoUnitario  quantidade  percentualMaiorDesconto
siglaUnidadeFornecimento  nomeUnidadeFornecimento
capacidadeUnidadeFornecimento          ← FATOR DE EMBALAGEM
siglaUnidadeMedida  nomeUnidadeMedida
niFornecedor (CNPJ)  nomeFornecedor  marca
codigoUasg  nomeUasg  codigoOrgao  nomeOrgao
estado  codigoMunicipio  municipio  poder  esfera
codigoItemCatalogo  codigoPdm  nomePdm  codigoClasse  nomeClasse
descricaoItem  descricaoDetalhadaItem  objetoCompra
```

Isto cobre **praticamente todo** o modelo normalizado do §7 do prompt,
com uma exceção: não há URL direta da contratação — só identificadores.
A referência oficial terá de ser montada a partir do `idCompra`, ou o
link virá do PNCP.

> **`capacidadeUnidadeFornecimento` é a peça que viabiliza o §13.** É ela
> que diz quantas unidades há na caixa. No registro que examinei veio
> `0.0` — isto é, **não informada** —, e pela regra do prompt esse
> candidato **não pode** ser convertido de caixa para unidade. A regra
> não é teórica: ela terá efeito real e frequente.

### CATMAT — **achado que muda a arquitetura**

`/modulo-material/4_consultarItemMaterial` funciona: **344.781 itens**.
Mas o parâmetro `descricaoItem` **não faz busca textual livre**. Testei
`PASTA CATALOGO`, `PASTA`, `CANETA`, `PAPEL A4` — todos devolveram
`totalRegistros: 0`, enquanto a consulta sem filtro devolve 344.781.

Consequência direta: **não existe, nesta API, o caminho
"descrição do item → CATMAT"**. E esse caminho é o primeiro passo do
pipeline inteiro, porque o endpoint de preços exige `codigoItemCatalogo`
ou `codigoPdm` como parâmetro obrigatório.

É a decisão arquitetural que motiva a parada desta fase (§M).

### PNCP

`GET https://pncp.gov.br/api/consulta/v1/contratacoes/publicacao` →
**HTTP 200**, 1.737 registros para um único dia. Envelope
`{data[], totalRegistros, totalPaginas, numeroPagina, paginasRestantes}`.
Campos do nível de contratação incluem `srp`, `orgaoEntidade`,
`unidadeOrgao`, `amparoLegal`, `objetoCompra`, `linkSistemaOrigem`,
`processo`.

O PNCP é navegável **de cima para baixo** (contratação → itens →
resultados). Não achei busca por descrição de item que sirva de porta de
entrada. Serve muito bem como **enriquecimento e comprovação** — que é
exatamente o papel que o §5.2 prevê — mas não substitui o Compras.gov
como fonte primária de preço por item.

---

## F. PIPELINE DE PESQUISA

```
item do processo
  → resolver CATMAT/CATSER            ← O GARGALO (ver M-1)
  → consultar Compras.gov por código
  → paginar e deduplicar (idCompraItem)
  → normalizar unidade                ← bloqueia se não houver fator
  → pontuar comparabilidade
  → detectar discrepância estatística
  → selecionar cesta
  → calcular
  → enriquecer com PNCP (evidência)
  → revisão humana
```

## G. MATCHING

Fatores separados e explicáveis, cada um com origem verificável:

| fator | fonte do dado |
|---|---|
| descrição | `descricaoItem` / `descricaoDetalhadaItem` |
| catálogo | `codigoItemCatalogo`, `codigoPdm` |
| unidade | `siglaUnidadeFornecimento` + `capacidadeUnidadeFornecimento` |
| quantidade | `quantidade` |
| temporalidade | `dataCompra` / `dataResultado` |
| geografia | `estado`, `codigoMunicipio` |
| condições | `criterioJulgamento`, `modalidade`, `forma` |

A IA propõe; o score é composto por código. Cada fator vira uma linha
explicável na UI (`✓ mesma unidade`, `! outro estado`).

## H. MODELO ESTATÍSTICO

Determinístico, testável isoladamente: contagem, média, mediana, menor,
maior, amplitude, desvio, CV, quartis, IQR, MAD.

**Ponto de atenção:** `planilha.py` usa `float` com `round(x, 2)`, não
`Decimal`. `Decimal` só aparece em `govbot.py`. O §9 manda usar `Decimal`
"onde o projeto já adotar" — e o núcleo monetário **não adota**. Proponho
`Decimal` dentro do módulo de preços e conversão na fronteira com
`planilha`, sem mexer no núcleo. Diverge do resto do projeto e por isso
está declarado aqui em vez de decidido em silêncio.

## I. ESTRATÉGIA DE JOBS — **não há infraestrutura**

Verifiquei: `threading`, `asyncio`, `celery`, `rq`, `multiprocessing`,
`concurrent.futures`, `add_script_run_ctx` — **nenhuma ocorrência** em
`src/` ou `app.py`. Tudo roda síncrono dentro do script run do Streamlit.

Com 210 itens e ~1 s por chamada externa, uma pesquisa completa levaria
minutos com a UI congelada. O §46 proíbe isso e o §19 exige checkpoint,
retry, cancelamento, retomada e idempotência.

Três opções, com o custo real de cada uma:

| opção | como funciona | custo |
|---|---|---|
| **1. Lotes reentrantes** (recomendada) | cada rerun processa N itens, persiste checkpoint e chama `st.rerun()`; progresso vem do banco | nenhuma infra nova; UI responsiva; cancelável e retomável; mais lento |
| 2. `ThreadPoolExecutor` + `add_script_run_ctx` | paraleliza dentro do script run | some se a sessão cair; sem retomada; risco no Streamlit Cloud |
| 3. Worker externo (fila) | robusto de verdade | **segunda aplicação** — o §46 manda documentar em vez de introduzir em silêncio |

A opção 1 satisfaz todos os requisitos do §19 sem infraestrutura nova, e
é a que recomendo. A 3 fica registrada para quando o volume exigir.

## J. PERSISTÊNCIA E RLS — **risco herdado**

As migrações **0018, 0019 e 0020 continuam `.NAO_APLICAR`**. Ou seja: o
RLS existe nas 28 tabelas, mas as políticas que amarram tenant ao
`auth.uid()` **não estão em produção**, e o app opera pelo cliente de
servidor, que atravessa RLS por definição.

O §39 diz: "não ativar este módulo em produção sem provar o mesmo
isolamento exigido do restante da plataforma". Traduzindo: as tabelas
novas nascem com RLS e política restritiva desde o primeiro commit, mas
**o isolamento efetivo do módulo depende de um débito que não é dele** e
que continua aberto. Isso limita o veredito final, não o início.

## K. INTEGRAÇÃO DFD / ETP / TR

O objeto de estimativa vira **fato canônico** em `fatos.py`, com
proveniência (`pesquisa_id`, `versao`, `metodologia`). DFD/ETP/TR
consomem o fato, não a pesquisa. A memória completa fica no relatório.
`consistencia.py` ganha a conferência: valor global do processo ==
valor global da pesquisa aplicada.

## L. RELATÓRIOS

Reuso integral de `export.py` — mesmo DOCX institucional, mesmo
LibreOffice, mesmas larguras proporcionais de tabela, mesmo gate de
geometria já provado na Fase 2.1. Nenhum segundo pipeline de PDF.
XLSX pela via que `planilha.modelo_xlsx()` já usa.

## M. RISCOS

**M-1 — resolução do código de catálogo — RESOLVIDO.** Ver adendo abaixo.

**M-2 — sem credencial de IA (ALTO, bloqueia parte).** `llm.motor_ativo()`
devolve `''`. A camada semântica (§8) não pode ser exercitada, exatamente
como a Fase 3 do padrão ouro segue bloqueada. As camadas determinísticas
— adapters, normalização, estatística, relatório — **podem** ser
construídas e testadas sem chave.

**M-3 — sem jobs (MÉDIO).** Ver §I. Mitigável pela opção 1.

**M-4 — RLS não aplicada (MÉDIO, herdado).** Ver §J.

**M-5 — dado externo é hostil (MÉDIO).** `objetoCompra` e
`descricaoDetalhadaItem` são texto livre de terceiros e vão para dentro
de um prompt. O §56 exige tratamento como dado. O `govbot.py` já resolve
isso e deve ser reusado, não reescrito.

**M-6 — float no núcleo monetário (BAIXO).** Ver §H.

**M-7 — sem URL direta no Compras.gov (BAIXO).** A evidência dependerá de
identificadores + PNCP.

## N. PLANO DE TESTES

- **adapters**: fixtures dos payloads reais já capturados; paginação,
  campo ausente, preço zero/nulo, `tamanhoPagina` fora de 10–500,
  timeout, 429, 5xx, duplicata por `idCompraItem`;
- **unidade**: `capacidadeUnidadeFornecimento = 0.0` **não converte**;
  com fator explícito, converte de forma determinística;
- **matching**: pares positivos e negativos (pasta catálogo 100 envelopes
  × pasta comum × pacote de envelopes);
- **monetário**: média, mediana, arredondamento, quantidade fracionária,
  outlier, exclusão, valor global;
- **regra dos três**: 2 referências ⇒ `INCOMPLETO`, nunca `CONCLUÍDO`;
- **não invenção**: `source_id` forjado, preço adulterado, CATMAT
  inexistente — servidor rejeita;
- **prompt injection**: descrição externa com "ignore as instruções";
- **integração**: 210 itens → aplicar → invalidar → conferir provenance;
- **multi-tenant**: A não vê B (limitado pelo M-4);
- **performance**: 1, 10, 50 e 210 itens.

## O. FASES E COMMITS

| fase | entrega | depende de |
|---|---|---|
| 1 | domínio, normalização, adapters Compras.gov + PNCP, fixtures | **decisão M-1** |
| 2 | matching e estatística determinística | — |
| 3 | schema + migration versionada (não aplicada) + RLS | — |
| 4 | UI GovConnect | 1–3 |
| 5 | integração com o processo (aplicar, invalidar, provenance) | 4 |
| 6 | relatórios via `export.py` | 5 |
| 7 | GovBot e camada semântica | **M-2 (credencial)** |
| 8 | QA, segurança, 210 itens | todas |

---

## VEREDITO

### APTO PARA INICIAR IMPLEMENTAÇÃO — com uma decisão pendente

A arquitetura existente comporta o módulo sem refatoração estrutural: a
estrutura canônica de itens serve, a invalidação já existe e é testada, o
exportador é reusável, o GovBot já traz a disciplina de "modelo propõe,
servidor valida", e as duas APIs oficiais respondem e têm contrato
compatível com o modelo normalizado do prompt.

**Paro aqui**, como o §65 determina, por causa do **M-1**: a resolução
`descrição → CATMAT` não existe na API, e ela é o primeiro passo de todo
o pipeline. As três alternativas mudam materialmente o escopo da Fase 1 e
a decisão é de produto, não minha.

Enquanto isso não se decide, as Fases 2 e 3 (matching/estatística e
schema/migration) podem andar sem risco, porque não dependem do M-1.

Não declaro `APTO PARA PRODUÇÃO` — e não declararei enquanto persistirem
o M-2 (sem credencial, camada semântica não exercitada) e o M-4 (RLS não
aplicada).

---

# ADENDO — decisão de produto sobre CATMAT/CATSER e o M-1

**Decisão recebida:** o sistema **não pode exigir** CATMAT/CATSER, mas
**deve aceitá-los e usá-los quando pertinentes**.

A decisão está certa, e a investigação que ela motivou mudou o desenho —
para melhor. Registro também uma correção do que eu havia concluído.

## Correção do que eu disse antes

Eu afirmei que "não existe o caminho descrição → CATMAT". Isso vale para
o **endpoint de catálogo** (`4_consultarItemMaterial`), onde `descricaoItem`
de fato devolve zero para texto livre — confirmado. Mas eu havia parado
cedo demais: a conclusão de que o pipeline inteiro dependia de resolver o
código **estava errada**.

Varri os 77 endpoints. Nenhum oferece busca textual livre — mas
`/modulo-contratacoes/2_consultarItensContratacoes_PNCP_14133` devolve,
**na mesma chamada e sem exigir código algum**:

```
descricaoResumida  descricaodetalhada        ← descrição em texto livre
codItemCatalogo  codigoPdm  codigoGrupo      ← o código, QUANDO existe
unidadeMedida  quantidade
valorUnitarioEstimado  valorUnitarioResultado ← preço homologado
nomeFornecedor  codFornecedor
situacaoCompraItemNome  temResultado
criterioJulgamentoNome  numeroControlePNCPCompra
```

Obrigatórios: apenas a janela de datas (`dataInclusaoPncpInicial/Final`).
Opcionais úteis: `codItemCatalogo`, `codigoClasse`, `codigoGrupo`,
`materialOuServico`, `temResultado`.

É exatamente a forma que a decisão pede: **filtra por código quando há
código, funciona sem ele quando não há.**

## Quanto disso é real — medido, não estimado

Amostra de **500 itens** de contratações reais (01–07/08/2025):

| campo | presença |
|---|---|
| descrição | **500/500 — 100%** |
| unidade | 500/500 — 100% |
| quantidade | 500/500 — 100% |
| `codItemCatalogo` | 490/500 — 98,0% |
| `codigoPdm` | 453/500 — 90,6% |
| preço homologado | 450/500 — 90,0% |

Ou seja: **o corpus federal é bem catalogado** (98% com CATMAT). O
problema nunca esteve lá — está do lado do usuário. A planilha municipal
do nosso caso de 210 itens traz **códigos internos do município**
(`572704`, `763`…), não CATMAT. Exigir CATMAT significaria mandar o
servidor mapear 210 itens à mão, que é precisamente o trabalho que o
módulo existe para eliminar (§68).

## A escada de resolução que implementa a decisão

```
1. CATMAT/CATSER informado pelo usuário
   → caminho preferencial: 1_consultarMaterial (tipo=codigoItemCatalogo)
   → série de preços mais precisa e mais barata em chamadas

2. Não informado → o sistema tenta resolver SOZINHO
   → casa a descrição do item contra descricaodetalhada de itens
     REALMENTE CONTRATADOS (que já trazem o codItemCatalogo)
   → confiança alta ⇒ segue para o caminho 1, marcando a proveniência
     "código resolvido pelo sistema", nunca como se o usuário o tivesse
     informado

3. Resolução fraca, ambígua ou item fora do catálogo
   → caminho SEM código: janela de data + classe/grupo quando inferível,
     com filtragem por descrição sobre o próprio corpus contratado
   → PNCP em paralelo, para enriquecimento e comprovação

4. Nada resolve
   → PESQUISA INCOMPLETA para aquele item, com o motivo nomeado
   → caminhos manuais: informar o código, ajustar filtros, anexar cotação
```

O passo 2 tem um efeito colateral bom: o índice local **não precisa ser o
catálogo inteiro de 344.781 itens**. Basta indexar itens efetivamente
contratados — que são menos, mais relevantes, já vêm com código **e já
trazem o preço**. O mesmo dado serve para resolver e para cotar.

## Consequência para as fases

- a Fase 1 deixa de depender de uma carga do catálogo completo;
- o adapter primário passa a ser `2_consultarItensContratacoes_PNCP_14133`
  (descrição + preço + código, sem exigência), com `1_consultarMaterial`
  como refinamento quando há código;
- o casamento por descrição do passo 2 tem uma camada **determinística**
  (tokens, unidade, classe) que roda **sem credencial de IA** — o M-2
  deixa de bloquear a Fase 1 e passa a limitar apenas o refinamento
  semântico;
- CATMAT/CATSER entram como **coluna opcional** na planilha, aproveitada
  quando presente. Nada a exigir do usuário.

**M-1 encerrado.** Não há mais decisão arquitetural pendente para iniciar
a implementação.

---

# FASE 1 — domínio, normalização e adapters (entregue)

Escopo do prompt: modelos, normalização, Compras.gov, PNCP, fixtures,
testes. **Sem** matching ranqueado, estatística, persistência, UI ou
integração com o processo — cada uma tem fase própria.

## O que foi criado

```
src/precos/
  modelo.py       Referencia, Fonte, StatusReferencia, Decimal, hash do bruto
  unidades.py     dicionário determinístico + regra que RECUSA converter
  fontes.py       Consulta, ResultadoBusca, FontePesquisaPreco
  compras_gov.py  adapter com os DOIS caminhos (com e sem código)
  pncp.py         adapter de comprovação + link oficial
tests/test_precos_fase1.py          58 provas
tests/fixtures/precos/*.json        payloads REAIS recortados
```

## As quatro garantias que a Fase 1 já entrega

1. **unidade só converte com prova.** `capacidadeUnidadeFornecimento`
   vem `0.0` quando a fonte não informa; tratar esse zero como fator 1
   transformaria "R$ 18,00 a caixa" em "R$ 18,00 a unidade". A referência
   não é convertida **nem descartada** — chega ao revisor na unidade
   original, com o motivo escrito;
2. **CATMAT aceito, nunca exigido** — virou teste: com código o adapter
   usa `1_consultarMaterial`; sem código ele **não chama** o endpoint que
   o exige e vai pelo caminho de contratações;
3. **preço é `Decimal`**, o payload bruto é preservado ao lado do
   normalizado, e "não informado" é `None`, nunca zero;
4. **falha de fonte vira ocorrência**, não exceção na tela: timeout e
   resposta não-JSON (que a API devolve em erro de validação) são
   retentados com recuo e registrados.

## Ensaio contra a API oficial

Executado de verdade, não simulado:

| | resultado |
|---|---|
| healthcheck Compras.gov / PNCP | ambos OK |
| busca **sem** código ("CADEIRA ESCRITORIO GIRATORIA") | 2 referências, CATMAT 373771 resolvido pela própria fonte, preços normalizados |
| busca **com** código (CATMAT 236168) | 30 referências: R$ 1.240,67 / R$ 1.980,00 / R$ 4.334,31, com órgão, UF, data e marca |
| link oficial de evidência | `00444232000139-1-000437/2025` → `https://pncp.gov.br/app/editais/00444232000139/2025/437` |

A dispersão do CATMAT 236168 (1.240 a 4.334 para o mesmo item) é o
material que a Fase 2 terá de tratar — e mostra por que "os três menores
preços" seria uma cesta falsa.

> Registro de um susto útil: no primeiro ensaio o caminho com código
> devolveu **zero**. Não era defeito — a janela de datas que passei
> (01–07/08) excluía o dado real, que é de 24/07. Verifiquei antes de
> concluir; a prova de contrato hoje roda sem janela, com o motivo
> comentado, para que ninguém leia esse zero como adapter quebrado.

## Testes

58 provas no arquivo novo: **55 rodam sem rede** (fixtures reais
injetados) e **3 são de contrato** contra a API oficial, atrás de
`GOVDOCS_ENSAIO_APIS_PRECOS=1` — a suíte inteira não depende da internet
(§48). Com a flag ligada, as 58 passam.

Suíte completa do projeto: **1429 passaram, 0 falharam, 158 pularam**
(155 de sempre + as 3 de contrato). `git diff --check` limpo.

## O que a Fase 1 NÃO faz — e é proposital

- não ranqueia candidatos (Fase 2);
- não calcula média/mediana/cesta (Fase 2);
- não persiste nada (Fase 3);
- não tem tela (Fase 4);
- não toca no processo (Fase 5);
- **não chama IA** — o filtro por descrição é determinístico (tokens
  significativos, ruído de catálogo descartado). O refinamento semântico
  é da Fase 7 e depende de credencial.

## Veredito da Fase 1

`APTO PARA AUDITORIA`

---

# FASE 2 — matching, estatística, anomalias e cesta (entregue)

Escopo: classificação, ranking, comparabilidade, cálculo, anomalias e
testes. **Sem** persistência, UI, integração com o processo ou IA.

```
src/precos/
  perfil.py       PerfilNormativo — Lei 14.133 (base) e IN 65/2021
  matching.py     comparabilidade explicável por fatores
  estatistica.py  cálculo Decimal, anomalias, cesta e estimativa
tests/test_precos_fase2.py   48 provas
```

## O defeito que os testes pegaram — e mudou o desenho

A primeira versão somava sete fatores numa média ponderada única. O teste
`test_cesta_nao_e_a_dos_tres_mais_baratos` reprovou: um **GRAMPEADOR**
entrava na cesta de uma **PASTA CATÁLOGO** com 55% de comparabilidade,
porque unidade, data, quantidade, estado e critério estavam todos
corretos — e juntos superavam o peso da descrição.

Circunstância impecável não transforma um produto em outro. O modelo
passou a responder **duas perguntas separadas**:

```
identidade      = é o mesmo produto?     (descrição, catálogo)
circunstancias  = a contratação é comparável?  (unidade, data,
                  quantidade, geografia, condições — média ponderada)

score = identidade × circunstancias
```

Multiplicação, não peso: produto diferente zera o total por melhor que
seja o resto. O grampeador agora tem circunstâncias 0,88 e identidade
0,05 — score 0,04, longe do piso.

Guardar as duas parcelas separadas tem valor próprio no relatório: "é o
produto certo, mas a contratação é velha" e "a contratação é perfeita,
mas é outro produto" dão notas parecidas e exigem decisões opostas.

Na descrição, a semelhança é a média de **Jaccard** e **sobreposição** —
Jaccard sozinho pune a fonte oficial por descrever o mesmo item com mais
detalhe; sobreposição sozinha aceita "PASTA" como igual a "PASTA CATÁLOGO
100 ENVELOPES". Código de catálogo idêntico prevalece sobre a redação;
código diferente derruba a identidade.

## As fronteiras que a Fase 2 impõe

- **cesta por comparabilidade e prioridade de fonte, nunca por preço**
  (§12). Sistema oficial antes de contratação similar;
- **outlier estatístico ≠ preço inexequível** (§10). IQR e MAD sinalizam
  e explicam a distância da mediana; há teste que proíbe as palavras
  "inexequível", "ilegal", "irregular" e "sobrepreço" no texto gerado;
- **exclusão não apaga** — o descartado fica na série com status e
  motivo; abaixo do piso vira `REVISAO_MANUAL`, disponível para inclusão
  humana;
- **a regra dos três não se cumpre fabricando referência** (§11, §53).
  Duas referências ⇒ `INCOMPLETO`, com o caminho de saída escrito;
- **série pequena (< 4) não gera alarme** — com três pontos qualquer um
  parece distante.

## Perfil normativo (§3, §22)

`Lei 14.133` é a base; `IN 65/2021` **não** é norma municipal automática
e por isso é um perfil próprio. A diferença material está implementada e
testada: com estimativa apoiada **exclusivamente** em sistema oficial, a
IN 65 limita o valor à mediana da amostra — média de 33,33 é ajustada
para 30,00; com uma fonte de outro tipo na cesta, a restrição não se
aplica.

## Ensaio ponta a ponta sobre dados REAIS

CATMAT 236168, 30 referências vindas da API oficial:

```
top por COMPARABILIDADE   83%  R$ 4.334,31  SP   (não é o mais barato)
                          79%  R$ 1.980,00  CE
                          77%  R$ 7.999,88  PA
n=30  menor R$ 490,00  maior R$ 7.999,88
média R$ 2.629,85   mediana R$ 2.244,94   CV 0,57   IQR 805,13
método automático: MEDIANA (série dispersa)
PREÇO ESTIMADO: R$ 2.244,94      total p/ 12 un: R$ 26.939,28
5 candidatos discrepantes sinalizados — nenhum excluído
```

Duas coisas que o revisor precisa ver aqui:

1. **a mais comparável (83%) é também a segunda mais cara**, e está entre
   as sinalizadas como discrepante. Não é contradição: comparabilidade e
   dispersão de preço são perguntas diferentes. É exatamente o caso em
   que o julgamento humano decide, e é por isso que o sistema mostra as
   duas informações em vez de resolver sozinho;
2. **CV de 0,57 no mesmo CATMAT** — R$ 490 a R$ 7.999 pelo mesmo item de
   catálogo. É o material real que torna "os três menores preços" uma
   cesta indefensável.

## Testes

48 provas novas, todas sem rede e sem IA. Suíte completa do projeto:
**1477 passaram, 0 falharam, 158 pularam**. `git diff --check` limpo.

## Veredito da Fase 2

`APTO PARA AUDITORIA`
