# C09 — aceite funcional do owner de parecer

Data: 18/10/2026  
Escopo: owner Python, aplicador canônico G4 e recibo transacional simulado  
Estado: **PASS LOCAL DO OWNER; navegador/WASM e SQL real ainda pendentes**

Este ensaio consome o cenário funcional exigido para C09 sem alterar o
manifesto de sementes do corpus. O manifesto continua `NOT_TESTED` porque sua
geração offline não executa produto. A evidência de execução pertence ao teste
`test_c09_acceptance_routes_objective_ambiguous_and_conflicting_findings`.

| Campo | Evidência |
|---|---|
| ID | C09-OWNER-01 |
| Dados | parecer sintético normalizado com uma recomendação objetiva, uma ambígua e uma incompatível com o texto editável; três heads nativas sintéticas |
| Ambiente | Windows local; Python isolado; sem rede, LLM ou dado real; engine nativo e RPC substituídos pelos adapters determinísticos já usados nos contratos do owner |
| Ações | carregar parecer pela RLS simulada; classificar o conjunto; preparar somente a recomendação objetiva; aplicar pelo mecanismo G4; gerar diff; revalidar; confirmar checkpoint exato; derivar atendimento da trilha imutável |
| Esperado | somente o alvo objetivo entra no plano; demais itens ficam pendentes; os outros documentos permanecem idênticos; commit exige os bytes confirmados; relatório não transforma aplicação em aceite jurídico |
| Observado | um bloco de `memo_a` alterado; zero adições/remoções; `memo_b` e `memo_c` sem qualquer diferença; item objetivo `APLICADO_PENDENTE_REVISAO`; itens ambíguo e incompatível `PENDENTE`; um único RPC de lote |
| Resultado | PASS LOCAL DO OWNER |
| Regressão | `tests/test_documentos_editor_patches.py`: 42 passed |

O teste também prova que a evidência literal e a âncora vêm do snapshot do
backend. Texto jurídico não escolhe livremente o caminho. A recomendação
ambígua não chega ao aplicador; a tentativa de remover assinatura que não
pertence ao texto editável não recebe path nativo.

O resultado ainda não cobre a Session WASM real, Undo posterior no navegador,
PostgreSQL/RLS real ou JWT GoTrue. Esses itens continuam necessários antes de
promover C09 a aceite end-to-end ou encerrar G5/G7.
