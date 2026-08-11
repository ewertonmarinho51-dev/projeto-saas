# P1 — Inteligência documental, grounding jurídico e consistência

Branch `p1-grounding-consistencia` (a partir de `main` `e088cef`, já com
o P0). **Nenhum merge foi aberto.** Commits: `f4fd7e2` (RAG + trace +
cláusulas condicionais) e `4bf6308` (ETP + consistência + testes).

---

## A. Arquitetura encontrada e reutilizada

Nenhum componente novo foi criado. Tudo entrou nos módulos que já
deveriam executar a função:

| Função | Componente existente | Situação encontrada |
|---|---|---|
| Recuperação de fundamentação | `rag.py` (+ RPCs `buscar_chunks_vetorial/textual`, migrações 0003/0007) | consulta única por documento; metadados (`titulo`, `categoria`, `similaridade`) **descartados** |
| Decisão de cláusulas condicionais | `conhecimento.py` (motor v5) + `fatos.py` | motor correto e completo, mas **`regras_conhecimento` nasce vazia** — nenhuma regra jamais era avaliada; a decisão só aparecia na tela final, depois do documento pronto |
| Estrutura e profundidade | `perfis.py` | numeração com buraco quando cláusula condicional era suprimida |
| Redação | `prompts.py` | modelo de execução entregue ao ETP como dado consumado |
| Coerência entre documentos | `consistencia.py` (v5 F5) | verificava valores, cálculo, quantidades, prazo e objeto — não verificava **decisões** |
| Registro técnico | `llm.registrar_geracao` → `db.registrar_geracao_bd` → `geracoes` | sem qualquer rastro do RAG |
| Ativação gradual | `config_app` + `db.flag_ativa` | reutilizado; nenhuma flag nova |

## B. Alterações realizadas

| Objetivo | Arquivo/função existente | Alteração |
|---|---|---|
| Recuperação temática | `rag.TEMAS_JURIDICOS`, `TEMAS_POR_DOCUMENTO`, `temas_para`, `recuperar` | 14 temas, ordenados por prioridade **por documento**; condicionais (SRP/TI/garantia) disparados por gatilho estrutural; orçamento fixo |
| Metadados | `rag.recuperar`, `montar_contexto` | título, categoria, similaridade, documento, ordem e tema preservados até o prompt e o trace |
| Piso de relevância | `rag.piso_de_relevancia` | configurável em `config_app` (`rag_piso_vetorial`/`rag_piso_textual`); padrões distintos por escala; busca textual preservada |
| Dedup / teto | `rag._identidade`, `recuperar` | mesma fonte nunca entra duas vezes; ordenação por hierarquia (norma > acórdão > molde); teto de 8 trechos |
| Regra de citação | `rag.REGRA_DE_CITACAO`, `_HIERARQUIA_FONTES` | artigo só com lastro recuperado ou mapa canônico; hierarquia e jurisdição municipal explícitas |
| Trace | `llm.registrar_geracao`, `db.registrar_geracao_bd`, migração `0011_rag_trace.sql` | `geracoes.rag_trace` jsonb (expand-only, idempotente), com fallback para bancos não migrados |
| Fatos estruturados | `fatos.categoria_do_objeto`, `extrair_do_formulario` | `objeto.categoria` por evidência ponderada; dedicação de mão de obra; garantia/amostra exigidas |
| Regras condicionais | `conhecimento.REGRAS_BASE`, `regras_base()`, merge em `executar_na_tela` | 13 regras na camada `nacional` (piso), consumidas pelo resolver existente |
| Cláusulas na geração | `conhecimento.diretrizes_para_prompt`, `bloco_de_diretrizes`, `llm.gerar_documento` | decisão do motor chega ao prompt (só com motor ativo) |
| Raciocínio do ETP | `prompts.RACIOCINIO_ETP`, `formatar_dados_formulario`, `montar_prompt` | ordem obrigatória; preferência × conclusão; papéis de TR e Edital |
| Numeração | `perfis.clausulas_aplicaveis` | renumeração contínua ao incluir/excluir cláusula condicional |
| Detecção do vício | `validacao._validar_raciocinio_etp`, `_validar_absolutismo`; `achados._CLASSIFICACAO` | avisos determinísticos que entram no ciclo v4 |
| Decisões cruzadas | `consistencia.DECISOES`, `_verificar_decisoes`, `_verificar_srp_contra_fato`, `_verificar_requisitos_operacionalizaveis` | coerência semântica DFD→ETP→TR→Edital |

## C. RAG — antes × depois

**Antes:** `objeto + justificativa + modelo` → 1 embedding → top-6 →
todos os trechos empilhados sem rótulo → prompt. Score, título e
categoria descartados. Nada registrado.

**Depois:** gatilhos estruturais (SRP/TI/garantia) selecionam até 4 temas
priorizados por documento → **um único lote de embeddings** para todas as
consultas → 1 busca geral (top-6) + N temáticas (top-3) → piso de
relevância por modo → deduplicação → ordenação por hierarquia da fonte →
teto de 8 trechos → bloco **agrupado por tema**, cada fonte rotulada com
o que pode sustentar → regra de citação conservadora → trace gravado.

Custo: 1 chamada de embeddings (igual a antes) e 4–5 RPCs no Postgres
(baratos, do lado do banco). Exemplo real medido:
`tr` → temas `srp, execucao_recebimento, pagamento, requisitos`;
`edital` → `srp, modalidade, requisitos, sancoes`.

## D. ETP — antes × depois

**Antes:** o formulário entregava "Modelo de Execução: SRP" como fato, e
o estudo nascia com a resposta pronta — o levantamento de soluções virava
formalidade e a conclusão confirmava a premissa.

**Depois:** (1) o campo é rotulado no prompt do ETP como *preferência de
modelagem a ser confirmada ou afastada*; (2) a solução do DFD entra como
*hipótese inicial*; (3) `RACIOCINIO_ETP` fixa a ordem necessidade →
requisitos → alternativas → análise → solução → consequências, com
alternativas reais e sem absolutismo; (4) o TR recebe o papel de
operacionalizar a decisão do ETP e o Edital de respeitá-la; (5) três
validações determinísticas apontam a inversão quando ela ocorre.

## E. Cláusulas condicionais efetivamente implementadas

Todas na camada `nacional` (a menos específica — qualquer regra do
município/secretaria/processo prevalece), avaliadas pelo resolver v5:

| Regra | Condição (fato) | Efeito |
|---|---|---|
| `base.srp.clausulas-proprias` | `procedimento.srp = true` | inclui vigência da ata, gerenciamento, adesão, cadastro de reserva, renovação |
| `base.srp.sem-srp-nao-ha-ata` | não SRP | exclui as mesmas cláusulas |
| `base.repactuacao.somente-mao-de-obra` | sem dedicação de mão de obra | exclui repactuação, inclui reajuste |
| `base.repactuacao.servico-com-mao-de-obra` | dedicação de mão de obra | inclui repactuação |
| `base.garantia.nao-presumida` | fato de garantia AUSENTE | exclui garantia |
| `base.garantia.exigida-no-processo` | garantia exigida | inclui garantia |
| `base.amostra.nao-presumida` / `.exigida-no-processo` | fato de amostra | exclui / inclui amostra |
| `base.me-epp.bens-e-servicos` | natureza BENS ou SERVICOS | inclui ME/EPP |
| `base.ti.requisitos-de-solucao-digital` | categoria TI_SOFTWARE/TI_EQUIPAMENTO | inclui SLA, segurança/backup, interoperabilidade, LGPD, migração |
| `base.epi.certificado-de-aprovacao` | categoria EPI | inclui exigência de CA |
| `base.veiculos.garantia-e-assistencia` | categoria VEICULOS | inclui garantia de fábrica, assistência, documentação |

Nenhuma depende de `if palavra in objeto`: a categoria é um **fato**
derivado de evidência ponderada (objeto ×3, itens ×1, requisitos ×1,
mínimo 3 pontos) e confirmável pelo humano como qualquer outro fato.

## F. Consistência transversal — novos invariantes

- **Decisões** (comparação por valor, não por texto): modalidade
  (pregão/concorrência/dispensa/inexigibilidade/leilão), adoção de SRP,
  adjudicação por item × lote, exigência de garantia. A referência é o
  documento anterior na cadeia; **silêncio não é divergência**; a
  negativa é testada antes da afirmativa ("não será exigida garantia"
  nunca é lido como "sim").
- **Modelagem × fato canônico**: documento que trata o SRP de forma
  incompatível com o formulário gera achado.
- **Requisito → execução → fiscalização → aceitação**: requisito
  objetivamente verificável (certificação, CA, laudo, ABNT NBR, INMETRO,
  ANVISA, licença ambiental) exigido no TR e não retomado nas cláusulas
  de verificação vira aviso.

## G. Trace — exemplo sanitizado

```json
{ "modo": "vetorial", "piso": 0.2, "descartados_por_piso": 0,
  "consultas": [
    {"tema": "geral",      "consulta": "edital de licitação registro de preços…", "recuperados": 2},
    {"tema": "srp",        "consulta": "sistema de registro de preços ata … cadastro de reserva…", "recuperados": 2},
    {"tema": "modalidade", "consulta": "modalidade de licitação pregão concorrência…", "recuperados": 2},
    {"tema": "sancoes",    "consulta": "infrações administrativas sanções advertência multa…", "recuperados": 2}],
  "referencias": [
    {"tema": "geral", "titulo": "Lei nº 14.133/2021", "categoria": "lei",
     "score": 0.7412, "documento_id": "doc-lei", "ordem": 42,
     "trecho": "Art. 84. O prazo de vigência da ata de registro de preços será de 1 (um) ano…"},
    {"tema": "geral", "titulo": "Edital 2019 (processo anterior)", "categoria": "processo_anterior",
     "score": 0.9, "documento_id": "doc-old", "ordem": 3,
     "trecho": "Cláusula 12 - pregão na forma do art. 4º da Lei 10.520/2002…"}]}
```

Sem chaves de API, sem prompt, sem documento gerado — apenas
identificação da fonte e trecho de 160 caracteres para localizar.

## H. Testes

| | main | branch |
|---|---|---|
| Suíte completa | **395 passed / 1 failed** | **449 passed / 1 failed** |

A falha é a mesma nos dois lados (`test_export_estilos.py::
test_pdf_via_libreoffice_quando_disponivel` — LibreOffice do container
substitui Times por Helvetica): **pré-existente, não é regressão**.

Novos: `tests/test_p1_grounding.py` (19) e `tests/test_p1_inteligencia.py`
(35) — RAG-01..06, ETP-01..04, COND-01..05, CONS-01..06, mais orçamento
de buscas, dedup, lote único de embeddings, precedência municipal sobre a
base, rastreabilidade da decisão até a fonte normativa e degradação
graciosa. Cenários: bens com SRP, bens sem SRP, serviço contínuo com
dedicação de mão de obra e SaaS/TI.

## I. Regressões

Uma alteração de contrato, declarada: `tests/test_rag.py::
test_bloco_referencias_formata_trechos` passava por
`rag.buscar_referencias`; como a montagem do bloco agora percorre a
recuperação temática, o teste foi reapontado para o mesmo ponto de
integração (`_executar_rpc`). `buscar_referencias` continua existindo e
funcionando para consulta única. Nenhuma outra regressão.

Um defeito de projeto foi encontrado **pelos próprios testes** durante a
implementação (RAG-02) e corrigido: com os temas em ordem arbitrária,
*pagamento* e *sanções* — matérias em que o sistema errou no P0 —
ficavam fora do orçamento do TR e do Edital. Daí `TEMAS_POR_DOCUMENTO`.

## J. Limitações remanescentes

1. **Base de conhecimento vazia = sem grounding.** As regras de citação e
   a hierarquia continuam no prompt, mas sem normas indexadas o modelo
   fica apoiado apenas no mapa canônico. Indexar Lei 14.133/2021,
   regulamentação municipal e acórdãos é pré-requisito para o ganho real.
2. **Jurisdição não é modelada no banco.** `documentos_referencia` tem
   `categoria`, não escopo (federal/estadual/municipal). A separação
   hoje é textual, no bloco do prompt. Modelá-la exigiria migração e
   recuradoria do acervo — não foi feito para não criar arquitetura
   normativa paralela.
3. **Piso de relevância sem calibração empírica.** Os padrões (0,20
   vetorial / 0,01 textual) são conservadores e configuráveis; a
   calibração real depende de scores observados em produção.
4. **Categoria do objeto é heurística** (confiança 0,6): cobre as classes
   do vocabulário e cai para `INDEFINIDA` sem evidência — nesse caso
   nenhuma regra específica dispara (conservador).
5. **Consistência semântica é determinística**, por decisões extraíveis.
   Divergências puramente redacionais (a necessidade do ETP contradizer
   em prosa a do DFD) continuam dependendo de revisão humana.
6. **Campos ausentes do formulário** (matrícula, equipe, prioridade, data
   da fase preparatória, CNPJ) seguem como `[PREENCHER]` — decisão de
   produto do P2, inalterada.
7. **Sem execução com IA real** neste ambiente (sem chaves/Supabase): o
   comportamento foi verificado por testes determinísticos sobre os
   componentes reais; o smoke test com IA continua pendente para o
   ambiente do usuário.

## Ativação sugerida (default conservador)

Nada muda com as flags como estão. Para colher o P1:
`flag_canonical_facts` → `flag_knowledge_engine_shadow` → conferir as
decisões na tela → `flag_knowledge_engine_active` (passa a influenciar a
geração) → `flag_process_consistency`. Migração `0011_rag_trace.sql`
pode ser aplicada a qualquer momento (expand-only); sem ela, o trace
simplesmente não é gravado.
