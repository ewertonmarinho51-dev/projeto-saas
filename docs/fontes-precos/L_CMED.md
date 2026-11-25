# L — CMED: teto de medicamentos (PF e PMVG)

Estado em 24/11/2026: **implementado e testado** no branch `claude/cmed-fonte`.
Migração `0050_precos_cmed_teto.sql` **não aplicada**; flag
`referencia_teto_cmed` **desligada**; nada importado em produção.

## O que é, e o que não é

A CMED (Anvisa) fixa o **preço máximo** de cada apresentação de medicamento:
o Preço Fábrica (PF) e o Preço Máximo de Venda ao Governo (PMVG), por
alíquota de ICMS. É **teto regulatório**, não preço praticado:

- não entra em `fontes_padrao()` nem na cesta
  (`tests/test_cmed.py::test_cmed_nao_e_fonte_da_cesta_de_compras`) — o
  preço praticado de medicamento continua vindo do BPS;
- consulta própria em `/app/precos/cmed`, separada dos preços de compra.

## Origem oficial

| Campo | Valor |
|---|---|
| Página | https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos |
| Arquivos | `arquivos/lista_pmvg_AAAAMMDD_NNNNNNNNN.xlsx/@@download/file` (e a `lista_pmc_…` da mesma publicação) |
| Conferida | publicação de 09/11/2026 17h30: `lista_pmvg_20261109_111901662.xlsx`, 13.617.885 bytes, sha256 `5a18ae40416fd00cb98299cfcf3fb1a174a23b12ac763a01c442e987b9478dae` |
| Abas | "Cabeçalho" (data e regras) e "Lista PMVG" (74 colunas) |

## A regra do teto (do cabeçalho da própria lista)

> Para os medicamentos do Anexo I da Resolução CTE-CMED (coluna **CAP =
> Sim**), o PMVG resulta da aplicação do CAP ao PF. Para os demais, o limite
> nas vendas à administração pública corresponde ao **PF** aplicável à
> respectiva alíquota.

A coluna PMVG vem preenchida **para todas** as apresentações (PF × 0,802…,
medido); mostrar o PMVG como teto de quem está fora do CAP seria errado. Por
isso `TetoCmed.teto_governo` aplica a regra: CAP → PMVG; sem CAP → PF. A tela
mostra o teto, a base dele e as duas colunas ao lado.

Isenção: o asterisco ("R$ 54,23*") marca apresentação isenta (CONFAZ 87 ou
ICMS 0% = Sim) — medido nas 26.694 linhas, aparece exatamente nelas. Para
essas, a tela mostra também o teto da coluna 0%. A alíquota do estado de
destino é escolha do comprador (nota (i) da CMED); a tela abre em 18% e pede
a conferência.

## Medição (09/11/2026, arquivo inteiro)

- 26.694 apresentações, **26.694 válidas**, GGREM único (15 dígitos);
- 6.549 com CAP; 2.979 CONFAZ 87; 1.184 ICMS 0%; 3.989 de uso hospitalar;
- **PF confrontado com a lista PMC da mesma publicação: 694.044 de 694.044
  valores iguais** (26 colunas × 26.694 apresentações) — a única diferença
  entre as listas é a marca `*`, que a PMC não põe nos itens só do CONFAZ 87.

## Banco (0050)

`precos_cmed_versoes` (controle, só servidor; uma lista vigente no total) e
`precos_cmed_registros` (`authenticated` lê só a vigente). PF e PMVG em
`jsonb` com as 26 chaves exigidas por `check`. RPC `precos_cmed_buscar`
por GGREM, registro, qualquer EAN ou termos (substância, produto,
apresentação, laboratório).

**Retenção**: cada lista (~26,7 mil linhas) fica gravada e ninguém apaga;
importar quando a CMED publicar lista nova, não por agenda cega.

## Operação (quando autorizado)

1. aplicar a 0050 pelo ritual (`revisar-migracao`);
2. com `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` no ambiente:
   `python -m src.precos.cmed_servico importar --banco` (descobre a lista
   mais recente na página oficial);
3. `python -m src.precos.cmed_servico conferir` (sai 1 se um PF divergir da
   lista PMC);
4. ligar `flag_referencia_teto_cmed = on`; rollback: `off`.

## Provas

- `tests/test_cmed.py` — 49, sobre amostra real de onze apresentações (listas
  PMVG e PMC recortadas); 18/18 mutações mortas;
- `tests/test_migracao_0050.py` — RLS, grants, checks e a conferência que
  morde (PostgreSQL do CI);
- `apps/api/tests/test_precos_referencias_cmed.py` — rota, flag, regra do teto;
- `apps/web/e2e/cmed.spec.ts` — conta `a1_cmed`, a amostra real na pilha.
