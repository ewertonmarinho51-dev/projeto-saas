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
| Suíte | **395 passed / 1 failed** | **507 passed / 1 failed** |

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

1. **Legislação sem embeddings** (§ K.1): a base tem a Lei nº
   14.133/2021, mas sem vetores — logo, invisível à busca vetorial de
   produção. Até a reindexação, o grounding se apoia só no mapa
   canônico. É o bloqueio principal.
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

## K. Smoke test — parcial, executado contra o Supabase real

**Correção de uma afirmação anterior deste relatório: a base de
conhecimento NÃO está vazia.** A inspeção do projeto real
(`govdocs-wizard`) mostrou 40 documentos e 4.539 chunks. O que foi
possível executar aqui (leitura do banco e recuperação real) revelou
três fatos que mudam o quadro:

### K.1 A legislação nunca foi recuperável em produção — causa-raiz de dados

| categoria | docs | chunks | **sem embedding** |
|---|---|---|---|
| processo_anterior | 20 | 1.401 | 0 |
| modelo | 16 | 1.577 | 0 |
| entendimento (manuais) | 3 | 1.311 | **1.311 (100%)** |
| **lei (Lei 14.133/2021)** | 1 | 250 | **250 (100%)** |

`buscar_chunks_vetorial` filtra `where c.embedding is not null`. Com
chave de API configurada — o caminho normal em produção — a busca é
vetorial, portanto **a Lei nº 14.133/2021 e os manuais jamais foram
recuperados**: só modelos e processos anteriores chegavam ao prompt.
Isso explica, no nível dos DADOS, os artigos errados encontrados no P0:
o modelo citava de memória porque a lei nunca esteve disponível — e o
que estava disponível eram justamente as fontes que não fundamentam.

**Ação necessária (no app, com a chave de API ativa): reindexar
`Lei 14133.pdf` e os manuais** pela página Base de Conhecimento (excluir
e reenviar). Sem isso, o grounding do P1 funciona, mas não terá
legislação para recuperar — e a verificação de lastro ficará restrita ao
mapa canônico.

### K.2 Defeito real encontrado e corrigido: recuperação textual zerada

`buscar_chunks_textual` usa `websearch_to_tsquery`, que combina os termos
com **E**. Medido na base real, a frase temática inteira devolvia **zero**
resultados para *pagamento* e *SRP*. Correção em `rag.consulta_textual()`
— termos significativos combinados com **OU** apenas na busca textual (a
vetorial mantém a frase semântica completa):

| tema | consulta longa (antes) | consulta reduzida (depois) |
|---|---|---|
| pagamento | **0** resultados | 3 (ts_rank 0,062) |
| SRP | **0** resultados | 3, incluindo a lei (arts. 85, 86) |
| sanções | 1 | 3, incluindo a lei (art. 156) |
| execução/recebimento | — | 3 |
| gestão/fiscalização | — | 3 |

Os `ts_rank` reais ficam entre **0,05 e 0,09**, o que confirma que o piso
textual conservador (0,01) filtra ruído sem cortar evidência.

### K.3 Contrato real dos RPCs

`buscar_chunks_vetorial/textual` devolvem apenas `conteudo, titulo,
categoria, similaridade` — **não expõem id do chunk, documento nem
ordem**. O trace passou a registrar somente o que existe (nada de campo
nulo inventado); a deduplicação usa o conteúdo. Expor o identificador do
chunk exigiria recriar as funções (expand-only) — **não foi feito para
não alterar objetos de produção sem autorização**.

### K.4 Também confirmado no banco real

- `regras_conhecimento` com **0 regras publicadas** — confirma o achado
  estrutural da 1ª rodada (o motor nunca teve o que avaliar);
- `geracoes` com 61 registros e **sem a coluna `rag_trace`** — a
  migração `0011` continua pendente de aplicação;
- **não há regulamentação municipal de Paragominas indexada** (a
  categoria `lei` tem apenas a Lei 14.133/2021).

### K.5 O que falta para o smoke test completo

1. reindexar a Lei nº 14.133/2021 e os manuais **com embeddings** (K.1);
2. indexar o decreto/regulamento municipal vigente de Paragominas —
   fonte oficial, não fornecida a este ambiente;
3. aplicar `0011_rag_trace.sql`;
4. ligar as flags na ordem: `canonical_facts` →
   `knowledge_engine_shadow` → conferir as decisões na tela →
   `knowledge_engine_active` → `process_consistency`;
5. gerar DFD→ETP→TR→Edital de um caso real **com chave de API** (não
   disponível aqui) e conferir: temas no `rag_trace`, ausência de
   `fundamento_sem_lastro`, cláusulas condicionais coerentes e nenhum
   finding de decisão.

## Veredito

**NÃO APTO PARA PR.**

Justificativa: os pontos técnicos das três revisões estão corrigidos e
cobertos por testes (**507 passed / 1 failed**, mesma falha pré-existente
da `main`, sem regressão). O smoke test foi executado **parcialmente**
contra o Supabase real e, em vez de confirmar, revelou dois problemas de
dados que precisam ser resolvidos ANTES de declarar o P1 pronto:

1. **a Lei nº 14.133/2021 está indexada sem embeddings** e, portanto,
   nunca foi recuperada em produção (§ K.1) — é preciso reindexá-la;
2. **não há regulamentação municipal de Paragominas na base** — fonte
   oficial que este ambiente não possui e que não deve ser inventada.

Sem essas duas correções de acervo, o grounding jurídico não tem o que
recuperar e o smoke test completo (geração com IA real, indisponível
neste ambiente) não teria valor probatório. Nenhuma alteração de código
adicional é necessária: resolvidos K.5, a branch passa a APTO.

---

## L. Migração 0011 aplicada e auditoria de proveniência dos embeddings

Executado em 11/08/2026 no projeto `govdocs-wizard`
(`nxibohgoekphxblqtqku`), com autorização expressa.

### L.1 Resultado da migração

`alter table … add column if not exists` + `comment` + índice parcial.
Aplicada com sucesso e verificada:

| Verificação | Resultado |
|---|---|
| Coluna criada | `rag_trace \| jsonb \| nullable=NO \| default='{}'::jsonb` |
| Default | `'{}'::jsonb` — **61/61** registros antigos ficaram com ele; 0 nulos |
| Dados preservados | 61 registros antes e depois; **MD5 dos ids idêntico** (`1d16b3c2…`) |
| Índice | `CREATE INDEX geracoes_rag_trace_idx ON public.geracoes USING btree (tenant_id, criado_em DESC) WHERE (rag_trace <> '{}'::jsonb)` |

### L.2 Retrocompatibilidade — teste controlado

Dois inserts, depois removidos (base restaurada: 61 registros, mesmo MD5):

| Insert | Resultado |
|---|---|
| Formato da `main` (**sem** informar `rag_trace`) | aceito; campo assumiu `{}` |
| Formato da branch P1 (**com** `rag_trace`) | aceito; `rag_trace #>> '{referencias,0,dispositivos,0}'` = `lei_14133_2021:84` |

A versão em produção hoje (`main`) continua gravando normalmente.

### L.3 Origem dos embeddings existentes — evidência convergente

Não existe metadado de provedor/modelo no banco: `chunks_referencia` tem
apenas `id, documento_id, ordem, conteudo, embedding, tsv` (e nem
`criado_em`); `documentos_referencia` não registra o motor usado. Os logs
do Supabase cobrem **24 horas** — nada de 08/07/2026. E **o repositório
git começa em 13/07/2026**: o código que rodou na indexação (08/07) não
está versionado aqui. Portanto **não há registro explícito** — a
conclusão vem de três evidências independentes que convergem:

**(a) Cronologia (config_app.atualizado_em × documentos_referencia.criado_em)**

| Horário (08/07/2026 UTC) | Evento | Embedding |
|---|---|---|
| 02:58:32 | indexada `Lei 14133.pdf` | **não** |
| 03:06:23–03:06:55 | indexados os 3 manuais | **não** |
| **03:13:13** | **`OPENAI_API_KEY` definida** (164 caracteres) | — |
| 03:13:14 | `OPENAI_MODEL` e `GEMINI_MODEL` gravados vazios (default do código) | — |
| 12:25:17–12:27:40 | indexados 16 modelos | **sim** |
| 12:32:36–12:41:15 | indexados 20 processos anteriores | **sim** |
| **12:46:13** | **`GOOGLE_API_KEY` definida** (53 caracteres) | — |

Todo chunk com vetor foi criado entre 12:25 e 12:41 — janela em que a
**única** chave configurada era a da OpenAI. A chave do Google entrou
**5 minutos depois** do último documento embeddado. Como
`rag._gerar_embeddings` usa OpenAI quando há chave OpenAI e só cai para o
Gemini na ausência dela, nenhum vetor pôde ter vindo do Gemini.

**(b) Impressão vetorial (L2)** — todos os 2.978 vetores normalizados:

| categoria | chunks | dims | norma mín | média | máx | desvio |
|---|---|---|---|---|---|---|
| modelo | 1.577 | 768 | 0,999340 | 1,000040 | 1,000703 | 0,00027 |
| processo_anterior | 1.401 | 768 | 0,999318 | 1,000032 | 1,000772 | 0,00025 |

Distribuição única e apertada (sem outliers, mesmo perfil nas duas
categorias) → **um único provedor/modelo para todos**. Normalização L2
é o comportamento do `text-embedding-3-*` da OpenAI com `dimensions=768`.

**(c) Precedência do código e o mistério dos 1.561 sem vetor** — a lei e
os manuais foram indexados **antes de qualquer chave existir**:
`_gerar_embeddings` devolveu `None`, `indexar_arquivo` gravou
`embedding = NULL` e seguiu (por desenho: "falha de embedding não impede
a indexação"). Falhou em silêncio, e ninguém percebeu que justamente a
legislação ficou fora do índice vetorial.

**Conclusão:** provedor **OpenAI**, dimensão 768, provedor único para
100% dos vetores existentes — comprovado por convergência, não por
registro. **Ressalva honesta:** a cronologia e a normalização provam o
*provedor*, mas **não distinguem `text-embedding-3-small` de
`text-embedding-3-large` truncado a 768** — ambos OpenAI, ambos
normalizados, e **espaços vetoriais incompatíveis entre si**. O default
do código é `text-embedding-3-small`, mas o código daquela data não está
no git.

### L.4 Estado atual do índice vetorial

| categoria | docs | chunks | com embedding | **sem embedding** |
|---|---|---|---|---|
| processo_anterior | 20 | 1.401 | 1.401 | 0 |
| modelo | 16 | 1.577 | 1.577 | 0 |
| entendimento (manuais) | 3 | 1.311 | 0 | **1.311** |
| **lei (Lei 14.133/2021)** | 1 | 250 | 0 | **250** |
| **total** | **40** | **4.539** | **2.978 (66%)** | **1.561 (34%)** |

### L.5 Recomendação objetiva — reindexação integral, provedor único

Como o **modelo exato** não é comprovável e 34% da base precisa de
vetores de qualquer forma, **não misturar**: reindexar tudo com um único
provedor/modelo declarado. Plano seguro, sem indisponibilidade e sem
perda (nada disto foi executado):

1. **Padronizar** em `text-embedding-3-small` @ 768 (provedor comprovado,
   chave já configurada, default do código, custo desprezível).
2. **Rastreabilidade permanente** (migração expand-only): acrescentar a
   `chunks_referencia` as colunas `embedding_provedor`, `embedding_modelo`
   e `embedding_em` — para que esta auditoria nunca precise ser refeita.
3. **Preservar o original**: `create table chunks_referencia_bkp_20260811
   as select * from chunks_referencia` antes de qualquer escrita.
4. **Escrita paralela**: nova coluna `embedding_v2 vector(768)` populada
   por lotes (100 chunks/chamada), documento a documento, **sem tocar**
   em `embedding` — a busca atual segue funcionando o tempo todo.
5. **Corte atômico** após 4.539/4.539 preenchidos e conferidos (contagem,
   dims, norma ≈ 1, busca de sanidade por tema): troca das colunas em
   transação curta e recriação do índice vetorial.
6. **Descarte** da coluna antiga e da tabela de backup só em migração
   posterior, depois de o smoke test passar.
7. **Custo estimado**: ~1,8 M tokens ≈ **US$ 0,04**; ~46 chamadas de API.

Enquanto isso não ocorrer, a busca vetorial continua sem legislação — o
P1 mitiga (regra de citação + verificação de lastro), mas o ganho real do
grounding depende deste passo.

**Nada da reindexação foi executado; aguarda autorização específica.**
Os RPCs também não foram alterados — nenhum defeito independente os
impede de rodar o smoke test.

---

## M. Homogeneização do índice vetorial — preparação concluída, backfill bloqueado

Executado em 11/08/2026 sob autorização. **A reindexação em si NÃO foi
executada** — o bloqueio está em M.7 e é de credencial, não de plano.

### M.1 Catálogo dos 40 documentos (item 6)

| categoria | docs | chunks | origem / natureza | jurisdição |
|---|---|---|---|---|
| `lei` | 1 | 250 | **Lei nº 14.133/2021** — Presidência da República (Planalto) | federal, aplicação direta |
| `entendimento` | 3 | 1.311 | ver quadro abaixo | federal |
| `modelo` | 16 | 1.577 | PGE-PA (5), AGU (5), Governo Digital/TIC (4), demais | referência de redação |
| `processo_anterior` | 20 | 1.401 | DFD/ETP/TR de processos já realizados | local |

**Os 3 documentos hoje classificados como `entendimento`** — inspeção do
primeiro chunk de cada:

| documento | emissor real | natureza |
|---|---|---|
| `instrumento-de-padronizacao-...-agu-fev-2024.pdf` (158) | AGU + Ministério da Gestão e da Inovação em Serviços Públicos | **manual/orientação federal** |
| `manual de fase de planejamento.pdf` (43) | **Ministério das Comunicações**, "Manual de Contratações — Módulo 1", ago/2025 | **manual interno de órgão federal** |
| `ManualdeLicitacoeseContratacoesAdministrativas.pdf` (1.110) | AGU — Consultoria-Geral da União / Corregedoria-Geral | **manual/orientação federal** |

**Nenhum dos três é entendimento de Tribunal de Contas.** No código,
`entendimento` está declarado como "Entendimento / Orientação de TC" e o
P1 os rotula no prompt como *jurisprudência/orientação de controle* —
o que **superestima** um manual interno do Executivo federal diante de
uma contratação municipal.

**Proposta (não executada, aguarda decisão):** criar a categoria
`manual` ("Manual / Orientação técnica") em `rag.CATEGORIAS`, com o mesmo
peso de hierarquia dos moldes (não fundamenta dispositivo), e
reclassificar esses 3 documentos. Impacto no lastro: **nenhum** — só
`lei` fornece lastro. Impacto real: rótulo correto no prompt.
Categoria de `lei` e das demais: **corretas, nada a mudar**.

### M.2 Padrão V2 fixado (itens 1 e 2)

`openai` / `text-embedding-3-small` / `768` / `v2`, declarado em
`src/config.EMBEDDING_V2_*`. `rag._gerar_embeddings` **não tem mais
fallback entre provedores**: sem a chave do provedor do índice não se
gera vetor com outro motor — a busca cai para textual, a indexação fica
`pendente` e o usuário é avisado. Vetor com dimensão diferente é
recusado. O fallback OpenAI → Gemini continua valendo **só para geração
de texto**. Provado por teste (`test_embeddings_nao_caem_para_outro_provedor`
verifica que o Gemini sequer é consultado).

### M.3 Backup e rollback (item 5)

Impressão digital tomada **antes** de qualquer alteração e reconferida
após a cópia — backup e tabela viva idênticos:

| | linhas | impressão estrutural (id\|doc\|ordem\|md5(conteúdo)) | legado com vetor |
|---|---|---|---|
| `chunks_referencia` | 4.539 | `90c41e57140a984909bbd86547d72d50` | 2.978 |
| `chunks_referencia_bkp_20260811` | 4.539 | `90c41e57140a984909bbd86547d72d50` | 2.978 |
| `documentos_referencia` / `_bkp_20260811` | 40 / 40 | `8a1c325f060d8ef9659ba6739b803ae6` (ambos) | — |

Hash do conteúdo puro: `226d8ce165b98cacf00b995756fe5956` (6.055.174
caracteres). Nenhuma linha de `conteudo` foi tocada em momento algum.

### M.4 Migrações aplicadas

- **0012** — backup (acima).
- **0013** — `embedding_v2 vector(768)` + `embedding_provider`,
  `embedding_model`, `embedding_dimensions`, `embedding_version`,
  `embedding_generated_at`, `embedding_status` (default `pendente`).
  Dois CHECKs impedem o retorno do problema histórico: vetor sem
  proveniência é rejeitado, e `status = 'ok'` sem vetor também.
  Índice parcial `…_backfill_idx` para a retomada em lotes.
  **Expand-only:** coluna e índice legados intactos; produção (`main`)
  segue lendo `embedding` normalmente.
- **0014** — HNSW do `embedding_v2`, gravado como
  `.sql.PENDENTE`: só deve ser aplicado **após** a cobertura integral
  (com `CONCURRENTLY`, sem bloquear a busca atual; o índice antigo
  permanece).

Estado após as migrações: 4.539 chunks, **4.539 `pendente`**, 0 com V2,
2.978 legados intactos, impressão estrutural **inalterada**.

### M.5 Backfill preparado (item 7)

`scripts/reindexar_embeddings_v2.py` — idempotente (processa apenas
`embedding_v2 is null`, em ordem estável por documento/ordem), retomável
sem checkpoint externo, em lotes configuráveis; grava vetor +
proveniência; **não toca** `conteudo`, `ordem`, `documento_id`, `tsv` nem
`embedding`. Falha de lote marca `falha` e o lote volta na execução
seguinte — nunca grava vetor de outro modelo. Tem `--simular` e
`--validar`. Sem credenciais, aborta sem alterar nada (verificado).

### M.6 Indexação futura (item 11)

`rag.indexar_arquivo` passou a gravar provedor, modelo, dimensão, versão
e data em cada chunk. Sem vetor, o chunk nasce `pendente` e a tela avisa
que o documento **não aparece na busca semântica** até ser reindexado.

### M.7 BLOQUEIO — por que o backfill não foi executado

O backfill precisa da chave da OpenAI, que está em
`config_app.OPENAI_API_KEY` **no banco de produção**. Duas formas de
obtê-la aqui e **ambas foram recusadas**:

1. **Ler a chave via SQL** — o valor voltaria como resultado de
   ferramenta e ficaria registrado no transcrito da sessão. Expor um
   segredo de produção é inaceitável, ainda que a operação fosse
   autorizada.
2. **Instalar `pg_net`/`http` no Postgres** para chamar a OpenAI de
   dentro do banco — ambas as extensões existem no projeto mas **não
   estão instaladas**. Instalá-las criaria um caminho de rede
   permanente no banco de produção, fora da arquitetura da aplicação, só
   para contornar a ausência da chave.

**Como destravar (qualquer uma das opções):**

- **(A) Rodar o script no ambiente que já tem as credenciais** — local
  ou Streamlit Cloud: `python scripts/reindexar_embeddings_v2.py --lote 100`
  e depois `--validar`. É o caminho recomendado: usa a mesma chave que a
  aplicação já usa, e nada trafega por aqui. ~46 chamadas, ~US$ 0,04.
- **(B) Fornecer uma chave temporária** por canal seguro, revogada
  depois — só se preferir que eu execute.

Enquanto isso não ocorre: **nada foi perdido**. A produção segue
funcionando com o índice legado, o V2 está criado e vazio, o backup está
verificado e o rollback é imediato (a coluna legada nunca foi tocada).

### M.8 O que permanece pendente (itens 8 a 16)

Todos dependem do backfill ou de credenciais indisponíveis aqui:
validação de cobertura 4.539/4.539 (8), índice HNSW (9), corte do RPC
(10), indexação da **regulamentação municipal de Paragominas** — que
continua **ausente** da base e exige fonte oficial (12), testes de
recuperação por tema com V2 ativo (13), isolamento semântico (14),
smoke test DFD→ETP→TR→Edital com IA real (15) e o `rag_trace` de cada
documento (16).

### Veredito

**NÃO APTO PARA PR** — inalterado e agora com o caminho crítico
totalmente instrumentado: falta executar o backfill (M.7), indexar a
regulamentação municipal e rodar o smoke test com IA real.
