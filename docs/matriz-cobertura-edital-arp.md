# Matriz de cobertura — templates determinísticos de Edital e ARP

Gerada a partir de `templates_gov.CLAUSULAS_BASE` (a fonte que o código
realmente monta), não de uma descrição paralela.

## ⚠️ Esta matriz NÃO declara conformidade jurídica

A última coluna está inteiramente marcada como **não comparado**, e é
por um motivo objetivo: **os modelos oficiais municipais de Edital e de
Ata de Registro de Preços não foram fornecidos**. O material de
referência recebido nesta sessão foram três conjuntos — `DFD
ANTERIORES`, `ETPs ANTERIORES` e `TRs ANTERIORES` —, nenhum deles com
edital ou ata.

Portanto, o que esta matriz sustenta é:

- **cobertura das matérias do art. 25** da Lei nº 14.133/2021 e dos
  dispositivos citados em cada cláusula;
- **rastreabilidade** de cada dado obrigatório até sua origem;
- **bloqueio efetivo** quando o dado não existe.

O que ela **não** sustenta — e que só a comparação com o modelo oficial
resolveria:

- se a redação adotada corresponde à praxe do município;
- se o Decreto Municipal nº 012/2023 exige cláusula que aqui não existe;
- se há exigência local de forma, ordem, numeração ou anexos;
- se o município tem cláusulas próprias de adesão, cadastro de reserva
  ou fiscalização que devam prevalecer.

**Para fechar essa lacuna**, envie um Edital e uma ARP oficiais do
município. A comparação preenche a última coluna e, onde houver
divergência, a cláusula municipal entra pelo catálogo versionado
(`catalogo.py`) — com a mesma chave, sobrepondo a base nacional, sem
tocar no código (ver `templates_gov.montar_oficial`).

## Como ler a coluna "Origem do dado"

Dado marcado como **decisão** não tem campo no Formulário Matriz **de
propósito**: modalidade, critério de julgamento, modo de disputa, regime
de execução e garantia são escolhas do estudo ou da autoridade. O
sistema não as deduz — apresenta `[PREENCHER: …]` e retém a emissão até
que a decisão seja registrada. O mesmo vale para o que só existe depois
do certame (fornecedor, CNPJ, datas, número da licitação).

<!-- GERADO A PARTIR DE templates_gov.CLAUSULAS_BASE -->
## Edital

| # | Cláusula gerada | Fundamento legal | Dado obrigatório | Origem do dado | Aplicabilidade | Bloqueio se ausente | Modelo oficial municipal |
|---|---|---|---|---|---|---|---|
| 1 | DO PREÂMBULO | art. 25 (conteúdo do edital); Decreto Municipal nº 012/2023 | `orgao`<br>`modalidade`<br>`criterio_julgamento`<br>`modo_disputa`<br>`regime_execucao`<br>`numero_processo`<br>`data_sessao`<br>`hora_sessao`<br>`plataforma` | Formulário Matriz, campo *Órgão*<br>**decisão do ETP** — não há campo<br>**decisão do ETP** — não há campo<br>**decisão humana** — não há campo<br>**decisão humana** — não há campo<br>autuação do processo — não há campo<br>publicação do aviso — não há campo<br>publicação do aviso — não há campo<br>plataforma contratada pelo município | sempre | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 2 | DO OBJETO | art. 25, caput; art. 6º, XXIII (TR como anexo) | `objeto` | Formulário Matriz, campo *Objeto* | sempre | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 3 | DAS CONDIÇÕES DE PARTICIPAÇÃO | art. 14 (vedações); LC nº 123/2006; art. 4º | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 4 | DA APRESENTAÇÃO DA PROPOSTA E DOS DOCUMENTOS | art. 25; art. 56 (modo de disputa) | `validade_proposta` | **decisão humana** — não há campo | sempre | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 5 | DO JULGAMENTO DAS PROPOSTAS | art. 33 (critérios); art. 61 (negociação) | `criterio_julgamento` | **decisão do ETP** — não há campo | sempre | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 6 | DA HABILITAÇÃO | arts. 62 a 70 | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 7 | DA IMPUGNAÇÃO E DOS PEDIDOS DE ESCLARECIMENTO | art. 164 | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 8 | DOS RECURSOS | arts. 165 a 168 | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 9 | DAS SANÇÕES ADMINISTRATIVAS | art. 155 (infrações); art. 156 (sanções e dosimetria) | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 10 | DA GARANTIA | arts. 96 a 98 | `clausula_garantia` | **decisão motivada** (arts. 96-98) | sempre | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 11 | DO RECEBIMENTO E DO PAGAMENTO | art. 140 (recebimento); arts. 141 a 146 (pagamento) | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |
| 12 | DAS DISPOSIÇÕES FINAIS | art. 25, §1º (anexos); Decreto Municipal nº 012/2023 | — (texto normativo fixo) | Lei nº 14.133/2021 | sempre | não se aplica | ⚠️ não comparado |

## Ata de Registro de Preços

| # | Cláusula gerada | Fundamento legal | Dado obrigatório | Origem do dado | Aplicabilidade | Bloqueio se ausente | Modelo oficial municipal |
|---|---|---|---|---|---|---|---|
| 1 | DO PREÂMBULO | arts. 82 e 83 (SRP); Decreto Municipal nº 012/2023 | `data_assinatura_ata`<br>`orgao`<br>`fornecedor`<br>`cnpj_fornecedor`<br>`modalidade`<br>`numero_licitacao`<br>`numero_processo` | ato de assinatura — não há campo<br>Formulário Matriz, campo *Órgão*<br>resultado do certame — não há campo<br>resultado do certame — não há campo<br>**decisão do ETP** — não há campo<br>autuação do certame — não há campo<br>autuação do processo — não há campo | somente com SRP | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 2 | DO OBJETO E DOS PREÇOS REGISTRADOS | art. 82 (registro); art. 83 (não obrigatoriedade de contratar) | `objeto` | Formulário Matriz, campo *Objeto* | somente com SRP | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 3 | DA VIGÊNCIA | **art. 84** (vigência da ata); art. 105 (contratos decorrentes) | — (texto normativo fixo) | Lei nº 14.133/2021 | somente com SRP | não se aplica | ⚠️ não comparado |
| 4 | DO GERENCIAMENTO E DO CADASTRO DE RESERVA | art. 82, §§ (órgão gerenciador e cadastro de reserva) | `orgao_gerenciador` | Formulário Matriz, campo *Órgão* | somente com SRP | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |
| 5 | DA ADESÃO POR ÓRGÃO NÃO PARTICIPANTE | **art. 86** (adesão por não participante); Decreto Municipal nº 012/2023 | — (texto normativo fixo) | Lei nº 14.133/2021 | somente com SRP | não se aplica | ⚠️ não comparado |
| 6 | DA ATUALIZAÇÃO DOS PREÇOS REGISTRADOS | art. 92, § 3º (reajuste); art. 124, II, 'd' (reequilíbrio) | — (texto normativo fixo) | Lei nº 14.133/2021 | somente com SRP | não se aplica | ⚠️ não comparado |
| 7 | DO CANCELAMENTO DO REGISTRO | art. 82, § 5º; arts. 155 e 156 | — (texto normativo fixo) | Lei nº 14.133/2021 | somente com SRP | não se aplica | ⚠️ não comparado |
| 8 | DAS SANÇÕES | arts. 155 e 156 | — (texto normativo fixo) | Lei nº 14.133/2021 | somente com SRP | não se aplica | ⚠️ não comparado |
| 9 | DO FORO | cláusula de foro (matéria processual, sem dispositivo próprio) | `comarca` | cadastro do município — não há campo | somente com SRP | **sim** — `[PREENCHER]` retém a emissão | ⚠️ não comparado |

## Resumo quantitativo

| | Edital | ARP |
|---|---|---|
| Cláusulas do catálogo | 12 | 9 |
| Cláusulas com dado obrigatório (bloqueiam) | 5 | 4 |
| Cláusulas de texto normativo fixo | 7 | 5 |
| Parâmetros obrigatórios distintos | 12 | 8 |
| Comparadas ao modelo oficial municipal | **0** | **0** |

## Matérias do art. 25 e onde cada uma é atendida

| Matéria (art. 25) | Cláusula |
|---|---|
| Objeto da licitação | `edital.objeto` |
| Modalidade, critério de julgamento e modo de disputa | `edital.preambulo`, `edital.julgamento` |
| Condições de participação e vedações | `edital.participacao` |
| Requisitos de habilitação | `edital.habilitacao` |
| Critérios de julgamento e negociação | `edital.julgamento` |
| Impugnação e esclarecimentos | `edital.impugnacao` |
| Recursos | `edital.recursos` |
| Sanções | `edital.sancoes` |
| Garantias | `edital.garantia` |
| Recebimento e pagamento | `edital.recebimento_pagamento` |
| Anexos (TR, minuta contratual/ata, declarações) | `edital.disposicoes_finais` |
| Especificações técnicas e quantitativos | Termo de Referência (anexo) + tabela injetada |

**Não coberto pelo catálogo, e por isso pendente de decisão humana:**
prazos e condições específicas de execução que o município fixe por
regulamento próprio; medidas de tratamento diferenciado além do padrão
da LC nº 123/2006; e qualquer exigência do Decreto Municipal nº 012/2023
que só o modelo oficial revelaria.
