-- ############################################################
-- ##  APLICADA EM PRODUÇÃO em 06/09/2026, com autorização
-- ##  expressa, em três partes, depois de 0018 e 0019.
-- ##
-- ##  PRINCÍPIO: credencial de servidor NÃO é autorização. Ela
-- ##  ignora RLS por definição; usá-la como modelo permanente
-- ##  transfere toda a autorização para o código do app, sem rede
-- ##  de proteção no banco.
-- ##
-- ##  A MIGRAÇÃO DE DADOS **NÃO FOI FEITA**, e é isso que separa
-- ##  "a matriz existe" de "a matriz protege". Estado real de
-- ##  produção em 06/09/2026:
-- ##
-- ##    * 0 contas no Supabase Auth; as 2 contas de `usuarios`
-- ##      continuam entrando por `senha_hash`, pelo caminho de
-- ##      servidor;
-- ##    * `usuarios.auth_user_id` e `processos.auth_user_id`
-- ##      existem e estão NULOS;
-- ##    * os 6 processos têm `secretaria_id` NULO — pela ETAPA C,
-- ##      cada um só seria visível ao admin.
-- ##
-- ##  Consequência prática: as políticas abaixo estão instaladas e
-- ##  corretas, mas ainda não governam ninguém, porque o app opera
-- ##  pela credencial de servidor. Elas passam a valer quando a
-- ##  ETAPA E for concluída — e a ETAPA C precisa vir antes, ou os
-- ##  servidores ficam trancados para fora dos próprios processos.
-- ##
-- ##  A criação das contas no Auth exige o e-mail de cada pessoa
-- ##  (a tabela guarda `login`, não e-mail) e a redefinição de
-- ##  senha pelo titular. A secretaria de cada processo legado é
-- ##  decisão HUMANA, processo a processo. Nada disso pode ser
-- ##  adivinhado por SQL, e nada disso foi feito aqui.
-- ##
-- ##  Verificação executada depois de aplicar: as três consultas
-- ##  do rodapé em zero, 45 políticas, 10 funções de contexto,
-- ##  `anon` recusado por privilégio, dados intactos.
-- ############################################################
--
-- DECISÃO DE ARQUITETURA (tomada explicitamente, 15/08/2026)
--
-- Escopo de LEITURA de processo: POR SECRETARIA, com o administrador
-- do município enxergando o tenant inteiro.
--
-- A versão anterior desta migração adotava leitura tenant-wide sem
-- decisão registrada — qualquer servidor autenticado do município lia
-- qualquer processo dele, e a Educação via os processos da Saúde. Não
-- era uma escolha, era o caminho mais curto de escrever a policy.
--
-- O meio-termo escolhido preserva o trabalho colaborativo dentro da
-- pasta (duas pessoas da mesma secretaria tocam o mesmo processo) sem
-- expor secretarias entre si.
--
-- Consequência que exige atenção no backfill: `processos.secretaria_id`
-- é NULLABLE desde a 0007. Processo legado sem secretaria fica
-- invisível para todo servidor comum. A ETAPA C trata disso — e a
-- decisão de para qual secretaria cada legado vai é HUMANA, não pode
-- ser adivinhada por SQL.

-- ===============================================================
-- ETAPA A — identidade: Supabase Auth como fonte única
-- ===============================================================
-- Cada conta de `usuarios` passa a corresponder a um usuário do
-- Supabase Auth. A migração dos dados é MANUAL e auditada: criar o
-- usuário em auth.users, registrar o id aqui, comunicar a redefinição
-- de senha.
--
-- NÃO copiar senha_hash: o PBKDF2 do app não é o formato do Supabase
-- Auth, e a senha deve ser redefinida pelo próprio titular. Ao fim da
-- transição a coluna `senha_hash` é REMOVIDA — enquanto ela existir,
-- existe um segundo caminho de autenticação para manter seguro.
alter table public.usuarios
  add column if not exists auth_user_id uuid unique
    references auth.users(id) on delete restrict;

-- ===============================================================
-- ETAPA B — papel e vínculos no JWT, em app_metadata
-- ===============================================================
-- `user_metadata` é EDITÁVEL PELO PRÓPRIO USUÁRIO
-- (`auth.updateUser({ data: … })`). Guardar `papel: 'admin'` aí é
-- entregar escalação de privilégio de graça: qualquer conta se promove
-- a administradora com uma chamada.
--
-- `app_metadata` só é gravável com credencial de servidor (Admin API).
-- É o único lugar onde papel, tenant e secretaria podem morar.
--
-- Ler do JWT também evita recursão de RLS: uma política de `usuarios`
-- que precisasse consultar `usuarios` para descobrir o tenant entraria
-- em laço.
create or replace function public.papel_do_jwt()
returns text language sql stable
set search_path = ''
as $$
  select coalesce(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb
      -> 'app_metadata' ->> 'papel',
    'usuario')
$$;

create or replace function public.tenant_do_jwt()
returns uuid language sql stable
set search_path = ''
as $$
  select nullif(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb
      -> 'app_metadata' ->> 'tenant_id', '')::uuid
$$;

create or replace function public.secretaria_do_jwt()
returns uuid language sql stable
set search_path = ''
as $$
  select nullif(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb
      -> 'app_metadata' ->> 'secretaria_id', '')::uuid
$$;

create or replace function public.e_admin()
returns boolean language sql stable
set search_path = ''
as $$
  select public.papel_do_jwt() = 'admin'
$$;

-- Predicado de leitura de processo, num lugar só. Escrito uma vez,
-- usado por `processos` e por tudo que pende dela — se o escopo mudar,
-- muda aqui, e não em vinte políticas.
create or replace function public.pode_ler_processo(
  p_tenant uuid, p_secretaria uuid)
returns boolean language sql stable
set search_path = ''
as $$
  select p_tenant is not null
     and p_tenant = public.tenant_do_jwt()
     and (public.e_admin()
          or (p_secretaria is not null
              and p_secretaria = public.secretaria_do_jwt()))
$$;

-- ---------------------------------------------------------------
-- EXECUTE explícito para as funções de contexto
--
-- A 0019 revogou o default `EXECUTE ON FUNCTIONS FROM PUBLIC` — e foi
-- correto: sem isso, toda função nova em `public` nasce executável por
-- qualquer papel, `anon` incluído.
--
-- O efeito colateral é que estas funções, criadas DEPOIS da 0019,
-- nascem sem EXECUTE para ninguém. E como as políticas de RLS as
-- chamam, o resultado seria "permission denied for function" em toda
-- consulta de todo usuário — o app inteiro fora do ar, com uma
-- mensagem que aponta para a função e não para a causa.
--
-- Conceder aqui não reabre nada: `anon` e PUBLIC continuam de fora, e
-- as funções só devolvem o que já está no JWT de quem chama.
-- ---------------------------------------------------------------
do $$
declare f text;
begin
  foreach f in array array[
    'public.papel_do_jwt()',
    'public.tenant_do_jwt()',
    'public.secretaria_do_jwt()',
    'public.e_admin()',
    'public.pode_ler_processo(uuid, uuid)'
  ] loop
    execute format('revoke all on function %s from public, anon', f);
    execute format('grant execute on function %s to authenticated, '
                   'service_role', f);
  end loop;
end $$;

-- Vocabulário e validação da trilha: só o servidor precisa deles
-- diretamente; `authenticated` os alcança por dentro da função
-- SECURITY DEFINER, que roda com o dono.
-- (concessões logo após a definição, no bloco de governança)

-- ===============================================================
-- ETAPA C — titularidade: a coluna que JÁ EXISTE e não serve
-- ===============================================================
-- ARMADILHA, e é o erro que a versão anterior desta migração continha:
--
--   alter table public.processos
--     add column if not exists usuario_id uuid references auth.users(id);
--
-- Isso NÃO faz o que parece. `processos.usuario_id` existe desde a
-- 0004 — `uuid`, sem FK. Como a coluna existe, o `IF NOT EXISTS` pula
-- o comando INTEIRO, cláusula `references` inclusive. Nenhuma chave
-- estrangeira é criada, e o SQL passa sem erro.
--
-- Pior que isso: os valores atuais são `usuarios.id`, o id da tabela
-- própria do app. `auth.uid()` devolve `auth.users.id`, que é OUTRO
-- identificador. Uma política `usuario_id = auth.uid()` não casaria
-- linha nenhuma — e o efeito não seria um erro visível, seria cada
-- servidor trancado para fora dos próprios processos, com a tela
-- vazia e nada no log.
--
-- A saída é coluna NOVA, com backfill conferido, mantendo a antiga
-- como legado até o fim da transição.
alter table public.processos
  add column if not exists auth_user_id uuid
    references auth.users(id) on delete restrict;
create index if not exists processos_auth_user_idx
  on public.processos (auth_user_id);

alter table public.revisoes  add column if not exists tenant_id uuid;
alter table public.geracoes  add column if not exists tenant_id uuid;

-- BACKFILL — executar com o app em manutenção, conferindo as contagens
-- antes e depois. NÃO é idempotente por acidente: `where` restringe às
-- linhas ainda não convertidas.
--
--   -- antes:
--   select count(*) filter (where auth_user_id is null) as pendentes,
--          count(*) as total from public.processos;
--
--   update public.processos p
--      set auth_user_id = u.auth_user_id
--     from public.usuarios u
--    where u.id = p.usuario_id
--      and p.auth_user_id is null
--      and u.auth_user_id is not null;
--
--   -- depois: `pendentes` deve ter caído para as linhas cujo dono
--   -- ainda não tem conta no Auth. Nenhuma delas pode ficar para trás
--   -- antes do NOT NULL.
--
-- Processos legados SEM secretaria_id precisam de decisão humana —
-- cada um vai para a pasta a que pertence. Enquanto houver
-- `secretaria_id is null`, o processo só é visível ao admin.
--
--   select id, criado_em from public.processos
--    where secretaria_id is null order by criado_em;
--
-- Só depois de tudo conferido:
--   alter table public.processos alter column tenant_id    set not null;
--   alter table public.processos alter column auth_user_id set not null;
--   alter table public.processos alter column secretaria_id set not null;

-- ===============================================================
-- ETAPA D — matriz completa: 28 tabelas
-- ===============================================================
-- Regra que não pode faltar em nenhuma escrita:
--
--   USING       → quais linhas o usuário ENXERGA (select/update/delete)
--   WITH CHECK  → quais linhas ele pode DEIXAR GRAVADAS (insert/update)
--
-- Um UPDATE só com USING permite pegar uma linha que se enxerga
-- legitimamente e reescrevê-la com `tenant_id` de outro município. Por
-- isso todo UPDATE abaixo tem os dois lados, e o WITH CHECK repete a
-- condição do USING.
--
-- Nenhuma política de DELETE em tabela de processo: exclusão passa a
-- ser lógica, preservando a auditoria do processo administrativo.

begin;

-- ---------------------------------------------------------------
-- Grupo 1 — EXCLUSIVAS DO SERVIDOR (3 tabelas)
-- Nenhum grant, nenhuma política. `authenticated` não alcança.
-- ---------------------------------------------------------------
--   config_app                        segredos e feature flags
--   chunks_referencia_bkp_20260811    backup
--   documentos_referencia_bkp_20260811 backup
--
-- Ficam como a 0019 as deixou. Registradas aqui para que a matriz
-- some 28 e a ausência seja deliberada, não esquecimento.

-- ---------------------------------------------------------------
-- Grupo 2 — PROCESSO e o que pende dele (11 tabelas)
-- Leitura por secretaria; escrita pelo dono; admin alcança o tenant.
-- ---------------------------------------------------------------
drop policy if exists "processos_le"     on public.processos;
drop policy if exists "processos_insere" on public.processos;
drop policy if exists "processos_edita"  on public.processos;

create policy "processos_le" on public.processos
  for select to authenticated
  using (public.pode_ler_processo(tenant_id, secretaria_id));

create policy "processos_insere" on public.processos
  for insert to authenticated
  with check (tenant_id = public.tenant_do_jwt()
              and auth_user_id = auth.uid()
              and (secretaria_id = public.secretaria_do_jwt()
                   or public.e_admin()));

create policy "processos_edita" on public.processos
  for update to authenticated
  using      (public.pode_ler_processo(tenant_id, secretaria_id)
              and (auth_user_id = auth.uid() or public.e_admin()))
  with check (tenant_id = public.tenant_do_jwt()
              and (auth_user_id = auth.uid() or public.e_admin())
              and (secretaria_id = public.secretaria_do_jwt()
                   or public.e_admin()));

grant select, insert, update on public.processos to authenticated;

-- As tabelas que pendem de `processos` herdam o escopo pelo PAI.
-- Repetir o predicado em cada uma abriria espaço para divergirem.
--
-- LER e ESCREVER têm escopos DIFERENTES, e a versão anterior desta
-- migração usava o mesmo predicado nos dois:
--
--   * LEITURA segue a secretaria — é o trabalho colaborativo dentro
--     da pasta, e foi a decisão de arquitetura registrada acima;
--   * ESCRITA exige ser o TITULAR do processo, ou admin. Poder ler o
--     processo do colega não dá direito de anexar revisão, gravar
--     parecer ou lançar fato canônico nele. Com o predicado de leitura
--     no `with check`, qualquer servidor da secretaria podia escrever
--     no processo de qualquer outro — e o registro sairia com a
--     aparência de ter vindo do titular.
--
-- E quando a filha tem `tenant_id` próprio, ele é amarrado ao tenant
-- do PAI e ao do JWT. Sem isso, a coluna aceitaria um tenant qualquer
-- vindo do cliente, e a linha ficaria pendurada num processo de um
-- município enquanto declara pertencer a outro.
do $$
declare t text;
begin
  foreach t in array array[
    'revisoes', 'geracoes', 'decisoes', 'fatos_canonicos',
    'qualidade_scores', 'pareceres', 'aprendizado_feedback'
  ] loop
    execute format('drop policy if exists "%s_le" on public.%I', t, t);
    execute format('drop policy if exists "%s_escreve" on public.%I', t, t);
    execute format($f$
      create policy "%1$s_le" on public.%1$I
        for select to authenticated
        using (exists (select 1 from public.processos p
                       where p.id = %1$I.processo_id
                         and public.pode_ler_processo(p.tenant_id,
                                                      p.secretaria_id)))
    $f$, t);
    execute format($f$
      create policy "%1$s_escreve" on public.%1$I
        for insert to authenticated
        with check (
          %1$I.tenant_id = public.tenant_do_jwt()
          and exists (select 1 from public.processos p
                      where p.id = %1$I.processo_id
                        and p.tenant_id = %1$I.tenant_id
                        and public.pode_ler_processo(p.tenant_id,
                                                     p.secretaria_id)
                        and (p.auth_user_id = auth.uid()
                             or public.e_admin())))
    $f$, t);
    execute format(
      'grant select, insert on public.%I to authenticated', t);
  end loop;
end $$;

-- `parecer_achados` não tem processo_id nem tenant_id: pende de
-- `pareceres`. O escopo vem em dois saltos.
drop policy if exists "parecer_achados_le" on public.parecer_achados;
create policy "parecer_achados_le" on public.parecer_achados
  for select to authenticated
  using (exists (
    select 1 from public.pareceres pa
      join public.processos p on p.id = pa.processo_id
     where pa.id = parecer_achados.parecer_id
       and public.pode_ler_processo(p.tenant_id, p.secretaria_id)));
grant select on public.parecer_achados to authenticated;

-- `simulacoes` tem tenant_id mas NÃO tem processo_id: escopo de
-- tenant, leitura só do admin (é ferramenta de gestão).
drop policy if exists "simulacoes_le" on public.simulacoes;
create policy "simulacoes_le" on public.simulacoes
  for select to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant select on public.simulacoes to authenticated;

-- ---------------------------------------------------------------
-- Grupo 3 — IDENTIDADE E ORGANIZAÇÃO (4 tabelas)
-- ---------------------------------------------------------------
drop policy if exists "usuarios_le_a_si"       on public.usuarios;
drop policy if exists "usuarios_admin_le"      on public.usuarios;
drop policy if exists "usuarios_admin_escreve" on public.usuarios;
drop policy if exists "usuarios_admin_edita"   on public.usuarios;

create policy "usuarios_le_a_si" on public.usuarios
  for select to authenticated
  using (auth_user_id = auth.uid());

create policy "usuarios_admin_le" on public.usuarios
  for select to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());

create policy "usuarios_admin_escreve" on public.usuarios
  for insert to authenticated
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());

create policy "usuarios_admin_edita" on public.usuarios
  for update to authenticated
  using      (public.e_admin() and tenant_id = public.tenant_do_jwt())
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());

grant select, insert, update on public.usuarios to authenticated;

-- ATENÇÃO: `papel` NÃO pode ser promovido por esta via. A fonte do
-- papel é `app_metadata` do Auth, gravada pela Admin API; a coluna
-- `usuarios.papel` vira ESPELHO informativo. Um gatilho deve recusar
-- divergência, ou a coluna sai ao fim da transição.

drop policy if exists "secretarias_le" on public.secretarias;
create policy "secretarias_le" on public.secretarias
  for select to authenticated
  using (tenant_id = public.tenant_do_jwt());
grant select on public.secretarias to authenticated;

drop policy if exists "tenants_le" on public.tenants;
create policy "tenants_le" on public.tenants
  for select to authenticated
  using (id = public.tenant_do_jwt());
grant select on public.tenants to authenticated;

drop policy if exists "config_orgaos_le"      on public.config_orgaos;
drop policy if exists "config_orgaos_admin"   on public.config_orgaos;
create policy "config_orgaos_le" on public.config_orgaos
  for select to authenticated
  using (tenant_id = public.tenant_do_jwt());
create policy "config_orgaos_admin" on public.config_orgaos
  for update to authenticated
  using      (public.e_admin() and tenant_id = public.tenant_do_jwt())
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant select, update on public.config_orgaos to authenticated;

-- ---------------------------------------------------------------
-- Grupo 4 — BASE DE CONHECIMENTO (4 tabelas)
-- Leitura do tenant inteiro: é acervo compartilhado, por natureza.
-- Escrita só do admin.
-- ---------------------------------------------------------------
do $$
declare t text;
begin
  foreach t in array array[
    'documentos_referencia', 'fontes_conhecimento', 'regras_conhecimento'
  ] loop
    execute format('drop policy if exists "%s_le" on public.%I', t, t);
    execute format('drop policy if exists "%s_admin" on public.%I', t, t);
    execute format($f$
      create policy "%1$s_le" on public.%1$I
        for select to authenticated
        using (tenant_id = public.tenant_do_jwt())
    $f$, t);
    execute format($f$
      create policy "%1$s_admin" on public.%1$I
        for insert to authenticated
        with check (public.e_admin()
                    and tenant_id = public.tenant_do_jwt())
    $f$, t);
    execute format('grant select, insert on public.%I to authenticated', t);
  end loop;
end $$;

-- `chunks_referencia` pende de `documentos_referencia`.
drop policy if exists "chunks_referencia_le" on public.chunks_referencia;
create policy "chunks_referencia_le" on public.chunks_referencia
  for select to authenticated
  using (exists (select 1 from public.documentos_referencia d
                 where d.id = chunks_referencia.documento_id
                   and d.tenant_id = public.tenant_do_jwt()));
grant select on public.chunks_referencia to authenticated;

-- ---------------------------------------------------------------
-- Grupo 5 — GOVERNANÇA (5 tabelas)
-- Leitura do tenant; escrita do admin; eventos APPEND-ONLY.
-- ---------------------------------------------------------------
drop policy if exists "governanca_artefatos_le"    on public.governanca_artefatos;
drop policy if exists "governanca_artefatos_admin" on public.governanca_artefatos;
create policy "governanca_artefatos_le" on public.governanca_artefatos
  for select to authenticated
  using (tenant_id = public.tenant_do_jwt()
         and (public.e_admin()
              or secretaria_id is null
              or secretaria_id = public.secretaria_do_jwt()));
create policy "governanca_artefatos_admin" on public.governanca_artefatos
  for insert to authenticated
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant select, insert on public.governanca_artefatos to authenticated;

do $$
declare t text;
begin
  foreach t in array array[
    'governanca_aprovacoes', 'governanca_publicacoes'
  ] loop
    execute format('drop policy if exists "%s_le" on public.%I', t, t);
    execute format('drop policy if exists "%s_admin" on public.%I', t, t);
    execute format($f$
      create policy "%1$s_le" on public.%1$I
        for select to authenticated
        using (tenant_id = public.tenant_do_jwt())
    $f$, t);
    execute format($f$
      create policy "%1$s_admin" on public.%1$I
        for insert to authenticated
        with check (public.e_admin()
                    and tenant_id = public.tenant_do_jwt())
    $f$, t);
    execute format('grant select, insert on public.%I to authenticated', t);
  end loop;
end $$;

-- `governanca_versoes` não tem tenant_id: pende de artefatos.
drop policy if exists "governanca_versoes_le" on public.governanca_versoes;
create policy "governanca_versoes_le" on public.governanca_versoes
  for select to authenticated
  using (exists (select 1 from public.governanca_artefatos a
                 where a.id = governanca_versoes.artefato_id
                   and a.tenant_id = public.tenant_do_jwt()));
grant select on public.governanca_versoes to authenticated;

-- ---------------------------------------------------------------
-- `governanca_eventos` — trilha de auditoria
--
-- A versão anterior desta migração dava INSERT direto a qualquer
-- `authenticated`, exigindo apenas `tenant_id = tenant_do_jwt()`. Numa
-- TRILHA isso é o defeito mais grave possível: `ator` é coluna comum,
-- então o cliente escolhia quem aparece como autor do evento. Dava
-- para registrar uma aprovação em nome de outra pessoa, com tipo e
-- entidade inventados, e a trilha — que existe justamente para dizer
-- quem fez o quê — passaria a testemunhar contra o inocente.
--
-- Trilha não se escreve, trilha se ACUMULA. O caminho passa a ser uma
-- função, e a tabela fica fechada para escrita direta.
-- ---------------------------------------------------------------
drop policy if exists "governanca_eventos_le"     on public.governanca_eventos;
drop policy if exists "governanca_eventos_insere" on public.governanca_eventos;

create policy "governanca_eventos_le" on public.governanca_eventos
  for select to authenticated
  using (tenant_id = public.tenant_do_jwt());

-- SEM política de INSERT, UPDATE ou DELETE para `authenticated`:
-- nenhuma escrita direta, por ninguém, nem o admin.
grant select on public.governanca_eventos to authenticated;
revoke insert, update, delete, truncate
  on public.governanca_eventos from authenticated;

-- ---------------------------------------------------------------
-- Vocabulário, CAPACIDADE e vínculo entidade→tabela
--
-- A versão anterior desta função derivava `ator` de `auth.uid()` e
-- parava aí. Isso resolve IMPERSONAÇÃO e não resolve AUTORIZAÇÃO: o
-- evento saía com o nome verdadeiro de quem o criou, e qualquer conta
-- autenticada podia criar um `aprovacao_registrada`. Atribuição
-- confiável de um ato que a pessoa não podia praticar não é trilha
-- boa — é uma confissão falsa bem assinada.
--
-- `authenticated` NÃO é autorização. Autorização aqui é o papel de
-- governança, e ele precisa vir de fonte controlada pelo SERVIDOR:
-- `app_metadata`, gravável só pela Admin API. Em `user_metadata` o
-- próprio usuário se promoveria.
-- ---------------------------------------------------------------
create or replace function public.papel_governanca_do_jwt()
returns text language sql stable
set search_path = ''
as $$
  select nullif(
    nullif(current_setting('request.jwt.claims', true), '')::jsonb
      -> 'app_metadata' ->> 'papel_governanca', '')
$$;

revoke all on function public.papel_governanca_do_jwt() from public, anon;
grant execute on function public.papel_governanca_do_jwt()
  to authenticated, service_role;

-- Vocabulário fechado. Tipo e entidade livres deixariam a trilha
-- receber qualquer string, e uma trilha que aceita tudo não sustenta
-- nada depois.
create or replace function public.tipos_de_evento_validos()
returns text[] language sql immutable
set search_path = ''
as $$ select array[
  -- ciclo do artefato
  'artefato_criado', 'artefato_alterado',
  -- ciclo da versão: é onde quase todo ato do Centro acontece
  'versao_criada', 'versao_alterada', 'versao_aprovada',
  'versao_publicada', 'versao_superada', 'versao_revogada',
  -- registro formal de aprovação
  'aprovacao_registrada', 'aprovacao_revogada',
  -- publicação
  'publicacao_registrada',
  -- laboratório de melhorias
  'proposta_aceita', 'proposta_rejeitada'
]::text[] $$;

-- Cada TIPO DE EVENTO exige um TIPO DE ENTIDADE específico, e cada
-- tipo de entidade tem UMA tabela.
--
-- Antes, `entidade_tipo` e `entidade_id` eram conferidos
-- separadamente: bastava declarar 'artefato' e passar o id de uma
-- publicação para a trilha registrar um vínculo que não existe. E
-- `entidade_id` nulo pulava a checagem inteira.
create or replace function public.entidade_do_tipo_de_evento(p_tipo text)
returns text language sql immutable
set search_path = ''
as $$
  select case p_tipo
    when 'artefato_criado'       then 'artefato'
    when 'artefato_alterado'     then 'artefato'
    when 'versao_criada'         then 'versao'
    when 'versao_alterada'       then 'versao'
    when 'versao_aprovada'       then 'versao'
    when 'versao_publicada'      then 'versao'
    when 'versao_superada'       then 'versao'
    when 'versao_revogada'       then 'versao'
    when 'aprovacao_registrada'  then 'aprovacao'
    when 'aprovacao_revogada'    then 'aprovacao'
    when 'publicacao_registrada' then 'publicacao'
    when 'proposta_aceita'       then 'proposta'
    when 'proposta_rejeitada'    then 'proposta'
  end
$$;

revoke all on function public.entidade_do_tipo_de_evento(text)
  from public, anon;
grant execute on function public.entidade_do_tipo_de_evento(text)
  to authenticated, service_role;

create or replace function public.entidades_de_evento_validas()
returns text[] language sql immutable
set search_path = ''
as $$ select array[
  'artefato', 'versao', 'aprovacao', 'publicacao', 'proposta'
]::text[] $$;

revoke all on function public.tipos_de_evento_validos() from public, anon;
revoke all on function public.entidades_de_evento_validas() from public, anon;
grant execute on function public.tipos_de_evento_validos()
  to authenticated, service_role;
grant execute on function public.entidades_de_evento_validas()
  to authenticated, service_role;


-- MATRIZ papel × tipo de evento.
--
-- Espelha as capacidades de `src/auth.py` (pode_criar_governanca,
-- pode_revisar_governanca, pode_publicar_governanca). Quem não está na
-- matriz não registra o evento — e `auditor`, que só lê, não registra
-- nenhum.
-- Repertório completo, para os papéis de alcance amplo. Existe como
-- função para que a lista viva em UM lugar: três cópias literais da
-- mesma matriz divergem na primeira vez que alguém acrescenta um ato.
create or replace function public.todos_os_eventos()
returns text[] language sql immutable
set search_path = ''
as $$ select public.tipos_de_evento_validos() $$;

revoke all on function public.todos_os_eventos() from public, anon;
grant execute on function public.todos_os_eventos()
  to authenticated, service_role;

create or replace function public.eventos_permitidos_ao_papel(p_papel text)
returns text[] language sql immutable
set search_path = ''
as $$
  select case p_papel
    -- Os três papéis de alcance amplo registram TODO ato do vocabulário.
    -- A lista é a mesma nos três de propósito: o que os distingue é o
    -- ALCANCE (tenant inteiro), não o repertório.
    when 'proprietario'     then public.todos_os_eventos()
    when 'admin_global'     then public.todos_os_eventos()
    when 'admin_municipal'  then public.todos_os_eventos()
    -- Revisor jurídico REVISA: aprova versão e registra/revoga a
    -- aprovação formal. Não publica, não revoga publicação.
    when 'revisor_juridico' then array['versao_aprovada',
                                       'aprovacao_registrada',
                                       'aprovacao_revogada']
    -- Publicador PUBLICA: publica, supera a anterior (efeito direto de
    -- publicar), revoga e registra a publicação. Não aprova.
    when 'publicador'       then array['versao_publicada',
                                       'versao_superada',
                                       'versao_revogada',
                                       'publicacao_registrada',
                                       'proposta_aceita',
                                       'proposta_rejeitada']
    -- auditor só LÊ: nenhum evento
    when 'auditor'          then array[]::text[]
    else array[]::text[]
  end::text[]
$$;

revoke all on function public.eventos_permitidos_ao_papel(text)
  from public, anon;
grant execute on function public.eventos_permitidos_ao_papel(text)
  to authenticated, service_role;

-- ---------------------------------------------------------------
-- Resolução de ESCOPO de uma aprovação
--
-- `governanca_aprovacoes` guarda `entidade_tipo` + `entidade_id`: ela
-- aprova ALGUMA COISA, e é essa coisa que tem secretaria. Conferir só
-- o tenant da linha de aprovação deixa passar objeto de outra pasta.
--
-- A matriz tipo→tabela é EXPLÍCITA. Tipo desconhecido não é tratado
-- como "provavelmente tudo bem": é recusado, porque uma aprovação que
-- aponta para algo que não sabemos resolver é justamente o caso em que
-- não dá para afirmar escopo nenhum.
--
-- Papéis de plataforma e do município alcançam o tenant inteiro, como
-- já documentado na decisão de arquitetura. Revisor jurídico e
-- publicador ficam presos à própria secretaria.
-- ---------------------------------------------------------------
create or replace function public.papel_alcanca_o_tenant(p_papel text)
returns boolean language sql immutable
set search_path = ''
as $$
  select p_papel in ('proprietario', 'admin_global', 'admin_municipal')
$$;

revoke all on function public.papel_alcanca_o_tenant(text) from public, anon;
grant execute on function public.papel_alcanca_o_tenant(text)
  to authenticated, service_role;

create or replace function public.aprovacao_no_escopo(
  p_aprovacao uuid, p_tenant uuid, p_secretaria uuid, p_papel text)
returns boolean
language plpgsql stable
security definer
set search_path = ''
as $$
declare
  v_tipo        text;
  v_alvo        uuid;
  v_tenant_alvo uuid;
  v_sec_alvo    uuid;
begin
  select ap.entidade_tipo, ap.entidade_id
    into v_tipo, v_alvo
    from public.governanca_aprovacoes ap
   where ap.id = p_aprovacao and ap.tenant_id = p_tenant;

  if not found then
    return false;                     -- inexistente ou de outro tenant
  end if;

  -- MATRIZ tipo → tabela. Sem `else` permissivo.
  if v_tipo = 'versao' then
    select a.tenant_id, a.secretaria_id into v_tenant_alvo, v_sec_alvo
      from public.governanca_versoes v
      join public.governanca_artefatos a on a.id = v.artefato_id
     where v.id = v_alvo;
  elsif v_tipo = 'artefato' then
    select a.tenant_id, a.secretaria_id into v_tenant_alvo, v_sec_alvo
      from public.governanca_artefatos a
     where a.id = v_alvo;
  else
    -- tipo desconhecido: não dá para afirmar escopo, então recusa.
    return false;
  end if;

  if not found or v_tenant_alvo is distinct from p_tenant then
    return false;
  end if;

  if public.papel_alcanca_o_tenant(p_papel) then
    return true;
  end if;
  -- papel local: a secretaria do objeto governado tem de bater
  return v_sec_alvo is not null and v_sec_alvo = p_secretaria;
end $$;

revoke all on function public.aprovacao_no_escopo(uuid, uuid, uuid, text)
  from public, anon;
grant execute on function public.aprovacao_no_escopo(uuid, uuid, uuid, text)
  to authenticated, service_role;

-- Único caminho de escrita na trilha.
--
-- SECURITY DEFINER para poder inserir numa tabela sem política de
-- escrita; `search_path` fixo para que a elevação não seja sequestrada
-- por um schema plantado no caminho de busca.
--
-- O `ator` NÃO é parâmetro. Vem de `auth.uid()`, dentro da função, e
-- não há como o chamador influenciá-lo.
create or replace function public.registrar_evento_governanca(
  p_tipo_evento   text,
  p_entidade_tipo text,
  p_entidade_id   uuid,
  p_payload       jsonb default '{}'::jsonb)
returns uuid
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_ator        uuid := auth.uid();
  v_tenant      uuid := public.tenant_do_jwt();
  v_secretaria  uuid := public.secretaria_do_jwt();
  v_papel       text := public.papel_governanca_do_jwt();
  v_esperada    text;
  v_id          uuid;
begin
  -- 1. IDENTIDADE
  if v_ator is null then
    raise exception 'sem identidade: trilha exige usuário autenticado'
      using errcode = '42501';
  end if;
  if v_tenant is null then
    raise exception 'sem tenant no JWT' using errcode = '42501';
  end if;

  -- 2. AUTORIDADE — é o que faltava, e é o que separa uma trilha de um
  --    formulário assinado. Estar autenticado não é ter competência
  --    para registrar um ato de governança.
  if v_papel is null then
    raise exception 'sem papel de governança: registrar ato de governança '
                    'exige competência atribuída pelo servidor'
      using errcode = '42501';
  end if;
  if not (p_tipo_evento = any (
            public.eventos_permitidos_ao_papel(v_papel))) then
    raise exception 'papel % não pode registrar evento do tipo %',
                    v_papel, p_tipo_evento
      using errcode = '42501';
  end if;

  -- 3. VOCABULÁRIO
  if not (p_tipo_evento = any (public.tipos_de_evento_validos())) then
    raise exception 'tipo de evento inválido: %', p_tipo_evento
      using errcode = '22023';
  end if;
  v_esperada := public.entidade_do_tipo_de_evento(p_tipo_evento);
  if v_esperada is null or p_entidade_tipo is distinct from v_esperada then
    raise exception 'evento % exige entidade do tipo %, recebeu %',
                    p_tipo_evento, v_esperada, p_entidade_tipo
      using errcode = '22023';
  end if;

  -- 4. ENTIDADE OBRIGATÓRIA — todo evento desta trilha é vinculado.
  --    Nulo pulava a checagem inteira e deixava passar qualquer coisa.
  if p_entidade_id is null then
    raise exception 'evento % exige entidade: id nulo não é aceito',
                    p_tipo_evento
      using errcode = '22023';
  end if;

  -- 5. EXISTÊNCIA na TABELA EXATA, dentro do TENANT e da SECRETARIA.
  --    Papéis de plataforma e do município alcançam o tenant inteiro;
  --    revisor e publicador ficam presos à própria secretaria.
  if p_entidade_tipo = 'artefato' then
    if not exists (select 1 from public.governanca_artefatos a
                    where a.id = p_entidade_id
                      and a.tenant_id = v_tenant
                      and (public.papel_alcanca_o_tenant(v_papel)
                           or (a.secretaria_id is not null
                               and a.secretaria_id = v_secretaria))) then
      raise exception 'artefato inexistente, de outro tenant ou de outra '
                      'secretaria' using errcode = '42501';
    end if;
  elsif p_entidade_tipo = 'versao' then
    if not exists (select 1 from public.governanca_versoes v
                     join public.governanca_artefatos a on a.id = v.artefato_id
                    where v.id = p_entidade_id
                      and a.tenant_id = v_tenant
                      and (public.papel_alcanca_o_tenant(v_papel)
                           or (a.secretaria_id is not null
                               and a.secretaria_id = v_secretaria))) then
      raise exception 'versão inexistente, de outro tenant ou de outra '
                      'secretaria' using errcode = '42501';
    end if;
  elsif p_entidade_tipo = 'aprovacao' then
    -- P2: aprovação NÃO é objeto raiz.
    --
    -- A versão anterior conferia só `ap.tenant_id`. Como
    -- `governanca_aprovacoes` é legível por todo o tenant, um revisor
    -- da secretaria A obtinha o id de uma aprovação da secretaria B e
    -- registrava evento sobre ela — com ator verdadeiro, o que torna a
    -- trilha convincente e errada ao mesmo tempo.
    --
    -- A aprovação carrega `entidade_tipo`/`entidade_id` apontando para
    -- o objeto GOVERNADO. É preciso seguir esse ponteiro até o artefato
    -- para descobrir a secretaria:
    --
    --   governanca_aprovacoes → governanca_versoes → governanca_artefatos
    --   governanca_aprovacoes → governanca_artefatos  (aprovação direta)
    --
    -- `aprovacao_no_escopo` faz essa resolução num lugar só, com matriz
    -- explícita tipo→tabela, e recusa tipo desconhecido.
    if not public.aprovacao_no_escopo(p_entidade_id, v_tenant,
                                      v_secretaria, v_papel) then
      raise exception 'aprovação inexistente, de outro tenant ou de '
                      'outra secretaria' using errcode = '42501';
    end if;
  elsif p_entidade_tipo = 'publicacao' then
    -- `governanca_publicacoes` não tem `secretaria_id`: o escopo que
    -- se pode afirmar aqui é o de TENANT, e é o que se afirma. Fingir
    -- uma checagem de secretaria que a tabela não sustenta seria pior
    -- que não checar — daria a impressão de uma fronteira inexistente.
    if not exists (select 1 from public.governanca_publicacoes pb
                    where pb.id = p_entidade_id
                      and pb.tenant_id = v_tenant) then
      raise exception 'publicação inexistente ou de outro tenant'
        using errcode = '42501';
    end if;
  elsif p_entidade_tipo = 'proposta' then
    -- idem: `melhoria_propostas` também é só por tenant.
    if not exists (select 1 from public.melhoria_propostas mp
                    where mp.id = p_entidade_id
                      and mp.tenant_id = v_tenant) then
      raise exception 'proposta inexistente ou de outro tenant'
        using errcode = '42501';
    end if;
  else
    raise exception 'entidade inválida: %', p_entidade_tipo
      using errcode = '22023';
  end if;

  insert into public.governanca_eventos
    (tenant_id, ator, tipo_evento, entidade_tipo, entidade_id, payload)
  values (v_tenant, v_ator, p_tipo_evento, p_entidade_tipo,
          p_entidade_id, coalesce(p_payload, '{}'::jsonb))
  returning id into v_id;
  return v_id;
end $$;

-- EXECUTE mínimo. `anon` e PUBLIC jamais.
--
-- `authenticated` recebe porque a função é o único caminho da trilha e
-- ela própria recusa quem não tem papel — a concessão não é a
-- autorização, é o acesso à porta onde a autorização é conferida.
--
-- `service_role` recebe com justificativa documentada: as rotinas
-- administrativas do servidor (migração de dados, correção de trilha
-- sob autorização, reprocessamento) rodam sem JWT de usuário e
-- precisam registrar eventos. Elas passam pelo MESMO caminho, e a
-- ausência de `auth.uid()` faz a função recusar — o servidor tem de
-- assumir uma identidade explícita para registrar, e isso é
-- deliberado.
revoke all on function public.registrar_evento_governanca(
  text, text, uuid, jsonb) from public, anon;
grant execute on function public.registrar_evento_governanca(
  text, text, uuid, jsonb) to authenticated, service_role;

-- Rede de proteção no banco: mesmo que uma política de INSERT volte
-- por engano numa migração futura, o gatilho recusa qualquer ator que
-- não seja quem está autenticado.
create or replace function public.trg_evento_ator_confiavel()
returns trigger language plpgsql
set search_path = ''
as $$
begin
  if auth.uid() is not null and new.ator is distinct from auth.uid() then
    raise exception 'ator do evento não confere com o usuário autenticado'
      using errcode = '42501';
  end if;
  return new;
end $$;

-- EXECUTE explícito, e não por simetria.
--
-- O ensaio LOCAL revelou que
-- `alter default privileges ... revoke execute on functions from public`
-- — a linha que a 0019 apresenta como "a causa da recorrência,
-- resolvida" — NÃO suprime o EXECUTE que o PostgreSQL concede a PUBLIC
-- por conta própria em toda função nova. Conferido em PG 16.13: a
-- revogação roda sem erro, não grava linha em `pg_default_acl`, e a
-- função seguinte nasce com `proacl` NULO — isto é, executável por
-- qualquer papel, `anon` inclusive.
--
-- Para TABELAS e SEQUENCES o mecanismo funciona (também conferido).
-- Para FUNÇÕES a única garantia é o revoke EXPLÍCITO, uma por uma.
-- Esta era a última função da 0020 sem ele.
revoke all on function public.trg_evento_ator_confiavel()
  from public, anon;

drop trigger if exists evento_ator_confiavel on public.governanca_eventos;
create trigger evento_ator_confiavel
  before insert or update on public.governanca_eventos
  for each row execute function public.trg_evento_ator_confiavel();

-- ---------------------------------------------------------------
-- Grupo 6 — MELHORIA CONTÍNUA (2 tabelas) — só admin
-- ---------------------------------------------------------------
drop policy if exists "melhoria_clusters_le" on public.melhoria_clusters;
create policy "melhoria_clusters_le" on public.melhoria_clusters
  for select to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant select on public.melhoria_clusters to authenticated;

drop policy if exists "melhoria_propostas_le"    on public.melhoria_propostas;
drop policy if exists "melhoria_propostas_admin" on public.melhoria_propostas;
create policy "melhoria_propostas_le" on public.melhoria_propostas
  for select to authenticated
  using (public.e_admin() and tenant_id = public.tenant_do_jwt());
create policy "melhoria_propostas_admin" on public.melhoria_propostas
  for update to authenticated
  using      (public.e_admin() and tenant_id = public.tenant_do_jwt())
  with check (public.e_admin() and tenant_id = public.tenant_do_jwt());
grant select, update on public.melhoria_propostas to authenticated;

commit;

-- ############################################################
-- VERIFICAÇÃO — todas devem devolver ZERO linhas
-- ############################################################
-- -- 1) nenhuma política alcança `anon` (a 0019 continua valendo):
-- select tablename, policyname from pg_policies
--  where schemaname='public' and roles && array['anon','public']::name[];
--
-- -- 2) nenhuma escrita sem WITH CHECK:
-- select tablename, policyname, cmd from pg_policies
--  where schemaname='public' and cmd in ('INSERT','UPDATE','ALL')
--    and with_check is null;
--
-- -- 3) nenhuma tabela com grant a authenticated e sem política:
-- select g.table_name from information_schema.role_table_grants g
--  where g.table_schema='public' and g.grantee='authenticated'
--    and not exists (select 1 from pg_policies p
--                    where p.schemaname='public'
--                      and p.tablename=g.table_name)
--  group by g.table_name;
--
-- -- 4) nenhum processo sem dono do Auth depois do backfill:
-- select count(*) from public.processos where auth_user_id is null;
--
-- -- 5) nenhum processo sem secretaria (some do alcance do servidor):
-- select count(*) from public.processos where secretaria_id is null;

-- ===============================================================
-- ETAPA E — código do app
-- ===============================================================
-- Enquanto o app autenticar por PBKDF2 contra `usuarios`, as políticas
-- acima não têm efeito: ele opera com credencial de servidor, que
-- ignora RLS. A troca é o que dá sentido a esta migração.
--
--   1. `src/auth.py` passa a usar `supabase.auth.sign_in_with_password`
--      e a sessão do usuário, não mais `verificar_senha`;
--   2. `db._cliente()` ganha uma variante por REQUISIÇÃO, com o JWT do
--      usuário, para tudo que não for operação administrativa;
--   3. papel, tenant e secretaria passam a ser gravados em
--      `app_metadata` pela Admin API, no cadastro e na troca de lotação;
--   4. `src/contexto.py` lê o vínculo do JWT, não de `st.session_state`;
--   5. `usuarios.senha_hash` é removida — enquanto existir, há um
--      segundo caminho de autenticação para manter seguro.
--
-- ETAPA F — retirada da credencial privilegiada
--   A cada operação que ganha política, ela sai do inventário de
--   exceções (docs/seguranca-achado-p0.md). Meta: inventário vazio,
--   exceto rotinas administrativas fora do app.
