-- ## 0040 — Lista de processos: quais documentos existem, sem trazer o texto
-- ## ESTADO: APLICADA EM PRODUÇÃO em 08/11/2026 como `m0040_documentos_gerados`,
-- ##   por autorização expressa do dono, depois do ensaio nos dois níveis.
--
-- REGISTRO DA APLICAÇÃO EM PRODUÇÃO (08/11/2026):
--   * ANTES: 8 processos; 104 políticas em public; 95 grants de tabela a
--     `authenticated`, 0 a `anon`; função inexistente; RLS de `processos` ligado;
--     `dados` + `documentos` somavam 1.221.545 bytes de texto;
--   * aplicação: conferência interna aprovada;
--   * DEPOIS: 8 processos, 104 políticas, 95 e 0 grants (nada mudou além da
--     função); ACL `{postgres, service_role, authenticated}`, `security invoker`,
--     `search_path=""`; os nomes dos documentos dos 8 processos somam 107 bytes;
--   * comportamento, num bloco desfeito, com dois órgãos sintéticos criados e
--     apagados na hora: o próprio órgão viu `{dfd,etp}` sem texto, o outro órgão
--     0 linhas, `anon` recusado (42501). Nenhum resíduo depois do bloco;
--   * advisors de segurança: nada sobre a função; os listados são anteriores.
--
-- REGISTRO DO ENSAIO (01/11/2026):
--   * nível 1: PostgreSQL do CI (`tests/test_migracao_0040.py`, ensaio
--     obrigatório), com cada ramo da conferência sob mutação;
--   * nível 2, descartável: ACL igual à de produção depois da aplicação;
--     comportamento idêntico ao registrado acima, num bloco desfeito;
--   * revisão do `revisor-de-banco-e-seguranca`: segura; os três reforços que
--     sugeriu (service_role, search_path, grant por coluna) entraram.
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
  -- Sem caminho de busca: um `create or replace` futuro que o perca passaria a
  -- resolver nomes pelo `search_path` de quem chama.
  if not coalesce((select proconfig from pg_proc where oid = funcao) @> array['search_path=""'], false) then
    faltou := faltou || ' sem_search_path_vazio';
  end if;
  if not has_function_privilege('authenticated', funcao, 'execute') then
    faltou := faltou || ' authenticated_sem_execute';
  end if;
  if not has_function_privilege('service_role', funcao, 'execute') then
    faltou := faltou || ' service_role_sem_execute';
  end if;
  if has_function_privilege('anon', funcao, 'execute') then
    faltou := faltou || ' anon_executa';
  end if;
  -- Por coluna também: um grant de coluna a `anon` não aparece em `has_table_privilege`.
  if has_any_column_privilege('anon', 'public.processos', 'select') then
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
