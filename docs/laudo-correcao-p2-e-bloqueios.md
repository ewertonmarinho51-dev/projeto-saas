# Laudo — correção do P2, dos bloqueios e dos três impedimentos

Branch local `correcao-achados-ensaio-seguranca`. Data: 17/08/2026.

## Declaração de escopo de execução

**Nada foi aplicado em produção.** Durante todo este trabalho:

- nenhuma migração foi executada **em produção** — 0018, 0019 e 0020
  continuam com a extensão `.NAO_APLICAR`, conferida ao final. Elas
  foram aplicadas num **PostgreSQL local descartável**, que é o oposto
  de aplicá-las em produção: é como se descobre se funcionam antes que
  alguém as aplique de verdade;
- nenhum SQL foi rodado contra o banco de produção;
- nenhum dado de negócio foi lido, escrito ou alterado;
- nenhuma credencial foi rotacionada;
- nenhum `push`, `pull request` ou `merge` — o branch é local;
- a única consulta remota foi `list_projects` da API de gerência do
  Supabase, para apurar se existe projeto de ensaio descartável. Não
  existe: há **um** projeto, `govdocs-wizard`, o de produção.

## Fases A e B — EXECUTADAS num projeto Supabase descartável

Projeto `govdocs-ensaio-descartavel` (`uslaxaxomjawydqtbwkb`, sa-east-1,
US$ 0/mês), criado só para isto. **Não é produção** — a produção
continua sendo `govdocs-wizard`, intocada. O schema real do repositório
foi aplicado, medido no estado vulnerável, e então contido com
0018/0019/0020.

### Fase A — anon, antes e depois

| | ANTES | DEPOIS |
|---|---|---|
| anon LÊ | **26** de 28 | **0** |
| anon NEGADO | 2 | **28** |
| inconclusivo | 0 | 0 |
| RPCs abertas a anon | — | 0 |
| Storage | — | sem buckets (não aplicável) |

O ANTES reproduz o diagnóstico com dados reais e pelo PostgREST de
verdade: 26 tabelas legíveis por qualquer portador da chave publicável.
Só os dois backups resistiam, porque a 0015/0016 já os havia fechado.

### Fase B — isolamento, com GoTrue e PostgREST reais

Nove identidades autenticadas de verdade, com `app_metadata` no JWT.
**20 provas, 20 passaram:**

- leitura de processo por secretaria: titular e colega veem, outra
  secretaria e outro tenant não veem, admin vê o tenant;
- **P2**, nos dois eventos (`aprovacao_registrada` e
  `aprovacao_revogada`): revisor da secretaria 1 recusado na aprovação
  da 2, revisor da 2 recusado na da 1, cada um permitido na própria, e
  admin municipal alcançando as duas;
- aprovação com `entidade_tipo` inventado: recusada até para o admin;
- papel sem competência (titular, auditor): recusado;
- `insert` direto na trilha por `authenticated`: negado;
- `ator` do evento gravado == `auth.uid()` de quem chamou.

### E o ensaio real achou mais dois defeitos

**3. A 0019 abortava inteira no Supabase gerenciado.** O papel que
aplica migrações não é membro de `supabase_admin`, e
`alter default privileges for role supabase_admin` devolve 42501. Como
a migração é um bloco `begin/commit`, a recusa derrubava tudo: nada de
RLS, nada de revoke, o banco seguia aberto — e o erro não parecia ter
relação com o que se tentava fazer. O ensaio local não pegava, porque
lá `supabase_admin` é papel comum e o superusuário pode alterá-lo.
Corrigido: cada tentativa isolada, recusa registrada com `raise notice`.

**4. Confirmação ponta a ponta do defeito de `default privileges`.**
`anon` chamou pelo PostgREST uma função criada DEPOIS da revogação e
recebeu o resultado — não é artefato do Postgres local. Os Security
Advisors do Supabase não acusam.

A correção é um **gatilho de evento** (`funcao_nasce_fechada`) que
revoga EXECUTE no momento da criação, em vez de depender de um default
que o PostgreSQL não aplica. Conferido no projeto descartável: a função
criada antes dele continua aberta, a criada depois nasce fechada, e o
PostgREST confirma dos dois lados. Cobre `CREATE` e `ALTER FUNCTION`,
porque `create or replace` sobre função existente entra como ALTER e
reabriria o que a criação fechou.

### Security Advisors no projeto de ensaio

Nada crítico. Os dois `WARN` de `SECURITY DEFINER` executável por
`authenticated` são **intencionais e documentados**: a RPC da trilha é
o único caminho de escrita e confere autoridade por dentro. Os `INFO`
de "RLS sem política" são `config_app` e os dois backups — fechados a
`authenticated` de propósito.

## Os três impedimentos — resolvidos

### 1. 105 provas pulando → 47 provas EXECUTADAS

Não havia projeto Supabase descartável, e continua não havendo. A saída
foi outra: `scripts/ensaio_local.py` levanta o schema **real** do
repositório (as 15 migrações aplicadas, sem cópia nem paráfrase) num
PostgreSQL local, emula o schema `auth` com as **mesmas definições** de
`auth.uid()`/`auth.jwt()` que o Supabase usa — leitura de
`request.jwt.claims`, que é o que o PostgREST injeta — e aplica 0018,
0019 e 0020 na ordem do runbook. A 0020 roda ali **sem uma linha de
adaptação**; migração que precisasse ser adaptada não estaria sendo
ensaiada.

As 18 provas dinâmicas do P2 agora rodam de verdade, junto com 29
outras: 47 no total.

**E o ensaio achou dois defeitos que nenhuma leitura tinha achado:**

- **`alter default privileges ... revoke execute on functions from
  public` não funciona.** A 0019 apresentava essa linha como "a causa da
  recorrência, resolvida". Conferido três vezes em PG 16.13: roda sem
  erro, não grava linha em `pg_default_acl`, e a função seguinte nasce
  com `proacl` nulo — executável por PUBLIC, portanto por `anon`. O
  motivo é que `alter default privileges` só materializa linha quando
  **concede**; revogar de PUBLIC algo nunca materializado é um no-op
  silencioso. Pior: a verificação que a própria migração sugeria devolve
  zero linhas tanto no caso fechado quanto no nunca-fechado. Para
  tabelas e sequences o mecanismo funciona — também conferido.
- **`trg_evento_ator_confiavel`**, criada pela própria 0020, era a única
  função da migração sem revoke explícito, e estava aberta a `anon`
  exatamente por causa do defeito acima.

Os dois estão corrigidos. A guarda que sobra olha as **funções**, não a
tabela de defaults, e há uma prova negativa que falha se o PostgreSQL
um dia passar a se comportar como a 0019 supunha.

**Fronteira, dita aqui e no módulo:** isto prova o **banco** —
políticas, `SECURITY DEFINER`, matriz papel×evento, resolução de
escopo, GRANTs. Não prova PostgREST, GoTrue nem `supabase-py`. As 105
provas que dependem daquela camada continuam pulando, **de propósito**,
e um projeto descartável ainda é necessário para elas.

### 2. Etapa E aberta → o login existe

Era a peça que faltava, e sem ela o resto não adiantava: enquanto a
autenticação foi a tabela `usuarios` com `senha_hash` conferido no
Python, **não existia JWT de usuário**, e sem JWT toda requisição ia com
a credencial de servidor, que atravessa o RLS.

`auth.autenticar` tenta o Supabase Auth primeiro, com a chave
**publicável** — o login é a única operação anterior à identidade, e
fazê-la com a credencial de servidor apagaria a diferença entre "o
servidor autenticou alguém" e "o servidor decidiu que estava tudo bem".
`entrar()` guarda o access token na sessão; `sair()` o apaga primeiro e
sempre.

Duas regras que o caminho de transição precisa ter, e tem: senha errada
no Supabase Auth **não** cai para o legado (seria uma segunda tentativa
contra outro banco de senhas), e conta sem vínculo em `usuarios` **não
entra** (autenticar não é autorizar).

`GOVDOCS_EXIGIR_SUPABASE_AUTH=1` fecha a porta legada.

**O que ainda falta**, e não dá para fazer daqui: aplicar a 0020 num
ambiente real e fazer o **backfill** das contas no Supabase Auth. Ver
`docs/etapa-e-credencial-de-servidor.md`, que lista a ordem de
implantação em seis passos e o que acontece se ela for desrespeitada.

### 3. Histórico com 31 segredos → exit 0

Os 31 achados viviam em 10 commits, todos de rodadas anteriores, todos
locais e nunca empurrados. Foram espremidos num único commit de árvore
limpa; os commits desta rodada, um por correção, seguem separados.

Sobraram 3 achados — endereços `@exemplo.invalid` das provas novas do
login. Foram resolvidos por **regra**, não por isenção: a RFC 2606
reserva `.invalid`, `.test`, `.example` e os `example.com/net/org` para
documentação e teste, e endereços ali não resolvem nem roteiam. A
ocorrência continua **aparecendo** no laudo como falso documentado —
sai da contagem que bloqueia, não da que informa.

| | árvore final | histórico |
|---|---|---|
| ocorrências | 33 | 47 |
| falsos documentados | 33 | 47 |
| **segredos reais** | **0** | **0** |
| exit | **0** | **0** |

O `format-patch` do branch deixou de vazar a referência do projeto de
produção. A árvore é **byte a byte idêntica** à de antes da reescrita —
conferido com `git diff --stat` entre as duas pontas.

### Bônus: a suíte ficou verde

`test_pdf_via_libreoffice_quando_disponivel` era a única falha, e vinha
de antes deste branch. O comentário dizia "nunca Helvetica **no
corpo**"; a asserção recusava Helvetica em qualquer posição da página, e
o único texto sans-serif do PDF é o rodapé "Página 1/1", que é assim de
propósito. Falhava por motivo diferente do declarado — o que treina
quem lê a suíte a ignorar o vermelho.

A asserção passou a dizer o que o comentário sempre disse, e ficou mais
forte: o corpo inteiro tem de ser serifado. O rodapé é **fixado**, não
apenas excluído.

## Veredito

> **A contenção está VERIFICADA EM EXECUÇÃO — banco, PostgREST e
> GoTrue —, num projeto descartável.**
> **Em PRODUÇÃO ela continua NÃO aplicada.**

O que sustenta a primeira frase: 47 provas executadas contra um
PostgreSQL real, com as três migrações aplicadas, cobrindo isolamento
por tenant e por secretaria, autoridade por papel, resolução de escopo
da aprovação, trilha append-only e GRANTs.

O que sustenta a primeira frase: 47 provas no PostgreSQL local, mais
Fase A (26 tabelas abertas → 0) e Fase B (20/20) num projeto Supabase
descartável, com PostgREST e GoTrue reais.

O que impede a segunda:

1. **Nada disto foi aplicado em produção.** As três migrações continuam
   `.NAO_APLICAR`. O que se sabe agora é que elas FUNCIONAM — inclusive
   que a 0019, como estava, teria abortado.
2. **O backfill não foi feito** e `GOVDOCS_EXIGIR_SUPABASE_AUTH`
   continua desligado. Até lá, quem entra pelo caminho legado opera sem
   JWT.
3. **A maior parte de `db.py` ainda usa a credencial de servidor.** A
   trilha, a decisão de proposta e o registro de aprovação foram
   movidos; processos, revisões, gerações e o resto não.
4. **O ensaio não cobriu `service_role`.** O MCP do Supabase não expõe
   a chave secreta, então "o servidor continua operando" (item 3 da
   fase A) não foi medido. É a única lacuna que resta no ensaio.

## Requisito → prova → resultado

| # | Requisito | Provas | Resultado |
|---|---|---|---|
| 1 | escopo da aprovação desce até o artefato; matriz tipo→tabela fechada | 9 estáticas + 18 executadas | **PASSA** — e 4 mutações, todas pegas |
| 2 | fixtures e provas dinâmicas de secretaria | 18, no ensaio SQL | **PASSA (executadas)** |
| 3 | varredura gera o próprio conteúdo; base/head/sha256; recusa escopo incompatível | 25 | **PASSA** |
| 4 | `42P17` fora dos códigos que provam NEGADO | 8 | **PASSA** |
| 5 | Etapa E: JWT do usuário, RPC, vocabulário reconciliado, login | 24 | **PARCIAL** — código completo; backfill e PostgREST pendentes |
| 6 | verificação e laudo | abaixo | **PASSA** |

## Verificação executada

```
git diff --check (árvore e intervalo)   limpo
suíte local                             826 passam · 0 falham · 152 pulam
suíte com o ensaio SQL ligado           873 passam · 0 falham · 105 pulam
ensaio SQL local                        47 provas, todas passam
varredura ÁRVORE                        exit 0 · 0 segredos reais
varredura HISTÓRICO                     exit 0 · 0 segredos reais
escopo incompatível                     RECUSADO (exit 2), nos dois sentidos
migrações .NAO_APLICAR                  3/3 intactas (0018, 0019, 0020)
fases A e B (PostgREST/GoTrue)          NÃO RODARAM — sem projeto descartável
```

Os 105 pulos são **um único motivo** — a ausência do projeto de ensaio —
multiplicado pelas provas que dependem dele.

## Commits

| commit | conteúdo |
|---|---|
| `6c75f3e` | rodadas 1 a 5, espremidas (árvore limpa) |
| `139f89e` | 0020: aprovação não é objeto raiz (P2) |
| `7ae3bf4` | dois revisores, três trilhas, prova dinâmica do escopo |
| `20162a1` | 42P17 é defeito de política, não prova de negação |
| `ac869d4` | varredura com escopo apurado |
| `0cf4ae9` | Etapa E: trilha pela RPC, com JWT do usuário |
| `19d8c93` | laudo (versão anterior) |
| `15c1b53` | ensaio SQL local — e os dois defeitos que ele achou |
| `544e8c3` | login por Supabase Auth |
| `c06221c` | domínio reservado (RFC 2606) por regra |
| `92217e7` | o PDF falhava por motivo diferente do declarado |

## Como reproduzir o ensaio

```bash
# cluster descartável (como usuário postgres; o servidor recusa root)
initdb -D /var/tmp/ensaio-pg -U postgres --auth=trust
pg_ctl -D /var/tmp/ensaio-pg -o "-k /tmp/pgens -h ''" start

# schema real + as três migrações .NAO_APLICAR
python scripts/ensaio_local.py \
    --dsn "postgresql://postgres@/postgres?host=/tmp/pgens"

# as provas
GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/postgres?host=/tmp/pgens" \
    python -m pytest tests/test_ensaio_sql_local.py -q
```

O script **recusa** DSN que não seja local. Sem isso, a mesma ferramenta
que ensaia serviria para aplicar `.NAO_APLICAR` em produção com uma
variável de ambiente trocada.

## O que falta para CONTIDO

1. criar um projeto Supabase **descartável** e aplicar 0018/0019/0020;
2. rodar as fases A e B, com as 105 provas restantes executando;
3. backfill das contas no Supabase Auth (Admin API, `app_metadata`);
4. ligar `GOVDOCS_EXIGIR_SUPABASE_AUTH=1`;
5. mover o restante de `db.py` para o JWT do usuário.
