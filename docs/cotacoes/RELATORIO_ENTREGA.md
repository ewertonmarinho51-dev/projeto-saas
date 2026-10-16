# Relatório de entrega — Cotações unificadas (Banco de Preços + Jev)

## Identificação

- **Branch:** `feature/cotacoes-unificadas-bp-jev` (local, **não publicada**).
- **HEAD inicial:** `0de2939` (main). **Commits:** G0 `59dd093` · G1 `eb9bbab` · G2 `fe9a13b` · G3 `05d416e` · G4 `d878123` · G5 `da161f4` · G6 = commit deste relatório.
- **Ambiente:** Windows 11, Python 3.11.9, Streamlit 1.64.0, local; banco dublê em memória; sem Postgres de ensaio; produção não tocada.
- **Gates:** G0 PASS · G1 PASS · G2 PASS · G3 PASS · G4 PASS (aceite automático bloqueado por desenho) · G5 PASS · G6 PASS com limites (RLS não exercida aqui).
- **Flags novas:** `flag_unified_quotations` = **off** (nasce off na 0029). `flag_jev_price_research` permanece **off**.
- **Veredito:** `APTO À HOMOLOGAÇÃO` — condicionado a: aplicar a 0029 em ambiente de homologação, rodar `tests/test_migracao_0029.py` e as provas de RLS contra PostgreSQL de ensaio, e ligar a flag só lá.

## Evidências de código

| Gate | O que entrou |
|---|---|
| G0 | inventário verificado das 116 linhas; baseline sintético; 13 defeitos P1 reproduzidos em `xfail(strict)` |
| G1 | `cesta.consideradas` (contagem única), exceção formal < 3, método por item, memória preservada, unidade inválida não mistura, importação diagnosticada e idempotente, relatório com trilha/inciso/pendências, hash formato 2 (formato 1 conferível), critério percentual opcional, `formulas.py` |
| G2 | `src/precos/cotacoes.py` (serviço único) e `src/ui/cotacoes_ui.py` (Minhas Cotações → Elaborar Cotação), concorrência com revisão vista por aba, demo sintética |
| G3 | ampliação semântica explícita, filtros de natureza/preço/consideradas, propostas só quando publicadas, diagnósticos distintos |
| G4 | `src/precos/seletor.py`: determinístico primeiro, Jev só no ambíguo, recomendação com abstenção, tetos de consulta e custo; benchmark sintético |
| G5 | registro de emissão (hash decisório + hash do arquivo + pendências, sem IP), conferência, prévia, fornecedores sugeridos, identificador na aplicação |
| G6 | E2E 1/10/50/210, cancelamento/retomada, acesso negado, benchmark antes/depois, otimização de requisições, rollback e matriz de substituição |

- **Serviços reaproveitados:** `busca`, `cesta`, `estatistica`, `perfil`, `matching`, `fontes`, `unidades`, `repositorio`, `relatorio`, `aplicacao`, `cotacao`, `decisoes`, `jev`, `ai_gateway`, `planilha` (leitura de XLSX). Nenhuma segunda tabela, busca, cesta ou cálculo.
- **Telas antigas:** descontinuadas com a flag ligada, **não removidas** (`matriz_substituicao.md`).
- **Migração:** `0029_cotacoes_unificadas.sql.NAO_APLICAR` (aditiva, RLS ligada e forçada, append-only, flag off) + `0029_rollback.sql`. **Não aplicada.**
- **Backlog:** `docs/cotacoes/10_BACKLOG_116_FUNCOES.csv`. P1 (24): 19 implementados/corrigidos, 1 reaproveitado (F120), 2 parciais (F102: três métodos com dados, saneadas sem norma do ente; F123: lote com prévia só no serviço), F100 com motor pronto e aplicação bloqueada por dado (nenhuma fonte publica propostas), F104 bloqueado (sem índices oficiais). P2 (47): 21 implementados, 6 reaproveitados, 9 bloqueados com evidência, 1 excluído com motivo (F042) + F131, 5 fora do escopo, 1 parcial, 1 medição.

## Testes

- **Comando:** `PYTHONUTF8=1 python -m pytest -q -p no:cacheprovider --basetemp <dir curto>`.
- **Suíte completa:** **2833 passed, 345 skipped, 0 failed** (4 min 22 s). Baseline do HEAD inicial: 2732 passed.
- **Provas novas:** 100 (+1 que exige Postgres de ensaio) em `tests/test_cotacoes_g0…g6*.py` e `tests/test_migracao_0029.py`.
- **Cálculo:** 29,00 → 25,85 → 20,45 (desvio amostral 9,86; CV 48,23 %) → excluir 9,66 → **25,85 com 2/3 pendente** (`test_cotacoes_g0_reproducao.py`, `test_cotacoes_g6_e2e.py`). Critério percentual: 9,66 = 42,56 % da média dos outros sem os elevados. Fórmulas J08: 29,99 / 31,56 / 29,00.
- **1/10/50/210 itens:** `test_cotacoes_g6_e2e.py` — todos preservados, códigos intactos, nenhum preço para zero/vizinhos/fonte fora, reexecução sem duplicar, cancelar com 15/50 e retomar só os 35 restantes.
- **Manual e automático no mesmo ID:** `test_cotacoes_g2_servico.py::test_u03_u04_…` e `test_cotacoes_g2_ui.py` (AppTest).
- **Relatório com pendência e hash:** `test_cotacoes_g5_emissao.py` (aviso nominal impede emitir até a ciência; registro com hash do arquivo).
- **Duas sessões:** conflito de versão detectado no Streamlit e "atualizar e reaplicar" (`test_cotacoes_g2_ui.py`).
- **RLS multi-tenant:** NÃO exercida nesta máquina (sem Postgres de ensaio). Políticas da 0029 espelham as da 0021; prova estática + prova de catálogo pronta para o banco de ensaio. O serviço recusa cotação fora do alcance e nunca cai para a credencial de servidor (`test_cotacoes_g6_e2e.py`).
- **IA offline e fallback:** `test_cotacoes_g4_seletor.py` (IA fora, sem flag, teto atingido → revisão humana; cotação segue).

## Métricas comparadas (mesma máquina e fixture; `docs/cotacoes/bench/`)

| Indicador | Antes (fluxo antigo) | Depois (Cotações) | Como medido |
|---|---:|---:|---|
| p50 / p95 por item, 210 itens, sem rede | 2,2 / 4,2 ms | 3,1 / 5,3 ms | `benchmark_cotacoes.py`, dublês |
| 10 itens com 300 ms por chamada de fonte | 3,03 s | 3,18 s | idem, `--latencia-ms 300` |
| Chamadas à fonte por item | 1 | 1 | idem |
| Requisições ao banco por item | 3,9 | **8,2** (era 11,8 antes da otimização do G6) | contador no dublê de PostgREST |
| Itens com 3+ considerados (210) | 157 | 157 | idem; mesmos estados |
| Falso positivo semântico (sintético) | não medido | 0 em 15 casos rotulados por construção | `seletor_benchmark.py` |
| Custo de IA por item / cotação | 0 | 0 (Jev off; teto US$ 1,00/cotação quando ligado) | provas e benchmark |
| Tempo de revisão humana | não medido | não medido | — |

**Leitura honesta:** não há ganho de velocidade a anunciar. O processamento do GovConnect custa milissegundos; a rede domina (p50 real ≈ 2 s/item, `docs/pricebank-baseline.md`). O serviço novo faz ~4 requisições a mais por item que o antigo — reler as referências antes de gravar (o fluxo antigo **sobrescrevia decisões humanas** numa nova busca) e registrar cada busca na trilha (F077). Com Supabase a ~50–100 ms por requisição, isso soma ~0,2–0,4 s por item. Otimização possível depois da homologação: mover a gravação da busca para uma RPC transacional.

## Segurança

- **RLS/RBAC:** repositório continua só com o JWT do usuário; sem sessão, recusa. Tabela nova com RLS ligada e forçada, `anon` sem grant, `service_role` sem DELETE/TRUNCATE, gatilho append-only e emissor carimbado.
- **Segredos e PII:** nenhuma credencial lida; capturas e PDF do dossiê ficaram fora do repositório; o registro de emissão não grava IP. A demo bloqueia qualquer acesso ao banco real.
- **Rollback:** documentado (`rollback.md`), não exercido em ambiente real (nada foi ativado).

## O que NÃO foi entregue, e por quê

| Item | Motivo |
|---|---|
| Aplicar a 0029, ligar flags, merge, deploy | exige autorização expressa |
| RLS exercida em PostgreSQL | sem `GOVDOCS_ENSAIO_PG_DSN` nesta máquina |
| Aceite automático pelo Jev | sem dataset humano rotulado nem meta de falso positivo aprovada |
| Propostas por referência (F094/F100 aplicado) | nenhuma fonte integrada publica propostas; motor pronto e testado |
| Índices de correção (F104/F026/F093) | sem série oficial integrada nem decisão de quais índices |
| Destaque de ARP (F078), filtro por modalidade | fontes não trazem ARP nem gravam modalidade |
| Envio de convite a fornecedor (F154/F155) | sem provedor de envio e sem consentimento |
| Assinatura no relatório de preços (F137) | assinaturas exigem signatário do cadastro de servidores/portarias |
| % de preço máximo (F042), configuração de relatório (F131) | sem regra normativa; evitar variações não auditadas |
| Exceção em lote pela tela | implementada e testada no serviço; a tela registra por item |
| Remoção das telas antigas | só após homologação (procedimento da matriz) |

## Demonstração reproduzível

```bash
.venv311/Scripts/python.exe -X utf8 -m streamlit run scripts/demo_cotacoes.py --server.port 8765
```

Banco em memória com 10 itens fictícios, fontes sintéticas (uma com preços, outra simulando indisponibilidade), item fictício `PARAFUSO TITANIO XQ9Z` com só vizinhos. Conferido no navegador em 16/10/2026: Minhas Cotações → Abrir → **Cotação automática** em lote → 9/10 itens com 3+ considerados, o item fictício em 0/3, PNCP mostrado como INDISPONÍVEL, chips de inciso e de sugestão da regra; cesta com preço, N/3, diagnóstico e pendência de análise crítica.
