# Banco de Preços — progresso por gate

Branch `feature/govconnect-banco-precos-ia`, a partir de `0167c5f`.
Sem merge, sem deploy, sem migração, sem flag de produção alterada.

| Gate | Commit | Entregue | Provas |
|---|---|---|---|
| 0 | `b2d759d` | inventário, baseline 10/210 itens contra API pública | `docs/pricebank/baseline-*.json` |
| 1 | `b2d759d` | `busca.coletar` (serviço único), código interno ≠ CATMAT, tela Banco de Preços, link oficial por referência | `test_pricebank_nucleo.py`, `test_pricebank_ui.py` |
| 2 | `b2d759d`, `85c00b4` | média padrão nas novas, cesta recalculada pela seleção gravada, salvar consulta como pesquisa (idempotente), relatório PDF/XLSX, aplicação ao processo | `test_pricebank_ponta_a_ponta.py` |
| 3 | `85c00b4` | fila sem travamento (210 itens em 42 rodadas), falha técnica 1×/execução, retomada sem repetir busca nem IA, N/3 na tabela | `test_pricebank_lote_210.py` |
| 4 | `f73879d` | PNCP como fonte de preço pela contratação conhecida, fusão entre portais, fixture real | `test_pricebank_pncp.py` + teste live |
| 5 | `f6a0893` | cotação direta (art. 23, § 1º, IV) com comprovante por SHA-256 | `test_pricebank_cotacao.py` |
| 6 | `d91155d` + este | análise crítica da média, exclusão humana de discrepantes, revisão paginada, correções vistas no navegador, XLSX sem fórmula | navegador + AppTest + mutação |
| 7 | este | suíte completa, documentação, relatório final | `docs/pricebank-relatorio-final.md` |

## Decisões que valem registro

* **Média provisória em vez de troca calada pela mediana.** O pacote manda
  média de referências "elegíveis e APROVADAS" e proíbe excluir
  discrepante automaticamente. A regra antiga trocava para a mediana sem
  avisar; a nova mantém a média, marca pendência e exige decisão humana
  para concluir. Pesquisas antigas continuam na regra antiga
  (`versao_regras`).
* **CV > 0,25 como pendência.** É o mesmo corte que a regra antiga usava.
  Resultado medido: 87 de 92 itens com 3+ ficam provisórios. Se for ruído
  demais na operação, o ajuste é de política (perfil), não de código.
* **PNCP pela contratação conhecida.** A API continua sem busca por
  descrição; varrer contratações seria caro e frágil. O servidor informa
  a contratação similar e o pipeline comum faz o resto.
* **Comprovante por hash, não por arquivo.** O projeto não tem Storage
  configurado; guardar o PDF exigiria bucket + política + migração.

## Bloqueios e o que não foi feito

| Item | Situação | Motivo |
|---|---|---|
| Índice persistente multi-fonte com job incremental | NÃO IMPLEMENTADO | exige migração nova; a regra é não aplicar em produção sem autorização, e o CI não tem Postgres configurado nesta máquina (`GOVDOCS_ENSAIO_PG_DSN` ausente) |
| BPS (Banco de Preços em Saúde) | NÃO IMPLEMENTADO | sem API REST pública verificada nesta sessão; não foi sondado |
| Link seguro e expirável para o fornecedor | NÃO IMPLEMENTADO | exige área pública + tabela de convites (migração) + mensageria; a cotação manual não depende disso |
| Triagem Jev real | IMPLEMENTADO SEM TESTE LIVE | regra do pacote: sem IA paga; provado com dublê |
| Teste de RLS das tabelas de preço | NÃO EXECUTADO AQUI | 40 provas de `test_precos_fase3_rls.py` pulam sem `GOVDOCS_ENSAIO_PG_DSN`; rodam no CI se configurado |
| Rodada em homologação com banco real | NÃO EXECUTADO | a homologação do Streamlit Cloud usa o banco de PRODUÇÃO; o teste no navegador usou banco em memória |

## Próxima ação

Push da branch e PR para revisão; o merge e o deploy dependem de
autorização expressa.
