# Runbook P06: operação e implantação do Gov Conect 2.0

Estado em 22/10/2026. Nada aqui foi executado em produção. Deploy,
DNS e credenciais só com aceite humano explícito (P06, 10_DEPLOY).

## 1. O que existe no repositório

| Peça | Arquivo | Prova |
|---|---|---|
| Imagem da API (FastAPI, uid 10002, sem Streamlit) | `implantacao/Dockerfile.api`, alvo `api` | job `imagens`: não-root, sem Streamlit, live 200, ready 503 e `/api/v1/me` 401 sem configuração |
| Imagem do worker (Celery + LibreOffice Writer + DejaVu) | `implantacao/Dockerfile.api`, alvo `worker` | job `imagens`: DOCX para PDF com a raiz somente leitura e `/tmp` em tmpfs |
| Imagem do web (Next standalone, usuário `node`) | `implantacao/Dockerfile.web` | job `imagens`: não-root, `/entrar` 200; build recusa chave de servidor |
| Compose com `web`, `api`, `worker`, `redis` | `implantacao/docker-compose.yml`, profile `govconect` | job `imagens`: sem profile continua só `app` + `caddy`; com profile, só o Caddy publica porta |
| Caddy do corte | `implantacao/Caddyfile.govconect` | não montado; só no corte |

Decisões de desenho (ADR-001/004/007):

- **A API não é pública.** O navegador fala com o `web` (BFF); o `web`
  fala com `api:8000` na rede interna. O Caddy do corte não tem rota
  para `/api/v1/*`.
- **Segredo por serviço.** `api.env` e `web.env` são arquivos novos; o
  `/etc/govdocs/env` do Streamlit (que tem a chave de SERVIDOR) não é
  lido por nenhum serviço novo.
- **Redis** com senha, sem persistência, `noeviction`, 256 MB: fila e
  arquivo efêmero (relatório por 30 min). Job de negócio no Postgres
  (0031/0032).
- **Raiz somente leitura** em `web`, `api`, `worker`, `redis`; `/tmp` em
  tmpfs; limites de memória por serviço; `stop_grace_period` de 60 s no
  worker (`acks_late` devolve o aviso se o item não terminar).

## 2. Arquivos de ambiente (nomes, nunca valores)

`/etc/govdocs/api.env` (API e worker):

| Variável | Valor esperado |
|---|---|
| `APP_ENV` | `production` |
| `SUPABASE_URL` | URL do projeto |
| `SUPABASE_KEY` | chave **publicável** (`sb_publishable_…`); a de servidor é recusada |
| `REDIS_URL` | `redis://:<senha>@redis:6379/0` (sem senha, a API recusa subir em staging/produção) |
| `PRICE_RESEARCH_ENABLED` | `0` até o corte do módulo; depois `1` |
| `GOVCONECT_LIMITE_POR_MINUTO` | opcional (padrão 120) |

`/etc/govdocs/web.env`:

| Variável | Valor esperado |
|---|---|
| `GOVCONECT_API_URL` | `http://api:8000` |
| `GOVCONECT_SITE_URL` | `https://<domínio novo>` |
| `PRICE_RESEARCH_ENABLED` | igual ao da API |

`/etc/govdocs/redis.env` (só o Redis):

| Variável | Valor esperado |
|---|---|
| `REDIS_SENHA` | a mesma senha de `REDIS_URL`; gerar com `openssl rand -hex 32` |

Build do web (shell do operador, não arquivo): `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.

`/etc/govdocs/caddy.env` ganha `GOVCONECT_DOMINIO` e
`GOVDOCS_DOMINIO_LEGADO` no corte.

## 3. Pendências que dependem do operador

1. ~~**Medir o host**~~ feito em 23/10/2026 pelo operador (Ubuntu 26.04.1,
   kernel 7.0):

   | Recurso | Medido |
   |---|---|
   | CPU | **1 vCPU** |
   | RAM | 3.910 MB total; 831 MB em uso; 3.078 MB disponíveis |
   | Swap | **nenhum** |
   | Disco | 48 GB, 7 GB usados (15%) |
   | Streamlit (`implantacao-app-1`) | 145 MiB, 4,6% de CPU |
   | Caddy | 18 MiB |

   Leitura:
   * **Memória cabe, sem folga para pico.** Os limites novos somam
     ~2,2 GB (web 512 MB, api 384 MB, worker 1 GB, redis 320 MB) contra
     3,0 GB disponíveis. O consumo REAL esperado em repouso é bem menor
     (Next e API na casa de 150–250 MB cada), mas o pico é o LibreOffice
     do worker (PDF do analítico integral). **Sem swap**, um pico acima do
     disponível vira OOM kill, não lentidão.
   * **CPU é o gargalo.** Um vCPU para Streamlit, Next (SSR), API, worker
     e Redis: um PDF grande no worker disputa CPU com cada página do web.
     A latência do usuário durante uma emissão pesada é o que mais vai
     sofrer.
   * **Build no host não cabe.** `npm ci` + `next build` em 1 vCPU sem
     swap é lento e arrisca OOM com o Streamlit de pé. As imagens devem
     ser construídas no CI (o job `imagens` já constrói) e publicadas num
     registro, e o host só faz `pull`.

   Recomendação (decisão do operador):
   1. ~~**Swap de 2 GB**~~ **feito em 23/10/2026** pelo operador:
      `/swapfile` de 2 GB, ativo (`swapon --show`: 2G, 0B usados), no
      `/etc/fstab` (cópia anterior em `/etc/fstab.bak-20261023`),
      `vm.swappiness=10` em `/etc/sysctl.d/99-govconect-swap.conf`.
      Depois: 3.102 MB de RAM disponíveis + 2.047 MB de swap. Desfazer:
      `swapoff /swapfile && rm /swapfile && cp /etc/fstab.bak-20261023
      /etc/fstab && rm /etc/sysctl.d/99-govconect-swap.conf && sysctl -w
      vm.swappiness=60`. O swap protege contra OOM; não resolve o vCPU.
   2. **Antes do corte**: VPS com **2 vCPU / 8 GB** (P06: "proponha
      upgrade, não esconda limitação"). Com o Streamlit como rollback
      durante a transição, são seis serviços num host.
   3. Publicar as imagens do CI num registro (GHCR) e promover por SHA.
2. **Staging isolado**: projeto Supabase separado (o descartável
   `govdocs-ensaio-descartavel` serve para ensaio, não para staging com
   identidades de teste estáveis) e domínio próprio (ex.:
   `staging.<domínio>`). DNS é decisão do operador.
3. **Domínio do Gov Conect 2.0** e o destino do `govconect.com` no corte.
4. ~~Senha do Redis~~: feito no P06c. O Redis exige `requirepass`
   (`redis.env`), a API recusa `REDIS_URL` sem senha em staging/produção,
   e o job `imagens` prova que PING sem senha é recusado.

## 4. Staging (quando houver projeto e domínio)

O host NÃO constrói imagem (1 vCPU). Elas vêm do GHCR, publicadas por
`.github/workflows/govconect-imagens.yml`:

1. **Variáveis do repositório** (Settings → Variables, não segredo):
   `NEXT_PUBLIC_SUPABASE_URL_staging` e
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY_staging` (e as `_production`
   no corte). A chave é a PUBLICÁVEL; a de servidor é recusada no build.
2. **Publicar**: a cada merge no `main`, api e worker saem como
   `ghcr.io/ewertonmarinho51-dev/govconect-{api,worker}:sha-<12>`. O web
   sai por *Run workflow* com o ambiente:
   `govconect-web:<ambiente>-sha-<12>`.
3. **Host, uma vez**: `docker login ghcr.io` com um token de **leitura**
   de pacotes (PAT `read:packages`), se os pacotes forem privados.
4. **Promover**:
   ```
   cd /opt/govdocs/implantacao && git pull
   ./promover_govconect.sh sha-<12> staging
   ./promover_govconect.sh --atual
   ```
   Baixa as três imagens antes de mexer em nada; sobe `redis`, `api`,
   `worker`, `web` (o Streamlit e o Caddy não são tocados); espera `api`
   e `web` healthy por 120 s; se não ficarem, volta sozinho às imagens
   anteriores. Provado no CI (job `imagens`): versão boa sobe, versão
   quebrada é recusada e a anterior volta healthy.

Smoke manual: login, lista de processos, pesquisa de preços (com a
flag), coleta (job até `succeeded`), emissão DOCX e PDF, download.

## 4a. Convivência no mesmo domínio e projeto (ADR-009, decisão de 23/10)

Sem staging separado por enquanto: o Gov Conect 2.0 sobe no mesmo host,
no `govconect.com` e no projeto Supabase de produção, nos caminhos dele
(`/entrar`, `/app/*`, `/auth/*`, `/privacidade`). O `/` continua sendo o
Streamlit.

1. **Release** que contenha `Caddyfile.convivencia`, `promover_govconect.sh`
   e o compose com profile (promoção do Streamlit de sempre,
   `promover.sh <tag>`).
2. **Ambiente** (valores no servidor, nunca no repositório):
   - `/etc/govdocs/api.env`: `APP_ENV=production`, `SUPABASE_URL` do
     projeto, `SUPABASE_KEY` **publicável**, `REDIS_URL` com senha,
     `PRICE_RESEARCH_ENABLED=1`;
   - `/etc/govdocs/web.env`: `GOVCONECT_API_URL=http://api:8000`,
     `GOVCONECT_SITE_URL=https://govconect.com`, `PRICE_RESEARCH_ENABLED=1`;
   - `/etc/govdocs/redis.env`: `REDIS_SENHA`.
3. **Variáveis do repositório** `NEXT_PUBLIC_SUPABASE_URL_production` e
   `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY_production` (URL e chave
   publicável do projeto) e *Run workflow* "Gov Conect - imagens" com
   `production`.
4. **Supabase Auth** (painel): acrescentar
   `https://govconect.com/auth/confirmar` às Redirect URLs (recuperação
   de senha do web).
5. **Host**: `docker login ghcr.io` (token só de leitura) e
   `./promover_govconect.sh sha-<12> production`.
6. **Ligar a convivência**:
   ```
   cd /opt/govdocs/implantacao
   echo 'GOVCONECT_CADDYFILE=Caddyfile.convivencia' >> .env
   docker compose up -d caddy
   ```
7. **Smoke** só com o tenant e as contas do canário: `/entrar`, lista de
   processos, pesquisa de preços, coleta, emissão, download; e `/` ainda
   o Streamlit.

**Desligar** (o Streamlit nunca saiu do ar):
```
cd /opt/govdocs/implantacao
sed -i '/^GOVCONECT_CADDYFILE=/d' .env
docker compose up -d caddy
```

## 5. Corte e rollback

Corte (com aceite): trocar o volume do Caddy de `./Caddyfile` para
`./Caddyfile.govconect`, `docker compose --profile govconect up -d`,
conferir TLS do domínio novo e o legado no domínio de rollback.

Rollback: voltar o volume do Caddy para `./Caddyfile` e
`docker compose up -d caddy`. Os serviços novos podem ficar de pé (não
publicam porta) ou sair com `docker compose --profile govconect stop`.
Nenhuma migração desta frente é destrutiva; rollback de código não pede
rollback de banco.

## 6. Ainda não feito no P06 (próximas fatias)

- métricas RED e de job, alertas de indisponibilidade e de orçamento de
  IA (ADR-005);
- backup e restauração testada do banco (inclui políticas de RLS);
- ~~promoção por SHA para os serviços novos~~: `promover_govconect.sh`
  + imagens no GHCR (rollback automático provado no CI);
- relatório de rollback **testado no host** (exige staging).

## 7. P05 (editor WordCraft): BLOCKED

Pelo critério do próprio P05 ("se contratos instáveis: manter UI feature
flag off e declarar BLOCKED"):

- a frente do WordCraft está ativa (último commit em 22/10/2026, 00:47);
- o runtime se declara `INTERNAL_LOCAL_QA_ONLY_NOT_DEPLOY_APPROVED`;
- o canário de 21/10 (`docs/wordcraft/canario-producao-2026-10-21.md`)
  reprovou fechado: o editor não montou em produção.

Achados para a frente do WordCraft (registrados, não alterados aqui):

1. `tests/test_seguranca_contencao.py` mantém `documentos_editor`,
   `documentos_editor_revisoes` e `documentos_editor_emissoes` como "não
   implantadas", mas o catálogo de produção as tem (48 tabelas = 45 do
   inventário + estas 3). O inventário afirma o contrário do catálogo.
2. As três estão com RLS **ligada mas não forçada** (`relforcerowsecurity
   = false`), com uma política cada; as tabelas desta frente são todas
   forçadas.
