-- ## 0038 — Base de Conhecimento: `authenticated` executa as funções de busca
-- ## ESTADO: aplicável. AINDA NÃO aplicada em produção.
--
-- O PROBLEMA (produção, 30/10/2026, log e catálogo)
--   A API responde com o JWT do usuário e não tem credencial de servidor
--   (ADR-002). A busca da Base falha para ela:
--     permission denied for function buscar_chunks_textual (42501)
--   Medido no catálogo: as duas funções têm ACL
--   {postgres=X,service_role=X}. O default de `postgres` para função
--   (`pg_default_acl`, tipo f) só concede a `service_role`, e o Streamlit
--   não sentiu porque busca com a credencial de servidor. Na interface
--   nova isso quebra o GovBot e a busca do admin em
--   `POST /base-conhecimento/busca`.
--
-- POR QUE ISTO NÃO ABRE DADO NOVO
--   * as duas funções são `security invoker` (0007): rodam com o papel de
--     quem chama, e o RLS das tabelas vale dentro delas;
--   * `authenticated` JÁ LÊ as duas tabelas (0020), com
--     `tenant_id = tenant_do_jwt()`. O parâmetro `tenant` da função é
--     filtro, não autorização: pedir o tenant de outro órgão devolve zero
--     linhas, porque o RLS decide antes;
--   * `anon` continua sem execução e sem leitura.
--   A concessão é nome a nome, porque cada função foi uma decisão. As
--   `documento_editor_*` seguem só de `service_role` por decisão da ADR-011:
--   esta migração não é sobre "todas as RPCs".
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * a PRÓXIMA função de leitura nasce de novo sem `authenticated`: o default
--     de `postgres` continua estreito, e é assim que deve ser. Concessão a
--     papel de rede tem de ser ato explícito, com a função revisada;
--   * o índice vetorial: `buscar_chunks_vetorial` passa a ser executável, mas
--     quem gera o embedding da consulta é a API, e sem a chave de embeddings
--     a busca segue em modo textual;
--   * a qualidade da busca textual, que é menos precisa que a vetorial.

grant execute on function public.buscar_chunks_textual(text, integer, uuid) to authenticated;
grant execute on function public.buscar_chunks_vetorial(public.vector, integer, uuid) to authenticated;

-- Um `grant` que não pega não levanta erro. Esta conferência é o que prova
-- que o estado afirmado acima existe, inclusive o que NÃO deveria mudar.
do $$
declare
  faltou text := '';
  funcao regprocedure;
begin
  foreach funcao in array array[
    'public.buscar_chunks_textual(text, integer, uuid)'::regprocedure,
    'public.buscar_chunks_vetorial(public.vector, integer, uuid)'::regprocedure
  ] loop
    if not has_function_privilege('authenticated', funcao, 'execute') then
      faltou := faltou || ' authenticated_sem_execute(' || funcao::text || ');';
    end if;
    if has_function_privilege('anon', funcao, 'execute') then
      faltou := faltou || ' anon_executa(' || funcao::text || ');';
    end if;
    -- Toda a garantia acima depende disto: com `security definer`, a função
    -- rodaria como o dono e o RLS deixaria de filtrar por órgão.
    if exists (select 1 from pg_proc p where p.oid = funcao and p.prosecdef) then
      faltou := faltou || ' security_definer(' || funcao::text || ');';
    end if;
  end loop;

  if exists (select 1 from pg_class c
             join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public'
               and c.relname in ('chunks_referencia', 'documentos_referencia')
               and not c.relrowsecurity) then
    faltou := faltou || ' rls_desligado;';
  end if;
  if has_table_privilege('anon', 'public.chunks_referencia', 'select')
     or has_table_privilege('anon', 'public.documentos_referencia', 'select') then
    faltou := faltou || ' anon_le_tabela;';
  end if;
  -- As RPCs de commit documental seguem fora do alcance do JWT (ADR-011).
  if exists (select 1 from pg_proc p
             join pg_namespace n on n.oid = p.pronamespace
             where n.nspname = 'public'
               and p.proname = 'documento_editor_checkpoint'
               and has_function_privilege('authenticated', p.oid, 'execute')) then
    faltou := faltou || ' authenticated_em_commit_documental;';
  end if;

  if faltou <> '' then
    raise exception 'A 0038 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
