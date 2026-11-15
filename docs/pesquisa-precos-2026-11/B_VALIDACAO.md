# B — Validação (o que rodou, onde, com que resultado)

Só entra aqui o que foi EXECUTADO. Nada de "deve passar".

## P0 — cesta (PR #217)

| Prova | Onde | Comando | Resultado |
|---|---|---|---|
| Reprodução da corrida + fila nova (7 casos) | local, Node 24 | `node node_modules/vitest/vitest.mjs run tests/fila-da-cesta.test.ts` (em `apps/web`) | 7 passaram |
| Mutação: fila sem ignorar página velha | local | mesmo comando com `revisao < -1` no lugar de `revisao < this.revisaoConfirmada` | 1 falhou ("a fila NOVA reconcilia…") — a prova morde |
| Tipos e lint | local | `tsc --noEmit -p .`; `eslint` nos arquivos tocados | sem erro |
| e2e contra a pilha real (API + GoTrue + PostgREST + Postgres) | CI `web-e2e` | `playwright test` | 1ª execução: 68 passaram, 1 falhou **no login** ("Muitas tentativas" — limite do próprio app), antes da prova da cesta; o cenário passou para a sessão do teste anterior. 2ª execução (run 43648842106): **69 passaram**, incluindo `precos.spec.ts:76` "cesta em um clique…" com os quatro cliques rápidos, recarga e conclusão (9,6 s) |
| CI completo do PR | GitHub Actions | `testes` 5.319 + `api` 651 + `api-rls` 71 + `web` 117 (vitest) | todos verdes; Vercel falha em todo PR (conhecido) |
| Regra de 5 e CV 25% (já existente) | local | `python -m pytest -q tests/test_cotacoes_teto5_cv.py tests/test_cotacoes_ux.py tests/test_ciencia_emissao.py` | 59 passaram |

### O que a prova de unidade cobre

- o modelo antigo (provedor recriado com a página do 1º refresh) **perde** B e faz C tomar 409 — o defeito relatado;
- a fila nova: If-Match 1, 2, 3; respostas 200, 200, 200; página velha ignorada; nada some; `aguardar()` devolve a revisão realmente confirmada (a do "Concluir");
- cliques repetidos na mesma linha valem pelo último, sem gravação a mais;
- outra aba gravou: a página nova é adotada e o clique pendente de outra linha segue;
- outra aba mexeu na mesma referência: o clique pendente é descartado com aviso — nunca sobrescrita calada;
- 422 volta só a linha recusada; nenhuma falha vira sucesso;
- um refresh por esvaziamento da fila.

### O que NÃO foi provado ainda

- homologação em produção com a conta do dono (depende da promoção);
- latência p50/p95 do clique antes/depois (a correção não muda o caminho de rede: mesmo PATCH por clique, mesmo refresh ao esvaziar a fila).

## Relatórios (PR #218)

| Prova | Onde | Resultado |
|---|---|---|
| `tests/test_relatorios_pacote_1114.py` (11) | local + CI | verdes: fontes A/B/C com cesta A/C → só A e C; data ausente sem invenção; 50/30/10/5/3/2 → Top 5 + Demais = 2; até 5 sem Demais; desempate pelo número; total zero; 33,33% ×3 sem forçar 100; PNG válido; seções em cada documento |
| `tests/test_revisao02_relatorio.py` atualizado | local + CI | retiradas e memória no Integral, ausentes no resumido |
| Relatório/emissão/preços (1.147) | local | verdes |
| PDF real com LibreOffice | local | resumido 3 páginas (extrato, fontes usadas); Integral com rosca e tabelas; geometria e paginação (`test_relatorio_cotacao.py`, 42) verdes |
| CI do PR | GitHub Actions | 1ª: falha em `test_pdf_analitico_paisagem…` (premissa de que toda página do meio era da tabela); prova ajustada; 2ª: todos verdes |

## Paginação, filtros e mapa (PR #219)

| Prova | Onde | Resultado |
|---|---|---|
| `apps/api/tests/test_precos_rotas.py` (31, 15 novas) | local (`.venvs/govconect-api`) | verdes |
| `apps/web/tests/triagem-url.test.ts` + design system | local (vitest 122) | verdes |
| e2e filtro/contagem/mapa | CI `web-e2e` | ver PR #219 |

### Não provado

- Benchmark de 1.000 referências em produção (o caso real ainda não tem 1.000 por item); a API pagina no banco (`limit/offset` + `count=exact`), então o custo por página não cresce com o total.
- Validação na tela de produção com a conta do dono: o navegador da sessão não tem login; depende do dono (Chrome).
