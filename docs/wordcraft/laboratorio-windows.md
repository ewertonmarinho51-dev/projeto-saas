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

O roteiro de QA work/run_local_backend_qa.py reutiliza as funções existentes;
configurar PYTHONPATH para o diretório absoluto work/pg-deps e PYTHONUTF8=1, usando
Python 3.12 com as dependências do produto. --http-only seleciona apenas o grupo HTTP.
Os caminhos de runtime e o banco de QA são explícitos no roteiro. Ele não busca
secrets de projetos hospedados. Não executar montar() sobre um banco parcialmente
preparado: o helper existente considera banco já existente como reaproveitável.

Encerrar ao terminar:

```powershell
& work/toolchain/postgresql-16.15-5/pgsql/bin/pg_ctl.exe -D work/wordcraft-pg/data -m fast -w stop
```

Este laboratório remove a ausência de PostgreSQL/PostgREST local como impedimento.
G1 continua pendente de WASM release integrado e de um proprietário de commit
documental conectado ao componente. Estas provas não validam persistência WordCraft,
CAS, histórico de documentos, exportação, caret/undo ou autenticação Supabase.
