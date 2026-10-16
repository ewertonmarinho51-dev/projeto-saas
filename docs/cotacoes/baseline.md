# Cotações — baseline do G0 (16/10/2026)

## Ambiente

| Campo | Valor |
|---|---|
| Branch | `feature/cotacoes-unificadas-bp-jev`, criada de `origin/main` |
| HEAD inicial | `0de2939` (merge do PR #50, Banco de Preços G0–G7) |
| Python / Streamlit / openpyxl | 3.11.9 / 1.64.0 / 3.1.5 (`.venv311`) |
| Máquina | Windows 11, local; sem Postgres de ensaio (`GOVDOCS_ENSAIO_PG_DSN` ausente) |
| Produção | não tocada; nenhuma migration aplicada; nenhuma chamada de IA |

## Suíte existente

Comando (paridade com o CI, que roda em Linux):

```bash
PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider --basetemp <dir curto fora do repo>
```

Resultado no HEAD inicial: **2732 passed, 344 skipped, 0 failed** (4 min).

Sem `PYTHONUTF8=1` a coleta quebra no Windows (`cp1252` lendo
`scripts/ensaio_seguranca.py`). Sem `--basetemp`, 55 provas que usam
`tmp_path` dão erro de permissão no `%TEMP%` desta máquina. Os dois são
do ambiente, não do código: as 55 passam com `--basetemp`.

Os 344 skips exigem ambiente ausente aqui (Postgres de ensaio para RLS,
projeto Supabase de ensaio, APIs oficiais ao vivo, LibreOffice).

## UX atual (o que existe no HEAD)

Uma entrada de menu, **Pesquisa de Preços** (flag `price_research`), com
sete telas trocadas por `st.session_state` em `src/ui/precos_ui.py`:

| Tela | Função | Observação |
|---|---|---|
| Minhas pesquisas | `_render_lista` | recortes por estado; nome, situação, processo, valor |
| Banco de Preços | `_render_banco` | consulta avulsa: resultado só na sessão até "Salvar como pesquisa", que cria **uma pesquisa nova por consulta** |
| Nova pesquisa | `_render_nova` | identidade antes dos itens |
| Itens | `_render_itens` | importação (processo/XLSX), tabela, editor |
| Execução | `_render_execucao` | lote automático reentrante |
| Revisão do item | `_render_revisao` | cesta, motivos, cotação direta, concluir |
| Resumo | `_render_resumo` | valor global, relatórios, aplicação ao processo |

O problema é de fragmentação: a pesquisa manual de um item de uma
pesquisa existente não existe (a consulta avulsa sempre cria outra
pesquisa), e o automático só roda em lote, em outra tela.

## Serviços reaproveitáveis (confirmados no HEAD)

`busca.coletar` (coleta única), `cesta.recalcular`/`recalcular_e_gravar`
(cesta pela seleção gravada), `estatistica.estimar` (Decimal, média
padrão versionada), `execucao` (lotes com checkpoint),
`repositorio` (JWT do usuário, RLS, idempotência), `relatorio`
(completo/resumido/XLSX), `aplicacao` (diff e proveniência),
`cotacao` (cotação direta), `decisoes`/`jev`/`ai_gateway` (triagem
tipada, cache, reserva, flag `jev_price_research`).

Consumidores externos do pacote: `app.py` e `src/ui/components.py`
(navegação), `src/fatos.py` e `src/govbot_alertas.py`
(`aplicacao.CHAVE_PROVENIENCIA`), `src/ai_gateway.py` (decisões).

## Benchmark sintético (antes)

`scripts/benchmark_cotacoes.py --modo legado` — Pesquisa Automática
atual (`execucao.executar_lote`, um item por lote), fonte e banco
dublês, **rede real não medida**. Arquivo: `bench/antes-legado.json`.

| Itens | Total (s) | p50/item (ms) | p95/item (ms) | Chamadas à fonte/item | Requisições ao banco/item | 3+ considerados | Incompletos | Erro técnico |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0,012 | 6,6 | 6,6 | 1 | 4,00 | 1 | 0 | 0 |
| 10 | 0,009 | 0,8 | 1,1 | 1 | 4,00 | 10 | 0 | 0 |
| 50 | 0,049 | 1,0 | 1,4 | 1 | 3,88 | 39 | 9 | 2 |
| 210 | 0,521 | 2,2 | 4,2 | 1 | 3,87 | 157 | 45 | 8 |

Chamadas de IA: 0 em todas as rodadas. A fixture distribui casos
difíceis em itens fixos: fonte fora do ar (múltiplos de 25), zero
resultado (17), só vizinhos não comparáveis (13), dois preços (11),
caixa sem fator contra unidade (7). Os 3 itens "vizinhos" entre os 50
primeiros terminaram com **zero** elegíveis — o motor determinístico já
não infla cobertura com produto aparentado.

O benchmark com fontes públicas reais continua em
`docs/pricebank-baseline.md` (210 itens: p50 1,98 s, p95 6,98 s por
item, rede doméstica).

## Defeitos P1 reproduzidos

`tests/test_cotacoes_g0_reproducao.py`: 5 provas de regressão
aritmética verdes (29,00 → 25,85 → 20,45; desvio 9,86; CV 48,23 %;
exclusão de 9,66 → 25,85 com 2/3) e **13 provas vermelhas**
(`xfail(strict=True)`), uma por achado do dossiê, cada uma falhando pelo
motivo descrito (conferido com `--runxfail`):

1. relatório completo conta a `warning` como desconsiderada;
2. quadro resumido omite a `warning` dos preços em destaque;
3. GovBot diz "abaixo do mínimo" com a `warning` na cesta;
4. concluir item **substitui** a memória de cálculo pela justificativa;
5. não existe caminho para concluir item com menos de três;
6. metodologia do relatório descreve a regra antiga (mediana por CV);
7. item sem unidade válida mistura caixa e unidade;
8. identificador da versão ignora quantidade, total, unidade e justificativa;
9. `distancia_da_mediana_pct` não é gravado;
10. não há critério percentual (n = 3 não é analisado);
11. relatório sem trilha de coleta nem enquadramento por referência;
12. importação descarta erros em silêncio;
13. não há fórmula por referência sobre propostas.

## Limites declarados

- Sem Postgres de ensaio: RLS das tabelas novas fica provado só por
  leitura das políticas e pelas provas existentes da 0021 quando o
  ambiente as rodar.
- Sem rede no benchmark sintético; sem IA paga em nenhuma prova.
