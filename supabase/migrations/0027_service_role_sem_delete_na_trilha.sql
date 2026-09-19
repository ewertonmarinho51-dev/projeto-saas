-- ############################################################
-- ##  0027 — A credencial de servidor não apaga a trilha
-- ##
-- ##  ESTADO: APLICÁVEL. Só REVOGA privilégio. Não cria nem
-- ##  remove tabela ou coluna, não apaga linha, não toca em
-- ##  política de RLS e não mexe em `anon` nem em
-- ##  `authenticated`.
-- ##
-- ##  APLICADA EM PRODUÇÃO em 19/09/2026. Medição depois:
-- ##  zero DELETE de papel de rede nas treze; de 34 para 21 as
-- ##  tabelas apagáveis por `service_role`; as três que o
-- ##  aplicativo usa intactas; `secretarias` e `usuarios`
-- ##  preservadas pela decisão de produto; 168 linhas de
-- ##  `geracoes` no lugar — nada foi apagado.
-- ############################################################

-- ===============================================================
-- A DECISÃO DE PRODUTO QUE DESTRAVOU ISTO
--
-- `docs/proposta-delete-service-role.md` (17/09/2026) terminava numa
-- pergunta só, e ela era de produto: em `secretarias`, `usuarios` e
-- `config_orgaos`, "remover" significa apagar a linha ou marcar como
-- inativa?
--
-- Em 19/09/2026 o operador respondeu: APAGAR A LINHA.
--
-- A resposta MANTÉM o DELETE nessas tabelas — tela de administração que
-- apaga precisa do privilégio — e não diz nada sobre o grupo da TRILHA.
-- Por isso é a trilha que esta migração fecha, e só ela: é o grupo onde
-- a resposta não muda nada e onde revogar é coerência, não aposta.
--
-- A proposta previa commits separados por grupo, na ordem
-- trilha → cadastro → conhecimento, para que uma quebra tenha endereço
-- óbvio. Este é o primeiro.
--
-- POR QUE A TRILHA
--
-- `governanca_eventos` já não aceita escrita de `authenticated` desde a
-- 0020 — "nenhuma escrita direta, por ninguém, nem o admin". E a
-- credencial de servidor apagava o que o admin não pode apagar. É a
-- mesma contradição que a 0021 corrigiu nas tabelas de preço e que
-- ninguém estendeu ao resto.
--
-- Agravante novo: desde a 0026 a tabela `geracoes` registra SOB QUAL
-- POLÍTICA cada documento foi gerado. Uma trilha que diz de quem é o
-- ato e sob que regra ele saiu, e que a credencial do app reescreve
-- linha a linha, prova menos do que aparenta.
--
-- O QUE ESTA MIGRAÇÃO NÃO FAZ, E É DELIBERADO
--
-- NÃO toca no DELETE de `processos`, `config_orgaos` e
-- `documentos_referencia`: são as três em que o aplicativo apaga de
-- verdade (`src/db.py:1385`, `src/db.py:1402`, `src/rag.py:447`).
-- Revogar ali derruba um botão que funciona hoje, e
-- `test_service_role_continua_apagando_onde_o_app_apaga` quebra se
-- alguém tentar.
--
-- NÃO toca em `secretarias` nem em `usuarios`, pela decisão acima.
--
-- NÃO toca no grupo de conhecimento (`chunks_referencia`,
-- `fatos_canonicos`, `fontes_conhecimento`, `melhoria_clusters`,
-- `melhoria_propostas`, `regras_conhecimento`): reindexação é operação
-- que às vezes precisa remover, e essa decisão ainda não foi tomada.
--
-- NÃO toca nas oito tabelas novas da 0025 que ainda têm DELETE. Elas
-- não existiam quando a proposta foi escrita e merecem levantamento
-- próprio — `portarias`, por exemplo, é soft-delete POR DESENHO ("não
-- se apaga: revoga-se"), então ali o DELETE provavelmente sai; mas
-- "provavelmente" não é como se mexe em privilégio de produção.
--
-- O QUE ISTO VALE, HONESTAMENTE
--
-- Não conserta o achado de primeira ordem: quem tiver a chave de
-- servidor continua apagando em `processos`, que é o dado que mais
-- importa. Nenhuma matriz de privilégio conserta chave vazada — o que
-- conserta é rotação.
--
-- O que se ganha é outra coisa, e é real: a trilha de governança deixa
-- de ser apagável por uma credencial que o próprio sistema descreve
-- como não podendo escrever nela.
--
-- A VOLTA ATRÁS, em um comando por tabela:
--   grant delete on public.<tabela> to service_role;
-- É privilégio, não dado — reversível de verdade, ao contrário do que
-- esta migração protege.
-- ===============================================================

revoke delete on
  public.aprendizado_feedback,
  public.decisoes,
  public.geracoes,
  public.governanca_aprovacoes,
  public.governanca_artefatos,
  public.governanca_eventos,
  public.governanca_publicacoes,
  public.governanca_versoes,
  public.parecer_achados,
  public.pareceres,
  public.qualidade_scores,
  public.revisoes,
  public.simulacoes
from service_role, authenticated, anon, public;

-- ===============================================================
-- CONFERÊNCIA — a migração falha se não cumpriu o que afirma
--
-- Mesmo padrão da 0024, da 0025 e da 0026: `revoke` que não pega não
-- levanta erro. Um arquivo que declara contenção precisa MEDIR.
--
-- E a conferência tem DOIS lados. Só medir "a trilha está fechada"
-- deixaria passar uma migração ampla demais — a que fecha a trilha e
-- leva junto as três tabelas que o aplicativo usa. Essa falharia em
-- produção, num botão, dias depois.
-- ===============================================================
do $$
declare
  sobrou text;
  trilha text[] := array[
    'aprendizado_feedback', 'decisoes', 'geracoes',
    'governanca_aprovacoes', 'governanca_artefatos', 'governanca_eventos',
    'governanca_publicacoes', 'governanca_versoes', 'parecer_achados',
    'pareceres', 'qualidade_scores', 'revisoes', 'simulacoes'];
  usadas text[] := array[
    'processos', 'config_orgaos', 'documentos_referencia'];
begin
  -- 1) as treze existem: um `revoke` sobre tabela ausente levantaria,
  --    mas um array digitado errado passaria calado.
  select string_agg(t, ', ') into sobrou
  from unnest(trilha) t
  where to_regclass('public.' || t) is null;
  if sobrou is not null then
    raise exception 'A 0027 nomeia tabela que não existe: %', sobrou;
  end if;

  -- 2) nenhum papel de rede apaga na trilha
  select string_agg(distinct table_name || '→' || grantee, ', ')
    into sobrou
  from information_schema.role_table_grants
  where table_schema = 'public' and table_name = any(trilha)
    and privilege_type = 'DELETE'
    and grantee in ('service_role', 'authenticated', 'anon', 'PUBLIC');
  if sobrou is not null then
    raise exception 'A 0027 deixou DELETE na trilha: %', sobrou;
  end if;

  -- 3) O OUTRO LADO: o aplicativo continua podendo apagar onde apaga.
  select string_agg(t, ', ') into sobrou
  from unnest(usadas) t
  where not exists (
    select 1 from information_schema.role_table_grants
    where table_schema = 'public' and table_name = t
      and privilege_type = 'DELETE' and grantee = 'service_role');
  if sobrou is not null then
    raise exception
      'A 0027 foi ampla demais e revogou DELETE de tabela que o '
      'aplicativo USA: % (ver src/db.py e src/rag.py)', sobrou;
  end if;
end
$$;
