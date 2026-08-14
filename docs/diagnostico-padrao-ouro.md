# Diagnóstico — aprovação e exportação de documentos fora do padrão

Branch `correcao-padrao-ouro-documentos` (a partir de `main` `72649bd`).
Caso reproduzido: processo `46610544-3227-4523-a3f6-724af01f4daa` —
Prefeitura Municipal de Paragominas, materiais de expediente, **210
itens**, valor global **R$ 8.024.834,67** (recalculado dos itens:
confere ao centavo). Todos os artefatos foram recuperados da base de
produção (tabelas `processos` e `revisoes`), não simulados.

## 1. Os cinco estágios, com hash e status

| # | Estágio | Artefato | Hash / identidade | Validadores (código atual) |
|---|---|---|---|---|
| 1 | Saída original do modelo | **não persistida** (lacuna de telemetria: só existe o pós-injeção) | — | — |
| 2 | Após injeção da tabela | snapshots v1 dos jobs de 14–15/07 em `revisoes` | `b39f30c3`, `1d9c327d`, `66013c30` | na época: 21–29 findings, até 20 `[PREENCHER]` no edital |
| 3 | Após autocorreção | bundle v4 do job de 15/07 23:09 | `eab5726f` | — |
| 4 | Conteúdo enviado ao exportador | `processos.documentos` (o que a tela exporta) | `eab5726f` — **idêntico ao aprovado** | **6 bloqueios + 17 avisos** |
| 5 | Texto extraído do PDF final | regenerado com `export.gerar_pdf_consolidado` (motor libreoffice) | sha256 `d8ae49ed…`, 190 páginas | defeitos do estágio 4 + defeitos próprios de renderização |

O PDF do usuário chama-se `prefeitura-municipal-de-paragominas-fase-preparatoria.pdf`
— exatamente o nome que `steps.render_sucesso` dá ao dossiê consolidado
(`{prefixo}-fase-preparatoria.pdf`). O estágio 4 é o conteúdo integral do
PDF: a exportação não revalida nada.

## 2. Por que a interface diz "nenhuma correção é necessária" com o PDF bloqueável

Linha do tempo dos jobs de revisão (tabela `revisoes`):

1. **14–15/07** — o bundle nasce cheio de defeitos (até 29 findings; 20
   `[PREENCHER]` no edital; `CORRECTION_FAILED`; 2× `WAITING_REQUIRED_DATA`;
   `BLOCKED_MAX_CYCLES`). O corretor por patches remove em 3 ciclos o que
   as regras **da época** apontavam; às 23:09 de 15/07 o bundle v4
   (`eab5726f`) é **APPROVED** — o único finding restante ("tabela sem
   linha de cabeçalho") é aviso, e aviso não bloqueia.
2. **08/08 23:01** — usuário reabre o processo. Novo job roda com o
   código então em produção (anterior aos merges P0/P1 de 09–11/08):
   **1 finding (aviso), APPROVED, ciclo 0** → a tela imprime
   "Documentos revisados e aprovados para emissão. **Nenhuma correção
   foi necessária**".
3. **Hoje** — o código atual encontra **6 bloqueios** nesse mesmo bundle
   (URL crua, cargo inventado ×2, tabela duplicada ×2, pregão fundado no
   art. 109). Mas a tela continua dizendo "aprovado", por **duas causas
   convergentes**:

**Causa A — o veredito é reaproveitado sem identidade do auditor.**
`ciclo.executar_com_persistencia` retoma qualquer job cujo status não
seja `REVIEW_QUEUED/REVIEWING` pela `idempotency_key =
ciclo-{processo}-{hash_do_bundle}`. A chave não carrega a versão das
regras: um APPROVED emitido por um auditor obsoleto é reproduzido para
sempre, e os validadores novos **nunca rodam** sobre o bundle.

**Causa B — o caminho "aprovado" não valida o pacote final.**
Em `steps.render_sucesso`, `validacao.validar_todos` só roda quando
`veredito is None` (tela antiga). Com `flag_tela_progresso` ligada e
veredito `aprovado` (replay do job velho), os downloads são liberados
**sem nenhuma validação determinística do conteúdo exportado**.
`flag_gate_emissao` está desligada em produção; e mesmo ligada só
compara hashes — não revalida.

## 3. Defeitos no conteúdo aprovado (estágio 4, bundle `eab5726f`)

- **DFD** — a cláusula "1.5. Prioridade da demanda:" contém `3(https://www.tkshopping.com.br/...)` —
  vazamento cru da planilha (a linha do item 572704 foi engolida pela
  prosa, com URL exposta), seguido de **tabela de 210 itens duplicada
  dentro da Identificação** (posição 496 do documento), além da tabela
  oficial adiante. Matrícula `999999`, "Representante da área: 15"
  (cargo preenchido com número), repactuação prevista para aquisição de
  bens.
- **ETP / TR** — tabelas íntegras (210/210, total confere), mas:
  matrícula `999999` (3×/1×), pagamento fundado no art. 98, vigência de
  ARP no art. 82, repactuação para bens, garantia declarada só com
  percentual.
- **EDITAL** — **3 fragmentos de tabela escritos pelo modelo somando 53
  códigos de 210** (tabela parcial/copiada), pregão fundamentado no
  art. 109, garantia sem fundamentação.
- **ARP** — não existe como instrumento: 10 menções dentro do edital,
  nenhum documento próprio.
- Nenhum validador conferia a tabela contra a fonte (contagem, códigos,
  total) — a duplicação/parcialidade passou pelas regras da época.

## 4. Defeitos próprios da exportação (estágio 5)

Inspeção visual dos PDFs renderizados (motor libreoffice):

- **190 páginas** para 4 documentos (~150 são tabela).
- Colunas de largura uniforme: a Descrição fica com ~2 cm e o LibreOffice
  quebra palavra a cada poucos caracteres ("ESPECIFICA ÇÃO", "PASTA
  SANFONAD A", "el ástico") — 455 fragmentos de 1–3 letras no texto
  extraído; até "matrícula:999999" deixa de ser localizável na extração.
- **Coluna final vazia** em todas as linhas da tabela de itens.
- ~5 itens por página; cabeçalho de tabela repetido 111 vezes.
- Página de rosto quase vazia; sem sumário/navegação no dossiê.

## 5. Lacunas de arquitetura confirmadas

- `planilha.resumo_para_prompt` envia **6 linhas reais** da planilha como
  "amostra ilustrativa" — material que o modelo pode copiar (é a origem
  provável dos fragmentos do edital).
- Com ≤ 12 itens o prompt pede que o **modelo redigite a tabela inteira**
  (caminho inline) — o modelo nunca deveria escrever linha de item.
- `injetar_tabela` deduplica o marcador, mas não detecta nem remove
  tabelas que o modelo copiou por conta própria, e nada confere o
  conjunto final contra a fonte.
- O auditor semântico (`flag_reauditoria`) corta cada documento em 20 000
  caracteres **com a tabela dentro** — a tabela determinística consome o
  orçamento e a prosa final (TR tem 91 KB) fica sem auditoria.
- Edital gerado por prosa livre da IA; ARP inexistente; nenhum template
  determinístico em uso (`templates_gov`/`catalogo` existem, atrás de
  flag, com catálogo vazio).

## 6. Achado colateral de segurança (fora do escopo desta branch — ação imediata recomendada)

Durante a recuperação do caso constatei que a tabela **`config_app` é
legível pela chave anônima pública** do Supabase — incluindo
`OPENAI_API_KEY` e `GOOGLE_API_KEY` em texto puro (as tabelas
`processos` e `revisoes` também são legíveis pela chave pública).
Qualquer visitante do app consegue extrair as chaves e todos os
processos. **Recomendação: rotacionar as duas chaves imediatamente e
aplicar RLS/revogação de grants nessas tabelas** (mesmo padrão das
migrações 0015/0016 dos backups). Não corrigi aqui para não misturar
escopos; nenhuma dessas chaves foi utilizada neste trabalho.

## 7. Resultado das correções

Branch `correcao-padrao-ouro-documentos`, cinco commits, **620 testes
passando e nenhum falhando** — a suíte inteira passa pela primeira vez
(a falha tida como "pré-existente" era o sintoma do defeito do motor de
PDF descrito abaixo).

| Métrica no caso real (210 itens) | Antes | Depois |
|---|---|---|
| Veredito do bundle exportado | APPROVED, "nenhuma correção foi necessária" | **BLOCKED**, 16 achados bloqueantes, 32 findings |
| Achados bloqueantes por documento | — | Edital 7, DFD 6, ETP 2, TR 1 |
| Páginas do dossiê | 190 | **79** |
| Palavras partidas no PDF | 455 | **0** (restam 12 palavras curtas legítimas) |
| Blocos fora da margem direita | 203 | **0** |
| Itens da planilha no PDF | 210/210 | 210/210 (agora conferidos por código) |
| ARP como instrumento | inexistente | documento próprio, exportado |

Defeito adicional descoberto na Fase 5, que sustentava todos os
problemas de apresentação: **o LibreOffice está no PATH mas a conversão
falha em tempo de execução**. `_docx_em_pdf` devolvia `None` em silêncio,
o dossiê saía pelo renderizador fpdf2 e a tela de auditoria continuava
anunciando "Motor de PDF ativo: libreoffice" — todo diagnóstico de
formatação ia para o motor errado. `motor_pdf()` passa a responder a
partir de uma conversão real de sonda.

## 8. Plano de correção (ordem de implementação)

1. **Gate e identidade** — chave de idempotência ganha a impressão
   digital do auditor (replay só entre regras idênticas); o caminho
   "aprovado" revalida deterministicamente o pacote exatamente como
   exportado; bloqueio impede downloads oficiais; minuta com marca
   "NÃO APROVADA PARA EMISSÃO" continua baixável; auditor semântico
   recebe a prosa sem a tabela determinística.
2. **Integridade factual e da tabela** — amostra real fora do prompt;
   marcador+injeção para qualquer tamanho; validador que confere
   contagem/códigos/valores/total contra a fonte e rejeita
   cópias/fragmentos; decisões não confirmadas silenciosamente.
3. **Estrutura DFD/ETP/TR** — prompts e validadores (ordem do ETP já
   existente, repactuação bloqueante para bens, referências internas).
4. **Edital e ARP determinísticos** — esqueleto versionado com o
   conteúdo mínimo do art. 25 e ARP como instrumento próprio (art. 84/86),
   campos faltantes explícitos bloqueando emissão.
5. **Exportação** — larguras de coluna, fonte da tabela, fim das
   palavras quebradas, sumário do dossiê; regressão com o fixture de
   210 itens e inspeção visual antes/depois.
