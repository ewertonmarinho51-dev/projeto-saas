# K — SICRO: custo referencial de obras de transportes (DNIT)

Estado em 24/11/2026: **implementado e testado** no branch `claude/sicro-fonte`.
Migração `0049_precos_sicro_referencia.sql` **não aplicada**; flag
`referencia_custos_sicro` **desligada**; nada importado em produção.

## O que é

O SICRO é o sistema de custos referenciais do DNIT para obras de
infraestrutura de transportes. O valor dele é **custo referencial** de
engenharia, como o do SINAPI (Lei 14.133, art. 23, § 2º, I; § 3º para
sistema adotado pelo ente) — não é preço de compra:

- não entra em `fontes_padrao()` nem na cesta
  (`tests/test_sicro.py::test_sicro_nao_e_fonte_da_cesta_de_compras`);
- tem consulta própria, `/app/precos/sicro`; BDI não incluído.

## Origem oficial

| Campo | Valor |
|---|---|
| Página | https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/sistemas-de-custos/sicro/relatorios |
| Edição | por UF e trimestre (jan, abr, jul, out), às vezes "revisado" — a revisada ganha |
| Caminho | `…/relatorios-sicro/<região>/<uf>/<ano>/<mês>/<mês>-<ano>[-revisado]` |
| Arquivo | um 7-Zip, ex. `pa-07-2026.7z` |
| Conferido | PA jul/2026: 26.174.897 bytes, sha256 `3a545a7d0a71d20dc5c72cb02bd9d921639922b18af2b1ae6b2a71cab2592de5`, 24 relatórios (PDF + XLSX) |

## O que é lido (XLSX sintéticos)

| Relatório | Tipo | Regime | Valor |
|---|---|---|---|
| Composições de Custos | composição (7 dígitos) | sem desoneração | custo unitário |
| Materiais | material (M####) | sem encargos | preço unitário |
| Mão de Obra (e "com desoneração") | mão de obra (P####) | sem / com | custo h ou mês |
| Equipamentos (e "com desoneração") | equipamento (E####, A####) | sem / com | custo horário produtivo e improdutivo |
| Origem de Preços do SICRO | sigla da UF por insumo (PC, PFM, PRE…) com a legenda do próprio relatório | | |

**Composição é sem desoneração** — provado no analítico do mesmo 7-Zip: toda
composição precifica o ajudante (P9801) a R$ 24,8197, o valor sem
desoneração (com seria R$ 23,6691). O DNIT não publica composição com
desoneração; a tela diz isso.

Recusas por linha, com motivo: "-" (sem preço na UF), preço zerado (PRZ),
linha repetida idêntica (equipamentos auxiliares listados de novo sob o
composto), código repetido com valor diferente (sai inteiro), código fora da
forma do tipo, valor ilegível (mais de 4 casas, negativo, texto).

## Medição (PA, julho/2026)

- 9.753 linhas, **9.639 válidas**: 6.615 composições, 1.636 materiais,
  145 + 145 mão de obra, 549 + 549 equipamentos; recusas: 68 sem preço,
  4 zeradas, 42 repetidas idênticas;
- **confronto com os PDFs sintéticos da mesma edição: 10.737 de 10.737
  valores iguais** (custo, preço, mão de obra nos dois regimes, produtivo e
  improdutivo dos equipamentos);
- reimportar o mesmo arquivo = `ja_publicado`.

## Extração do 7-Zip

O Python não lê 7-Zip sem biblioteca nova; o serviço usa o extrator do
sistema (`bsdtar` — o `tar.exe` do Windows 10+ — ou `7z`), sem dependência
nova:

1. lista antes: até 40 entradas, até 400 MB descompactados;
2. extrai só os sintéticos numa pasta vazia (bsdtar sem `-P` recusa caminho
   absoluto e `..`);
3. aceita só arquivo regular com o nome de relatório da UF e competência; os
   XLSX passam por `arquivos.conferir_zip` antes do openpyxl.

A imagem de produção não tem extrator: a importação roda na bancada (Windows)
com `--banco`, como a do BPS, ou num servidor com `libarchive-tools`.

## Banco (0049)

`precos_sicro_versoes` (controle, só servidor; versão = competência + UF +
SHA-256, uma vigente por competência e UF) e `precos_sicro_registros`
(`authenticated` lê só o vigente). Código amarrado ao tipo e regime ao que o
DNIT publica, por `check`. RPC `precos_sicro_buscar` `security invoker`; o
material aparece em qualquer regime pedido.

## Operação (quando autorizado)

1. aplicar a 0049 pelo ritual (`revisar-migracao`);
2. na bancada, com `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` no ambiente:
   `python -m src.precos.sicro_servico importar --uf PA --competencia 2026-07 --banco`;
3. `python -m src.precos.sicro_servico conferir --uf PA --competencia 2026-07`
   (sai 1 se um valor divergir do PDF);
4. ligar `flag_referencia_custos_sicro = on`; rollback: `off`.

## Provas

- `tests/test_sicro.py` — 52, sobre amostra real (sete XLSX recortados e um
  7-Zip); 19/19 mutações mortas;
- `tests/test_migracao_0049.py` — RLS, grants, checks e a conferência que
  morde (PostgreSQL do CI);
- `apps/api/tests/test_precos_referencias_sicro.py` — rota, flag, filtros;
- `apps/web/e2e/sicro.spec.ts` — conta `a1_sicro`, cinco referências reais.
