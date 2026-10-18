# PostgREST local: contenção das superfícies documentais

Em 18/10/2026 a pilha descartável local executou PostgreSQL 16.15, PostgREST
12.2.12 e o gateway canônico somente em `127.0.0.1`. Cada execução criou um
banco e um login efêmeros, aplicou a sequência integral de migrations e removeu
ambos no `finally`. O PostgreSQL foi encerrado ao final.

A enumeração comportamental passou a incluir as RPCs
`documento_editor_emitir` e `documento_editor_aplicar_template`, além das RPCs
documentais anteriores. O usuário `anon` tentou cada chamada pelo endpoint HTTP
real e recebeu negação estruturada `42501`; nenhuma função foi inferida apenas
do catálogo. As tabelas privadas, escrita no objeto descartável, default
privileges, operação legítima de `service_role` e catálogo também foram
revalidados. Resultado: **68 passed, 282 deselected em 18,10 s**, XML local em
`work/http-wordcraft-rpc-20261018-04/http.xml`.

O cliente `supabase-py` não estava instalado no runtime local e a tentativa de
instalá-lo não foi executada porque a revisão automática de permissão ficou sem
cota. O harness ganhou um cliente mínimo ativado somente por
`GOVDOCS_ENSAIO_CLIENTE_HTTP_MINIMO=1`: aceita exclusivamente uma raiz HTTP de
loopback, não segue redirects, limita respostas, implementa somente as operações
usadas no ensaio e preserva o `code` JSON do PostgREST sem incluir JWT em erros.
O produto e os testes normais continuam usando `supabase-py`.

Storage é **não aplicável neste desenho atual**: o schema canônico possui zero
buckets e os checkpoints/artefatos nativos ficam nas tabelas privadas
documentais. O harness não inicia nem simula um serviço Storage; retorna lista
vazia somente no cliente local explicitamente selecionado, e o teste registra
`NAO_APLICAVEL`. Se um bucket for adotado no futuro, esta conclusão expira e
policies/URLs temporárias voltam a ser obrigatórias.

Esta evidência prova contenção HTTP anônima e operação administrativa do ensaio.
Não prova login GoTrue, JWT real de usuário, save/aprovação/emissão autenticados
via PostgREST nem revogação de sessão. Esses itens permanecem no gate Auth real.
