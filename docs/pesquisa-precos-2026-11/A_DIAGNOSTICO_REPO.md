# A — Diagnóstico do repositório (pesquisa de preços, pacote de 14/11/2026)

- **SHA inicial:** `31ad0876c020` (`main`, 14/11/2026), o mesmo em produção (`promover_govconect.sh --atual`).
- **Escopo deste documento:** o que foi CONFERIDO no código e em prova. O que não foi auditado está marcado como tal — não é "funciona" nem "não funciona".

## P0 — referência entra na cesta e some

### Causa confirmada

`apps/web/app/app/precos/[id]/itens/[itemId]/page.tsx` montava o provedor da cesta com `key={item.revisao}`. Cada gravação aumenta a revisão; o `router.refresh()` que a fila dispara traz a página nova e o provedor — com a triagem, o filtro e a fila de cliques — **nascia de novo** com o que aquela página dizia.

Com cliques seguidos em referências diferentes:

1. o clique A grava (revisão 1 → 2) e dispara o refresh;
2. o clique B começa a gravar (2 → 3) enquanto o refresh do A está em voo;
3. a página do refresh, lida antes de B, chega com a revisão 2: o provedor é recriado **sem B** — B some da tela;
4. o clique C sai do provedor novo com `If-Match: 2`, mas o servidor já está na 3 → **409**, C volta para fora com aviso;
5. "Concluir item e avançar" espera a fila do provedor NOVO e conclui com a revisão vencida → conflito, item não conclui.

A fila antiga continuava gravando no provedor desmontado: **o servidor ficava certo e a tela, não** — exatamente o relato ("parece entrar e em seguida desaparece; impede a conclusão").

Reprodução determinística: `apps/web/tests/fila-da-cesta.test.ts`, caso "o modelo ANTIGO perde a seleção" (servidor falso com a mesma regra de If-Match da API; as respostas são soltas na ordem exata do navegador).

### Hipóteses do pacote, uma a uma

| # | Hipótese | Resultado | Evidência |
|---|---|---|---|
| 1 | remount pela `key` + `router.refresh` com payload defasado | **confirmada** | acima; prova de unidade |
| 2 | `gravarMarcacao` com sucesso e estado final diferente | rejeitada | `cotacoes.alterar_status_referencia` grava `selected`/`warning`; `naCesta` (web) e `NA_CESTA` (domínio) contam os dois; o recálculo não muda status (`cesta.recalcular_e_gravar`) |
| 3 | cache de Server Component / leitura stale | rejeitada como causa | `lib/api.ts` usa `cache: "no-store"`; o "stale" vinha da ORDEM das respostas, não de cache |
| 4 | fluxo coexistente `acao-cesta.tsx` | rejeitada | o componente não é importado por nenhuma tela (código morto; remoção fica para o PR de limpeza) |
| 5 | item concluído / tenant / RLS tratado como sucesso falso | rejeitada | a rota devolve 404/403/409 distintos (`apps/api/govconect_api/cesta.py`); a fila não confirma sem `ok` |
| 6 | busca automática sobrescreve escolha humana | já protegido | `tests/test_cotacoes_teto5_cv.py::test_cv_reprovado_preserva_a_escolha_de_pessoa`, `::test_mais_de_cinco_escolhidas_a_mao_ficam_como_estao` |

### Correção (PR do P0)

- `apps/web/components/fila-da-cesta.ts`: a fila sem React, viva enquanto o item estiver aberto, que **reconcilia** a página do servidor pela revisão: instantâneo mais velho que a revisão confirmada é ignorado; o mais novo (outra aba) é adotado; clique pendente numa referência que a outra aba mudou é descartado com aviso (conflito explícito, nunca sobrescrita calada).
- `cesta-do-item.tsx` usa a fila por `useSyncExternalStore`; a página põe `key={item.id}`.
- Contrato da API inalterado (PATCH com `If-Match`, 409 em revisão vencida).

## Status por requisito (conferido nesta etapa)

| RF | Status | Evidência |
|---|---|---|
| P0-01 cesta permanece após incluir e recarregar | **corrigido neste PR** | `tests/fila-da-cesta.test.ts`; e2e `precos.spec.ts` "P0: cliques rápidos…" |
| P0-02 retirar sem justificativa, com trilha | já funciona | `cotacoes.alterar_status_referencia` (motivo opcional, evento `referencia_excluida` com ator/de/para) |
| P0-03 If-Match / 409 | já funciona na API; a tela agora não fabrica 409 | `cesta.py::_revisao`; casos de conflito na prova de unidade |
| P0-04 automática até 5, CV > 25% não entra | já funciona | `tests/test_cotacoes_teto5_cv.py` (59 verdes com UX e ciência): 25,00% exatos passam, 25,004% não; teto 5; escolha de pessoa preservada |
| PERF-01 clique sem consulta externa | já funciona | `_mudar_e_recalcular`: só a linha e o item, "nenhuma fonte externa, nenhum Jev" |
| UX-10 paginação server-side 20 (10/20/50) | **não existe** | `apps/api/govconect_api/precos.py`: `LIMITE_REFERENCIAS = 500`, ordem `valor,id`; a triagem filtra no cliente |
| UX-11 filtros server-side, Lista/Mapa | não existe (filtros só por situação, no cliente) | `triagem-item.tsx` |
| UX-01…09, R-01…R-05 | a auditar no PR correspondente | — |

## Riscos

- Item com mais de 500 referências: as excedentes não aparecem na triagem (corte da API). Não afeta a cesta já gravada, mas a seleção manual não as alcança — entra no PR de paginação.
- A semente do e2e ganhou uma pesquisa própria ("Cesta rápida E2E"); as provas que contam pesquisas na lista foram conferidas pelo CI.

## Plano de PRs

1. **P0 cesta** — este.
2. Fluxo: ações, manual/auto, cabeçalho do item, dropzone (auditar antes; só o que falta).
3. API paginada + filtros + mapa por UF.
4. Relatórios: resumido sem memória de cálculo/exclusões/alertas, extrato e fontes consideradas; completo com rosca Top 5 + Demais.
5. Refino, desempenho, limpeza (`acao-cesta.tsx`).
