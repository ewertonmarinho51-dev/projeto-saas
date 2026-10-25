-- ## 0034 — Base de Conhecimento: o ADMIN grava os trechos e exclui a
-- ##        referência com o próprio JWT (interface nova, M6)
-- ## ESTADO: aplicável. NÃO aplicada em produção.
--
-- O PROBLEMA (auditoria de produção, 24/10/2026, catálogo)
--   A 0020 decidiu o grupo da Base de Conhecimento: "leitura do tenant
--   inteiro; escrita só do admin". Escreveu metade da decisão:
--   * `documentos_referencia`: SELECT do tenant e INSERT do admin — sem
--     política nem grant de DELETE;
--   * `chunks_referencia`: SELECT do tenant — sem política nem grant de
--     INSERT.
--   O Streamlit não sentiu porque indexa e exclui com a credencial de
--   SERVIDOR. A API não tem essa credencial (ADR-002) e escreve com o JWT
--   do usuário: o admin conseguiria criar a referência e nenhum trecho
--   dela — um documento "indexado" com zero trechos, invisível na busca —
--   e não conseguiria excluí-la.
--
-- O QUE FAZ
--   * `chunks_referencia_admin`: INSERT por `authenticated` só quando é
--     admin E o documento-pai é do tenant do JWT. O trecho não tem
--     `tenant_id` próprio: o tenant é o do pai, como na leitura;
--   * `documentos_referencia_admin_exclui`: DELETE por `authenticated` só
--     do admin, no próprio tenant. Os trechos caem pelo `on delete
--     cascade` da 0003 — ação referencial, que o PostgreSQL executa sem
--     RLS e sem exigir DELETE em `chunks_referencia`. Por isso NÃO há
--     grant de DELETE nos trechos: apagar trecho solto, deixando o
--     documento com `total_chunks` mentindo, não é ato de ninguém;
--   * os grants correspondentes (INSERT nos trechos, DELETE na
--     referência), nome a nome: cada um foi uma decisão.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 24/10/2026)
--   * `chunks_referencia`: `authenticated` com SELECT; 1 política
--     (`chunks_referencia_le`); `id` é identity (INSERT não pede USAGE em
--     sequência);
--   * `documentos_referencia`: `authenticated` com INSERT, SELECT; 2
--     políticas (`_le`, `_admin` de INSERT); `tenant_id` com default fixo
--     do tenant original — a API grava o tenant explícito;
--   * nenhum gatilho nas duas tabelas;
--   * `anon` sem grant algum nas duas.
--
-- O QUE NÃO RESOLVE
--   * UPDATE continua fechado nas duas: reindexar (trocar o vetor de um
--     trecho PENDENTE) segue sendo trabalho de servidor;
--   * as outras duas tabelas do grupo (`fontes_conhecimento`,
--     `regras_conhecimento`) continuam sem DELETE: a interface nova não as
--     edita, e abrir escrita sem tela que a use é porta sem dono;
--   * a PROVENIÊNCIA do vetor: o INSERT é de tabela inteira, então o admin
--     consegue gravar `embedding_v2`/`embedding_status` com o valor que
--     quiser. Quem garante o modelo pinado é o código (`rag.indexar`), não o
--     banco. Alcance: o próprio tenant, só o admin;
--   * a exclusão não deixa trilha no banco (só o log da API), como já era no
--     Streamlit com `service_role` — a 0027 manteve esse DELETE de propósito;
--   * o cascade sob `force row level security` (0019): o PostgreSQL não
--     aplica RLS às ações referenciais; o ensaio local roda como dono e
--     prova o PostgreSQL. A primeira exclusão real em produção é a medida;
--   * o vetor: sem `OPENAI_EMBEDDINGS_KEY` no ambiente da API, o trecho
--     nasce PENDENTE (busca textual). Isso é configuração do servidor, não
--     do banco.

drop policy if exists "chunks_referencia_admin" on public.chunks_referencia;
create policy "chunks_referencia_admin" on public.chunks_referencia
  for insert to authenticated
  with check (public.e_admin()
              and exists (select 1 from public.documentos_referencia d
                          where d.id = chunks_referencia.documento_id
                            and d.tenant_id = public.tenant_do_jwt()));
grant insert on public.chunks_referencia to authenticated;

drop policy if exists "documentos_referencia_admin_exclui" on public.documentos_referencia;
create policy "documentos_referencia_admin_exclui" on public.documentos_referencia
  for delete to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant delete on public.documentos_referencia to authenticated;

-- Conferência que falha sozinha: um grant ou uma política que não pegou
-- não levanta erro; este bloco levanta.
do $$
declare faltou text;
begin
  select string_agg(item, ', ') into faltou from (
    select 'grant_insert_chunks' as item
     where not has_table_privilege('authenticated', 'public.chunks_referencia', 'INSERT')
    union all
    select 'grant_delete_documentos'
     where not has_table_privilege('authenticated', 'public.documentos_referencia', 'DELETE')
    union all
    select 'politica_chunks_admin'
     where not exists (select 1 from pg_policies
                        where schemaname = 'public' and tablename = 'chunks_referencia'
                          and policyname = 'chunks_referencia_admin' and cmd = 'INSERT'
                          and roles = '{authenticated}'::name[])
    union all
    select 'politica_documentos_exclui'
     where not exists (select 1 from pg_policies
                        where schemaname = 'public' and tablename = 'documentos_referencia'
                          and policyname = 'documentos_referencia_admin_exclui' and cmd = 'DELETE'
                          and roles = '{authenticated}'::name[])
    union all
    -- o que NÃO pode ter vindo junto
    select 'delete_em_chunks'
     where has_table_privilege('authenticated', 'public.chunks_referencia', 'DELETE')
    union all
    select 'update_em_' || t
      from unnest(array['chunks_referencia', 'documentos_referencia']) t
     where has_table_privilege('authenticated', 'public.' || t, 'UPDATE')
    union all
    select 'anon_em_' || t
      from unnest(array['chunks_referencia', 'documentos_referencia']) t
     where has_table_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
    union all
    -- a classe da 0021/0024: o privilégio que ninguém nomeou
    select 'privilegio_largo_em_' || t
      from unnest(array['chunks_referencia', 'documentos_referencia']) t
     where has_table_privilege('authenticated', 'public.' || t, 'TRUNCATE,REFERENCES,TRIGGER')
    union all
    select 'update_por_coluna_em_' || t
      from unnest(array['chunks_referencia', 'documentos_referencia']) t
     where has_any_column_privilege('authenticated', 'public.' || t, 'UPDATE')
    union all
    select 'rls_desligado_em_' || c.relname
      from pg_class c
     where c.oid in ('public.chunks_referencia'::regclass, 'public.documentos_referencia'::regclass)
       and not c.relrowsecurity
  ) achados;
  if faltou is not null then
    raise exception 'A 0034 não cumpriu o que afirma: %', faltou;
  end if;
end
$$;
