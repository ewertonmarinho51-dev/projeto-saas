# G7 — ensaio Auth real em Linux CI

Contrato registrado antes do código em 2026-10-15. Execução somente em banco
novo descartável de PostgreSQL local e serviços HTTP em `127.0.0.1`; nenhum
Supabase hospedado, dado privado, SMTP externo, deploy ou produção.

O executável é a distribuição oficial Supabase Auth v2.197.0 Linux amd64,
upstream SHA `4eee58f296d9698a1c2c0ae14d7a0b379c7622d3`:
`https://github.com/supabase/auth/releases/download/v2.197.0/auth-v2.197.0-amd64.tar.xz`,
9.897.464 bytes, SHA-256
`b5c2991d1df760c9b099c1c2395a94bd1c2f83ed58901934921997179dc9f7ea`.
Nenhum patch/fork do serviço. A falha `unix.SO_REUSEPORT` ao compilar esse
upstream no Windows não é contornada alterando o produto upstream.

O harness reutiliza `ensaio_local.criar_banco_descartavel`, o mesmo catálogo e
ordem de migrações, helpers de auth/GRANTs e o orquestrador HTTP canônico.
`preparar(auth_real=False)` mantém a fixture existente; o modo `auth_real=True`
exige tabelas/colunas de Auth reais e histórico de migrações GoTrue antes de
aplicar o schema do produto. O serviço Auth é iniciado/migrado antes das
migrações de aplicação. O novo modo jamais cria a fixture reduzida auth.users.

O gateway existente ganha apenas destino Auth opcional em loopback. Sem ele,
`/auth/v1` mantém o 501 explícito. Com ele, encaminha método, headers, corpo e
query para o GoTrue real, sem interpretar credenciais, token, claims ou RLS.
Storage/functions continuam ausentes. Nenhuma rota escuta interface pública.

Contas de QA são criadas pela API admin local, com email `.invalid` confirmado
sem envio de email e senha aleatória em memória. O login usa senha no GoTrue e
emite os access/refresh tokens de usuário reais, com expiração curta. JWT local
de infraestrutura admin/service_role pode existir para configurar o stack; não
é apresentado como prova de login de usuário.

A prova usa os clientes existentes `db._cliente()` e
`db.cliente_do_usuario()` para Auth/PostgREST e o `DocumentoService` existente
para operações de documentos. Claims de tenant/secretaria/papel são gravadas
por API admin em app_metadata; tentativa do usuário de promover user_metadata
não concede autorização. RLS é verificado com titular A, colega da mesma
secretaria, usuário B e sessão anônima; save/revisão e artefato imutável devem
passar somente pelo owner e RPCs canônicos, sem duplicar SQL de negócio.

Revogação é observada separadamente: logout global/refresh recusado não é prova
de invalidação imediata de access token já emitido. O harness também confere a
revogação do vínculo do produto e a recusa da escrita sensível com token ainda
válido, quando coberta pelo contrato atual; qualquer lacuna é explícita e
nunca transformada em PASS.

Segredos só existem no processo/ambiente dos filhos, sem arquivos, argv,
relatórios ou logs anexados. Saída registra somente versões/hashes, contagens,
nomes de provas e vereditos. Logs dos serviços são descartados; falhas devolvem
etapa/tipo fechado, sem resposta HTTP ou DSN. O encerramento atinge somente
processos, banco e login criados pela própria execução, incluindo falhas.

Workflow independente do build WordCraft prepara Linux, PostgreSQL com pgvector,
PostgREST pinado e o Auth oficial verificado por tamanho/hash. Unit tests
exercitam contratos/recusas do harness; a execução real no CI é um gate
separado. Enquanto não houver run real concluído, o estado é IMPLEMENTADO /
EXECUÇÃO REAL PENDENTE, sem alegar emissão de sessão ou prova RLS real.

Implementação preparada: `scripts/ensaio_auth_real.py`,
`scripts/gateway_supabase.py`, modo opcional em `scripts/ensaio_local.py` e
workflow independente `.github/workflows/auth-real.yml`. O PREAMBULO fixture
original mantém SHA-256 de string UTF-8
`86dd2897a540b5b792961dd1f0ab38ea9f69b91f20c71cfde888495e16454a7f`.
O novo modo exige a migração Auth `20260831180000`, além de colunas reais em
users/identities/sessions/refresh_tokens/schema_migrations, antes de SQL da app.

O workflow consome o ZIP QA WordCraft existente, sem recompilar: artifact
`11995992777`, produtor `39fec20fc5e94590a95cfd9af8d0ce34d07c3e54`, SHA-256
`a57bdc0b05660afb3ea37e0625e50fc2d33e78fa9e995822210e51580c79221d` e manifesto
`bd306cdb4709a43314366375da91ca1d00b2dd6db3c7683fff44eb15eb087548`.
O instalador canônico valida o arquivo inteiro e só instala em laboratório novo
marcado `.wordcraft-local-qa` sob WORK_ROOT, sem publicar endpoint de assets.
Artifact expirado/ausente ou hash divergente falha o job, sem procurar um build
alternativo. PostgREST 12.2.12 usa o mesmo binário/hash do ensaio HTTP existente.

O fluxo usa `auth._cliente_de_login` e `auth.autenticar_no_supabase` existentes,
sem contaminar o cache do cliente de servidor com sessão de login. A API admin
local cria três contas; JWTs retornados pelo GoTrue são conferidos por assinatura,
issuer/audience/sub/exp e por auth.sessions. `DocumentoService.criar`, checkpoint,
abrir_revisao e exportar exercitam o owner real com fixture DOCX sintética pinada
importada pelo mesmo WASM, sem validador falso ou payload SQL opaco.

Os testes `test_auth_real_harness.py` verificam admissão, preservação do fixture,
ordem dos gates, extração confinada, sigilo de falha e limpeza dos filhos.
`test_gateway_supabase.py` mede encaminhamento HTTP contra stub loopback
explicitamente identificado; esse teste não emite JWT nem prova GoTrue.
O integrador executou a rodada final completa: **38 passed em 4,04 s**, incluindo
os quatro casos de HTTP, com XML em
`outputs/tests-wordcraft-auth-real-harness-final.xml`. A rodada local do agente,
com `work/pg-deps` e `work/document-deps`, passou 34 testes offline; os quatro
casos HTTP foram executados no contexto do integrador porque o sandbox do
agente recusa conexão loopback. `py_compile`, YAML e
`git diff --check` passaram. Esses resultados não são o gate Auth real Linux.

Somente `auth-real.json` sanitizado é anexado pelo CI. A evidência distingue
logout/refresh revogado do comportamento observado do access token antigo no
PostgREST; não declara revogação imediata do JWT. A desativação canônica do
perfil deve bloquear leitura e save mesmo com aquele token ainda válido.
Revisões e artefato exportado anteriores devem permanecer iguais após as
tentativas negadas, sem gravação parcial.

Referências consultadas: [login Python oficial](https://supabase.com/docs/reference/python/auth-signinwithpassword),
[admin update oficial](https://supabase.com/docs/reference/python/auth-admin-updateuserbyid),
e código/CHANGELOG do upstream Auth pinado localmente. A tentativa de leitura
do índice changelog.md foi recusada pelo leitor web por content-type; as
opções do serviço foram verificadas no README, configuration e handlers do
v2.197.0, sem assumir compatibilidade de uma versão posterior.
