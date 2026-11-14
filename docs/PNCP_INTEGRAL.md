# PNCP integral — importação nacional contínua

Serviço que alimenta o índice de preços do PNCP (0042) com todo o país,
por uma fila durável (0045), com o ano da cotação primeiro e o histórico
atrás. Código: `src/precos/pncp_integral.py`. Operação no VPS:
`implantacao/importador_pncp.sh`.

## Estados — não confunda

| Estado | O que significa | Como se prova |
|---|---|---|
| implementado | código e migração no `main` | PR mesclado |
| testado | provas verdes (sem rede e PostgreSQL no CI) | `tests/test_pncp_integral.py`, `tests/test_migracao_0045.py` |
| implantado | 0045 aplicada e `importador-pncp` rodando no SHA de produção | `importador_pncp.sh status` |
| carga em andamento | partições lidas crescendo entre duas medições | `status` duas vezes, com intervalo |
| ano da cotação concluído | todas as partições `recente` lidas **e** reconciliadas | `status` + `reconciliar` |
| histórico concluído | idem para `historico`, com falhas e quarentena listadas | idem |

Fila vazia não é "tudo importado"; contagem bruta não é cobertura.

## Duas fontes, uma conferência

| Fonte | Cobre | Custo medido (13/11/2026) |
|---|---|---|
| `comprasgov_lote` — API de Dados Abertos do Compras.gov | quem conduz a licitação no Compras.gov (27 UFs) | ~11 mil resultados/dia útil; ~25 páginas + 2 chamadas por contratação; dia útil ≈ 25 min a 2 req/s; o ano ≈ 4 dias |
| `pncp_descoberta` → `pncp_contratacao` — API do PNCP | todos os demais publicadores (BLL, Licitanet, Portal de Compras Públicas…) | ~1 chamada por resultado; out/2026: ~118 mil contratações publicadas no PNCP |

A base em lote **não** tem Careaçu/MG, Dom Pedro/MA nem Santa Helena de
Goiás/GO — vêm pelo PNCP item a item. Validado na fonte real: Careaçu,
39 itens, 38 gravados, item 2 a R$ 12.300,00, 40 chamadas.

As duas passam pela mesma `pncp_indice.linha_do_resultado` (item
homologado, sem julgamento por desconto, pessoa física sem nome nem
documento, total coerente) e pela mesma chave `controle#item#sequencial`:
a mesma compra vista pelos dois caminhos conta uma vez.

## ETA honesto

Medido: ~1 chamada útil por resultado no PNCP. Fora a fatia do
Compras.gov, um mês de publicações custa da ordem de 0,75 a 1 milhão de
chamadas. A 1 req/s, o ano da cotação leva ~4 meses; a 2 req/s, ~2 meses.
O Compras.gov em lote fecha o ano em ~4 dias. O histórico mais antigo
vem depois (prioridade 10.000+). Velocidade é limitada pela fonte, não
por nós: subir o orçamento sem medir 429 só piora.

## Fila (0045)

- Partição: um dia (`comprasgov_lote`), uma modalidade num dia
  (`pncp_descoberta`, ex.: `6:2026-10-29`), uma contratação
  (`pncp_contratacao`, cabeçalho no checkpoint).
- Reserva com `FOR UPDATE SKIP LOCKED`, lease de 10 min com heartbeat, só
  o token confirma; lease vencido volta à fila com outro token.
- `concluida` é final. O que precisa ser relido volta `pendente` com data
  futura e `checkpoint.lido_em`. Releitura SOBREPOSTA: os últimos 3 dias
  todo dia (mesmo com resultado), semanal no mês, 60 dias no ano; o
  histórico não volta; contratação só volta com item sem homologação.
- O dia lido com falta (menos únicas que o declarado depois de 3
  passadas) **grava o que veio** e vira `parcial` com `faltantes` nos
  totais — nunca `concluida`, nunca descartado. Medido em 14/11/2026: a
  regra antiga jogava fora 9.599 de 9.695 e nada entrava.
- Rede caindo no meio grava o lido e guarda a retomada no checkpoint
  (`compra_feita_ate`, `item_feito_ate`); a tentativa seguinte continua
  dali. O cliente tenta 3 vezes o 429/5xx respeitando `Retry-After`.
- Gravação recusada pelo banco vira erro da tarefa (`gravação: ...`) e
  `falhas_gravacao` nos totais; exceção inesperada volta a tarefa com
  `inesperado: ...` — a pista não morre calada.

## Pistas e orçamento

- **Duas pistas** no mesmo processo (threads), um limitador por host: a
  do Compras.gov e a do PNCP. O 429 do PNCP dorme só a pista do PNCP.
  Um escritor: as duas usam o mesmo `dono` e só o líder reserva.
- **Faixas intercaladas**: prioridade = posição na faixa × passo
  (`recente` 1, `atualizacao` 2, `historico` 4). A cada 7 partições, 4
  do ano da cotação, 2 de publicação fresca (< 30 dias) e 1 do
  histórico. `urgente` (o plano do dia) passa na frente e é pequeno.
- **Plano do dia** (`run --campanha`): o serviço cria sozinho os dois
  últimos dias do lote, a publicação de ontem e as ATUALIZAÇÕES de ontem
  (`/contratacoes/atualizacao`, partição `u:<mod>:<dia>`), que reagendam
  a contratação já lida — correção e resultado tardio entram assim.

## Medição

Cada tarefa grava em `totais`: `recebidos`, `declarados`, `resultados`
(únicos), `faltantes`, `recusadas` por motivo, `inseridas` (linha nova),
`atualizadas` (mesma chave, conteúdo novo), `inalteradas`, `invalidadas`,
`falhas_gravacao` e `tempos` por fase (`espera_s` do limitador,
`requisicao_s`, `transformacao_s`, `validacao_s`, `gravacao_s`). O
gargalo se lê aí. `ritmo --minutos N` soma a janela por fonte, com
inseridas por minuto; o stdout do contêiner tem uma linha JSON por
tarefa. Novos únicos de verdade: a contagem de `precos_pncp_resultados`
entre duas medições (chave primária).

## Operação (no VPS, `implantacao/importador_pncp.sh`)

```bash
sudo ./importador_pncp.sh subir                       # para o indexador antigo, sobe o novo
sudo ./importador_pncp.sh plano nacional-2026-11 2023-01-01
sudo ./importador_pncp.sh status nacional-2026-11     # JSON por fonte/faixa/estado
sudo ./importador_pncp.sh ritmo 30                    # a janela: inseridas/min, recusas, gargalo
sudo ./importador_pncp.sh logs 50                     # uma linha JSON por tarefa
sudo ./importador_pncp.sh pausar "manutenção do banco"
sudo ./importador_pncp.sh retomar
sudo ./importador_pncp.sh reconciliar nacional-2026-11 2026-10-01 2026-10-31
sudo ./importador_pncp.sh reabrir-falhas nacional-2026-11
sudo ./importador_pncp.sh voltar                      # pausa e religa o indexador antigo
```

Proteções: pausar o backfill se o disco livre do banco cair abaixo de
20% ou a busca dos usuários piorar; o cursor não se perde. Infraestrutura
paga a mais é decisão do dono, com medição.

## O que ainda não está aqui

- descrição de item com nome de pessoa (ex.: inscrição em treinamento)
  segue para a busca, como no coletor antigo — sanitizar é o próximo passo;
- atas, contratos/empenhos e documentos: coletores complementares;
- a atualização é lida só para ONTEM (plano do dia); atualizações de
  dias anteriores à subida do serviço chegam pela releitura por idade.
