# Relatório de Cotação — progresso por gate

Pacote: `PACOTE_CLAUDE_CODE_RELATORIO_COTACAO_2026-10-16` (prompt mestre,
diagnóstico, design, contratos, aceite, gates). Branch
`feature/relatorio-cotacao-visual`, a partir de `main` em `f5c004d`
(v1.9.1). **Sem merge, sem deploy, sem migração.**

## Estado

| Gate | Situação | Evidência |
|---|---|---|
| G0 auditoria e baseline | feito | abaixo, "Baseline" |
| G1 projeção canônica | feito | `src/precos/relatorio_view.py`; provas em `tests/test_relatorio_cotacao.py` |
| G2 template compacto | feito | `src/precos/documento_cotacao.py`; PDF 5 itens/871 em 6 páginas (antes 321) |
| G3 anexo integral e pacote | feito | analítico paisagem + XLSX com link e ID; provas de concordância |
| G4 UI, histórico, alternância | feito, flag OFF | `precos_ui._render_relatorios_visuais`; `tests/test_relatorio_cotacao_tela.py` |
| G5 qualidade e entrega | feito | `scripts/relatorio_cotacao_amostras.py`; `docs/precos-relatorio/` |

## G0 — diagnóstico confirmado contra os arquivos reais

* **PDF GovConnect anterior** (`Material-de-Expediente-rev1-completo.pdf`):
  907 páginas, A4 retrato, **0 links**, fontes DejaVu Serif (o Times do
  DOCX não existe no servidor). Cabeçalhos partidos `Méto/do`,
  `Situaç/ão`, `Unitá/rio` no quadro de 9 colunas (pág. 4); tabela de
  referências de 11 colunas a partir da pág. 5; identificador da versão
  só na última página.
* **PDF comercial de referência**: 6 páginas, 16 links, quadro de poucas
  colunas, blocos por referência. Lido para hierarquia — nada dele foi
  copiado (marca, QR, certificado, URL, CNPJ, pessoas). Há prova disso.
* **Causa no código**, confirmada no HEAD: `relatorio.completo()` e
  `resumido()` geram Markdown com tabelas de 9 a 13 colunas, convertidas
  pelo exportador genérico (`export.gerar_pdf`, larguras proporcionais).
* **Defeito colateral achado**: `precos_ui` lia
  `st.session_state["branding"]`, chave que nenhuma tela grava — os
  relatórios de preços nunca saíram com timbrado. O caminho novo usa o
  mesmo resolvedor das exportações do processo
  (`contexto.identidade_para_exportacao`, depois o órgão padrão). O
  caminho antigo fica como estava, para o rollback ser exato.
* **Ambiente**: produção tem `libreoffice-writer` 7.4 e `fonts-dejavu`
  (inclui DejaVu Sans Condensed — conferido no contêiner). Local: LibreOffice
  26.2; as DejaVu foram registradas na pasta de fontes dele para que o
  render local use as mesmas fontes da produção.

### Baseline (mesmo snapshot sintético, gerador anterior)

| Cenário | Completo (anterior) | Resumido (anterior) |
|---|---|---|
| 5 itens / 871 consideradas / 2.857 refs (regra legada: mediana) | 321 págs · 13,9 MB · 55 s | 2 págs |
| 210 itens / 1.474 refs | 374 págs · 12,7 MB · 55 s | 32 págs |
| pendências (5 itens) | 11 págs | 2 págs |

O sintético tem descrições mais curtas que o real; por isso 321 e não
907 páginas. A comparação válida é a do MESMO snapshot, abaixo.

### Os 22 pontos de informação do relatório anterior → onde estão agora

| § | Informação | Relatório de Cotação | Analítico | XLSX |
|---|---|---|---|---|
| 1 | Identificação (nome, id, revisão, situação, data-base) | abertura + identificação | abertura | Identificação |
| 2 | Objeto | abertura | abertura | — |
| 3 | Processo | abertura | abertura | — |
| 4 | Responsáveis e local | abertura | abertura | — |
| 5 | Perfil normativo | abertura + Método | abertura | Identificação |
| 6 | Metodologia | Método e critérios | — | Identificação (regra) |
| 7 | Fontes e trilha | Fontes consultadas | Fontes consultadas | Referências |
| 8 | Critérios de busca | Método e critérios (janela, UF, catálogo) | — | — |
| 9 | Comparabilidade | Método (contagem N/mínimo) | coluna Compat. | colunas de nota |
| 10 | Critérios estatísticos (por regra da pesquisa) | Método e critérios | — | — |
| 11 | Quadro-resumo | Resumo da cotação (7 colunas) | — | Itens |
| 12 | Análise item a item | Detalhamento | por item | Itens |
| 13 | Referências consideradas | amostra declarada "X de N" | todas | todas |
| 14 | Não consideradas e motivo | resumo por situação + exclusões do revisor | todas, com motivo | todas |
| 15 | Memória de cálculo | por item | — | — |
| 16 | Unitário | quadro + KPI | por item | Itens |
| 17 | Total do item | quadro + KPI | — | Itens |
| 18 | Valor global (só concluídos) e pendências | Subtotal + aviso | — | Itens |
| 19 | Alertas e ressalvas | Alertas e ressalvas | discrepantes | — |
| 20 | Evidências | identificador + link por referência | evidência por linha | impressão da evidência |
| 21 | Data e hora | abertura + identificação (UTC e Brasília) | idem | — |
| 22 | Identificador da versão | identificação + rodapé | identificação + rodapé | Identificação |

Nenhum dos 22 pontos ficou de fora do Relatório de Cotação.

## G1 — projeção

`relatorio_view.projetar(pesquisa, itens, referencias, emitido_em,
processo, branding)` → `CotacaoReportView` (dataclasses congeladas,
dicionários internos em `MappingProxyType`). Lê o que o motor gravou;
N/3 é `cesta.consideradas`; a regra legada continua mediana. Não altera
os dicionários recebidos (prova). Três funções de dados foram extraídas
de `relatorio.py` sem mudar o Markdown anterior (comparado byte a byte
com a `main` nos 12 cenários): `fontes_consultadas`,
`alertas_estruturados`, `url_de_verificacao`.

## G2/G3 — documentos

* **Relatório de Cotação** (A4 retrato): abertura com metadados, aviso de
  pendências, quadro de 7 colunas, subtotal dos concluídos (valor global
  só com todos concluídos), método, detalhamento por item com KPIs,
  até 5 preços REPRESENTATIVOS (menor, quartis, mediana, maior) com
  "exibidas X de N", não consideradas resumidas, exclusões do revisor
  com preço riscado e justificativa, memória de cálculo, exceção formal,
  fontes, alertas e identificação. Rodapé com versão e "Página X de Y".
* **Relatório Analítico Integral** (A4 paisagem): todas as referências,
  uma linha cada, cabeçalho repetido, situação e motivo, link real.
* **Memória Analítica (XLSX)**: a de sempre, mais "Link de verificação" e
  "ID da referência" (no fim, para não deslocar colunas) e a regra de
  formação na aba Identificação.
* Item sem preço: "Não estimado". Item não concluído com valor
  calculado: "R$ x (provisório)" no detalhe, "—" no quadro, fora do
  subtotal. Nenhum concluído: o subtotal diz "Nenhum item concluído",
  não R$ 0,00.
* PDF só pelo LibreOffice; sem ele, erro explícito na tela (o DOCX tem
  o mesmo conteúdo). `export._docx_em_pdf` ganhou `tempo_limite`
  opcional (padrão 120 s, igual ao anterior) — único toque em `export.py`.

## G4 — tela

Flag `precos_relatorio_visual` (`governanca.FLAG_RELATORIO_VISUAL`),
**desligada por padrão** (sem linha em `config_app`). Ligada, os mesmos
lugares oferecem: Relatório de Cotação (PDF), Relatório de Cotação
(DOCX), Memória analítica (XLSX) e Relatório Analítico Integral (PDF)
com aviso de volume e limite de 15.000 referências; o pacote ZIP leva
Cotação + XLSX e só inclui o integral se marcado. Chave de cache na
sessão inclui o identificador do resultado e a versão do layout.

Registro de emissão sem migração: a tabela da 0029 aceita
`completo|resumido|analitico|pacote`; o Relatório de Cotação registra
como `completo`, o analítico integral como `analitico`, distinguidos
pelo nome e pelo hash do arquivo.

## Rollback

Desligar a flag (`delete from config_app where chave =
'flag_precos_relatorio_visual'` ou valor `off`). Não altera cesta,
preço, emissões registradas nem PDFs emitidos. O gerador anterior
(`relatorio.completo/resumido` + `export.gerar_pdf`) continua intacto.

## Itens abertos

* O compacto de 210 itens tem 122 páginas (um bloco por item). Se o
  operador preferir, um modo "só quadro + pendências" para processos
  grandes é extensão simples do mesmo renderer.
* Sessão guarda os bytes gerados (até ~12 MB no analítico grande), como
  já fazia com o relatório anterior.

Entrega e capturas: `docs/precos-relatorio/RELATORIO_ENTREGA.md`.
