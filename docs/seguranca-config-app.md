# Exposição de segredos e de processos pela chave anônima

**Achado em 14/08/2026**, durante a auditoria do padrão ouro documental
(`docs/diagnostico-padrao-ouro.md`, seção 6). Branch própria porque a
correção é de infraestrutura, não de geração documental.

## O que está exposto

A chave anônima (`anon` / publicável) do Supabase é a que vai no
navegador de qualquer visitante do app. Com ela, hoje:

| Tabela | O que se obtém | Gravidade |
|---|---|---|
| `config_app` | `OPENAI_API_KEY` e `GOOGLE_API_KEY` **em texto puro** | **crítica** |
| `processos` | conteúdo integral dos documentos, formulário, nomes de servidores | alta |
| `revisoes` | snapshots, relatórios e diffs de todos os processos | alta |

Como foi constatado: um `GET` no endpoint REST do projeto, autenticado
apenas com a chave publicável, devolveu as três tabelas. Foi assim que
os artefatos do caso auditado foram recuperados nesta sessão — sem
nenhuma credencial privilegiada.

## Ordem de execução (a migração NÃO é o primeiro passo)

1. **Rotacionar as duas chaves** nos provedores (OpenAI e Google) e
   gravar as novas no painel administrativo. Fechar o acesso sem
   rotacionar não resolve: as chaves atuais já estiveram legíveis
   publicamente e devem ser tratadas como comprometidas.
2. **Conferir o consumo**: painéis da OpenAI e do Google — uso fora do
   padrão indica que a exposição já foi explorada.
3. **Verificar como o app lê a configuração.** Depois da migração,
   `config_app` só é legível por `service_role`. Se o servidor ainda
   ler com a chave anônima, a leitura passa a falhar; o certo é migrar
   essa leitura para o lado servidor — **não** reabrir o acesso.
4. **Aplicar** `supabase/migrations/0018_rls_config_app_e_processos.sql`.
5. **Validar**: com a chave anônima, `select` em `config_app` deve
   voltar vazio; `insert`/`update`/`delete` em `processos` e `revisoes`
   devem ser negados; e o app deve continuar funcionando.

## O que a migração 0018 faz — e o que deixa em aberto

**Fecha:**
- revoga todos os privilégios de `anon`, `authenticated` e `public`
  sobre `config_app`, e habilita RLS (`force`) sem nenhuma política —
  com RLS ativo e zero políticas, todo papel sujeito a RLS lê zero
  linhas; `service_role` contorna o RLS e segue atendendo o servidor;
- revoga `insert`, `update`, `delete` e `truncate` de `anon` sobre
  `processos` e `revisoes`: nenhum visitante altera ou apaga processo
  alheio.

**Deixa em aberto, de propósito:** a **leitura** de `processos` e
`revisoes` continua pública. Fechá-la exige política de RLS por
tenant/usuário, e aplicar isso sem antes conferir como o app autentica
derrubaria o acesso legítimo dos servidores. É a etapa seguinte, com o
modelo de autenticação em mãos.

**Não toca em dados:** nenhuma linha é lida, alterada ou removida. A
migração é idempotente.

## Estado

**Não aplicada.** Escrita, revisada e versionada nesta branch; a
aplicação em produção depende da rotação das chaves (etapa 1) e é
decisão do responsável pelo projeto.
