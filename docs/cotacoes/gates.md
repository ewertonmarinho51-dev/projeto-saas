# Cotações — provas de aceite por gate (definidas no G0)

Cada gate só passa com estas provas verdes e a suíte inteira sem falha.
Arquivos de prova previstos; o relatório de cada gate aponta a saída.

| Gate | Prova de aceite | Arquivo |
|---|---|---|
| G1 | As 13 reproduções do G0 viram verdes sem `xfail` | `tests/test_cotacoes_g0_reproducao.py` |
| G1 | 29,00 → 25,85 → 20,45 → excluir 9,66 → 25,85 e 2/3 pendente; sem referência = sem preço | idem |
| G1 | Exceção com menos de três: exige perfil, texto, fundamento e aprovador; cesta mudou invalida a exceção; lote com prévia | `tests/test_cotacoes_g1_nucleo.py` |
| G1 | Importação: todas as linhas diagnosticadas; nada gravado com erro; reimportar não duplica nem perde seleção; código preservado | idem |
| G1 | Relatório, resumido, XLSX, GovBot e tela contam os mesmos considerados | idem |
| G2 | Criar → itens → buscar manual → automático no MESMO item → mesma cesta; reabrir em outra sessão mostra o mesmo | `tests/test_cotacoes_g2_servico.py` |
| G2 | Conflito de versão: segunda aba com revisão antiga recebe erro claro, nada sobrescrito | idem |
| G2 | Telas Minhas Cotações e Elaborar Cotação rodam no AppTest com flag ligada; flag desligada mantém a tela antiga | `tests/test_cotacoes_g2_ui.py` |
| G3 | Item fictício com 11 vizinhos: zero elegíveis; fonte fora ≠ zero resultado ≠ sem comparáveis ≠ amostra insuficiente; estimado de origem fora da cesta; dedupe entre portais | `tests/test_cotacoes_g3_busca.py` |
| G4 | Seletor: exato sem IA, ambíguo com Jev (dublê), incompatível recusado; orçamento por item/cotação; cache; abstenção; flag OFF = nenhuma chamada; nunca aceita sozinho | `tests/test_cotacoes_g4_seletor.py` |
| G5 | Aviso nominal de pendências antes de emitir; registro de emissão com hash decisório e do arquivo; reemitir mesmo resultado = mesmo hash decisório; aplicação com diff | `tests/test_cotacoes_g5_emissao.py` |
| G6 | 1/10/50/210 itens ponta a ponta; manual + automático na mesma cotação; concorrência; tenant B não lê A (RLS: ensaio SQL); IA indisponível mantém manual | `tests/test_cotacoes_g6_e2e.py` |
