# Fase 2 — Relatório

Branch: `integracao-padrao-ouro-main-atual`. Data: 20/08/2026.
**Nenhum merge na `main`. Nenhum PR. Fase 3 não iniciada.**

---

## A. CAUSA-RAIZ

Existia **uma única representação** do Formulário Matriz, escrita para o
modelo, e o Modo Demonstração a colava no corpo do documento:

```
_gerar_demo(doc_key, dados)
 └─ prompts.formatar_dados_formulario(dados)          ← A FUNÇÃO QUE MISTURAVA
      └─ campo "itens" → planilha.resumo_para_prompt(itens, valor_global)
           ├─ "PROIBIDO escrever a lista de itens…"           instrução ao modelo
           ├─ "…coloque a marca [[TABELA_ITENS]] EXATAMENTE UMA VEZ…"
           └─ planilha.resumo_semantico(itens)
                └─ "COMPOSIÇÃO FUNCIONAL DO OBJETO (para você compreender…"
 └─ planilha.injetar_tabela(texto, itens)   substitui o marcador pela planilha
```

Reproduzido antes de alterar qualquer linha, com o fixture de 210 itens
(34.940 caracteres, 267 linhas). Trechos internos encontrados **dentro do
DFD**:

| linha | trecho |
|---|---|
| 34 | `PROIBIDO escrever a lista de itens, ainda que parcialmente…` |
| 34 | `…é inserida AUTOMATICAMENTE no lugar da marca` |
| 34 | `…se eles contiverem a lista, ignore-a…` |
| 250 | `.` — sobra da frase partida quando o marcador virou tabela |
| 251 | `Escreva o texto da cláusula de estimativa de valor … EXATAMENTE UMA VEZ, SOZINHA em uma linha própria` |
| 252 | `COMPOSIÇÃO FUNCIONAL DO OBJETO (para você compreender o que se contrata; NÃO reproduza esta análise como lista)` |

Um ato administrativo dando ordens a quem o redige. O marcador
`[[TABELA_ITENS]]` não sobrevivia (a injeção o consumia), mas a frase que
o citava sobrevivia — partida ao meio.

## B. ARQUITETURA — antes e depois

**Antes**

```
CAMPOS_FORMULARIO ─→ formatar_dados_formulario ─┬─→ montar_prompt   (IA)
                                                └─→ _gerar_demo     (documento)
```

**Depois**

```
CAMPOS_FORMULARIO ─→ _bloco_do_formulario(dados, doc_key, para_modelo)
                       │  percurso ÚNICO dos campos
                       │  planilha.calcular() ÚNICO
                       ├─ para_modelo=True  → formatar_dados_formulario
                       │     └─ planilha.resumo_para_prompt   → montar_prompt
                       └─ para_modelo=False → dados_objetivos_do_formulario
                             └─ planilha.resumo_objetivo      → _gerar_demo
```

A separação é de **destino**, não de dados. Continuam únicos: o percurso
dos campos, o cálculo da planilha e o ponto de injeção
(`MARCADOR_TABELA`). A diferença fica em dois pontos, ambos fala dirigida
ao modelo: o rendering do bloco da planilha e o enquadramento
"PREFERÊNCIA DE MODELAGEM" do modelo de execução no ETP.

`planilha.resumo_objetivo` é a contrapartida documental de
`resumo_para_prompt`: os mesmos fatos (nº de itens, valor global,
unidades de fornecimento) sem uma linha de instrução. O marcador da
tabela permanece nas duas — é o ponto de injeção determinístico, e
`injetar_tabela` o consome antes de o documento existir.

O resumo semântico por famílias continua indo **para o prompt** de DFD,
ETP e TR, intocado.

## C. MODO DEMONSTRAÇÃO — antes e depois

**Antes** (cláusula 5 do DFD):

```
## 5. Estimativa Preliminar de Valor

Conforme dados informados:

- Planilha Orçamentária (itens da contratação):
A planilha orçamentária do processo possui 210 item(ns). VALOR GLOBAL … 
PROIBIDO escrever a lista de itens, ainda que parcialmente: nada de códigos,
descrições, quantidades, preços, links ou linhas de tabela — nem a partir do
memorando ou dos anexos (se eles contiverem a lista, ignore-a: a tabela oficial
vem da planilha do sistema). A TABELA COMPLETA … é inserida AUTOMATICAMENTE no
lugar da marca [[TABELA_ITENS]].
```

**Depois**:

```
## 5. Estimativa Preliminar de Valor

Conforme dados informados:

- Órgão / Entidade Requisitante: Prefeitura Municipal de Ensaio
- Responsável pela Demanda (nome e cargo): Maria Souza Lima
- Objeto Detalhado da Contratação: Aquisição de materiais de expediente
- Justificativa e Problema a Ser Resolvido: Reposição do estoque.
- Alinhamento Estratégico (PCA / Planejamento): PCA 2026, item 14.
- Planilha Orçamentária (itens da contratação):
Quantidade de itens: 210.
Valor global estimado: R$ 8.024.834,67.
Unidades de fornecimento: CAIXA, CARTELA, EMBALAGEM, …

| Código | Descrição | Unidade | Quantidade | Valor Unitário | Valor Total |
…210 linhas…
```

Continua explícito, offline, identificado como
`Minuta-esqueleto gerada em Modo Demonstração (sem IA)` e útil para
exercitar interface e exportação. Verificado nos **quatro** documentos
(DFD, ETP, TR, Edital), não só no DFD.

## D. VALIDAÇÃO — a segunda barreira

Oito padrões novos em `validacao._BLOQUEANTES` (mecanismo existente,
nenhum validador paralelo). Todos miram **frases** inequívocas:

| padrão | rótulo |
|---|---|
| `PROIBIDO escrever a lista de itens` | instrução de prompt no corpo |
| `EXATAMENTE UMA VEZ, SOZINHA` | instrução de prompt no corpo |
| `não reproduza esta análise/lista/tabela/amostra` | instrução de prompt no corpo |
| `amostra (apenas) ilustrativa` | instrução de prompt no corpo |
| `para você compreender/entender/saber/usar` | fala dirigida a quem redige |
| `(tabela\|planilha) … (será\|é) inserida … automaticamente\|no lugar da marca` | mecânica interna de injeção |
| `no lugar da marca` | ponto de injeção interno |
| `COMPOSIÇÃO FUNCIONAL DO OBJETO (` | bloco de contexto do prompt |

`[[TABELA_ITENS]]` já bloqueava, desde antes.

**Positivos testados** (8): os oito trechos acima, injetados
artificialmente num documento limpo — todos bloqueiam a emissão.

**Negativos testados** (12), todos passam sem bloqueio:

- "A **análise** de riscos consta do item 7 deste documento."
- "Os valores serão reajustados **automaticamente** na forma do art. 92, §3º."
- "O pagamento será processado **automaticamente** após o atesto da nota."
- "A **amostra** do produto poderá ser exigida para fins de aceitação."
- "O licitante deverá apresentar **amostra** no prazo de 5 (cinco) dias úteis."
- "**Não reproduza** o logotipo do órgão sem autorização prévia."
- "A **tabela** de preços de referência integra o Anexo I deste Termo."
- "A **planilha** orçamentária **será inserida** no processo pela unidade requisitante."
- "A **composição funcional do objeto** abrange materiais de expediente."
- "A contratada deverá **escrever** o relatório mensal de execução."
- "Cada item deverá ser entregue **exatamente uma vez** por competência."
- "O sistema atualiza o saldo **automaticamente** a cada empenho."

Mais dois controles: o Edital e a ARP do catálogo determinístico
atravessam a barreira sem tropeçar; e o bloco destinado ao modelo, se
algum dia voltar a virar corpo de documento, **é reprovado**.

## E. GEOMETRIA

**Motor de PDF real: `libreoffice`.** Este contêiner tinha apenas
`libreoffice-core` — sem `libreoffice-writer`, nenhum filtro de documento
carrega e a sonda de `motor_pdf()` respondia `fpdf2`, fazendo as provas
de PDF institucional **pularem**. Instalei o Writer para poder medir. O
`packages.txt` do repositório já declara `libreoffice` (meta-pacote que
inclui o Writer), então a implantação real não tem essa lacuna — o
ambiente é que estava incompleto.

Foram encontrados **dois** defeitos distintos, não um.

### E.1 — Texto fora da folha (renderizador fpdf2)

| | páginas | largura da folha | maior `x1` | spans fora |
|---|---|---|---|---|
| **antes** (commit-base `7953a35`, fpdf2) | 35 | 595,3 pt | **603,5 pt** | **3** |
| **depois** (HEAD, fpdf2) | 14 | 595,3 pt | 535,8 pt | **0** |
| **depois** (HEAD, LibreOffice) | 15 | 595,3 pt | 541,7 pt | **0** |

Spans reprovados no "antes": `'  -  Respons'` (×2, 598,1 pt) e
`'coloque a m'` (603,5 pt).

**Causa real:** não é o fpdf2 "por ser fpdf2", e não é o LibreOffice — o
LibreOffice nunca reprovou (0 spans fora, nas duas pontas). É a mecânica
de cursor do fpdf2: `multi_cell` deixa, por padrão, o cursor **à direita
da célula e na mesma linha**; dois parágrafos consecutivos sem linha em
branco entre eles faziam o segundo começar na borda direita e escorrer
para fora do papel. A correção — `new_x="LMARGIN", new_y="NEXT"` em toda
chamada — **já veio na integração do padrão ouro** (Fase 1), o que
explica o "depois" limpo.

Restava um flanco, corrigido agora: o laço que tenta fontes decrescentes
ao renderizar uma tabela podia recomeçar de onde uma tentativa fracassada
parou. Cada tentativa passa a começar em `pdf.l_margin`, e o caminho
degradado também.

### E.2 — Palavra partida na tabela (conversão DOCX→PDF) — defeito novo

Este só apareceu com o LibreOffice instalado, e é mais grave que o
overflow: no PDF real o código `572704` saía como `57270` + `4`, e o
cabeçalho `Quantidade` como `Quanti` + `dade`.

| | códigos ausentes do texto extraído | valor global |
|---|---|---|
| **antes** | **210 de 210** | ausente |
| **depois** | **0** | presente |

Os 210 códigos existiam na página, mas partidos — impossíveis de
localizar, conferir ou auditar no PDF.

**Causa:** o piso de largura de coluna era um número fixo (`1,4 cm`) que
não olhava para o texto, e a margem interna de célula do Word (0,19 cm de
cada lado, por padrão) não entrava na conta. Sobravam 1,02 cm de área
útil para um código que ocupa 1,06 cm em Times 10.

**Correção:** o piso passa a ser o do **maior token indivisível** de cada
coluna, medido pelas métricas reais da fonte (o fpdf2 já embarca as do
Times — nada de constante de "largura média de caractere", que erra
justamente em dígitos e maiúsculas); e a margem interna passa a ser
declarada (`w:tblCellMar`, 0,08 cm) e descontada. O excedente sai das
colunas com folga sobre o próprio piso: a Descrição cede, o Código não.

Larguras do caso de 210 itens, em cm:

| coluna | antes | depois | piso exigido |
|---|---|---|---|
| Código | 1,40 | 1,40 | 1,24 |
| Descrição | 8,59 | 7,36 | 3,79 |
| Unidade | 1,55 | **2,43** | 2,43 |
| Quantidade | 1,64 | **1,94** | 1,94 |
| Valor Unitário | 1,94 | 1,85 | 1,59 |
| Valor Total | 2,01 | 2,01 | 2,01 |
| **soma** | 17,13 | **16,99** | (útil: 17,00) |

### E.3 — Área útil

Medida à parte e com tolerância própria: **1,5 mm**. Na borda da área
útil a caixa do glifo passa da largura de avanço em itálico e em linha
justificada — medido neste corpus, 3,09 a 3,14 pt, sempre em linha
justificada encostada na margem. O gate da **folha** permanece estrito
(0,5 pt). Cabeçalho, rodapé e timbrado são medidos pela folha, não pela
área útil — reprová-los seria falso positivo.

A prova de geometria tem **controle positivo**: um PDF deliberadamente
estourado precisa ser reprovado pela mesma medição, senão o teste poderia
estar passando por não medir nada.

## F. FIXTURE DE 210 ITENS

| aferição | resultado |
|---|---|
| linhas de item no DFD demo | **210** |
| cabeçalhos de tabela | **1** (tabela única) |
| valor global | **R$ 8.024.834,67** |
| `conferir_tabela` | sem divergência |
| bloqueios de vazamento de prompt | **nenhum** |
| códigos ausentes do PDF extraído | **0** (eram 210) |
| spans fora da folha | **0** |
| linguagem interna no corpo | **zero**, nos 4 documentos |

O DFD demo mantém 2 bloqueios e 8 avisos — todos de **profundidade e
pendência** (`[PREENCHER: …]`), que é o que uma minuta-esqueleto deve
ter. Nenhum é de mecânica interna.

## G. TESTES

| | coletados | passaram | falharam | pulados |
|---|---|---|---|---|
| antes da Fase 2 | 1106 | 951 | 0 | 155 |
| **HEAD** | **1154** | **999** | **0** | **155** |

`git diff --check`: limpo.

**48 provas novas** — 38 de separação prompt × conteúdo e validação, 10
de geometria e tabelas.

Os 155 skips são os mesmos de sempre: 65 de isolamento, 50 de ensaio SQL
local e 40 de ensaio de segurança, todos exigindo projeto/banco
descartável que a Etapa E proíbe substituir por produção.

**Três testes que estavam pulando passaram a rodar** quando instalei o
LibreOffice Writer, e falharam. Verifiquei no commit-base: falhavam
igual lá — **não eram regressão da Fase 2**. Um revelou o defeito E.2
(corrigido). Os outros dois mediam a coisa errada e foram corrigidos:

- `test_pdf_via_libreoffice_quando_disponivel` exigia numeração de página
  no PDF institucional **sem timbrado**. O rodapé numerado é desenhado
  pelo renderizador fpdf2; o DOCX só ganha rodapé quando há timbrado, e
  aí ele é o texto institucional do órgão. A asserção passou a fixar o
  que existe de fato, e a conferir que **com** timbrado o rodapé aparece;
- `test_pdf_nao_quebra_palavras_a_cada_poucos_caracteres` reprovava
  `el ástico`, `integr ada` e `ident ificação` — que estão **quebradas no
  próprio fixture**, porque o caso real veio de uma extração de PDF.
  Reprovar por elas era testar o fixture, não o exportador. A asserção
  passa a ignorar o que já vem partido da fonte e a cobrar apenas o que a
  renderização parte.

**Sem regressão:** as 7 chamadas a `components.*` em `steps.py` seguem
idênticas às da `main` (GovConnect intacto); `src/auth.py`, `src/db.py`,
`src/trilha.py`, `supabase/**` e `scripts/**` com **diff vazio**; os 11
pontos de integração P0/P1 iguais ou maiores.

## H. ARQUIVOS E COMMITS

```
3061c4c  fix: separa o que é para a IA do que é para o documento
06c7ba2  fix: linguagem de prompt no corpo do ato passa a bloquear a emissão
f196194  fix: coluna de tabela não parte mais palavra, e o cursor volta à margem
```

| arquivo | o que mudou |
|---|---|
| `src/prompts.py` | `_bloco_do_formulario` (percurso único) + `dados_objetivos_do_formulario` |
| `src/planilha.py` | `resumo_objetivo`, `_unidades_de_fornecimento` |
| `src/llm.py` | `_gerar_demo` usa a representação documental; docstring de `gerar_documento` corrigida |
| `src/validacao.py` | 8 padrões de linguagem de prompt em `_BLOQUEANTES` |
| `src/export.py` | piso por token indivisível, margem de célula explícita, cursor na margem a cada tentativa |
| `tests/test_fase2_prompt_e_conteudo.py` | novo — 38 provas |
| `tests/test_fase2_geometria_pdf.py` | novo — 10 provas |
| `tests/test_padrao_ouro_export.py` | asserção de quebra corrigida |
| `tests/test_export_estilos.py` | asserção de rodapé corrigida |

## I. LIMITAÇÕES — o que continua dependendo da Fase 3

- **A prosa real da IA não foi medida.** Não há chave de OpenAI nem de
  Gemini neste ambiente. Tudo aqui foi medido no Modo Demonstração e nos
  instrumentos determinísticos. Se o modelo devolver a instrução que
  recebeu, a barreira da Etapa D bloqueia — mas **isso não foi observado
  com um modelo real**, apenas com o vazamento injetado à mão;
- as metas de `perfis.py` (~4.800 / ~12.500 / ~11.400 palavras) seguem
  sem aferição: exigem geração real;
- comparação textual profunda com o corpus ouro: Fase 3;
- a prova de geometria e as de PDF institucional **pulam** onde o
  LibreOffice Writer não estiver instalado. O skip é explícito e nomeia o
  motivo; `packages.txt` já declara `libreoffice`.

## J. VEREDITO

### APTO PARA AUDITORIA DA FASE 2

Os cinco objetivos foram fechados, e cada um com medição:

1. vazamento de instrução de prompt — eliminado na origem, zero
   ocorrências nos quatro documentos;
2. mistura arquitetural — separada por destino, sem segundo pipeline;
3. bloqueio de linguagem interna — 8 padrões, 8 positivos e 12 negativos;
4. texto fora da folha — 3 spans → 0, com a causa nomeada (cursor do
   fpdf2), mais um segundo defeito que ninguém tinha visto: 210 códigos
   ilegíveis no PDF real → 0;
5. docstring de `gerar_documento` — passa a descrever o código.

Dois pontos que a auditoria deve pesar:

1. **o defeito E.2 estava invisível** porque o ambiente não tinha o
   LibreOffice Writer e as provas pulavam. Vale considerar tornar a
   ausência do motor institucional uma falha de ambiente, e não um skip,
   em CI;
2. **duas asserções antigas foram alteradas.** Ambas mediam coisa
   diferente do que declaravam, e a mudança está justificada em G — mas é
   alteração de teste existente e merece confirmação.

Nada aqui autoriza merge, PR ou implantação. **Fase 3 não foi iniciada.**
