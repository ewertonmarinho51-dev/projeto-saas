-- ## 0040 — Lista de processos: quais documentos existem, sem trazer o texto
-- ## ESTADO: APLICÁVEL. NÃO aplicada em produção.
--
-- O PROBLEMA (produção, 01/11/2026, medido)
--   `GET /processos` lia `dados` e `documentos` inteiros de cada linha para
--   calcular status, etapa e progresso. Com 8 processos, cada listagem trazia
--   1,22 MB de São Paulo até a VPS: o texto de todos os DFD, ETP e TR e as
--   planilhas de itens. Início e Processos levavam 1,4 s até o conteúdo, contra
--   600 ms de Preços, e o custo cresce a cada processo.
--
--   Dos documentos, o cálculo só pergunta QUAIS existem. Os campos de `dados` o
--   PostgREST já recorta por caminho JSON; o conjunto de chaves de um objeto
--   ele não sabe devolver sem trazer os valores. Daí esta função.
--
-- O QUE FAZ
--   `documentos_gerados(processos)`: os nomes das chaves de `documentos`
--   (`dfd`, `etp`...), nunca o texto. Recebe a linha da tabela, o que no
--   PostgREST a torna campo calculado: `select=id,documentos_gerados`.
--
-- POR QUE ISTO NÃO ABRE DADO NOVO
--   * `security invoker` e recebe uma linha que quem chama já leu: o RLS de
--     `processos` (0020) decide antes. Fora do órgão, a linha não chega;
--   * `authenticated` já lê a coluna `documentos` inteira. O nome da chave é
--     parte do que ele já vê;
--   * `anon` continua sem execução e sem leitura.
--   Concessão nome a nome: o default de `postgres` para função só alcança
--   `service_role` (a mesma razão da 0038).
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * a rede: uma consulta segue custando cerca de 170 ms da VPS ao Supabase;
--   * as rotas que precisam do texto continuam lendo `documentos` inteiro;
--   * `api-rls` e o ensaio provam o comportamento; a medição do ganho só existe
--     em produção, depois de aplicar.
--
-- ORDEM: esta migração ANTES da imagem que usa `documentos_gerados`. Ao
-- contrário quebra a lista: o PostgREST recusa coluna que não conhece.

create or replace function public.documentos_gerados(processo public.processos)
returns text[]
language sql
stable
security invoker
set search_path = ''
as $$
  select coalesce(array_agg(chave order by chave), '{}'::text[])
  from jsonb_object_keys(
    case when jsonb_typeof(processo.documentos) = 'object'
         then processo.documentos else '{}'::jsonb end
  ) as chave
$$;

comment on function public.documentos_gerados(public.processos) is
  'Nomes dos documentos gerados do processo, sem o texto. Campo calculado da lista (0040).';

revoke all on function public.documentos_gerados(public.processos) from public, anon;
grant execute on function public.documentos_gerados(public.processos) to authenticated;
grant execute on function public.documentos_gerados(public.processos) to service_role;

-- O PostgREST guarda o esquema em cache: sem isto, a função nova não existe
-- para ele até o próximo recarregamento.
notify pgrst, 'reload schema';

do $$
declare
  faltou text := '';
  funcao constant regprocedure := 'public.documentos_gerados(public.processos)'::regprocedure;
begin
  if (select prosecdef from pg_proc where oid = funcao) then
    faltou := faltou || ' security_definer';
  end if;
  if (select provolatile from pg_proc where oid = funcao) <> 's' then
    faltou := faltou || ' nao_estavel';
  end if;
  if not has_function_privilege('authenticated', funcao, 'execute') then
    faltou := faltou || ' authenticated_sem_execute';
  end if;
  if has_function_privilege('anon', funcao, 'execute') then
    faltou := faltou || ' anon_executa';
  end if;
  if has_table_privilege('anon', 'public.processos', 'select') then
    faltou := faltou || ' anon_le_tabela';
  end if;
  if not (select relrowsecurity from pg_class where oid = 'public.processos'::regclass) then
    faltou := faltou || ' rls_desligado';
  end if;
  if faltou <> '' then
    raise exception 'A 0040 não cumpriu o que afirma:%', faltou;
  end if;
end
$$;
