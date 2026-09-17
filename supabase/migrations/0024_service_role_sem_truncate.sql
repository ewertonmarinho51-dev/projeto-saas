-- ############################################################
-- ##  0024 — TRUNCATE fora do alcance da credencial de servidor
-- ##
-- ##  ESTADO: APLICÁVEL. Só revoga privilégio e estreita o
-- ##  default. Não cria tabela, não altera coluna, não apaga
-- ##  dado, não mexe em política de RLS nem em credencial.
-- ##
-- ##  NÃO APLICADA EM PRODUÇÃO por este arquivo. Quando for,
-- ##  este cabeçalho registra a data, como a 0022 e a 0023.
-- ############################################################

-- ===============================================================
-- O ACHADO
--
-- Medido em produção em 17/09/2026: `service_role` tinha TRUNCATE em
-- 26 das 32 tabelas do schema `public`. As 6 de fora não foram
-- decisão de arquitetura — foram as 4 tabelas da 0021, que revogou
-- explicitamente, e as 2 de backup, que a 0016 fechou. Ou seja: onde
-- alguém escreveu o revoke, não havia; no resto, havia.
--
-- Ninguém concedeu esse privilégio. Ele vem do `alter default
-- privileges ... grant all on tables` que o Supabase deixa no schema
-- `public`: toda tabela criada por `postgres` nasce com `arwdDxtm`
-- para `service_role` — o `D` é o TRUNCATE. Foi assim que a 0021
-- descobriu o problema em si mesma, e é por isso que a 0021 sozinha
-- não resolveu: ela consertou as tabelas dela, não a fábrica.
--
-- Esta migração fecha os dois lados: o estoque (as tabelas que já
-- existem) e a fábrica (o default que fabrica as próximas).
-- ===============================================================

-- ===============================================================
-- O QUE ISTO RESOLVE — E, COM A MESMA CLAREZA, O QUE NÃO RESOLVE
--
-- RESOLVE: TRUNCATE é o único jeito de esvaziar uma tabela SEM passar
-- por gatilho de linha. `governanca_eventos` tem
-- `evento_ator_confiavel`; `pesquisa_preco_eventos` tem
-- `pesquisa_preco_trilha_imutavel`; `processos` tem
-- `trg_processos_atualizado`. Todos são `before insert/update/delete`
-- — e TRUNCATE não é nenhum dos três. A trilha que a plataforma
-- promete a um órgão público cabia inteira num comando que nenhum
-- gatilho veria passar. Também é instantâneo: não há janela para
-- notar e interromper, como haveria num DELETE de milhões de linhas.
--
-- NÃO RESOLVE: `service_role` continua com DELETE em 26 tabelas e
-- continua `BYPASSRLS`. Quem obtiver a chave de servidor ainda apaga
-- linha por linha, e o PostgREST expõe DELETE — que é, aliás, o
-- caminho que o próprio aplicativo usa em `config_orgaos`,
-- `processos` e `documentos_referencia`. Esta migração não é um
-- cadeado na porta da frente; é tirar da mesa o comando que apaga
-- tudo sem deixar rastro. Chamar isso de "service_role contido"
-- seria mentira, e mentira em cabeçalho de migração é pior que
-- buraco conhecido.
--
-- O passo seguinte — revogar DELETE onde o aplicativo não apaga (23
-- das 26) — não está aqui porque exige decidir tabela a tabela o que
-- é retenção e o que é esquecimento, e porque quebrar uma escrita
-- legítima para fechar um buraco hipotético é trocar de problema.
-- Fica registrado como achado aberto, com o número medido.
-- ===============================================================

-- ---------------------------------------------------------------
-- 1) O ESTOQUE — as tabelas que já existem
--
-- Aqui a forma genérica (`all tables in schema public`) é a CERTA, ao
-- contrário da 0021, que listou as quatro tabelas dela uma a uma. A
-- diferença não é estilo: lá, o revoke era uma decisão sobre aquelas
-- tabelas — a trilha de preços é append-only, e isso é uma escolha de
-- domínio. Aqui a afirmação é sobre o schema inteiro, sem exceção
-- prevista. Listar 32 nomes daria a impressão de que alguém decidiu
-- cada um, e a primeira tabela nova ficaria de fora em silêncio.
--
-- `anon` e `authenticated` entram no mesmo revoke. Em produção eles
-- já não têm TRUNCATE em tabela nenhuma — a 0019 e a 0020 cuidaram
-- disso. A linha existe para que este arquivo não dependa daquelas
-- duas terem passado: ele afirma o estado final, não um delta.
-- ---------------------------------------------------------------
revoke truncate on all tables in schema public
  from service_role, authenticated, anon, public;

-- ---------------------------------------------------------------
-- 2) A FÁBRICA — as tabelas que ainda não existem
--
-- Sem esta parte, a 0025 cria uma tabela e o TRUNCATE volta, calado,
-- exatamente como voltou depois da 0021. `alter default privileges`
-- é o único lugar onde isso se decide uma vez só.
--
-- `for role postgres` é explícito de propósito. Sem a cláusula, vale
-- o `current_user`, e o arquivo passaria a significar coisas
-- diferentes conforme quem o aplica. As migrações rodam como
-- `postgres` (medido: `current_user` = postgres no MCP e no painel), e
-- é o default de `postgres` que rege as tabelas que elas criam.
--
-- LIMITE CONHECIDO, e ele é real: o `pg_default_acl` de `public` tem
-- DUAS entradas em produção. A de `postgres`, que esta linha estreita,
-- e uma de `supabase_admin`, que concede `arwdDxtm` a `anon`,
-- `authenticated` e `service_role`. `postgres` não é membro de
-- `supabase_admin` (medido) e não pode alterá-la. Ela só rege tabelas
-- CRIADAS por `supabase_admin`, e hoje não existe nenhuma: as 32
-- tabelas de `public` são todas de `postgres` (medido). Se um recurso
-- do Supabase criar uma tabela em `public` como `supabase_admin`, ela
-- nascerá larga — e nenhuma linha deste arquivo impedirá isso. Quem
-- notar, revoga na mão e registra aqui.
-- ---------------------------------------------------------------
alter default privileges for role postgres in schema public
  revoke truncate on tables from service_role, authenticated, anon, public;

-- ---------------------------------------------------------------
-- 3) A CONFERÊNCIA — a migração falha se não cumpriu o que diz
--
-- Um `revoke` que não pega não levanta erro: ele simplesmente não faz
-- nada e devolve sucesso. Um arquivo que afirma no cabeçalho ter
-- fechado o TRUNCATE precisa medir, e não supor, antes de comitar.
-- Falhando aqui, a transação inteira volta.
--
-- `postgres` fica de fora da conferência, e não por descuido: é o DONO
-- das tabelas. Dono tem tudo por construção do PostgreSQL, e revogar
-- dele seria teatro — ele se reconcede no comando seguinte. O que
-- importa é quem chega pela REDE, e pela rede chegam `anon`,
-- `authenticated` e `service_role`.
-- ---------------------------------------------------------------
do $$
declare
  faltou text;
begin
  select string_agg(format('%s→%s', grantee, table_name), ', ')
    into faltou
  from information_schema.role_table_grants
  where table_schema = 'public'
    and privilege_type = 'TRUNCATE'
    and grantee in ('service_role', 'authenticated', 'anon', 'PUBLIC');

  if faltou is not null then
    raise exception
      'A 0024 não cumpriu o que afirma: TRUNCATE ainda concedido em %',
      faltou;
  end if;

  perform 1
  from pg_default_acl d, aclexplode(d.defaclacl) a
  where d.defaclnamespace = 'public'::regnamespace
    and d.defaclobjtype = 'r'
    and d.defaclrole = 'postgres'::regrole
    and a.privilege_type = 'TRUNCATE'
    and a.grantee::regrole::text
        in ('service_role', 'authenticated', 'anon');

  if found then
    raise exception
      'A 0024 estreitou o estoque mas não a fábrica: o default de '
      'postgres em public ainda concede TRUNCATE. A próxima tabela '
      'nasceria com o problema de volta.';
  end if;
end
$$;
