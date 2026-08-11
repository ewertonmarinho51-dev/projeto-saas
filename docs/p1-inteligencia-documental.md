# P1 — Inteligência documental, grounding jurídico e consistência

Branch `p1-grounding-consistencia` (a partir de `main` `e088cef`, já com o
P0). **Nenhum PR aberto.** Commits: `f4fd7e2` (RAG temático + trace +
cláusulas condicionais), `4bf6308` (ETP + consistência + testes),
`0c8064d` (relatório), `91f6fde` (**correções da 2ª auditoria**) e
`d57c796` (**ajustes da 3ª revisão**).

---

## A. Arquitetura encontrada e reutilizada

Tudo entrou nos módulos que já deveriam executar a função: `rag.py`,
`conhecimento.py` (motor v5), `fatos.py`, `consistencia.py`, `perfis.py`,
`prompts.py`, `validacao.py`, `achados.py`, `llm.py`, `db.py`,
`config_app` (flags). O único arquivo novo é `src/normas.py` — não é
motor nem pipeline: é o normalizador de identidade `norma:dispositivo`
usado pelos três consumidores existentes (mapa canônico, RAG e
validação), justamente para que não existam três normalizações
divergentes.

Achado estrutural da 1ª rodada: **o motor v5 estava correto, mas
`regras_conhecimento` nasce vazia** — nenhuma regra era avaliada. A base
de regras entrou como DADO na camada `nacional` (a menos específica),
consumida pelo resolver existente.

## B. Problemas encontrados na 2ª auditoria e correções

| # | Problema apontado | Correção |
|---|---|---|
| 1 | Autoridade decisória: `_verificar_decisoes` tratava "o primeiro que falou" como verdade; `_verificar_srp_contra_fato` tratava o formulário como definitivo; as diretrizes derivavam sempre do formulário — contradizendo o `RACIOCINIO_ETP` | autoridade por decisão e estágio (§ C); `documento_consolidador()`; sobreposição do formulário pelo que o ETP consolidou (refinada na 3ª revisão, § B2) |
| 2 | `objeto.natureza` deduzida de `modelo_execucao` com *fallback* BENS — errado para SRP (modelagem ≠ natureza) | natureza só das opções que a declaram (obra/serviço); senão, da categoria (inferência); sem base, **nenhum fato** |
| 3 | Fatos derivados booleanos: ausência de evidência virava `False` | tri-state — `True` / `False` explícito / **ausente**; sem informação o motor **alerta**, não decide |
| 4 | Termos em frases negativas geravam fato positivo | `avaliar_termos()` detecta negação ("não será exigida", "dispensa-se", "sem exigência de", "fica dispensada") |
| 5 | Inferência de baixa confiança virava cláusula obrigatória | fato com fonte `inferencia:` não vincula: a regra vira **sugestão + alerta** até confirmação; `aceita_inferencia` permite política explícita |
| 6 | `srp.renovacao_quantitativo` ativado pela mera adoção do SRP | removido do automático; alvo preservado para regra municipal fundamentada |
| 7 | Amostra fundamentada só no art. 42 | art. 41, II **e** art. 42; e a exigência depende de fato, não da palavra "amostra" |
| 8 | TI_EQUIPAMENTO recebia LGPD, backup e migração de dados | regra separada: só TI_SOFTWARE/SaaS; hardware não recebe nada por padrão |
| 9 | Veículos: rede de assistência como exigência nacional | vira **alerta**; restrição territorial/rede só com justificativa técnica |
| 10 | EPI com fonte genérica | NR-6 — Portaria MTP nº 672/2021, com nota de confirmação de vigência na base |
| 11 | `MAX_TEMAS=4`: sanções/pagamento ficavam fora do TR | núcleo garantido + complementares (§ G) |
| 12 | Ranking global podia zerar um tema consultado | reserva de ≥1 evidência por tema prioritário |
| 13 | Regra de citação dependia da obediência do LLM | verificação determinística pós-geração (§ H) |
| 14 | Acórdão rotulado como "fonte normativa" | hierarquia em 4 níveis: legislação / jurisprudência de controle / processo atual / molde |
| 15 | Jurisdição | mantida explícita, com **precedência operacional** da regulamentação municipal; limitação registrada (§ J) |

## B2. Ajustes da 3ª revisão

| # | Problema apontado | Correção |
|---|---|---|
| 1 | `documento_consolidador()` promovia o último documento anterior quando o consolidador estava silencioso (o DFD virava "decisão consolidada") | consulta **apenas** o documento com autoridade; sem manifestação dele a decisão fica *não consolidada* e ninguém é acusado. Divergência sem consolidação vira aviso MEDIUM apontado ao documento competente — e só se ele existir no dossiê |
| 2 | Consolidar "não SRP" reescrevia `modelo_execucao` como "Entrega parcelada" | `sobrepor_decisoes_consolidadas()` substitui **apenas o fato** `procedimento.srp` (fonte `documento:etp`, versionado). A forma de execução informada permanece intacta |
| 3 | Lastro comparava número de artigo solto | identidade **`norma:dispositivo`** (`src/normas.py`): `lei_14133_2021:84` ≠ `decreto_10024_2019:84`. Reconhece leis, LCs, decretos, INs, NRs e NBRs; citação sem norma declarada assume a norma de referência da fase preparatória (suposição explícita). `MAPA_CANONICO` ancorado à Lei nº 14.133/2021 |
| 4 | `lastro_do_trace()` aceitava artigo de qualquer fonte | só `categoria = lei` sustenta dispositivo normativo. Acórdão/entendimento não autorizam artigo de lei só por mencioná-lo; processo anterior e modelo nunca dão lastro |
| 5 | `_rag_trace` era gravado antes da IA responder | associado **após geração bem-sucedida**, com `hash_texto`, `request_id` e `modelo`. Falha de todos os motores preserva o rastro anterior; no fallback OpenAI→Gemini vale o rastro da geração vencedora |
| 6 | Gatilho `ti` tratava software e hardware igual | proteção de dados dispara para software/SaaS/hospedagem **ou** quando o processo exige o tema (dados pessoais, sigilo, segurança da informação). Monitor não recebe LGPD |
| 7 | "mão de obra" genérico decidia o regime | só expressão inequívoca (dedicação exclusiva/predominante/pessoal residente) decide; menção genérica vira indício inferido (`procedimento.mencao_mao_de_obra`) e o regime permanece UNKNOWN, com alerta |

## C. Autoridade decisória por estágio

```
FORMULÁRIO  preferência/hipótese de modelagem
DFD         solução preliminar do demandante
ETP         CONSOLIDA solução, SRP e parcelamento  ← pode afastar o que veio antes
TR          consolida modalidade e garantia; operacionaliza o ETP
EDITAL      herda o que o TR definiu
```

| Decisão | Consolidador | Divergência antes | Divergência depois |
|---|---|---|---|
| adoção de SRP | ETP | legítima | finding |
| adjudicação item × lote | ETP | legítima | finding |
| modalidade | TR | legítima | finding |
| garantia contratual | TR | legítima | finding |

Regras: **somente o documento com autoridade consolida** — silêncio dele
significa "não consolidado", e nunca promove um documento preliminar a
decisão vinculante; silêncio de um documento qualquer não é divergência;
sem ETP no dossiê, a divergência com o formulário vira aviso MEDIUM
("modelagem não confirmada"), nunca erro do documento.

## D. ETP — antes × depois

Antes o formulário entregava "Modelo de Execução: SRP" como fato e o
estudo nascia com a resposta pronta. Agora: o campo é rotulado no prompt
do ETP como *preferência a confirmar ou afastar*; a solução do DFD é
*hipótese inicial*; `RACIOCINIO_ETP` fixa necessidade → requisitos →
alternativas → análise → solução → consequências, com alternativas reais
e sem absolutismo; TR operacionaliza e Edital herda; três validações
determinísticas apontam a inversão; `perfis.clausulas_aplicaveis`
renumera sem buraco quando uma cláusula condicional sai.

## E. Regras-base finais (camada `nacional`)

| Regra | Condição | Efeito |
|---|---|---|
| `base.srp.clausulas-proprias` | SRP = true | inclui vigência da ata, gerenciamento, adesão, cadastro de reserva |
| `base.srp.sem-srp-nao-ha-ata` | não SRP | exclui todas as cláusulas da ARP (inclusive renovação) |
| `base.repactuacao.sem-dedicacao-de-mao-de-obra` | dedicação = **False** | exclui repactuação, inclui reajuste |
| `base.repactuacao.servico-com-mao-de-obra` | dedicação = True | inclui repactuação |
| `base.repactuacao.regime-nao-informado` | continuado **e** dedicação ausente | **alerta** (não decide) |
| `base.reajuste.bens` | natureza = BENS | exclui repactuação, inclui reajuste |
| `base.garantia.nao-presumida` | garantia ≠ true | exclui garantia |
| `base.garantia.exigida-no-processo` | garantia = true | inclui garantia |
| `base.amostra.nao-presumida` / `.exigida-no-processo` | amostra | exclui / inclui (art. 41, II e 42) |
| `base.me-epp.bens-e-servicos` | natureza BENS/SERVICOS | inclui ME/EPP |
| `base.ti.solucao-de-software` | categoria TI_SOFTWARE | inclui SLA, segurança/backup, interoperabilidade, LGPD, migração |
| `base.epi.certificado-de-aprovacao` | categoria EPI | inclui exigência de CA |
| `base.veiculos.condicoes-a-justificar` | categoria VEICULOS | **alerta** — nenhuma exigência automática |

Regra municipal/secretaria/processo prevalece sempre (precedência já
existente, com teste).

## F. Confiança e tri-state

- **Informação prestada** (campo do formulário) → vincula.
- **Fato confirmado** por humano → vincula (confiança 1,0).
- **Inferência do sistema** (fonte `inferencia:`) → **sugere** com alerta
  e o motivo ("confirme o fato para que a regra passe a valer"); nunca
  cria exigência técnica, exclui matéria nem restringe competição.
- **Ausência de fato** → constatação sobre o processo (ex.: "garantia não
  foi pedida"), não é inferência: vale para excluir o que não foi pedido.
- Regra pode declarar `aceita_inferencia: True` — política explícita.

## G. Orçamento final do RAG (medido)

| Documento | Buscas | Temas núcleo (garantidos) | Complementares |
|---|---|---|---|
| DFD | 1 + 3 | necessidade | srp*, parcelamento |
| ETP | 1 + 7 | necessidade, requisitos, parcelamento, modalidade | srp*, protecao_dados*, reajuste, me_epp |
| TR | 1 + 7 | execução/recebimento, **pagamento**, **sanções**, gestão/fiscalização | srp*, garantia*, protecao_dados*, reajuste, requisitos |
| Edital | 1 + 7 | modalidade, requisitos, sanções, recursos | srp*, garantia*, protecao_dados*, me_epp, parcelamento |

`*` = condicional (só com gatilho estrutural). Sempre **uma única**
chamada de embeddings em lote; top-6 na geral, top-3 por tema; piso de
relevância; dedup; **reserva de ≥1 evidência por tema prioritário**; teto
de 10 trechos no prompt.

## H. Grounding pós-geração

```
texto gerado → dispositivos citados → lastro? → finding
```
Toda comparação usa a identidade **`norma:dispositivo`** de
`src/normas.py`. Lastro válido: (a) `prompts.MAPA_CANONICO` — **dado
declarado** e ancorado à Lei nº 14.133/2021, lido pelo prompt e pela
validação (não há duas listas para divergirem); (b) dispositivos
extraídos dos trechos de **legislação** que o RAG recuperou naquela
geração (`geracoes.rag_trace[].dispositivos`) — acórdão, entendimento,
processo anterior e modelo não dão lastro. O rastro pertence à geração
bem-sucedida que produziu o texto (`hash_texto`). Sem lastro → finding
`fundamento_sem_lastro` (HIGH), cuja correção **remove o número e mantém
a norma** — nunca substitui por outro artigo. Documento sem rastro
(importado, editado à mão, gerado antes do P1) fica de fora: a checagem
não opina.

Exemplos verificados: `art. 347` → finding; `art. 84`/`arts. 141 a 146`
(canônicos) → passam; `art. 250 da Lei nº 14.133/2021` presente no trace
→ passa; `art. 84 do Decreto nº 10.024/2019` **não** valida o `art. 84`
da Lei nº 14.133/2021.

## I. Testes

| | main | branch |
|---|---|---|
| Suíte | **395 passed / 1 failed** | **503 passed / 1 failed** |

Mesma única falha nos dois lados (`test_export_estilos.py::
test_pdf_via_libreoffice_quando_disponivel` — LibreOffice do container
troca Times por Helvetica): **pré-existente, não é regressão**.

`tests/test_p1_grounding.py` (40) e `tests/test_p1_inteligencia.py` (68)
— RAG-01..06, ETP-01..04, COND-01..05, CONS-01..06 e todos os testes
exigidos na 2ª auditoria: autoridade (5 cenários A–E), tri-state,
negações, natureza, confiança, regras revisadas, orçamento/reserva do
RAG e grounding (4 casos). A 3ª revisão acrescentou: consolidador
silencioso (3), norma × dispositivo e origem do lastro (6), ciclo de vida
do trace (3), gatilho de TI (3) e dedicação inequívoca (2).

**Regressões declaradas:** cinco testes anteriores foram atualizados —
não por conveniência, mas porque a semântica mudou de propósito:
`test_fatos` (SRP não gera mais natureza BENS), `test_conhecimento`,
`test_explicacoes` e `test_politicas` (fixtures passam a informar a
natureza como fato confirmado, como o revisor faria) e
`test_rag.py::test_bloco_referencias_formata_trechos` (montagem do bloco
agora percorre a recuperação temática). Nenhuma perda de cobertura.

## J. Limitações remanescentes

1. **Base de conhecimento vazia** — sem normas indexadas o grounding se
   apoia só no mapa canônico, e a verificação de lastro fica restrita a
   ele. É o bloqueio do § K.
2. **Jurisdição não é metadado do banco**: `documentos_referencia` tem
   `categoria`, não escopo federal/estadual/municipal. A separação é
   feita no bloco do prompt. Não foi criada segunda arquitetura.
3. **Piso de relevância sem calibração empírica** (0,20 vetorial / 0,01
   textual): conservador e configurável.
4. **Categoria do objeto é inferência** — por isso não vincula sem
   confirmação; sem evidência suficiente, `INDEFINIDA` e nenhuma regra
   específica dispara.
5. **Consistência semântica é determinística**: contradições puramente
   redacionais seguem dependendo de revisão humana.
6. **Campos ausentes do formulário** (matrícula, equipe, prioridade,
   CNPJ) seguem como `[PREENCHER]` — P2, inalterado.
7. **Sem execução com IA real** neste ambiente (sem chaves/Supabase).

## K. Smoke test pendente (item 17)

Não executável neste ambiente: não há chaves de API nem Supabase, e a
base de conhecimento está vazia. Não foi criado seed com conteúdo
normativo — inventar norma seria pior que não ter nenhuma.

Para executá-lo no ambiente do usuário, usando a página **Base de
Conhecimento** já existente (nenhum código novo é necessário):

1. indexar, a partir de **fontes oficiais**: (a) Lei nº 14.133/2021
   (Planalto), categoria `lei`; (b) o decreto/regulamento municipal
   vigente de Paragominas que disciplina a Lei nº 14.133/2021, categoria
   `lei`; (c) as normas específicas usadas pelas regras que forem
   testadas (ex.: NR-6/Portaria MTP nº 672/2021 para EPI);
2. aplicar a migração `0011_rag_trace.sql`;
3. ligar as flags na ordem: `canonical_facts` →
   `knowledge_engine_shadow` → conferir decisões na tela →
   `knowledge_engine_active` → `process_consistency`;
4. gerar DFD→ETP→TR→Edital de um caso real e conferir: temas
   recuperados no `rag_trace`, ausência de `fundamento_sem_lastro`,
   cláusulas condicionais coerentes e nenhum finding de decisão.

## Veredito

**NÃO APTO PARA PR.**

Justificativa: os 16 pontos técnicos da 2ª auditoria estão corrigidos e
cobertos por testes (485 passed, sem regressão frente à `main`), mas o
item 17 — smoke test em ambiente com RAG funcional e fontes oficiais
indexadas — **não pôde ser executado aqui** e foi expressamente colocado
como condição para declarar o P1 pronto. O bloqueio é ambiental, não de
implementação: assim que o § K for concluído com sucesso no ambiente do
usuário, a branch passa a APTO sem necessidade de novas alterações.
