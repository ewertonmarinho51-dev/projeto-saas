# Auditoria e Plano de Correção do Sistema de Geração Documental

**Data:** 09/08/2026 · **Base de evidência:** 4 documentos reais gerados
(DFD 103 p., ETP 69 p., TR 69 p., Edital 159 p. — Prefeitura de
Paragominas) analisados linha a linha, cruzados com o código em `main`
(`048c39f`). **Regra seguida:** nenhuma funcionalidade nova — todas as
correções foram feitas nos componentes existentes.

---

## 1. Mapa da arquitetura atual (ETAPA A)

Monólito Streamlit (sem API HTTP), estado em `st.session_state`,
persistência Supabase/Postgres + pgvector. Fluxo de geração:

```
Formulário Matriz (ui/steps.render_formulario → CAMPOS_FORMULARIO)
   └─ dados{} ─→ prompts.montar_prompt (instruções do perfil + memorando
                  + formulário formatado + doc anterior aprovado)
        └─ rag.montar_bloco_referencias (top-6 chunks, consulta =
           objeto+justificativa+modelo)  → llm.gerar_documento
             └─ planilha.injetar_tabela ([[TABELA_ITENS]] → tabela real)
                  └─ validacao.validar_documento → achados.gerar_relatorio
                       → ciclo (auditoria→corretor→patches→reauditoria)
                            → export.gerar_docx/pdf (LibreOffice)
```

Componentes já existentes e REUTILIZADOS na correção: `validacao.py`
(revisor determinístico), `achados.py` (findings estruturados),
`ciclo.py`/`corretor.py`/`patches.py` (correção automática v4),
`perfis.py` (estrutura dos documentos aprovados), `planilha.py`,
`export.py`, `prompts.py`, `state.py`, `rag.py`.

## 2. Componentes envolvidos em cada sintoma

| Sintoma observado (evidência literal) | Componentes reais envolvidos |
|---|---|
| `matrícula: 15` / `Representante…: 15` / `…: alto` (DFD 9.1.x, ETP 16.1.x) | `config.CAMPOS_FORMULARIO` + `perfis.py` + `prompts.py` + `validacao.py` |
| `Prioridade da demanda: 3(https://www.tkshopping.com.br/produto/alfinete-…) \|` (DFD 1.5) | memorando com planilha embutida → `prompts.montar_prompt`; sem checagem de URL em `validacao.py` |
| `matrícula: 999999` (DFD/ETP/TR) | dado provisório não sinalizado por `validacao.py` |
| Item 572704 repetido **95× no DFD e 96× no Edital** | `planilha.injetar_tabela` + `export._docx_inserir_markdown`/`_docx_formatar_tabela` |
| 1 item por página na tabela (DFD com 103 páginas) | `w:cantSplit` em toda linha em `export._docx_formatar_tabela` |
| Itens copiados na prosa (10 itens na cláusula 1.5, 5 na 7.3) | amostra do `resumo_para_prompt` + planilha embutida no memorando |
| Pregão "na forma do art. 109" (Edital 1.3) | citação de memória do LLM; sem verificação em `validacao.py`; RAG não ancora artigo |
| Vigência da Ata fundada no art. 82 (Edital 2.5) | idem |
| Pagamento fundado no art. 98 (ETP/TR, 6 ocorrências) | idem — art. 98 é o limite da garantia |
| "Repactuação" para materiais de expediente (ETP 6.14, TR 3.10) | instituto errado para bens; correto = reajuste (art. 92, §3º) |
| `Garantia contratual: 5%.` seca (Ata cl. 9.2) | cláusula não desenvolvida; sem checagem |
| Datas/estado vazando entre contratações | `state.reiniciar_processo` não limpava `_ciclo_resultado`, `_fatos_cache`, `_familia_escolha_*`, `_memorando_lido`, `_xlsx_lido`, `registro_geracoes` |

## 3. Sintoma → causa-raiz → correção (ETAPA B)

| # | Sintoma | Causa-raiz (por que o sistema fez isso) | Componente corrigido | Correção |
|---|---|---|---|---|
| 1 | `15`/`alto` em cargo; `999999` em matrícula | O **perfil** do DFD/ETP (extraído dos documentos aprovados) exige cláusulas (equipe, matrícula, prioridade, data) que o **formulário não coleta**; o LLM tapava a lacuna com tokens do contexto (`R$ 15,75` → "15"; "alta absorção/alto giro" → "alto") em vez de `[PREENCHER]`. O prompt já foi endurecido (PR #7); faltava a **rede determinística** | `validacao.py` + `achados.py` | Bloqueio: cargo/função com número/escala; aviso: matrícula toda igual/curtíssima; ambos viram findings do ciclo |
| 2 | URL na Prioridade | O memorando enviado contém a planilha completa (com links); o prompt inteiro vai ao LLM e nada bloqueava URL na prosa | `validacao.py` + `prompts.py` | Bloqueio de URL crua na prosa (allowlist institucional gov.br/plataformas); instrução explícita no bloco do memorando |
| 3 | Item repetido 95×/96× | `[[TABELA_ITENS]]` escrito **no meio de uma frase** → `str.replace` colava o cabeçalho Markdown na prosa → o conversor DOCX perdia o cabeçalho e promovia o **1º item** a linha-cabeçalho (`w:tblHeader` = repetida em TODA página) | `planilha.injetar_tabela` + `export.py` | Tabela injetada SEMPRE em bloco próprio e UMA única vez (ocorrências extras da marca são removidas); no DOCX, linha 0 só vira cabeçalho se existir separador `\|---\|` real |
| 4 | 1 item por página | `w:cantSplit` em todas as linhas + descrições longas | `export._docx_formatar_tabela` | `cantSplit` apenas em linhas ≤ 250 chars; longas podem dividir entre páginas |
| 5 | Tabela/itens duplicados na prosa | `str.replace` substituía TODAS as marcas; amostra do resumo e planilha do memorando eram copiadas | `planilha.py` + `validacao.py` | Injeção única + bloqueio quando o cabeçalho `\| Código \| Descrição \|` aparece 2+ vezes no documento |
| 6 | Artigos errados (109/82/98/repactuação) | Regra 7 do prompt convidava a citar dispositivos sem âncora; RAG (top-6 por similaridade, sem filtro temático) não fundamenta artigo a artigo; nenhuma verificação posterior | `prompts.py` + `validacao.py` + `achados.py` | **Mapa canônico** da Lei 14.133 no system prompt (pregão=28,I/29; ARP=82-86; vigência ata=84; pagamento=141-146; garantia=96-98; reajuste=92,§3º; repactuação=135; sanções=155/156) + verificação determinística por parágrafo (pregão×109 bloqueia; vigência×82, pagamento×98, repactuação sem mão de obra, garantia seca = avisos) |
| 7 | CNPJ improvisado | Nenhuma validação de dígitos verificadores | `validacao.py` | CNPJ com DV inválido ou zerado bloqueia |
| 8 | Datas/estado entre contratações | `reiniciar_processo` limpava só `dados/documentos/aprovados/processo_id`; caches `_*` e uploads liam o processo anterior | `state.py` | Limpeza de todas as chaves transitórias `_*`, dos uploaders e do `registro_geracoes` |

## 4. Recursos existentes reutilizados (nada paralelo foi criado)

- Os novos defeitos entram no **mesmo** `validacao.py` → viram findings pelo
  **mesmo** `achados.py` → alimentam o **mesmo** ciclo v4
  (corretor/patches) e o **mesmo** gate de emissão. Zero pipelines novos.
- O mapa legal canônico vive no `SYSTEM_PROMPT_BASE` existente (regra 7) —
  não foi criado segundo RAG nem base jurídica paralela.
- A robustez da tabela usa `planilha.injetar_tabela` e o conversor
  Markdown→DOCX existentes.

## 5. Alterações por arquivo

| Arquivo | Alteração |
|---|---|
| `src/planilha.py` | `injetar_tabela`: injeção única, em bloco próprio; `resumo_para_prompt`: marca exatamente 1×, proibição de copiar itens do memorando |
| `src/export.py` | `_tem_cabecalho` (separador real exigido); `tblHeader`/negrito só com cabeçalho real; `cantSplit` só em linha curta; fallback fpdf2 idem |
| `src/validacao.py` | `_validar_dados_improvisados` (URL crua, cargo inválido, matrícula suspeita, CNPJ, tabela duplicada) e `_validar_fundamentos_legais` (mapa de confusões da Lei 14.133 + repactuação + garantia seca) |
| `src/achados.py` | Classificação dos 9 novos achados (categoria/gravidade/auto/bloqueio) para o ciclo de correção |
| `src/prompts.py` | Regra 7 + mapa canônico da Lei 14.133; instrução anti-cópia de itens no bloco do memorando |
| `src/state.py` | `reiniciar_processo` limpa estado transitório e uploads |
| `tests/test_auditoria_p0.py` | 29 testes cobrindo os 10 testes obrigatórios, com trechos literais dos documentos reais |

## 6. O que NÃO será criado (e por quê)

- **Novo agente/RAG/pipeline/base paralela** — proibido pela regra
  principal; os componentes existentes cobrem os defeitos.
- **Campos novos no formulário** (matrícula, equipe, prioridade, data
  prevista) — seria funcionalidade nova; o mecanismo existente
  (`[PREENCHER]` + revisão `aplicar_dado_pontual`) já resolve o dado
  faltante com controle humano. Fica como decisão de produto (P2).
- **Correções hardcoded por documento** — todas as regras são
  generalizáveis (padrões de improviso, mapa canônico da lei, injeção de
  tabela), nenhuma cita Paragominas ou o processo específico.
- **Reescrita de módulos** — todos os diffs são pontuais.

## 7. Plano por prioridade

- **P0 (implementado nesta entrega):** itens 1–8 da tabela da seção 3.
- **P1 (próxima onda, componentes existentes):**
  - ETP: reordenar as instruções do perfil para necessidade→requisitos→
    alternativas→solução (hoje o SRP chega decidido pelo formulário) —
    ajuste em `perfis.estrutura_para_prompt`/`_ABERTURAS`;
  - cláusulas condicionais (SRP/repactuação/garantia/amostra/ME-EPP) —
    regras no motor de conhecimento v5 já existente (dados, não código);
  - consistência cruzada de valores/prazos entre documentos — ampliar
    `consistencia.py` (v5 F5) com comparação de fundamentos legais;
  - RAG: gravar trace de recuperação (títulos/trechos usados) na tabela
    `geracoes` existente para auditabilidade das citações.
- **P2 (decisão de produto):** campos estruturados novos no formulário;
  fechamento de RLS via Supabase Auth; auditoria gold-standard do Edital.

## 8. Testes (10 obrigatórios → 29 casos)

`tests/test_auditoria_p0.py` — todos com trechos LITERAIS dos PDFs reais:
isolamento de campos (3), prioridade/URL (3), tabela 210 itens (5),
datas/estado (1), placeholders/matrícula (3), fundamentos legais (4),
repactuação (2), consistência do dossiê (2), garantia (2), CNPJ (2) +
integração com o ciclo (2). **Resultado: 29/29 verdes; suíte completa
395 passed, 1 failed** (`test_pdf_via_libreoffice_quando_disponivel` —
falha pré-existente de fonte do container, não relacionada).

## 9. Riscos de regressão e mitigação

- **Falso positivo nos bloqueios novos** (URL institucional, cargo com
  valor legítimo): mitigado por allowlist gov.br/plataformas, padrões
  restritos a número-solto/palavra-de-escala e testes de contraprova
  ("Maria Silva, Diretora" passa; `[link](url)` em tabela passa).
- **Checagem legal**: só o par inequívoco (pregão×109) bloqueia; os demais
  são avisos revisáveis — não travam emissão legítima.
- **`cantSplit` condicional**: tabelas curtas mantêm o comportamento
  antigo (limiar 250 chars testado nos dois sentidos).
- **Limpeza de sessão**: exclui apenas chaves transitórias `_*` (convenção
  já usada por todos os caches); `usuario`/chaves de API preservados.

## 10. Instruções para outra IA (Codex) dar continuidade

1. **Não crie** agentes, RAGs, pipelines ou bases paralelas; todo defeito
   de geração entra por `validacao.py` → `achados.py` → ciclo v4.
2. Antes de alterar, pergunte "por que o sistema atual fez isso?" — as
   causas-raiz mapeadas estão na seção 3; os PDFs de evidência são a
   referência de regressão (`tests/test_auditoria_p0.py` usa trechos
   literais deles).
3. P1 pendente: ordem do ETP (`perfis.py`), cláusulas condicionais como
   REGRAS do motor v5 (`conhecimento.py`, dados não código), consistência
   de fundamentos (`consistencia.py`), trace do RAG (tabela `geracoes`).
4. Convenções: migrações expand-only idempotentes; flags `config_app`
   default OFF; proxy git bloqueia force-push (nunca amende após push);
   commits em português; falhas do check Vercel nos PRs são ruído.
5. Segredos apenas em `.streamlit/secrets.toml`; tenant vem da SESSÃO;
   dado determinístico ausente vira `[PREENCHER: …]`, nunca improviso.
