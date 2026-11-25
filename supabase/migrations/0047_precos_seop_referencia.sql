-- ## 0047 — Referência de custos da SEOP-PA (Planilha Padrão), importação supervisionada
-- ## ESTADO: NÃO APLICADA EM PRODUÇÃO. Aplicável; aguarda o ensaio nos dois
-- ##   níveis (o do CI roda em `tests/test_migracao_0047.py`), a revisão do
-- ##   `revisor-de-banco-e-seguranca` e a autorização do dono.
--
-- O PROBLEMA (23/11/2026)
--   O pacote pede a tabela de custos de obras do próprio Estado do Pará
--   (SEOP-PA), começando pela publicação de outubro de 2026. A SEOP só
--   publica PDF: a Planilha Padrão (48 páginas) e as composições analíticas
--   (511 páginas). PDF não é planilha; por isso a importação é SUPERVISIONADA:
--   a versão fica em conferência, com o relatório (página de cada linha,
--   recusas e o confronto com o PDF analítico), e só entra na consulta quando
--   uma pessoa a aprova.
--
-- O QUE FAZ
--   * `precos_seop_versoes`   — cada PDF importado por competência: SHA-256 da
--     planilha e do analítico, endereços, cabeçalho da publicação (BDI,
--     desoneração, leis sociais), contagens e recusas, o confronto, o estado
--     (em_conferencia, publicado, recusado) e QUEM aprovou e quando;
--   * `precos_seop_registros` — uma linha da Planilha Padrão: item, código de
--     6 dígitos, descrição, unidade, valor, grupo, a PÁGINA do PDF oficial e o
--     resultado do confronto daquela linha;
--   * `precos_seop_buscar(...)` — por código ou termos, só do vigente.
--
-- DECISÕES
--   * como o SINAPI (0046): NÃO é preço de compra, não alimenta a cesta, sem
--     `tenant_id` (publicação oficial), leitura só do vigente por
--     `authenticated`, escrita só do servidor, sem DELETE/TRUNCATE/
--     REFERENCES/TRIGGER nem para ele, busca `security invoker` com teto;
--   * PUBLICAÇÃO SÓ POR APROVAÇÃO: versão publicada sem `aprovado_por` é
--     recusada pelo banco (check). O importador grava `em_conferencia`; quem
--     publica é o ato `seop.aprovar`;
--   * VERSÃO = (competência, SHA-256 da planilha). Republicação da mesma
--     competência é versão nova, com as próprias linhas; a anterior fica;
--   * valor zero não é gravado (check `valor > 0`): a planilha de 10/2026 traz
--     "Mobilização e Desmobilização" com 0,00;
--   * a rota NÃO decide se a consulta está aberta: isso é a flag
--     `referencia_custos_seop_pa` (governança), que nasce desligada.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar e alguém aprovar;
--   * não guarda o analítico (coeficientes) nem as tabelas auxiliares — só o
--     custo unitário da Planilha Padrão, que é o que a consulta mostra;
--   * não decide se o órgão pode adotar a tabela da SEOP no lugar do SINAPI
--     (art. 23, § 3º): isso é do orçamentista, registrado no processo.

create table if not exists public.precos_seop_versoes (
  competencia text not null check (competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'em_conferencia' check (estado in
    ('em_conferencia', 'publicado', 'recusado')),
  vigente boolean not null default false,
  url text not null check (url ~ '^https://seop\.pa\.gov\.br/sites/default/files/[a-z0-9_]+\.pdf$'),
  url_analitico text check (url_analitico is null
    or url_analitico ~ '^https://seop\.pa\.gov\.br/sites/default/files/[a-z0-9_]+\.pdf$'),
  sha256_analitico text not null default '' check (sha256_analitico ~ '^([0-9a-f]{64})?$'),
  cabecalho jsonb not null default '{}'::jsonb,
  paginas integer not null default 0,
  lidas integer not null default 0,
  validas integer not null default 0,
  recusas jsonb not null default '{}'::jsonb,
  recusadas jsonb not null default '[]'::jsonb,
  confronto jsonb not null default '{}'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  aprovado_por text,
  aprovado_em timestamptz,
  divergencias_aceitas integer not null default 0,
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (competencia, sha256),
  check (not vigente or estado = 'publicado'),
  -- publicação é ato de pessoa: sem quem aprovou, não há versão publicada
  constraint precos_seop_versoes_publicacao_aprovada
    check (estado <> 'publicado' or (length(trim(coalesce(aprovado_por, ''))) >= 3
                                     and aprovado_em is not null))
);

-- uma versão vigente por competência, no máximo
create unique index if not exists precos_seop_versoes_vigente_idx
  on public.precos_seop_versoes (competencia) where vigente;

create table if not exists public.precos_seop_registros (
  registro_id text primary key,
  chave_linha text not null,
  competencia text not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  item text not null check (item ~ '^[0-9]{1,3}(\.[0-9]{1,4})+$'),
  codigo text not null check (codigo ~ '^[0-9]{6}$'),
  descricao text not null,
  descricao_busca text not null,
  unidade text not null,
  valor numeric(22, 6) not null check (valor > 0),
  grupo text,
  pagina integer not null check (pagina > 0),
  bdi text not null default '',
  desoneracao text not null default '',
  conferencia jsonb not null default '{}'::jsonb,
  url_arquivo text not null check (url_arquivo ~ '^https://seop\.pa\.gov\.br/sites/default/files/[a-z0-9_]+\.pdf$'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, descricao_busca)) stored,
  unique (arquivo_sha256, chave_linha),
  foreign key (competencia, arquivo_sha256)
    references public.precos_seop_versoes (competencia, sha256)
);

create index if not exists precos_seop_registros_busca_idx
  on public.precos_seop_registros using gin (busca) where vigente;
create index if not exists precos_seop_registros_codigo_idx
  on public.precos_seop_registros (codigo, competencia) where vigente;
create index if not exists precos_seop_registros_versao_idx
  on public.precos_seop_registros (competencia, arquivo_sha256);

alter table public.precos_seop_versoes   enable row level security;
alter table public.precos_seop_registros enable row level security;

revoke all on public.precos_seop_versoes   from anon, authenticated, public;
revoke all on public.precos_seop_registros from anon, authenticated, public;

grant select, insert, update on public.precos_seop_versoes   to service_role;
grant select, insert, update on public.precos_seop_registros to service_role;
revoke delete, truncate, references, trigger on public.precos_seop_versoes   from service_role;
revoke delete, truncate, references, trigger on public.precos_seop_registros from service_role;

grant select on public.precos_seop_registros to authenticated;
drop policy if exists "precos_seop_registros_leitura" on public.precos_seop_registros;
create policy "precos_seop_registros_leitura" on public.precos_seop_registros
  for select to authenticated using (vigente);

create or replace function public.precos_seop_buscar(
  p_termos text[],
  p_codigo text default null,
  p_competencia text default null,
  p_limite integer default 50)
returns setof public.precos_seop_registros
language sql
stable
security invoker
set search_path = ''
as $$
  with consulta as (
    -- mesmo teto de custo da 0042/0044/0046: 24 termos, 60 caracteres cada
    select websearch_to_tsquery('portuguese'::regconfig,
             coalesce((select string_agg(left(t, 60), ' or ')
                         from unnest(coalesce(p_termos, '{}'::text[]))
                              with ordinality as u(t, n)
                        where n <= 24), '')) as q
  ),
  -- sem competência pedida: a mais recente com referência vigente
  alvo as (
    select coalesce(nullif(p_competencia, ''),
                    (select max(r.competencia)
                       from public.precos_seop_registros r
                      where r.vigente)) as competencia
  )
  select r.*
    from public.precos_seop_registros r, consulta c, alvo a
   where r.vigente
     and r.competencia = a.competencia
     and case when nullif(p_codigo, '') is not null
              then r.codigo = p_codigo
              else r.busca @@ c.q end
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.codigo
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_seop_buscar(text[], text, text, integer) is
  'Custos de referência da SEOP-PA no índice, por código ou por termos (0047).';

revoke all on function public.precos_seop_buscar(text[], text, text, integer)
  from public, anon;
grant execute on function public.precos_seop_buscar(text[], text, text, integer)
  to authenticated;
grant execute on function public.precos_seop_buscar(text[], text, text, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_seop_buscar(text[], text, text, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_seop_versoes', 'precos_seop_registros'] loop
    if not (select relrowsecurity from pg_class
             where oid = ('public.' || tabela)::regclass) then
      faltou := faltou || ' rls_desligado:' || tabela;
    end if;
    if has_any_column_privilege('anon', 'public.' || tabela,
                                'select, insert, update, references') then
      faltou := faltou || ' anon_alcanca:' || tabela;
    end if;
    if has_table_privilege('anon', 'public.' || tabela, 'delete, truncate') then
      faltou := faltou || ' anon_apaga:' || tabela;
    end if;
    if has_any_column_privilege('authenticated', 'public.' || tabela,
                                'insert, update, references') then
      faltou := faltou || ' authenticated_escreve:' || tabela;
    end if;
    if has_table_privilege('authenticated', 'public.' || tabela,
                           'delete, truncate') then
      faltou := faltou || ' authenticated_apaga:' || tabela;
    end if;
    if has_table_privilege('service_role', 'public.' || tabela,
                           'delete, truncate') then
      faltou := faltou || ' service_role_apaga:' || tabela;
    end if;
    -- REFERENCES por coluna não aparece em `has_table_privilege`
    if has_table_privilege('service_role', 'public.' || tabela, 'trigger')
       or has_any_column_privilege('service_role', 'public.' || tabela,
                                   'references') then
      faltou := faltou || ' service_role_gatilho_ou_fk:' || tabela;
    end if;
    -- fora o dono, só `service_role` e `authenticated` podem aparecer no ACL
    -- da tabela ou de qualquer coluna (PUBLIC é o grantee 0 e também cai)
    if exists (
         select 1 from pg_class c,
                aclexplode(coalesce(c.relacl, acldefault('r', c.relowner))) a
          where c.oid = ('public.' || tabela)::regclass
            and a.grantee not in (c.relowner, 'service_role'::regrole::oid,
                                  'authenticated'::regrole::oid))
       or exists (
         select 1 from pg_attribute at, pg_class c, aclexplode(at.attacl) a
          where at.attrelid = ('public.' || tabela)::regclass
            and c.oid = at.attrelid and at.attacl is not null
            and a.grantee not in (c.relowner, 'service_role'::regrole::oid,
                                  'authenticated'::regrole::oid)) then
      faltou := faltou || ' grant_a_papel_inesperado:' || tabela;
    end if;
    -- a migração não cria gatilho; um que apareça mudaria o que é gravado
    if exists (select 1 from pg_trigger
                where tgrelid = ('public.' || tabela)::regclass
                  and not tgisinternal) then
      faltou := faltou || ' gatilho:' || tabela;
    end if;
    -- com lista, `has_table_privilege` responde "algum": cada um é conferido
    if not (has_table_privilege('service_role', 'public.' || tabela, 'select')
            and has_table_privilege('service_role', 'public.' || tabela, 'insert')
            and has_table_privilege('service_role', 'public.' || tabela, 'update')) then
      faltou := faltou || ' service_role_sem_escrita:' || tabela;
    end if;
  end loop;

  if has_any_column_privilege('authenticated', 'public.precos_seop_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_seop_registros', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_seop\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_seop_registros'
          and policyname = 'precos_seop_registros_leitura'
          and cmd = 'SELECT' and roles = '{authenticated}'
          and qual = 'vigente') then
    faltou := faltou || ' politica_fora_do_previsto';
  end if;
  -- a publicação por aprovação é garantia desta migração: o check tem de estar lá
  if not exists (
       select 1 from pg_constraint
        where conrelid = 'public.precos_seop_versoes'::regclass and contype = 'c'
          and conname = 'precos_seop_versoes_publicacao_aprovada'
          and pg_get_constraintdef(oid) like '%aprovado_por%'
          and pg_get_constraintdef(oid) like '%aprovado_em%') then
    faltou := faltou || ' publicacao_sem_aprovacao';
  end if;

  if (select prosecdef from pg_proc where oid = funcao) then
    faltou := faltou || ' security_definer';
  end if;
  if (select provolatile from pg_proc where oid = funcao) <> 's' then
    faltou := faltou || ' nao_estavel';
  end if;
  if not coalesce((select proconfig from pg_proc where oid = funcao)
                  @> array['search_path=""'], false) then
    faltou := faltou || ' sem_search_path_vazio';
  end if;
  if not has_function_privilege('authenticated', funcao, 'execute') then
    faltou := faltou || ' authenticated_sem_execute';
  end if;
  if has_function_privilege('anon', funcao, 'execute') then
    faltou := faltou || ' anon_executa';
  end if;

  if faltou <> '' then
    raise exception 'A 0047 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
