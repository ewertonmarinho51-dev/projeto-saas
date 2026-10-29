-- ## 0036 — Governança: escrita por RPC, com a separação de funções e a
-- ##        máquina de estados das versões NO BANCO (interface nova, M8b)
-- ## ESTADO: aplicável. NÃO aplicada em produção.
--
-- O PROBLEMA (auditoria de produção, 27/10/2026, catálogo)
--   O Centro de Governança separa funções — autor, revisor jurídico,
--   publicador, auditor — e versiona cada artefato numa máquina de estados
--   (rascunho → revisão → aprovada → shadow/agendada → publicada →
--   superada/revogada). Essas regras viviam SÓ no Python do Streamlit
--   (`catalogo`, `auth.pode_*`), que escreve com a credencial de servidor.
--   No banco, para o JWT do usuário:
--   * `governanca_versoes` é SÓ leitura (nenhum INSERT/UPDATE);
--   * `governanca_artefatos` tem INSERT direto para `e_admin()` (0020) —
--     sem evento na trilha e com `secretaria_id` livre;
--   * nenhuma política conhece `papel_governanca`.
--   A interface nova escreve com o JWT do usuário (ADR-002). Abrir
--   INSERT/UPDATE nas tabelas daria ao autor o poder de se aprovar e se
--   publicar pelo PostgREST direto: a separação de funções sumiria.
--
-- O QUE FAZ
--   Quatro funções SECURITY DEFINER, `search_path` vazio, executáveis só
--   por `authenticated` — o ÚNICO caminho de escrita pelo JWT:
--   * `governanca_criar_versao(tipo, chave, payload, hash, versao)`: cria o
--     artefato DO MUNICÍPIO (sem secretaria) se não existir, e a próxima
--     versão DRAFT;
--   * `governanca_editar_rascunho(versao, payload, hash, esperado)`: só
--     DRAFT/UNDER_REVIEW, com trava otimista em `atualizado_em`;
--   * `governanca_derivar_versao(versao, hash, proxima)`: de uma
--     PUBLICADA, a próxima versão em rascunho com o MESMO conteúdo (lido do
--     banco, não do cliente) — "editar" o que é imutável;
--   * `governanca_transicionar(versao, novo, esperado, vigencia_inicio)`: a
--     tabela de transições do Python, repetida aqui, com trava otimista:
--     a pessoa aprova/publica o texto que LEU, não o que alguém editou no
--     meio. Publicar SUPERA a anterior.
--   O hash canônico do domínio inclui o NÚMERO da versão; quem calcula é o
--   app, então criar e derivar recebem o número que o app usou e a RPC o
--   confere sob a trava: divergiu, 40001.
--   E mais:
--   * `revoke insert on governanca_artefatos from authenticated`: o INSERT
--     direto da 0020 pulava a trilha;
--   * índice único parcial: UMA versão publicada por artefato — vale também
--     para o Streamlit (credencial de servidor), que não trava nada.
--
-- QUEM PODE O QUÊ — a MATRIZ QUE JÁ EXISTE (0020, `eventos_permitidos_ao_papel`)
--   Cada ato exige poder registrar o evento dele: criar/derivar
--   `versao_criada`; editar `versao_alterada`; transição o evento da
--   transição (`versao_aprovada`, `versao_publicada`, `versao_revogada`, ou
--   `versao_alterada` nos movimentos sem porteiro). Resultado, sem segunda
--   cópia da regra: admins tudo; revisor jurídico só aprova; publicador só
--   publica e revoga (superar vem junto); auditor nada.
--   Papel EFETIVO = `papel_governanca` do JWT; sem ele, o admin opera como
--   `admin_municipal` — a regra do Streamlit (`auth.papel_governanca`).
--   `registrar_evento_governanca` (0020) usa só o do JWT; por isso as RPCs
--   gravam o evento direto (vocabulário fixo, ator = `auth.uid()`).
--
-- ALCANCE (decisão desta migração)
--   Papel amplo: o município inteiro. Revisor e publicador: os artefatos da
--   PRÓPRIA secretaria E os do MUNICÍPIO (`secretaria_id` nulo) — é o que a
--   leitura já mostra a todos (`governanca_artefatos_le`) e o que o Python
--   faz (papel, não secretaria). Sem isto, revisor e publicador não
--   alcançariam nenhum artefato criado aqui e a separação de funções viraria
--   "só o admin faz tudo" (revisão de segurança, 27/10/2026). É mais largo
--   que `registrar_evento_governanca`, que não aceita secretaria nula para
--   papel não amplo; aquela função não é usada por estas.
--
-- AUDITORIA ANTES DE ESCREVER (produção, 27/10/2026)
--   * grants de `authenticated`: artefatos INSERT/SELECT; versões SELECT;
--     eventos SELECT; `anon` sem nada;
--   * políticas: `_le` nas três; `governanca_artefatos_admin` (INSERT);
--   * gatilho `evento_ator_confiavel` em eventos; nenhum em versões;
--   * índices: `unique (artefato_id, versao)`; `governanca_artefatos_chave_idx`
--     único em (tipo, chave, tenant, secretaria); nenhuma unicidade de
--     PUBLISHED; 0 artefatos com duas publicadas;
--   * 1 artefato, 1 versão; `flag_governance_center` não existe.
--
-- O QUE NÃO RESOLVE
--   * a validação do CONTEÚDO (contrato do payload por tipo e o hash
--     canônico) continua no app (`governanca.nova_versao_artefato`): a RPC
--     confere forma (hash hex de 64), não semântica. Quem lê `hash` como
--     prova de integridade do payload confia no app;
--   * artefatos da PLATAFORMA (tenant nulo) e de secretaria não são criados
--     aqui — continuam no Streamlit;
--   * a mesma pessoa pode ser autora e publicadora quando tem papel amplo
--     (admin): separação por PAPEL, não por pessoa — como no Streamlit;
--   * revisor e publicador NÃO movem os estados sem porteiro (revisão,
--     rascunho, shadow, agendada): o Python deixava; aqui é do autor;
--   * imutabilidade da versão publicada vale nestas funções; o Streamlit
--     (credencial de servidor) segue sem barreira no banco — um gatilho de
--     imutabilidade é endurecimento à parte.

-- ---------------------------------------------------------------------------
-- Uma vigente por artefato, para todo mundo (inclusive o Streamlit)
-- ---------------------------------------------------------------------------
create unique index if not exists governanca_versoes_uma_publicada
  on public.governanca_versoes (artefato_id) where status = 'PUBLISHED';

-- O INSERT direto da 0020 pulava a trilha: o caminho agora são as RPCs.
revoke insert on public.governanca_artefatos from authenticated;

-- ---------------------------------------------------------------------------
-- Apoio
-- ---------------------------------------------------------------------------
create or replace function public.papel_governanca_efetivo()
returns text language sql stable
set search_path = ''
as $$
  select coalesce(public.papel_governanca_do_jwt(),
                  case when public.e_admin() then 'admin_municipal' end)
$$;
revoke all on function public.papel_governanca_efetivo() from public, anon;
grant execute on function public.papel_governanca_efetivo() to authenticated;

-- A tabela de transições de `governanca._TRANSICOES_ARTEFATO`.
create or replace function public.governanca_transicao_valida(p_de text, p_para text)
returns boolean language sql immutable
set search_path = ''
as $$
  select coalesce((p_de, p_para) in (
    ('DRAFT', 'UNDER_REVIEW'),
    ('UNDER_REVIEW', 'APPROVED_FOR_SIMULATION'), ('UNDER_REVIEW', 'DRAFT'),
    ('APPROVED_FOR_SIMULATION', 'SHADOW'), ('APPROVED_FOR_SIMULATION', 'UNDER_REVIEW'),
    ('SHADOW', 'SCHEDULED'), ('SHADOW', 'PUBLISHED'), ('SHADOW', 'UNDER_REVIEW'),
    ('SCHEDULED', 'PUBLISHED'), ('SCHEDULED', 'UNDER_REVIEW'),
    ('PUBLISHED', 'SUPERSEDED'), ('PUBLISHED', 'REVOKED')), false)
$$;
revoke all on function public.governanca_transicao_valida(text, text) from public, anon;
grant execute on function public.governanca_transicao_valida(text, text) to authenticated;

-- `trilha.EVENTO_DA_TRANSICAO`: só os estados com porteiro têm ato próprio.
create or replace function public.governanca_evento_da_transicao(p_status text)
returns text language sql immutable
set search_path = ''
as $$
  select case p_status
    when 'APPROVED_FOR_SIMULATION' then 'versao_aprovada'
    when 'PUBLISHED' then 'versao_publicada'
    when 'REVOKED' then 'versao_revogada'
    when 'SUPERSEDED' then 'versao_superada'
    else 'versao_alterada'
  end
$$;
revoke all on function public.governanca_evento_da_transicao(text) from public, anon;
grant execute on function public.governanca_evento_da_transicao(text) to authenticated;

-- Identidade, papel, competência e alcance — num lugar só para as quatro.
-- `p_artefato` nulo só para CRIAR (ainda não há artefato). Devolve o papel.
create or replace function public.governanca_exigir(p_evento text, p_artefato uuid)
returns text language plpgsql stable
set search_path = ''
as $$
declare
  v_papel text := public.papel_governanca_efetivo();
  v_tenant uuid := public.tenant_do_jwt();
begin
  if auth.uid() is null or v_tenant is null then
    raise exception 'sem identidade ou sem tenant no JWT' using errcode = '42501';
  end if;
  if v_papel is null then
    raise exception 'sem papel de governança' using errcode = '42501';
  end if;
  if not (p_evento = any (public.eventos_permitidos_ao_papel(v_papel))) then
    raise exception 'papel % não pode %', v_papel, p_evento using errcode = '42501';
  end if;
  if p_artefato is not null and not exists (
      select 1 from public.governanca_artefatos a
       where a.id = p_artefato and a.tenant_id = v_tenant
         and (public.papel_alcanca_o_tenant(v_papel)
              or a.secretaria_id is null
              or a.secretaria_id = public.secretaria_do_jwt())) then
    -- Inexistente, da plataforma, de outro tenant ou de outra secretaria:
    -- a MESMA resposta (não é sonda de existência).
    raise exception 'artefato fora do seu alcance' using errcode = '42501';
  end if;
  return v_papel;
end
$$;
revoke all on function public.governanca_exigir(text, uuid) from public, anon, authenticated;

create or replace function public.governanca_evento(p_tipo text, p_versao uuid, p_payload jsonb)
returns void language sql volatile
set search_path = ''
as $$
  insert into public.governanca_eventos (tenant_id, ator, tipo_evento, entidade_tipo, entidade_id, payload)
  values (public.tenant_do_jwt(), auth.uid(), p_tipo, 'versao', p_versao, coalesce(p_payload, '{}'::jsonb))
$$;
revoke all on function public.governanca_evento(text, uuid, jsonb) from public, anon, authenticated;

create or replace function public.governanca_usuario_do_jwt()
returns uuid language sql stable
set search_path = ''
as $$
  select u.id from public.usuarios u where u.auth_user_id = auth.uid() limit 1
$$;
revoke all on function public.governanca_usuario_do_jwt() from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- As quatro RPCs
-- ---------------------------------------------------------------------------
create or replace function public.governanca_criar_versao(
  p_tipo text, p_chave text, p_payload jsonb, p_hash text, p_versao integer)
returns uuid language plpgsql security definer
set search_path = ''
as $$
declare
  v_tenant uuid := public.tenant_do_jwt();
  v_artefato uuid;
  v_novo boolean := false;
  v_proxima integer;
  v_versao uuid;
begin
  perform public.governanca_exigir('versao_criada', null);
  if coalesce(p_tipo, '') not in ('clausula', 'politica', 'familia', 'template') then
    raise exception 'tipo de artefato inválido' using errcode = '22023';
  end if;
  if coalesce(p_chave, '') !~ '^[a-z0-9][a-z0-9._-]{2,}$' or length(p_chave) > 200 then
    raise exception 'chave estável inválida' using errcode = '22023';
  end if;
  if coalesce(p_hash, '') !~ '^[0-9a-f]{64}$' or coalesce(jsonb_typeof(p_payload), '') <> 'object' then
    raise exception 'conteúdo inválido' using errcode = '22023';
  end if;

  -- Só o artefato DO MUNICÍPIO (sem secretaria): a busca é determinística.
  perform pg_advisory_xact_lock(hashtext('governanca:' || v_tenant::text || ':' || p_tipo || ':' || p_chave));
  select a.id into v_artefato from public.governanca_artefatos a
   where a.tenant_id = v_tenant and a.secretaria_id is null
     and a.tipo_artefato = p_tipo and a.chave_estavel = p_chave;
  if v_artefato is null then
    perform public.governanca_exigir('artefato_criado', null);
    insert into public.governanca_artefatos (tenant_id, tipo_artefato, chave_estavel)
    values (v_tenant, p_tipo, p_chave) returning id into v_artefato;
    v_novo := true;
  else
    perform public.governanca_exigir('versao_criada', v_artefato);
    -- A mesma trava da derivação e das transições.
    perform 1 from public.governanca_artefatos where id = v_artefato for update;
  end if;

  select coalesce(max(v.versao), 0) + 1 into v_proxima
    from public.governanca_versoes v where v.artefato_id = v_artefato;
  if p_versao is distinct from v_proxima then
    raise exception 'outra versão foi criada no meio: recarregue' using errcode = '40001';
  end if;
  insert into public.governanca_versoes (artefato_id, versao, status, payload, hash, autor)
  values (v_artefato, v_proxima, 'DRAFT', p_payload, p_hash, public.governanca_usuario_do_jwt())
  returning id into v_versao;

  if v_novo then
    insert into public.governanca_eventos (tenant_id, ator, tipo_evento, entidade_tipo, entidade_id, payload)
    values (v_tenant, auth.uid(), 'artefato_criado', 'artefato', v_artefato,
            jsonb_build_object('tipo_artefato', p_tipo, 'chave', p_chave));
  end if;
  perform public.governanca_evento('versao_criada', v_versao, jsonb_build_object(
    'tipo_artefato', p_tipo, 'chave', p_chave, 'versao', v_proxima, 'origem', 'rascunho_criado'));
  return v_versao;
end
$$;

create or replace function public.governanca_editar_rascunho(
  p_versao uuid, p_payload jsonb, p_hash text, p_esperado timestamptz)
returns timestamptz language plpgsql security definer
set search_path = ''
as $$
declare
  v public.governanca_versoes%rowtype;
  v_agora timestamptz := clock_timestamp();  -- não `now()`: a trava compara instantes, e `now()` é o início da transação
begin
  select * into v from public.governanca_versoes where id = p_versao for update;
  if v.id is null then
    raise exception 'artefato fora do seu alcance' using errcode = '42501';
  end if;
  perform public.governanca_exigir('versao_alterada', v.artefato_id);
  if v.status not in ('DRAFT', 'UNDER_REVIEW') then
    raise exception 'versão publicada é imutável: derive uma nova' using errcode = '55000';
  end if;
  if p_esperado is null or v.atualizado_em <> p_esperado then
    raise exception 'a versão mudou desde a sua leitura' using errcode = '40001';
  end if;
  if coalesce(p_hash, '') !~ '^[0-9a-f]{64}$' or coalesce(jsonb_typeof(p_payload), '') <> 'object' then
    raise exception 'conteúdo inválido' using errcode = '22023';
  end if;
  update public.governanca_versoes
     set payload = p_payload, hash = p_hash, atualizado_em = v_agora
   where id = p_versao;
  perform public.governanca_evento('versao_alterada', p_versao, jsonb_build_object(
    'versao', v.versao, 'origem', 'rascunho_editado'));
  return v_agora;
end
$$;

create or replace function public.governanca_derivar_versao(
  p_versao uuid, p_hash text, p_proxima integer)
returns uuid language plpgsql security definer
set search_path = ''
as $$
declare
  v public.governanca_versoes%rowtype;
  v_proxima integer;
  v_nova uuid;
begin
  select * into v from public.governanca_versoes where id = p_versao;
  if v.id is null then
    raise exception 'artefato fora do seu alcance' using errcode = '42501';
  end if;
  perform public.governanca_exigir('versao_criada', v.artefato_id);
  -- A trava do artefato serializa derivações, criações e publicações; o
  -- status é relido DEPOIS dela (pode ter sido superada no meio).
  perform 1 from public.governanca_artefatos where id = v.artefato_id for update;
  select * into v from public.governanca_versoes where id = p_versao;
  if v.status <> 'PUBLISHED' then
    raise exception 'só se deriva de uma versão publicada' using errcode = '55000';
  end if;
  select coalesce(max(x.versao), 0) + 1 into v_proxima
    from public.governanca_versoes x where x.artefato_id = v.artefato_id;
  if p_proxima is distinct from v_proxima then
    raise exception 'outra versão foi criada no meio: recarregue' using errcode = '40001';
  end if;
  if coalesce(p_hash, '') !~ '^[0-9a-f]{64}$' then
    raise exception 'conteúdo inválido' using errcode = '22023';
  end if;
  insert into public.governanca_versoes (artefato_id, versao, status, payload, hash, autor)
  values (v.artefato_id, v_proxima, 'DRAFT', v.payload, p_hash, public.governanca_usuario_do_jwt())
  returning id into v_nova;
  perform public.governanca_evento('versao_criada', v_nova, jsonb_build_object(
    'de', v.versao, 'para', v_proxima, 'origem', 'versao_derivada'));
  return v_nova;
end
$$;

create or replace function public.governanca_transicionar(
  p_versao uuid, p_novo text, p_esperado timestamptz, p_vigencia_inicio timestamptz default null)
returns text language plpgsql security definer
set search_path = ''
as $$
declare
  v public.governanca_versoes%rowtype;
  v_evento text := public.governanca_evento_da_transicao(p_novo);
  v_usuario uuid := public.governanca_usuario_do_jwt();
  anterior record;
begin
  if p_novo is null or p_novo = 'SUPERSEDED' then
    -- Superar é efeito de publicar outra versão, nunca pedido.
    raise exception 'transição inválida' using errcode = '22023';
  end if;
  select * into v from public.governanca_versoes where id = p_versao;
  if v.id is null then
    raise exception 'artefato fora do seu alcance' using errcode = '42501';
  end if;
  -- Competência pelo evento DA TRANSIÇÃO: revisor só aprova, publicador
  -- só publica/revoga, auditor nada — a matriz da 0020, sem cópia.
  perform public.governanca_exigir(v_evento, v.artefato_id);
  -- Serializa transições do mesmo artefato (duas publicações ao mesmo tempo).
  perform 1 from public.governanca_artefatos where id = v.artefato_id for update;
  select * into v from public.governanca_versoes where id = p_versao for update;
  -- Aprova/publica o texto que a pessoa LEU: editado no meio, recusa.
  if p_esperado is null or v.atualizado_em <> p_esperado then
    raise exception 'a versão mudou desde a sua leitura' using errcode = '40001';
  end if;
  if not public.governanca_transicao_valida(v.status, p_novo) then
    raise exception 'transição inválida: % → %', v.status, p_novo using errcode = '22023';
  end if;

  if p_novo = 'PUBLISHED' then
    -- Uma vigente por vez: a publicada anterior é SUPERADA (evento próprio).
    perform public.governanca_exigir('versao_superada', v.artefato_id);
    for anterior in
      select x.id, x.versao from public.governanca_versoes x
       where x.artefato_id = v.artefato_id and x.status = 'PUBLISHED' and x.id <> v.id
    loop
      update public.governanca_versoes set status = 'SUPERSEDED', atualizado_em = clock_timestamp()
       where id = anterior.id;
      perform public.governanca_evento('versao_superada', anterior.id,
                                       jsonb_build_object('versao', anterior.versao));
    end loop;
    -- `vigencia_inicio` como o Python: só o que foi pedido (nulo = já).
    update public.governanca_versoes
       set status = 'PUBLISHED', aprovador = v_usuario,
           vigencia_inicio = p_vigencia_inicio, atualizado_em = clock_timestamp()
     where id = p_versao;
  elsif p_novo = 'APPROVED_FOR_SIMULATION' then
    update public.governanca_versoes
       set status = p_novo, revisor = v_usuario, atualizado_em = clock_timestamp() where id = p_versao;
  else
    update public.governanca_versoes set status = p_novo, atualizado_em = clock_timestamp() where id = p_versao;
  end if;

  perform public.governanca_evento(v_evento, p_versao, jsonb_build_object(
    'versao', v.versao, 'de', v.status, 'status', p_novo));
  return p_novo;
end
$$;

revoke all on function public.governanca_criar_versao(text, text, jsonb, text, integer) from public, anon;
revoke all on function public.governanca_editar_rascunho(uuid, jsonb, text, timestamptz) from public, anon;
revoke all on function public.governanca_derivar_versao(uuid, text, integer) from public, anon;
revoke all on function public.governanca_transicionar(uuid, text, timestamptz, timestamptz) from public, anon;
grant execute on function public.governanca_criar_versao(text, text, jsonb, text, integer) to authenticated;
grant execute on function public.governanca_editar_rascunho(uuid, jsonb, text, timestamptz) to authenticated;
grant execute on function public.governanca_derivar_versao(uuid, text, integer) to authenticated;
grant execute on function public.governanca_transicionar(uuid, text, timestamptz, timestamptz) to authenticated;

-- Conferência que falha sozinha.
do $$
declare faltou text;
begin
  select string_agg(item, ', ') into faltou from (
    -- as quatro existem, são definer, com search_path vazio, e authenticated executa
    select 'rpc_' || f as item
      from unnest(array['governanca_criar_versao', 'governanca_editar_rascunho',
                        'governanca_derivar_versao', 'governanca_transicionar']) f
     where not exists (select 1 from pg_proc p
                        where p.pronamespace = 'public'::regnamespace and p.proname = f
                          and p.prosecdef and p.proconfig @> array['search_path=""']
                          and has_function_privilege('authenticated', p.oid, 'EXECUTE'))
    union all
    -- ninguém de fora executa
    select 'execucao_' || p.proname || '_' || r
      from pg_proc p, unnest(array['anon', 'public']) r
     where p.pronamespace = 'public'::regnamespace
       and p.proname in ('governanca_criar_versao', 'governanca_editar_rascunho',
                         'governanca_derivar_versao', 'governanca_transicionar')
       and has_function_privilege(r, p.oid, 'EXECUTE')
    union all
    -- os apoios internos não são chamáveis de fora
    select 'apoio_exposto_' || p.proname
      from pg_proc p
     where p.pronamespace = 'public'::regnamespace
       and p.proname in ('governanca_exigir', 'governanca_evento', 'governanca_usuario_do_jwt')
       and (has_function_privilege('authenticated', p.oid, 'EXECUTE')
            or has_function_privilege('anon', p.oid, 'EXECUTE')
            or has_function_privilege('public', p.oid, 'EXECUTE'))
    union all
    -- e as tabelas seguem SEM escrita direta (tabela e coluna)
    select 'escrita_direta_em_' || t
      from unnest(array['governanca_artefatos', 'governanca_versoes', 'governanca_eventos']) t
     where has_table_privilege('authenticated', 'public.' || t, 'INSERT,UPDATE,DELETE,TRUNCATE')
        or has_any_column_privilege('authenticated', 'public.' || t, 'INSERT,UPDATE')
    union all
    select 'anon_em_' || t
      from unnest(array['governanca_artefatos', 'governanca_versoes', 'governanca_eventos']) t
     where has_table_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
        or has_any_column_privilege('anon', 'public.' || t, 'SELECT,INSERT,UPDATE')
    union all
    select 'rls_desligado_em_' || c.relname
      from pg_class c
     where c.oid in ('public.governanca_artefatos'::regclass, 'public.governanca_versoes'::regclass,
                     'public.governanca_eventos'::regclass)
       and not c.relrowsecurity
    union all
    -- as redes de proteção de que as RPCs dependem
    select 'sem_indice_uma_publicada'
     where not exists (select 1 from pg_indexes where schemaname = 'public'
                          and indexname = 'governanca_versoes_uma_publicada')
    union all
    select 'sem_gatilho_ator_confiavel'
     where not exists (select 1 from pg_trigger
                        where tgrelid = 'public.governanca_eventos'::regclass
                          and tgname = 'evento_ator_confiavel' and not tgisinternal)
  ) achados;
  if faltou is not null then
    raise exception 'A 0036 não cumpriu o que afirma: %', faltou;
  end if;
end
$$;
