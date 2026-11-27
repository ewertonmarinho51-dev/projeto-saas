-- ## 0051 — A resolução de escopo de aprovação deixa de ser RPC pública
-- ## ESTADO: aplicável; NÃO aplicada em produção ainda.
-- ## ENSAIO: CI (`tests/test_migracao_0051.py`, PostgreSQL).
--
-- O ACHADO (27/11/2026, revisão de segurança + `get_advisors` do Supabase)
--   `public.aprovacao_no_escopo(p_aprovacao, p_tenant, p_secretaria, p_papel)`
--   é SECURITY DEFINER (lê governança atravessando o RLS) e recebe o ESCOPO
--   como argumento. A 0020 concedeu EXECUTE a `authenticated`, então qualquer
--   usuário logado a chama por `/rest/v1/rpc/aprovacao_no_escopo` passando o
--   tenant de OUTRA prefeitura e um papel que alcança o tenant inteiro — e a
--   resposta diz se aquela aprovação existe lá. É um oráculo de existência
--   entre tenants: só booleano, só para quem já conhece o UUID, mas é
--   exatamente a fronteira que a 0020 existe para guardar.
--
--   Ninguém precisa dela por fora. A única chamadora é
--   `registrar_evento_governanca`, que também é SECURITY DEFINER e roda como
--   o DONO (`postgres`), que mantém o EXECUTE. Nenhuma política de RLS, nem o
--   app (`src/`), nem a API (`apps/`) a chama. Medido no catálogo de produção
--   em 27/11/2026.
--
-- A CLASSE, NÃO SÓ A INSTÂNCIA
--   A classe é: função SECURITY DEFINER que aceita tenant/secretaria/papel/
--   usuário como ARGUMENTO e está aberta a `authenticated`. No catálogo de
--   produção (27/11/2026) ela tem UM membro, este. As outras oito
--   SECURITY DEFINER executáveis por `authenticated` tiram o escopo do JWT
--   (`tenant_do_jwt`, `governanca_exigir`). A fábrica já está fechada:
--   o default ACL de funções criadas por `postgres` em `public` não concede
--   EXECUTE a `anon` nem a `authenticated`. A conferência abaixo mede a
--   CLASSE, não o nome: a próxima função desse formato reprova aqui.
--
-- O QUE FAZ
--   * revoga EXECUTE de `authenticated` (e reafirma de `public`/`anon`);
--   * mantém `service_role` (o servidor pode precisar) e o dono.
--
-- O QUE ESTA MIGRAÇÃO NÃO RESOLVE
--   * as outras SECURITY DEFINER continuam chamáveis por `authenticated`, de
--     propósito: são as RPCs de escrita da governança e da pesquisa de
--     preços, e cada uma recusa fora do escopo do JWT;
--   * o alerta `extension_in_public` (pgvector em `public`) segue aberto;
--     mover a extensão mexe no tipo das colunas de embedding e é outra
--     migração, com ensaio próprio;
--   * a proteção contra senha vazada do Supabase Auth é configuração do
--     painel, não SQL.

revoke all on function public.aprovacao_no_escopo(uuid, uuid, uuid, text)
  from public, anon, authenticated;
grant execute on function public.aprovacao_no_escopo(uuid, uuid, uuid, text)
  to service_role;

-- Conferência que falha sozinha: um `revoke` que não pega não levanta erro.
do $$
declare
  faltou text;
  dono   oid;
begin
  -- 1) a classe inteira: SECURITY DEFINER com escopo em argumento, aberta
  --    a `anon` ou `authenticated`
  select string_agg(p.oid::regprocedure::text, ', ') into faltou
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
   where n.nspname = 'public' and p.prokind = 'f' and p.prosecdef
     and pg_get_function_identity_arguments(p.oid)
         ~* '\m(p_tenant|p_secretaria|p_papel|p_auth_user|p_usuario)\M'
     and (has_function_privilege('authenticated', p.oid, 'execute')
          or has_function_privilege('anon', p.oid, 'execute'));
  if faltou is not null then
    raise exception 'A 0051 não cumpriu o que afirma: escopo em argumento aberto a usuário: %', faltou;
  end if;

  -- 2) a chamadora continua podendo chamar: quem executa o corpo de
  --    `registrar_evento_governanca` é o dono dela
  select p.proowner into dono
    from pg_proc p join pg_namespace n on n.oid = p.pronamespace
   where n.nspname = 'public' and p.proname = 'registrar_evento_governanca';
  if dono is null or not has_function_privilege(
       dono, 'public.aprovacao_no_escopo(uuid, uuid, uuid, text)', 'execute') then
    raise exception 'A 0051 não cumpriu o que afirma: o dono de registrar_evento_governanca perdeu o EXECUTE';
  end if;
end
$$;
