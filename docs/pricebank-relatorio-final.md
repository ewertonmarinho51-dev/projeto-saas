# Relatório de entrega — Banco de Preços GovConnect + Pesquisa Automática

## Cabeçalho

- **Repositório:** ewertonmarinho51-dev/projeto-saas
- **Branch:** `feature/govconnect-banco-precos-ia`
- **HEAD inicial:** `0167c5f` (main, v1.7.2) · **HEAD final:** ver `git log -1` da branch
- **Data:** 15/10/2026 · **Ambiente:** local (Windows, Python 3.11), APIs públicas
  reais em leitura, banco **dublado em memória**; produção não tocada
- **Flags aplicadas:** nenhuma · **Migrations novas:** nenhuma ·
  **Dependências novas:** nenhuma
- **Limitações descobertas:**
  - a homologação do Streamlit Cloud usa o banco de produção, então não serve para teste isolado;
  - sem `GOVDOCS_ENSAIO_PG_DSN`, as provas de RLS pulam nesta máquina;
  - o projeto não tem Storage nem mensageria configurados;
  - o PNCP não tem busca de item por descrição.

## Resumo executivo

Objetivo **entregue em homologação parcial**. O Banco de Preços manual e a
Pesquisa Automática usam agora o MESMO núcleo:
- coleta: `busca.coletar`;
- cesta: `cesta.py`;
- cálculo: `estatistica.estimar`;
- entidade, relatório e aplicação ao processo: os mesmos.

Funcionam de ponta a ponta, provados no navegador e em AppTest:
- consulta manual com link oficial por preço;
- cesta N/3 com média ao vivo;
- salvar como pesquisa e revisão;
- exclusão justificada e conclusão;
- relatório PDF/XLSX e aplicação ao processo.

Também entram:
- contratação similar do PNCP como fonte de preço (verificada ao vivo);
- cotação direta com fornecedor (art. 23, § 1º, IV);
- pesquisa automática de 210 itens sem travar, com retomada.

Medido nos 210 itens reais:
- 3 → 92 itens com 3+ preços comparáveis;
- só 5 sem pendência: o preço público real é disperso;
- a média passou a ser PROVISÓRIA até a decisão humana. Sem isso, havia médias como R$ 30.002,33 para uma divisória de R$ 14,90.

Ficaram de fora (ver Gate 4/5):
- índice persistente com job incremental;
- BPS;
- link seguro ao fornecedor.

## Quadro funcional

| Área | Estado anterior | Entrega realizada | Evidência | Status |
|---|---|---|---|---|
| Catálogo pesquisável | busca só dentro do lote automático | tela Banco de Preços: descrição/CATMAT/UF/janela, encontradas × únicas × comparáveis × N/3, link oficial | `test_pricebank_ui.py`; navegador (almofada de carimbo, 285 encontradas) | IMPLEMENTADO E TESTADO (live) |
| Conectores de fonte | Compras.gov preço; PNCP só evidência | `codigo_confirmado`; `url_de_verificacao`; `PNCPContratacao` com resultado homologado | `test_pricebank_pncp.py` (fixture real); teste live 15/10 14:23 UTC | IMPLEMENTADO E TESTADO (live) |
| Pesquisa manual | inexistente | consulta → cesta → salvar como pesquisa (idempotente) | `test_pricebank_ui.py`, `test_pricebank_ponta_a_ponta.py`, navegador | IMPLEMENTADO E TESTADO |
| Pesquisa automática IA | fila travava com erro permanente; erro nunca re-tentado | prioridade interrompido→pendente→erro; erro 1×/execução; retomada sem repetir busca/IA | `test_pricebank_lote_210.py` (210 sintéticos, 42 rodadas) | IMPLEMENTADO E TESTADO (mock de IA e fonte) |
| Cesta e método | revisão não refazia preço; CV trocava método calado | média padrão (novas); recálculo pela seleção gravada; pendência de análise crítica; exclusão humana em lote | `test_pricebank_nucleo.py`, navegador (R$ 4.955,86 → R$ 4,72) | IMPLEMENTADO E TESTADO |
| Cotação direta | inexistente | registro com CNPJ, solicitação formal, justificativa, ≤ 6 meses, SHA-256 do comprovante | `test_pricebank_cotacao.py` | IMPLEMENTADO E TESTADO (sintético); link ao fornecedor NÃO IMPLEMENTADO |
| Relatórios/proveniência | sem cotação; XLSX aceitava fórmula | seção de cotações; neutralização de fórmula (prova com mutação) | `test_pricebank_cotacao.py`; PDF gerado no navegador | IMPLEMENTADO E TESTADO |
| Aplicação ao processo | existente | inalterada; consulta manual chega por ela | `test_pricebank_ponta_a_ponta.py` | TESTADO |
| Tenant, segurança e custos | RLS 0021 | nenhuma mudança de schema; PNCP monta URL só de dígitos (sem SSRF); 0 chamadas de IA | testes de entrada hostil; RLS não executado aqui | PARCIAL |

## Benchmark

| Indicador | Antes | Depois | Medida de teste |
|---|---:|---:|---|
| Itens com 3 preços comparáveis | 3/210 (1,4%) | 92/210 (43,8%) — 5 sem pendência | `benchmark_precos.py`, 210 itens reais, API pública |
| P50/P95 por item | 2,20 s / 7,77 s | 1,98 s / 6,98 s | idem; ver nota de rede em `pricebank-baseline.md` |
| Tempo lote 10/50/210 | 26,0 / 124,6 / 639,5 s | 30,1 / 146,0 / 568,9 s | soma dos tempos por item na mesma rodada |
| Duplicados cross-source | não tratado | 1 fusão Compras.gov×PNCP + 1 cota em 524 brutas | teste live 15/10 14:23 UTC |
| Falso positivo de comparabilidade | NÃO MEDIDO | NÃO MEDIDO | falta dataset rotulado por humano |
| Chamadas/custo de IA por item | 0 | 0 (dublê de triagem: 1 por item com referência, 0 na retomada) | `test_pricebank_lote_210.py` |
| Tempo até exportação | NÃO MEDIDO | ≈ 10 s consulta + ≤ 8,1 s revisão + ≤ 10 s PDF | navegador, esperas fixas (limite superior) |
| Revisão de cesta de 283 referências | > 80 s sem terminar | ≤ 8,1 s (25 por página) | navegador |

## Registro de fonte

| Fonte | Endpoint verificado | Capability | Último teste | Resultado | Bloqueio |
|---|---|---|---|---|---|
| Compras.gov preços praticados | `modulo-pesquisa-preco/1_consultarMaterial` | PREÇO | 15/10 14:50 UTC (210 itens) | 604 chamadas, 0 erros | — |
| Compras.gov catálogo | `modulo-material/3_consultarPdmMaterial`, `4_consultarItemMaterial` | apoio | 15/10 | ok | — |
| PNCP consulta | `api/consulta/v1/orgaos/{cnpj}/compras/{ano}/{seq}` | evidência | 15/10 14:19 UTC | 200 | `/api/pncp/v1/...` sem barra final responde 301 |
| PNCP itens/resultados | `api/pncp/v1/orgaos/.../itens`, `.../itens/{n}/resultados` | PREÇO (contratação conhecida) | 15/10 14:23 UTC | 200, 0,2 s; 7/7 totais coerentes | sem busca por descrição |
| BPS | — | — | não sondado | — | NÃO IMPLEMENTADO |

## Mudanças e qualidade

- **Criados:**
  - `src/precos/busca.py`, `cesta.py`, `cotacao.py`;
  - `scripts/benchmark_precos.py`;
  - 6 arquivos `tests/test_pricebank_*.py`;
  - `tests/fixtures/pncp_resultados_2026-10-15.json` (resposta real, com URL e horário);
  - `docs/pricebank-*.md` e `docs/pricebank/*.json`.
- **Modificados:** `src/precos/{catalogo,compras_gov,estatistica,execucao,fontes,modelo,pncp,relatorio,repositorio}.py`, `src/ui/precos_ui.py` e `tests/test_precos_fase4.py` (ordem da fila, com explicação).
- **Removidos:** a coleta duplicada em `execucao.pesquisar_item` e o mapa de rótulos que nunca casava.
- **Schema/RLS:** nenhuma alteração.
- **Testes:**
  - regressão de preços: `pytest -k "preco or precos or … or cotacao"` → 633 passed, 66 skipped, exit 0 (antes da última correção de XLSX);
  - suíte completa: ver a seção seguinte.
- **Regra normativa:** média aritmética padrão nas pesquisas novas, com pendência de análise crítica (IN 65, art. 6º, § 3º, onde aplicável); pesquisas antigas mantêm a regra do CV.
- **Bugs conhecidos / pendências:**
  - **P1:** 87/92 itens ficam provisórios pelo CV > 0,25. Confirmar com a área demandante se o corte vale para todos os perfis.
  - **P1:** marcador para quadro (nº 116) sai R$ 39,54 sem pendência contra R$ 5,22 da planilha; provável caixa × unidade.
  - **P2:** índice persistente.
  - **P2:** BPS.
  - **P2:** link ao fornecedor.
  - **P2:** rodar as provas de RLS com Postgres de ensaio.

## Suíte completa

- **Comando:** `PYTHONUTF8=1 python -X utf8 -m pytest -q -p no:cacheprovider --basetemp <tmp>`, sem LibreOffice no PATH (paridade com o CI).
- **Resultado:** 2732 passed, 344 skipped em 271,97 s, **exit 0**. Rodado em 15/10/2026 sobre o código de `d91155d` mais a correção de XLSX e os docs deste commit.
- **Com LibreOffice no PATH:** `test_precos_fase6.py`, que tem as 29 provas de PDF do módulo de preços, deu 29 passed. A suíte inteira com LibreOffice foi interrompida por lentidão: cada dossiê converte vários PDFs de verdade.
- **Skips:** são provas que exigem ambiente ausente aqui, sem relação com o diff:
  - Postgres de ensaio para RLS;
  - projeto de ensaio do Supabase;
  - APIs oficiais de contrato;
  - LibreOffice.

## Gate e decisão

| Gate | Veredito | Evidência |
|---|---|---|
| 0 Diagnóstico + baseline | APROVADO | `pricebank-inventory.md`, `pricebank-baseline.md`, `baseline-*.json` |
| 1 Catálogo consultável | APROVADO | tela + link oficial + fonte indisponível sinalizada; live |
| 2 Cesta e relatório compartilhados | APROVADO | ponta a ponta até PDF/XLSX e processo; navegador |
| 3 Pesquisa automática no mesmo motor | APROVADO (mock) | 210 sintéticos: termina, retoma, não duplica, não inventa |
| 4 Fontes adicionais e índice | NÃO APROVADO (parcial) | PNCP como preço: sim, live. Índice/job incremental e BPS: não |
| 5 Cotações | NÃO APROVADO (parcial) | registro manual com trilha: sim. Link seguro/expirável ao fornecedor: não |
| 6 UX e performance | APROVADO | navegador real, 7 defeitos achados e corrigidos, antes/depois medido |
| 7 Homologação final | BLOQUEADO POR ACESSO (parcial) | suíte local; sem Postgres de ensaio para RLS; sem homologação isolada |

**Veredito: `HOMOLOGAÇÃO PARCIAL`.**

Nenhum merge ou deploy foi feito. Ambos dependem de autorização expressa.
