-- ## 0048 — Tabela Unificada do SUS (SIGTAP/DATASUS), em consulta própria
-- ## ESTADO: APLICADA EM PRODUÇÃO em 25/11/2026 como `m0048_precos_sigtap_referencia`
-- ##   (registro 20261125021219), a pedido expresso do dono ("aplique as migrações e importe as fontes").
-- ##   SIGTAP 11/2026 importado e publicado em 25/11/2026: 5.068 vigentes.
-- ##   Numerada depois da 0047 (SEOP-PA, PR #229): as duas não dependem uma da
-- ##   outra, só a ordem do ensaio.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (25/11/2026):
--   * ANTES (25/11, antes da 0047): 58 tabelas em `public`; a `authenticated`,
--     SELECT em 48, INSERT em 32, UPDATE em 15, DELETE em 3; a `service_role`,
--     DELETE em 23, REFERENCES e TRIGGER em 43;
--   * DEPOIS (25/11, com 0047–0050): 66 tabelas, todas as novas com RLS;
--     `authenticated` só ganhou SELECT nas quatro tabelas de registros
--     (48 → 52), nenhuma escrita; `service_role` seguiu com DELETE em 23 e
--     REFERENCES/TRIGGER em 43 (nenhum nas tabelas novas); `precos_bps_registros`
--     seguiu com 10.755 linhas;
--   * COMPORTAMENTO: como `anon`, SELECT recusado (42501) nas tabelas novas e
--     EXECUTE recusado nas cinco funções `precos_*_buscar`; como
--     `authenticated`, as buscas devolvem só o vigente;
--   * o bloco de conferência do fim do arquivo passou na aplicação.
--
-- O PROBLEMA (24/11/2026)
--   O pacote pede o SIGTAP: a remuneração da Tabela Unificada de
--   procedimentos do SUS, por competência e código, com modalidade e as
--   parcelas ambulatorial e hospitalar. Não é preço de compra nem custo de
--   obra: é o valor que o SUS paga por procedimento, e a consulta tem de
--   dizer isso. O DATASUS publica um ZIP por competência, só por FTP.
--
-- O QUE FAZ
--   * `precos_sigtap_versoes`        — cada arquivo importado por competência:
--     SHA-256, nome oficial e versão de geração (`_v…`), contagens, recusas,
--     estado (importando, publicado, recusado) e qual é a VIGENTE;
--   * `precos_sigtap_procedimentos`  — um procedimento: código de 10 dígitos,
--     nome, valores SA, SH e SP (o total hospitalar é SH + SP), modalidades,
--     financiamento, rubrica, grupo/subgrupo/forma de organização, a linha de
--     `tb_procedimento.txt` e o arquivo de onde veio;
--   * `precos_sigtap_buscar(...)`    — por código ou termos, só do vigente.
--
-- DECISÕES
--   * CATEGORIA PRÓPRIA, como a 0046/0047: fora da cesta, sem `tenant_id`, leitura só do vigente
--     por `authenticated`, escrita só do servidor, sem DELETE/TRUNCATE/
--     REFERENCES/TRIGGER nem para ele, busca `security invoker` com teto;
--   * valor ZERO é permitido (`>= 0`): é dado da tabela (procedimento sem
--     valor unitário), não erro de leitura;
--   * VERSÃO = (competência, SHA-256). O DATASUS regera a competência com
--     outra versão no nome do arquivo: versão nova, publicada inteira;
--   * a consulta é aberta pela flag `referencia_sus_sigtap`, desligada.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * não importa nada: índice vazio até o importador rodar;
--   * não guarda CID, CBO, habilitação, leito nem compatibilidades — só o
--     que a consulta de remuneração mostra;
--   * a publicação de versão nova são quatro UPDATEs pela API REST, não uma
--     transação (como no SINAPI): entre o 1º e o 2º, a versão velha e a nova
--     aparecem juntas; se o importador cair ali, a versão nova fica em
--     `importando` e reimportar o mesmo arquivo refaz a publicação inteira;
--   * o canal oficial é FTP sem criptografia: a integridade vem das
--     conferências do leitor (leiaute embutido, competência de cada linha) e
--     do SHA-256 registrado, não do transporte.

create table if not exists public.precos_sigtap_versoes (
  competencia text not null check (competencia ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
  sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
  estado text not null default 'importando' check (estado in
    ('importando', 'publicado', 'recusado')),
  vigente boolean not null default false,
  arquivo text not null check (arquivo ~ '^TabelaUnificada_[0-9]{6}_v[0-9]{10}\.zip$'),
  versao_arquivo text not null check (versao_arquivo ~ '^[0-9]{10}$'),
  linhas integer not null default 0,
  validos integer not null default 0,
  sem_valor integer not null default 0,
  recusas jsonb not null default '{}'::jsonb,
  recusadas jsonb not null default '[]'::jsonb,
  motivo text not null default '',
  versao_parser text not null default '',
  publicado_em timestamptz,
  criado_em timestamptz not null default now(),
  primary key (competencia, sha256),
  check (not vigente or estado = 'publicado')
);

-- uma versão vigente por competência, no máximo
create unique index if not exists precos_sigtap_versoes_vigente_idx
  on public.precos_sigtap_versoes (competencia) where vigente;

create table if not exists public.precos_sigtap_procedimentos (
  registro_id text primary key,
  chave_linha text not null,
  competencia text not null,
  arquivo_sha256 text not null,
  vigente boolean not null default false,
  codigo text not null check (codigo ~ '^[0-9]{10}$'),
  nome text not null,
  nome_busca text not null,
  complexidade text,
  sexo text,
  valor_sa numeric(14, 2) not null check (valor_sa >= 0),
  valor_sh numeric(14, 2) not null check (valor_sh >= 0),
  valor_sp numeric(14, 2) not null check (valor_sp >= 0),
  financiamento text,
  rubrica text,
  modalidades text[] not null default '{}',
  grupo text,
  subgrupo text,
  forma_organizacao text,
  linha_arquivo integer not null check (linha_arquivo > 0),
  arquivo text not null check (arquivo ~ '^TabelaUnificada_[0-9]{6}_v[0-9]{10}\.zip$'),
  hash_linha text not null,
  versao_parser text not null,
  importado_em timestamptz not null default now(),
  busca tsvector generated always as
    (to_tsvector('portuguese'::regconfig, nome_busca)) stored,
  unique (arquivo_sha256, chave_linha),
  foreign key (competencia, arquivo_sha256)
    references public.precos_sigtap_versoes (competencia, sha256)
);

create index if not exists precos_sigtap_procedimentos_busca_idx
  on public.precos_sigtap_procedimentos using gin (busca) where vigente;
create index if not exists precos_sigtap_procedimentos_codigo_idx
  on public.precos_sigtap_procedimentos (codigo, competencia) where vigente;
create index if not exists precos_sigtap_procedimentos_versao_idx
  on public.precos_sigtap_procedimentos (competencia, arquivo_sha256);

alter table public.precos_sigtap_versoes       enable row level security;
alter table public.precos_sigtap_procedimentos enable row level security;

revoke all on public.precos_sigtap_versoes       from anon, authenticated, public;
revoke all on public.precos_sigtap_procedimentos from anon, authenticated, public;

grant select, insert, update on public.precos_sigtap_versoes       to service_role;
grant select, insert, update on public.precos_sigtap_procedimentos to service_role;
revoke delete, truncate, references, trigger on public.precos_sigtap_versoes       from service_role;
revoke delete, truncate, references, trigger on public.precos_sigtap_procedimentos from service_role;

grant select on public.precos_sigtap_procedimentos to authenticated;
drop policy if exists "precos_sigtap_procedimentos_leitura" on public.precos_sigtap_procedimentos;
create policy "precos_sigtap_procedimentos_leitura" on public.precos_sigtap_procedimentos
  for select to authenticated using (vigente);

create or replace function public.precos_sigtap_buscar(
  p_termos text[],
  p_codigo text default null,
  p_competencia text default null,
  p_modalidade text default null,
  p_limite integer default 50)
returns setof public.precos_sigtap_procedimentos
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
  -- sem competência pedida: a mais recente com procedimento vigente
  alvo as (
    select coalesce(nullif(p_competencia, ''),
                    (select max(r.competencia)
                       from public.precos_sigtap_procedimentos r
                      where r.vigente)) as competencia
  )
  select r.*
    from public.precos_sigtap_procedimentos r, consulta c, alvo a
   where r.vigente
     and r.competencia = a.competencia
     and case when nullif(p_codigo, '') is not null
              then r.codigo = p_codigo
              else r.busca @@ c.q end
     and (nullif(p_modalidade, '') is null or p_modalidade = any (r.modalidades))
   order by case when nullif(p_codigo, '') is not null then 0
                 else ts_rank(r.busca, c.q) end desc,
            r.codigo
   limit least(greatest(coalesce(p_limite, 50), 1), 200)
$$;

comment on function public.precos_sigtap_buscar(text[], text, text, text, integer) is
  'Remuneração da Tabela Unificada do SUS no índice, por código ou termos (0048).';

revoke all on function public.precos_sigtap_buscar(text[], text, text, text, integer)
  from public, anon;
grant execute on function public.precos_sigtap_buscar(text[], text, text, text, integer)
  to authenticated;
grant execute on function public.precos_sigtap_buscar(text[], text, text, text, integer)
  to service_role;

notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  tabela text;
  funcao constant regprocedure :=
    'public.precos_sigtap_buscar(text[], text, text, text, integer)'::regprocedure;
begin
  foreach tabela in array array['precos_sigtap_versoes', 'precos_sigtap_procedimentos'] loop
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

  if has_any_column_privilege('authenticated', 'public.precos_sigtap_versoes', 'select') then
    faltou := faltou || ' authenticated_le_controle_da_importacao';
  end if;
  if not has_table_privilege('authenticated', 'public.precos_sigtap_procedimentos', 'select') then
    faltou := faltou || ' authenticated_sem_leitura';
  end if;
  if (select count(*) from pg_policies
       where schemaname = 'public' and tablename like 'precos\_sigtap\_%' escape '\') <> 1
     or not exists (
       select 1 from pg_policies
        where schemaname = 'public' and tablename = 'precos_sigtap_procedimentos'
          and policyname = 'precos_sigtap_procedimentos_leitura'
          and cmd = 'SELECT' and roles = '{authenticated}'
          and qual = 'vigente') then
    faltou := faltou || ' politica_fora_do_previsto';
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
    raise exception 'A 0048 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
