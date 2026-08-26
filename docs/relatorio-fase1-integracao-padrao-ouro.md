# Fase 1 — Relatório de integração do padrão ouro

Branch de trabalho: `integracao-padrao-ouro-main-atual`
Data: 19/08/2026. **Nenhum merge na `main`. Nenhum PR aberto.**

---

## A. BASE

| | commit | observação |
|---|---|---|
| base da integração (`main` real, verificada após atualizar a visão do repositório) | `7953a356a92ede77beb8bea0d6f918f073709863` | `docs: plano para alcançar e superar o padrão ouro` |
| branch do padrão ouro | `62fe0e1135b8794327b0c400e2d7508e970068c1` | 8 commits exclusivos |
| ancestral comum | `72649bd7eaade4646b3e4c6bbdf135f6aca4d694` | |

A branch nova nasceu de `7953a35` (a `main` atual, não de um ponto
anterior) e a `correcao-padrao-ouro-documentos` entrou por merge
**controlado**, com resolução manual — nunca por aceite automático.

## B. ESTRATÉGIA

Precedência aplicada, exatamente como determinado:

| domínio | quem prevalece | como se verifica |
|---|---|---|
| UX / apresentação | **`main`** | as 7 chamadas a `components.*` em `steps.py` são idênticas às da `main`, uma a uma |
| segurança / auth / Supabase | **`main`** | `src/auth.py`, `src/db.py`, `src/trilha.py`, `supabase/` e `scripts/` têm **diff vazio** contra a `main` |
| inteligência documental (P0/P1) | **`main` preservada; padrão ouro complementa** | tabela em D |
| qualidade / gate / documentos | **padrão ouro**, por ser mais rigoroso | capacidades em E |

## C. ARQUIVOS DE INTERSEÇÃO

Classificação completa: **44** arquivos só na `main`, **21** só na branch
do padrão ouro, **4** nos dois — exatamente os quatro previstos.

Antes de resolver, foi feita varredura de **conflito semântico sem
conflito textual**: a branch do padrão ouro tem **zero** ocorrências de
`registrar_evento_governanca`, `cliente_do_usuario`, `_autenticar_legado`,
`from . import trilha` e `ator=` — ou seja, ela não toca em nenhum ponto
onde a evolução de segurança da `main` mudou a semântica sob o mesmo
nome. Nada foi aceito só porque o Git não reclamou.

### `src/llm.py` — auto-mesclado, +33 linhas, 0 removidas
Ganhou `gerar_instrumento_oficial()`, o caminho determinístico de
Edital/ARP: quando `doc_key` está em `templates_gov.TEMPLATES_OFICIAIS`,
o instrumento é montado a partir do catálogo versionado, não pedido em
prosa livre ao modelo. **Tudo o que a `main` fazia continua**: RAG
(`rag.montar_contexto`), `rag_trace`, diretrizes condicionais do motor de
conhecimento, famílias de modelo, registro técnico de geração e o
fallback OpenAI → Gemini estão intactos.

### `src/state.py` — auto-mesclado, +11 linhas, 0 removidas
Ganhou `usa_srp(dados)`, com critério **único e explícito**: o modelo de
execução declarado no Formulário Matriz. Não deduz SRP de objeto,
quantidade ou parcelamento.

### `src/ui/revisao.py` — auto-mesclado, +85/−2
Removeu-se exatamente **duas** linhas da `main`: o import e a montagem da
chave de idempotência. Entraram `AVISO_MINUTA`, `docs_como_minuta()`,
`_prefixo_arquivo()`, `render_minuta_nao_aprovada()` e
`_render_reprovado_na_revalidacao()`.

### `src/ui/steps.py` — **único conflito textual**, 5 blocos, +50/−12
Regra seguida: **visual e UX da `main` + comportamento funcional do
padrão ouro**. Interface antiga não foi restaurada em nenhum bloco.

| bloco | resolução |
|---|---|
| imports | união — `components` permanece, `DOCUMENTOS_EXPORTAVEIS` entra |
| geração do documento | `render_document_skeleton` da `main` **mantido**; dentro dele entra a geração da ARP quando `usa_srp` (o `st.spinner` da branch antiga foi descartado por ser a UX anterior) |
| cabeçalho da tela final | `render_page_header` + `render_stepper` **mantidos**; o título passou de "Processo concluído" para "Emissão dos documentos" — a semântica do padrão ouro ("concluído" só quando a emissão é de fato liberada) sem abandonar o componente |
| banner de sucesso | `render_success_banner()` + `render_summary_strip()` **mantidos**; abaixo deles, já passados todos os gates, a frase que afirma que a revisão aprovou exatamente o conteúdo a ser exportado |
| downloads | contêineres GovConnect **mantidos**; passam a iterar `DOCUMENTOS_EXPORTAVEIS`, e os rótulos dos ZIPs deixaram de ser fixos em "4" para acompanhar o que será empacotado |

Prova de não regressão de UX — contagem de componentes GovConnect em
`steps.py`, `main` × integrada:

```
render_document_skeleton 1×1   render_guidance          1×1
render_page_header       2×2   render_section_heading   7×7
render_stepper           3×3   render_success_banner    1×1
render_summary_strip     1×1
```

Idênticas. **Nenhuma linha de `steps.py` desapareceu sem substituta
nomeada** — as 12 linhas removidas são: 1 import (ampliado), 1 rótulo de
botão (agora condicional), 3 do título da página, 1 chamada de
`validar_todos` (que ganhou o argumento `dados`), 2 rótulos de ZIP
(agora dinâmicos) e 4 iterações `SEQUENCIA_DOCUMENTOS` → `DOCUMENTOS_EXPORTAVEIS`.

## D. FUNCIONALIDADES PRESERVADAS (sem regressão)

Contagem de ocorrências no diretório `src/`, `main` × integrada:

| ponto de integração | main | integrada |
|---|---|---|
| `rag.montar_contexto` | 1 | 1 |
| `_associar_rag_trace` | 3 | **4** |
| `conhecimento.diretrizes_para_prompt` | 1 | 1 |
| `conhecimento.executar_na_tela` | 1 | 1 |
| `fatos.processar_na_tela` | 1 | 1 |
| `consistencia` (módulo transversal) | 18 | **19** |
| `qualidade.processar_na_tela` | 1 | 1 |
| `corretor.plano_em_shadow` | 1 | 1 |
| `achados.relatorio_para_tela` | 1 | 1 |
| `familias.resolver_para_processo` | 1 | 1 |
| `db.flag_ativa` (feature flags) | 32 | 32 |

Nenhum valor caiu. Segurança, autenticação e trilha: **diff vazio** —
`auth.py`, `db.py`, `trilha.py`, `supabase/` e `scripts/` não foram
tocados, inclusive as correções recentes de login e os arquivos
`.NAO_APLICAR` das migrações 0018/0019/0020.

## E. FUNCIONALIDADES INCORPORADAS — as 8 capacidades exigidas

Cada linha foi verificada **executando o código**, não lendo o diff.

**1. `versao_do_auditor()` na chave de idempotência — SIM.**
`sha256` do conjunto de arquivos do auditor. A chave passou de
`ciclo-{processo}-{hash do bundle}` para
`ciclo-{processo}-{hash}-r{versao_do_auditor()[:12]}`, em `ciclo.py:469` e
`ui/revisao.py:180`. Auditor mudou ⇒ chave nova ⇒ reauditoria.

*Ajuste pós-auditoria:* a identidade cobria só
`validacao/achados/consistencia/perfis` e deixava de fora regras que o
auditor **consulta**. Entraram `planilha.py` (`conferir_tabela` decide
bloqueio de integridade), `fatos.py` (natureza do objeto: vira
repactuação de aviso em bloqueio), `normas.py` e `prompts.py` (decidem
"fundamento sem lastro") e `blocos.py` (escopo autorizado do achado).
Fora, com o motivo escrito no código: `db.py` e `governanca.py` (estado
de execução e nome de flag), `config.py` (rótulo e ordem) e apresentação.

**2. Gate final de emissão — SIM.**
`revisao.render_correcao_automatica()` só devolve `"aprovado"` depois de
rodar `validacao.bloqueios(validacao.validar_todos(resultado["documentos"], …))`
sobre **o conteúdo exato que será exportado**. Havendo bloqueio,
`_render_reprovado_na_revalidacao()` retém a emissão, lista as pendências,
oferece o caminho de correção ("Executar a revisão novamente") e libera
**apenas a minuta**, prefixada com `AVISO_MINUTA` e nomeada
`…-MINUTA-NAO-APROVADA.docx`. Um `APPROVED` persistido não libera nada
sozinho.

> Registro de correção de uma leitura minha anterior: eu havia anotado que
> a validação continuava presa a `if veredito is None:` e que, portanto, a
> capacidade 2 não seria entregue pela integração. Estava errado — a
> revalidação vive dentro de `revisao.py`, no caminho `"aprovado"`, e é
> exercida pelos testes `test_padrao_ouro_fase1.py`. Nada precisou ser
> escrito para esta capacidade.

**3. Integridade da planilha — SIM, com uma lacuna que foi fechada aqui.**
`planilha.conferir_tabela` é 100 % determinístico. Provado por mutação
sobre o caso de 210 itens:

| defeito injetado | resultado |
|---|---|
| item ausente | detecta |
| item estranho | detecta |
| item duplicado | detecta |
| código trocado | detecta |
| unidade errada | detecta |
| quantidade errada | detecta |
| preço unitário errado | detecta |
| **total da linha errado** | **não detectava — corrigido nesta branch** |
| valor global errado | detecta |
| múltiplas tabelas | detecta |

A conferência é **por valor de código**, jamais por quantidade de
dígitos — está escrito no próprio código (`_e_tabela_de_itens`: "O código
NÃO é reconhecido por quantidade de dígitos") e há prova nova para isso.

Ao fechar a lacuna do total apareceu o defeito que ela escondia:
`para_markdown` lia `valor_total` direto do item e, com item ainda não
passado por `calcular()`, imprimia **R$ 0,00** em toda a coluna Valor
Total. O produto passa a ser derivado ali mesmo.

**4. Identificações — SIM.** Verificado por execução:

| defeito | veredito |
|---|---|
| matrícula improvisada (`999999`, `12`) | aviso **com pendência** (`campo='matrícula do agente responsável'`) |
| número funcional improvisado (`000000`) | aviso com pendência |
| cargo preenchido por número ("Representante da área: 15") | **bloqueia** |
| CNPJ com 15 dígitos | **bloqueia** |
| CNPJ com dígito verificador errado | **bloqueia** |
| fornecedor genérico ("licitantes", "a definir") | **bloqueia** |
| agente público inventado (nome fora do processo) | **bloqueia** |

Matrícula e número funcional são **aviso com pendência**, não bloqueio,
de propósito: viram pergunta objetiva ao servidor, aproveitando o
mecanismo de pendências humanas que a `main` já tinha. Dado desconhecido
vira `[PREENCHER: descrição precisa]` — a ARP gerada no ensaio traz
`[PREENCHER: razão social do fornecedor beneficiário]`,
`[PREENCHER: CNPJ do fornecedor beneficiário]`,
`[PREENCHER: número do processo administrativo]`. Nada é inventado.

**5. Natureza do objeto e fundamentação — SIM, sem segundo classificador.**
`_natureza_do_objeto()` **reutiliza `fatos.py`** (`NATUREZA_POR_EXECUCAO`,
`categoria_do_objeto`, `NATUREZA_POR_CATEGORIA`) e devolve `""` quando o
processo não permite concluir — "não sei" nunca vira "BENS". Verificado:
repactuação em aquisição de bens **bloqueia**; pregão fundado no art. 109
**bloqueia**; vigência da Ata fundada no art. 82 sem o art. 84 gera aviso;
cláusula de garantia seca gera aviso.

**6. Edital — SIM.** `TEMPLATE_EDITAL` em `templates_gov.py`, montado por
`gerar_instrumento_oficial` a partir do catálogo existente. Nenhuma
arquitetura duplicada, nenhum retorno à prosa livre — o rótulo do botão
inclusive muda para "Gerar minuta do EDITAL" (sem "com IA"), porque é o
que o botão de fato faz.

**7. ARP — SIM.** Instrumento próprio (`TEMPLATE_ARP`), `etapa: 4` — a
mesma do edital. **O wizard continua com quatro etapas de documento**
(`['dfd','etp','tr','edital']`); a ARP é instrumento, não etapa. É
exportável de forma independente (DOCX próprio de 54.639 bytes no ensaio)
e entra no dossiê: o ZIP saiu com
`['01-DFD.docx','02-ETP.docx','03-TR.docx','04-Edital.docx','05-ARP.docx']`.

*Ajuste pós-auditoria:* estar fora de `SEQUENCIA_DOCUMENTOS` e dentro de
`DOCUMENTOS_EXPORTAVEIS` abria uma trajetória de Ata obsoleta — a
invalidação de estado percorria só a sequência, então mudar a modelagem
de SRP para não-SRP derrubava os quatro documentos e deixava a Ata para
trás, exportável. Fechado com duas linhas de defesa:
`config.INSTRUMENTOS_DERIVADOS` faz a Ata cair junto com o edital que a
funda, e `config.exportaveis_do_processo` impede que um processo sem SRP
exporte ARP ainda que a chave residual exista.

**8. Resumo semântico dos itens — SIM.** `resumo_semantico()` entrega
famílias e **distribuição percentual por contagem**. Não entrega códigos,
descrições, quantidades, links nem linhas de tabela.

*Ajuste pós-auditoria:* a faixa mínima/máxima de preço unitário
(`R$ 0,27` e `R$ 329,00` no caso real) **saiu** do prompt por decisão de
auditoria — não é necessária a DFD, ETP ou TR e estimula inferência
econômica que o processo não sustenta. O bloco da planilha enviado à IA
ficou com: número de itens, **valor global como único valor monetário**,
unidades de fornecimento, composição funcional por famílias e o marcador
determinístico da tabela. O teste que aceitava até três valores
monetários passou a exigir exatamente um.

## F. TESTES — uma única suíte do código combinado

Executada **uma** vez sobre o código integrado. Não somei 902 + 641: os
conjuntos se sobrepõem e a soma seria ficção.

| | coletados | passaram | falharam | pulados |
|---|---|---|---|---|
| `main` em `7953a35` (linha de base) | 1007 | 852 | 0 | 155 |
| integrada (merge + total da linha) | 1089 | 934 | 0 | 155 |
| **após os três ajustes de auditoria (HEAD)** | **1106** | **951** | **0** | **155** |

Motivo de **cada** skip (os mesmos 155 da `main`, nenhum novo):

| nº | motivo | por que é legítimo |
|---|---|---|
| 65 | `isolamento: exige GOVDOCS_ENSAIO_URL, _ANON_KEY e _SECRET_KEY de um projeto de ENSAIO descartável` | Etapa E proíbe tocar produção; sem projeto descartável ligado, o teste se recusa a rodar |
| 50 | `ensaio SQL: defina GOVDOCS_ENSAIO_PG_DSN apontando para um PostgreSQL LOCAL descartável` | idem — exige Postgres local descartável |
| 40 | `ensaio de segurança: defina GOVDOCS_ENSAIO_URL e GOVDOCS_ENSAIO_ANON_KEY apontando para um projeto de ENSAIO (nunca produção)` | idem |

Nenhum skip decorre da integração; todos são as travas de ambiente da
frente de segurança, e todos pulam **por recusa deliberada**, não por
falha.

Comparação nominal (`--collect-only`) `main` × integrada: **nenhum teste
da `main` desapareceu**, exceto quatro de `tests/test_planilha.py` que
foram **substituídos** por testes do comportamento invertido:

| teste da `main` removido | substituto | por quê |
|---|---|---|
| `test_prompt_inclui_a_planilha` | `test_prompt_informa_o_valor_global_mas_nao_o_conteudo_da_planilha` | o prompt não pode mais levar descrições |
| `test_resumo_para_prompt_e_compacto` | `test_resumo_para_prompt_nao_leva_nenhuma_linha_real` | a "amostra de 6 linhas" era material pronto para cópia |
| `test_prompt_reproduz_tabela_pequena_inline` | `test_prompt_nunca_manda_a_ia_escrever_a_tabela_nem_com_poucos_itens` | tabela pequena segue o mesmo caminho determinístico |
| `test_injetar_tabela_pequena_nao_altera` | `test_injetar_tabela_pequena_tambem_e_injetada` | abaixo de 12 itens a tabela dependia de a IA redigitá-la |

Essa inversão **é** o que a capacidade 8 exige. Não é perda de cobertura:
os quatro comportamentos continuam cobertos, com o sinal trocado.

`git diff --check`: **limpo**.

Nenhum teste foi criado exigindo contagem exata de palavras. Busca por
`4800`, `12500`, `11400` (e as formas com ponto) em `tests/`: **nenhuma
ocorrência**. As metas de `perfis.py` continuam sendo referência de
corpus, não limite rígido — não há incentivo a enchimento textual.

## G. FIXTURE DE 210 ITENS — reexecução

Conferência determinística sobre `tests/fixtures/caso_210_itens.json`:

| aferição | resultado |
|---|---|
| itens na planilha | **210** |
| linhas de item reconhecidas na tabela emitida | **210** |
| códigos únicos na fonte / no documento | 210 / 210 |
| itens faltando | **nenhum** (`[]`) |
| códigos estranhos | **nenhum** (`[]`) |
| linhas duplicadas | **0** |
| valor global | **R$ 8.024.834,67** — confere ao centavo |
| unidades, quantidades, valores unitários, totais de linha | conferem item a item |
| `conferir_tabela` | `[]` — sem divergência |

**Comprimento dos códigos: 3 dígitos (2 itens), 4 (4), 5 (13), 6 (191).**
Foi por isso que a conferência é por valor de código: qualquer regex de
tamanho fixo daria por perdidos 19 itens — foi exatamente o erro de
medição que cometi no diagnóstico anterior, e agora há um teste que o
impede de voltar.

## H. DEFEITOS QUE PERMANECEM ABERTOS

**1. Vazamento de instrução de prompt para dentro do documento — CONTINUA
REPRODUZÍVEL.** Conforme determinado, **não foi corrigido** e não está
escondido. Reproduzido agora, no código integrado, gerando o DFD do caso
de 210 itens em Modo Demonstração:

| marca no corpo do documento | estado |
|---|---|
| `PROIBIDO escrever a lista de itens…` | **reproduz** |
| `…EXATAMENTE UMA VEZ, SOZINHA em uma linha própria…` | **reproduz** |
| `COMPOSIÇÃO FUNCIONAL DO OBJETO (para você compreender…)` | **reproduz** |
| `NÃO reproduza esta análise como lista` | **reproduz** |
| `Escreva o texto da cláusula de estimativa…` | **reproduz** |
| `[[TABELA_ITENS]]` residual | ausente |
| `IMPORTANTE: NÃO redija` (redação antiga) | ausente |
| `Amostra apenas ilustrativa` (redação antiga) | ausente |

A causa é a mesma de antes: `_gerar_demo()` cola
`formatar_dados_formulario(dados)` no corpo, e essa função produz
**material endereçado ao modelo**. As duas últimas linhas mudaram de
redação porque a branch do padrão ouro reescreveu `resumo_para_prompt` —
**o defeito não mudou, só o texto vazado**. É a Fase 2.

**Efeito colateral positivo, medido:** a tabela duplicada no DFD
**desapareceu**. O documento saiu com uma única tabela, 210 linhas, e
`conferir_tabela` devolveu vazio. A causa B do diagnóstico anterior está
resolvida pela integração.

**2. Texto fora da página (spans com borda direita em 598,1 e 602,7 pt num
papel A4 de 595,3 pt)** — não foi objeto desta fase e continua aberto.

**3. Docstring de `gerar_documento` descrevendo um fallback silencioso que
o código não faz** — continua aberta; é item da Fase 2.

## I. DIFF

```
222d7c0  merge: integra o padrão-ouro documental na arquitetura atual da main
4c1499c  fix(planilha): confere o total de cada linha e nunca escreve R$ 0,00
2ffed0e  docs: relatório da Fase 1 de integração do padrão ouro
—— ajustes pedidos pela auditoria independente ——
35c8213  fix: Ata de Registro de Preços obsoleta não sobrevive à mudança de modelagem
5b5d564  fix: identidade do auditor cobre as dependências que decidem o veredito
e97afd9  fix: só o valor global vai para a IA; extremos de preço unitário saem
```

`4c1499c` é a única alteração de comportamento escrita além da resolução
do conflito e dos ajustes pedidos, e existe porque a capacidade 3 a
exigia nominalmente ("total incorreto").

Arquivos com diff vazio contra a `main`, por decisão: `src/auth.py`,
`src/db.py`, `src/trilha.py`, `supabase/**`, `scripts/**`.

## J. VEREDITO

### APTO PARA AUDITORIA

Sustenta-se em: base correta e verificada; conflito único resolvido com a
UX da `main` intacta e comprovada componente a componente; P0/P1
preservados por contagem; segurança com diff vazio; as 8 capacidades
verificadas **por execução**; suíte única com 951 passando, 0 falhando e
os mesmos 155 skips da linha de base, todos com motivo nomeado; fixture
de 210 itens conferida por código, 210/210, R$ 8.024.834,67, tabela
única; e o defeito da Fase 2 confirmado como ainda reproduzível, sem
disfarce.

### Os três ajustes da auditoria independente — fechados

1. **ARP obsoleta** — conflito semântico que os testes não cobriam,
   fechado com invalidação em cascata (estado) e decisão por formulário
   (exportação), com as duas transições SRP ↔ não-SRP provadas;
2. **identidade do auditor incompleta** — cinco dependências que decidem
   veredito entraram no hash, e a regra passou a ser provável com fontes
   simuladas;
3. **extremos de preço unitário no prompt** — removidos; o valor global
   é agora o único valor monetário do bloco da planilha.

Permanece para confirmação de quem manda no produto: **a substituição dos
quatro testes de `test_planilha.py`** — inversão intencional de
comportamento (o prompt deixou de levar amostra de linhas reais).

Nada aqui autoriza merge, PR ou implantação. **Fase 2 não foi iniciada.**

### Restrições de segurança — cumpridas

Nenhuma migração aplicada (0018, 0019 e 0020 seguem `.NAO_APLICAR`);
nenhum SQL executado; nenhuma política RLS tocada; nenhum backfill de
Supabase Auth; nenhuma credencial rotacionada; nenhum dado de produção
lido ou modificado. Esta tarefa foi **exclusivamente integração de
código** — os testes que exigiriam banco pularam, e pularam por recusa
explícita.
