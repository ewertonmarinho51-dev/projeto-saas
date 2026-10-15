# Laboratório local Windows — 14/10/2026

Este ensaio reutiliza homologacao_local.py, homologacao_stack.py, gateway_supabase.py
e as migrações reais do produto. Não implementa um segundo backend documental.
Não usa projeto Supabase, senha real, serviço Windows, instalador ou PATH global.
GoTrue e Storage Supabase não estão presentes e não são certificados aqui.

## Runtime efetivamente executado

| Componente | Origem | Versão / SHA-256 do pacote |
|---|---|---|
| PostgreSQL portátil | EDB, link disponibilizado por postgresql.org/download/windows | 16.15-5 / 43bb45f173a6f08cf1d29a97a6d8deb119e8e8093a24c00d2d1001a0ccaa8281 |
| PostgREST | release oficial PostgREST/postgrest | 12.2.12 / 4e7c92f1c89babf91f580d5012b9f2f20944da34bfd64521615297bf7ac780eb |
| pgvector | conda-forge win-64, opção de instalação indicada no projeto pgvector | 0.8.6-h2466b09_0 / 5730998991a2b7349c4253ed7881f339bd43d005949b655edc616cca8caf21dd |
| psycopg | pacote PyPI, instalado somente em work/pg-deps | 3.2.13 + binary 3.2.13 |

O SHA pgvector foi comparado com os metadados publicados pelo canal antes de extrair.
Os hashes PostgreSQL/PostgREST registram os bytes baixados por HTTPS das origens
oficiais; não são uma alegação de assinatura independente do distribuidor.

URLs:
- https://www.postgresql.org/download/windows/
- https://get.enterprisedb.com/postgresql/postgresql-16.15-5-windows-x64-binaries.zip
- https://github.com/PostgREST/postgrest/releases/tag/v12.2.12
- https://github.com/pgvector/pgvector#installation
- https://api.anaconda.org/package/conda-forge/pgvector
- https://conda.anaconda.org/conda-forge/win-64/pgvector-0.8.6-h2466b09_0.conda

## Estado isolado

Cluster: work/wordcraft-pg/data; porta 55439, listen_addresses=127.0.0.1, timezone UTC.
Banco pronto: wordcraft_qa_ready. O banco inicial wordcraft_qa ficou vazio após
rollback da tentativa que encontrou vector ausente; não foi reutilizado como pronto.
26 migrações reais, 44 tabelas públicas, 43 com RLS e 85 políticas. A tabela
ensaio_objeto_novo é deliberadamente sem RLS para testar a ausência de grants.
O harness espelha suas 37 flags legadas somente neste banco sintético. WordCraft
continua sem ativação operacional. Nenhuma flag remota foi alterada.

PostgREST: 127.0.0.1:55440; gateway existente: 127.0.0.1:55441. Ambos iniciam para
os testes e são encerrados no finally do roteiro. JWTs anon/service_role são
gerados em memória contra segredo efêmero deste PostgREST; não são credenciais de
projeto Supabase e não são impressos ou incluídos nos artefatos. O cluster usa
trust exclusivamente no laboratório em loopback com dados sintéticos; não copiar
essa configuração para ambiente compartilhado ou produção.

## Execução e escopo provados

As três suítes SQL existentes passaram: test_ensaio_sql_local.py,
test_precos_fase3_rls.py e test_multi_prefeituras_rls.py: 111 pass. Cada uma usa
bancos descartáveis próprios e limpa seu cenário. Elas injetam claims no PostgreSQL;
não provam emissão GoTrue ou sessão de usuário real.

O grupo HTTP selecionado de test_seguranca_contencao.py passou: 55 pass,
283 deselected. Ele mede catálogo pós-0020, recusa de leitura/escrita/RPC por anon,
default privileges e operação legítima do servidor via supabase-py/PostgREST.
Não foram selecionadas provas que exigem GoTrue ou Storage ausentes.

A primeira execução HTTP falhou em cinco expectativas preexistentes: fase A do
catálogo aplicada ao schema pós-0020; exigência de RLS até na tabela descartável;
select(id) em config_app cuja chave é chave. Os testes foram corrigidos para fase B,
RLS das tabelas privadas do inventário e a coluna real de cada tabela. Um teste
adicional exige WITH CHECK e policy para grants authenticated, preservando as
restrições adicionais da fase B. As regras e migrações do banco não foram alteradas.

## Retomada sem recriar dados

Do diretório raiz desta tarefa, iniciar o cluster existente:

```powershell
& work/toolchain/postgresql-16.15-5/pgsql/bin/pg_ctl.exe -D work/wordcraft-pg/data -l work/wordcraft-pg/server.log -o '-h 127.0.0.1 -p 55439 -c timezone=UTC' -w start
```

O orquestrador versionado scripts/ensaio_http_local.py reutiliza as funções existentes.
Ele cria banco próprio com nome aleatório, além de um login efêmero membro de
authenticator, sem trocar a senha desse papel existente. Ao final encerra PostgREST
e gateway, apaga seu banco e seu login, e verifica que o banco desapareceu. A execução
real desse caminho passou nos 55 testes; consulta de catálogo confirmou zero bancos
http_qa_* e zero logins http_login_* restantes. Não há busca de secrets hospedados.

Com Python do projeto e as dependências de teste, do checkout GovConnect:

```powershell
$env:PYTHONUTF8='1'
$env:PYTHONPATH=(Resolve-Path ../pg-deps).Path
python scripts/ensaio_http_local.py --dsn 'postgresql://postgres@127.0.0.1:55439/postgres' --postgrest ../toolchain/postgrest-12.2.12/postgrest.exe --pg-bin ../toolchain/postgresql-16.15-5/pgsql/bin --work-dir ../http-qa-canonical
```

O CI também executa esse orquestrador após a suíte principal, usando a imagem
pgvector/pgvector:pg16 já existente e PostgREST Linux oficial 12.2.12. O arquivo Linux
é verificado contra SHA-256 5de4092f1719da3353c40bf96c8dec6913f2254a7cd0b61cc05f233153b557d5
antes de extrair; o JUnit é preservado como artefato. A prova no CI ainda aguarda seu
primeiro run. O DSN do serviço efêmero é explícito; JWTs só existem no processo filho.

Não executar montar() sobre um banco parcialmente preparado: o helper existente
considera banco já existente como reaproveitável. O novo orquestrador evita esse
caminho com nomes novos por execução, e não aceita nome de banco vindo do chamador.

Encerrar ao terminar:

```powershell
& work/toolchain/postgresql-16.15-5/pgsql/bin/pg_ctl.exe -D work/wordcraft-pg/data -m fast -w stop
```

Este laboratório remove a ausência de PostgreSQL/PostgREST local como impedimento.
G1 continua pendente de WASM release integrado e de um proprietário de commit
documental conectado ao componente. Estas provas não validam persistência WordCraft,
CAS, histórico de documentos, exportação, caret/undo ou autenticação Supabase.
