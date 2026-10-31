-- ## 0037 — Fatos canônicos: substituir e confirmar por RPC (interface nova, Issue #138 M1)
-- ## ESTADO: APLICADA EM PRODUÇÃO em 31/10/2026 como
-- ##   `m0037_fatos_canonicos_transicao_por_rpc` (registro 20261031142917), por
-- ##   autorização expressa do dono, depois do ensaio no projeto descartável
-- ##   `govdocs-ensaio-descartavel` no mesmo dia.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (31/10/2026):
--   * ANTES: 864 confirmados, 306 extraídos, 1 substituído; 7 processos, 1
--     documento nativo; 95 grants de tabela a `authenticated`, 0 a `anon`; 104
--     políticas em public; `authenticated` com INSERT e SELECT em
--     `fatos_canonicos`; 170 funções em public; função ausente;
--   * aplicação: conferência interna aprovada;
--   * DEPOIS: mesmos fatos (hash por id, status e autor idêntico), 7 processos,
--     1 documento; 95 e 0 grants; 104 políticas; INSERT e SELECT; 171 funções.
--     `authenticated` executa, `anon` não. Corpo com o mesmo md5 do descartável.
--     Chamada sem identidade: 42501, sem tocar dado;
--   * COMPORTAMENTO, no descartável, num bloco desfeito com tenants próprios:
--     colega, admin de outro tenant, conta inativa, processo inexistente e
--     `anon` = 42501; id de outro processo = PT409, sem mudar nada; confirmado e
--     disputado = PT409; lista duplicada ou sobreposta = 22023; titular e admin
--     passam, com `confirmado_por` do banco; UPDATE direto = 42501;
--   * advisors: só um aviso novo, a própria RPC (authenticated, intencional).
--
-- O PROBLEMA (catálogo de produção, 30/10/2026)
--   A aprovação nativa de documento exige que TODO fato vigente do processo
--   esteja `confirmado` (`DocumentoService.aprovar`). Quem confirma é a pessoa:
--   o Streamlit mostra os fatos e chama `fatos.confirmar_todos`, que faz UPDATE
--   com a credencial de servidor. Em `fatos_canonicos`, o JWT do usuário tem só
--   SELECT e INSERT (0020), e a tabela tem FORCE RLS e nenhuma política de
--   UPDATE. Pela API (ADR-002) a confirmação não passa, e sem ela nenhum
--   documento se aprova na interface nova.
--   Em produção: 864 confirmados, 306 extraídos, 1 substituído.
--
-- O QUE FAZ
--   Uma função SECURITY DEFINER, `search_path` vazio, executável só por
--   `authenticated`: `fatos_canonicos_transicionar(processo, substituir,
--   confirmar)`. São as duas únicas transições que o domínio faz
--   (`fatos.sincronizar` e `fatos.confirmar_todos`), numa transação:
--   * quem pode é quem já pode lançar fato (política `fatos_canonicos_escreve`
--     da 0020): tenant do JWT, leitura do processo, e ser o TITULAR ou admin.
--     Reler o processo do colega não dá direito de confirmar fato nele;
--   * `extraido → confirmado`, com `confirmado_por` lido do banco (a linha de
--     `usuarios` do JWT), nunca do pedido;
--   * `vigente → substituido`. Nenhuma outra transição: valor, path, versão e
--     `disputado` não passam por aqui;
--   * lista fechada de ids: cada um precisa ser do processo e estar no estado
--     de origem. Faltou um, nada muda e sobe `PT409` (o PostgREST devolve 409):
--     a pessoa confirma o que LEU, não o que entrou depois.
--   Mesma resposta (42501) para processo inexistente, de outro município e sem
--   permissão: não é sonda de existência.
--
-- POR QUE NÃO `grant update` + política
--   Coluna liberada deixaria o titular pôr qualquer status e qualquer
--   `confirmado_por` pelo PostgREST direto. A RPC mantém a tabela sem escrita
--   de UPDATE para o JWT, e a conferência no fim mede isso.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * Não muda o Streamlit: ele segue com a credencial de servidor.
--   * Não grava evento em `governanca_eventos`: `confirmado_por` continua sendo
--     o único rastro, como hoje no legado. Trilha própria é decisão à parte.
--   * Sincronizar é INSERT + esta RPC, sem transação comum. Falha no meio
--     deixa versão nova ao lado da vigente, como já acontece no legado; a
--     próxima sincronização reconcilia, e fato não confirmado barra a aprovação.
--   * Não confere a matriz de competência de aprovação: isso é da
--     `documento_editor_aprovar`.

create or replace function public.fatos_canonicos_transicionar(
  p_processo uuid,
  p_substituir uuid[],
  p_confirmar uuid[]
)
returns integer language plpgsql security definer
set search_path = ''
as $$
declare
  v_tenant uuid := public.tenant_do_jwt();
  v_processo record;
  v_usuario uuid;
  v_substituir uuid[] := coalesce(p_substituir, '{}');
  v_confirmar uuid[] := coalesce(p_confirmar, '{}');
  v_mudou integer;
  v_total integer := 0;
begin
  if auth.uid() is null or v_tenant is null then
    raise exception 'sem identidade ou sem tenant no JWT' using errcode = '42501';
  end if;
  -- Trava o processo: duas abas confirmando não se atropelam.
  select p.id, p.tenant_id, p.secretaria_id, p.auth_user_id into v_processo
    from public.processos p
   where p.id = p_processo
   for update;
  if not found
     or v_processo.tenant_id is distinct from v_tenant
     or not public.pode_ler_processo(v_processo.tenant_id, v_processo.secretaria_id)
     or not (v_processo.auth_user_id = auth.uid() or public.e_admin()) then
    raise exception 'processo fora do seu alcance' using errcode = '42501';
  end if;
  select u.id into v_usuario
    from public.usuarios u
   where u.auth_user_id = auth.uid() and u.tenant_id = v_tenant and u.ativo
   limit 1;
  if v_usuario is null then
    raise exception 'sem vínculo ativo' using errcode = '42501';
  end if;
  if cardinality(v_substituir) > 1000 or cardinality(v_confirmar) > 1000 then
    raise exception 'lote de fatos excessivo' using errcode = '22023';
  end if;
  -- Duplicado e sobreposição derrubariam a contagem abaixo sem dizer por quê.
  if cardinality(v_substituir) <> (select count(distinct i) from unnest(v_substituir) i)
     or cardinality(v_confirmar) <> (select count(distinct i) from unnest(v_confirmar) i)
     or v_substituir && v_confirmar then
    raise exception 'lista de fatos ambígua' using errcode = '22023';
  end if;

  update public.fatos_canonicos f set status = 'substituido'
   where f.id = any (v_substituir) and f.processo_id = p_processo
     and f.tenant_id = v_tenant and f.status <> 'substituido';
  get diagnostics v_mudou = row_count;
  if v_mudou <> cardinality(v_substituir) then
    raise exception 'os fatos mudaram: recarregue' using errcode = 'PT409';
  end if;
  v_total := v_mudou;

  update public.fatos_canonicos f set status = 'confirmado', confirmado_por = v_usuario
   where f.id = any (v_confirmar) and f.processo_id = p_processo
     and f.tenant_id = v_tenant and f.status = 'extraido';
  get diagnostics v_mudou = row_count;
  if v_mudou <> cardinality(v_confirmar) then
    raise exception 'os fatos mudaram: recarregue' using errcode = 'PT409';
  end if;
  return v_total + v_mudou;
end
$$;
revoke all on function public.fatos_canonicos_transicionar(uuid, uuid[], uuid[]) from public, anon;
grant execute on function public.fatos_canonicos_transicionar(uuid, uuid[], uuid[]) to authenticated;

-- ---------------------------------------------------------------------------
-- Conferência: um `revoke` que não pega não levanta erro.
-- ---------------------------------------------------------------------------
do $$
declare faltou text;
begin
  select string_agg(item, ', ') into faltou from (
    select 'sem_funcao' item
     where to_regprocedure('public.fatos_canonicos_transicionar(uuid, uuid[], uuid[])') is null
    union all
    select 'funcao_sem_security_definer_ou_search_path'
      from pg_proc p
     where p.oid = to_regprocedure('public.fatos_canonicos_transicionar(uuid, uuid[], uuid[])')
       and not (p.prosecdef and coalesce(p.proconfig, '{}') @> array['search_path=""'])
    union all
    select 'anon_ou_public_executa'
      from pg_proc p
     where p.oid = to_regprocedure('public.fatos_canonicos_transicionar(uuid, uuid[], uuid[])')
       and (has_function_privilege('anon', p.oid, 'EXECUTE')
            or exists (select 1 from aclexplode(p.proacl) a where a.grantee = 0 and a.privilege_type = 'EXECUTE'))
    union all
    select 'authenticated_nao_executa'
     where not has_function_privilege('authenticated',
             'public.fatos_canonicos_transicionar(uuid, uuid[], uuid[])', 'EXECUTE')
    union all
    -- a tabela segue sem UPDATE/DELETE direto, nem por coluna
    select 'escrita_direta_em_fatos'
     where has_table_privilege('authenticated', 'public.fatos_canonicos', 'UPDATE,DELETE,TRUNCATE')
        or has_any_column_privilege('authenticated', 'public.fatos_canonicos', 'UPDATE')
    union all
    select 'anon_em_fatos'
     where has_table_privilege('anon', 'public.fatos_canonicos', 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE')
        or has_any_column_privilege('anon', 'public.fatos_canonicos', 'SELECT,INSERT,UPDATE')
    union all
    select 'rls_desligado_em_fatos'
      from pg_class c
     where c.oid = 'public.fatos_canonicos'::regclass
       and not (c.relrowsecurity and c.relforcerowsecurity)
  ) achados;
  if faltou is not null then
    raise exception 'A 0037 não cumpriu o que afirma: %', faltou;
  end if;
end
$$;
