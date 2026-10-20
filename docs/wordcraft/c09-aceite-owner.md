# C09 — aceite funcional do owner de parecer

Data: 19/10/2026

Escopo: owner Python, PostgREST/JWT/RLS/SQL local e Chromium/WASM coevo

Estado: **PASS LOCAL INTEGRADO; GoTrue e homologação-alvo ainda pendentes**

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

Em 19/10/2026, o mesmo cenário foi repetido no stack descartável integrado. O
parecer e os três achados foram persistidos no PostgreSQL real; o owner os leu
pelo PostgREST sob JWT sintético e RLS. A recomendação objetiva foi preparada
pelo aplicador G4, enviada ao mesmo Chromium/WASM que mantinha a revisão 3,
confirmada por checkpoint byte a byte e persistida como revisão 4. O recibo do
backend foi entregue ao controller, que terminou em `saved` com hash nativo
igual ao head. O atendimento persistido marcou somente o objetivo como
`APLICADO_PENDENTE_REVISAO`; os itens ambíguo e incompatível permaneceram
`PENDENTE`. As revisões 1, 2 e 3 foram relidas com os bytes esperados.

A evidência canônica é
`outputs/WORDCRAFT_G4_OWNER_REAL_PERSISTENCE.json`, SHA-256
`993c4416f473c8b51cb4b8860eb15aa2c6fe8cdc6e11a575561eb4f5dce8011e`:
32/32 checks verdadeiros e cleanup positivo de navegador, processos, banco e
login. O harness cunha o JWT; portanto GoTrue real e homologação na
infraestrutura-alvo continuam necessários para G7.
