# Implantação no VPS da Hostinger — do Streamlit Cloud para casa própria

**19/09/2026.** Sai a Vercel, entra o seu VPS na Hostinger servindo
`govconect.com` por HTTPS. O **Streamlit Cloud fica**, como homologação
— ver a seção *Homologação e produção*, que diz também o que ele **não**
é.

> **O IP do VPS não aparece escrito neste documento**, e a omissão é
> deliberada: este repositório é **público**. Um runbook que anuncia
> "há SSH de root neste endereço" é exatamente o que se varre no GitHub
> atrás de alvo. O domínio pode aparecer — DNS é público por natureza;
> o IP do servidor e o e-mail de contato, não precisam.
>
> Onde estiver `SEU_IP`, use o IPv4 do seu VPS, que está no hPanel.

**O que NÃO muda:** banco, autenticação e RLS continuam no Supabase.
Nenhuma das migrações 0018–0027 é tocada. O que muda é **onde o
processo Python roda** — e só isso.

> **Eu não executei nada disto.** A porta 22 do VPS é inalcançável do
> ambiente onde trabalho (a saída de rede é HTTPS por proxy) e não há
> chave privada aqui. O que está neste documento você roda; o que está
> em `implantacao/` eu escrevi e provei com `tests/test_implantacao_vps.py`.

---

## O que precisa ser feito, em ordem

A ordem importa em dois pontos, e os dois estão marcados.

### 1. Apontar o DNS ANTES de subir o servidor

O arquivo de zona que você me mandou mostra:

```
@    50 IN A    2.57.91.91
```

**`2.57.91.91` não é o seu VPS.** É um IP de parking/compartilhado da
Hostinger. Enquanto ele estiver ali, o domínio não chega ao servidor.

No painel da Hostinger (hPanel → Domínios → `govconect.com` → DNS /
Nameservers → Registros DNS), troque o registro `A` de `@`:

| Tipo | Nome | Valor atual | Valor novo | TTL |
|---|---|---|---|---|
| A | `@` | `2.57.91.91` | **o IPv4 do seu VPS** | 3600 |

O `CNAME` de `www` já aponta para a raiz e **não precisa mudar**.

**Por que antes e não depois:** o Caddy emite o certificado pelo desafio
HTTP-01, que consiste no Let's Encrypt bater em `http://govconect.com/`
e esperar a resposta do **seu** servidor. Com o DNS apontando para outro
lugar, a emissão falha — e falhas repetidas consomem a cota do Let's
Encrypt por domínio.

Confira a propagação antes de seguir (o TTL atual é de 50 s, então é
rápido):

```bash
dig +short govconect.com
# tem que responder o IPv4 do seu VPS
```

### 2. Preparar o servidor

Entre como root:

```bash
ssh root@SEU_IP        # o IPv4 do VPS, no hPanel da Hostinger
```

Instale o Docker (o script oficial cobre Ubuntu e Debian, que é o que a
Hostinger entrega):

```bash
curl -fsSL https://get.docker.com | sh
docker --version && docker compose version
```

**Firewall.** Abra só o necessário. A porta do Streamlit (8501) **não**
entra na lista — quem fala com a internet é o Caddy:

```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 443/udp     # HTTP/3
ufw --force enable
ufw status
```

### 3. Trazer o código

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/ewertonmarinho51-dev/projeto-saas.git govdocs
cd govdocs
```

### 4. Os segredos — e é aqui que eu paro de poder ajudar

```bash
mkdir -p /etc/govdocs
cp implantacao/env.exemplo /etc/govdocs/env
nano /etc/govdocs/env          # preencha os valores
chmod 600 /etc/govdocs/env
chown root:root /etc/govdocs/env
```

E o arquivo do Caddy, com **uma variável só** — o endereço que recebe os
avisos de expiração do certificado:

```bash
printf 'ACME_EMAIL=%s\n' 'voce@seu-dominio' > /etc/govdocs/caddy.env
chmod 600 /etc/govdocs/caddy.env
```

Ele é separado do arquivo do app de propósito: o Caddy não tem o que
fazer com as chaves do Supabase e das IAs, e dar a um proxy o ambiente
inteiro da aplicação amplia o estrago de graça no dia em que ele for
comprometido.

Os valores saem do painel do Supabase (Project Settings → API) e do
painel administrativo do próprio sistema. **Eu não os leio, não os peço
e não os escrevo em lugar nenhum** — é a regra desta empreitada desde a
primeira sessão, e ela não muda porque a hospedagem mudou.

`implantacao/env.exemplo` explica cada variável. Três pontos que decidem
segurança:

- **`GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR=1` e
  `GOVDOCS_EXIGIR_SUPABASE_AUTH=1`** ficam ligados. São os portões de
  falha fechada: sem eles o app degrada em silêncio para um modo que lê
  menos, ou aceita acesso sem login.
- **`GOVDOCS_MODO_ABERTO` fica de fora.** É o modo sem login, de
  desenvolvimento. Num servidor com domínio público, abre o sistema.
- **`OMNIROUTE_ROUTING_ENABLED=true`** precisa ir junto. Você ligou essa
  política à mão no Streamlit Cloud; trocar de casa sem levá-la
  devolveria, calado, o comportamento que ela impede — um edital caindo
  para motor não homologado quando a OpenAI falha. Há prova disso em
  `tests/test_implantacao_vps.py`.

### 5. Subir

```bash
cd /opt/govdocs/implantacao
docker compose up -d --build
docker compose ps          # o app deve aparecer como "healthy"
docker compose logs -f caddy
```

Na primeira subida o Caddy emite o certificado. Nos logs você verá
`certificate obtained successfully`. Se aparecer erro de desafio, o DNS
ainda não propagou — volte ao passo 1.

Abra **https://govconect.com**.

### 6. Desligar a Vercel — e MANTER o Streamlit Cloud

**Vercel:** vercel.com → projeto `projeto-saas` → Settings → Git →
*Disconnect*. Ou remova o projeto inteiro.

**Streamlit Cloud: fica.** Decisão do operador em 19/09/2026 — ele passa
a servir de homologação, para conferir alterações antes de promovê-las.
Configure nos Secrets dele:

```toml
GOVDOCS_AMBIENTE = "homologacao"
```

Isso faz o app desenhar a tarja de homologação. **Leia a seção seguinte
antes de tratá-lo como ambiente de teste** — ele não é um.

> A integração da Vercel nunca teve o que construir aqui: este
> repositório é um app **Streamlit** (`app.py`, `requirements.txt`,
> `packages.txt`), sem `vercel.json`, sem `package.json` na raiz, sem
> framework detectável. Por isso o check `Vercel` está vermelho em
> **toda** PR deste repositório desde sempre — e um check que sempre
> mente é pior que check nenhum, porque treina quem revisa a ignorar
> vermelho. Está documentado na PR #38.

---

## Homologação e produção

**A homologação acompanha `main`. A produção só se move por TAG.** É o
intervalo entre as duas que dá sentido a "testar antes de subir": tudo
que mergeia aparece no Streamlit Cloud sozinho; o VPS fica onde está até
alguém promover.

### ⚠ O que a homologação NÃO é

**Ela aponta para o banco de PRODUÇÃO.** Decisão do operador, registrada
— e a consequência não é opinião:

- **processo criado ali é processo real**, na tabela real;
- **documento aprovado ali congela snapshot de verdade**, com assinatura;
- **evento gravado ali entra na trilha de governança**, e desde a 0027 a
  credencial do aplicativo não apaga mais: lixo de teste fica;
- **flag ligada ali muda produção na hora, para todo mundo** — inclusive
  para quem está no VPS. As flags de `config_app` têm chave primária
  apenas em `chave`, sem escopo por instalação.

Então ela serve para **conferir tela e comportamento de código**. Não
serve para testar dado nem configuração. O app avisa isso numa tarja
vermelha no topo, e há prova de que a tarja não amolece
(`tests/test_ambiente_e_promocao.py`).

O isolamento de verdade seria apontar os Secrets do Streamlit Cloud para
o projeto `govdocs-ensaio-descartavel` do Supabase, que existe e só
precisa das migrações 0022, 0023, 0026 e 0027. O dia em que isso for
feito, `ambiente.grava_em_producao()` passa a devolver `False` — uma
linha, com o teste que já descreve a transição — e a tarja amansa
sozinha.

### Promover uma versão

No seu computador, quando o que está em `main` tiver sido conferido na
homologação:

```bash
git tag -a v1.4.0 -m "o que muda nesta versão"
git push origin v1.4.0
```

No VPS:

```bash
cd /opt/govdocs/implantacao
sudo ./promover.sh v1.4.0
sudo ./promover.sh --atual      # que versão está no ar?
```

O script recusa tag inexistente **antes** de tocar no serviço, guarda a
versão anterior para o caso de precisar voltar, e só declara sucesso
quando `https://govconect.com/_stcore/health` responde — `docker compose
up` devolve o controle quando os contentores foram criados, não quando o
aplicativo está servindo, e a diferença aparece justamente no dia em que
a versão nova não sobe.

Para voltar, é o mesmo comando com a versão anterior:

```bash
sudo ./promover.sh v1.3.0
```

## Reverter

**Uma versão:** `sudo ./promover.sh <versão anterior>` — ver acima.

**A hospedagem inteira:** devolva o registro `A` para `2.57.91.91`. O
Streamlit Cloud continua no ar como homologação e apontando para o mesmo
banco, então ele volta a atender sozinho assim que o DNS propagar. É um
efeito colateral agradável da decisão de manter os dois no mesmo banco —
e o único.

---

## O que esta mudança ganha, além de sair de hospedagem alheia

**O PDF institucional passa a sair pelo motor certo.** `packages.txt`
pedia `libreoffice` ao Streamlit Cloud; a imagem instala
`libreoffice-writer` **e** uma família de fontes. A diferença não é
cosmética: o binário `soffice` sem o pacote do Writer faz a conversão
DOCX→PDF cair no fallback `fpdf2` **sem avisar**, com geometria
diferente — foi exatamente o que fazia
`test_os_210_codigos_saem_uma_unica_vez_no_pdf[libreoffice]` falhar no
ambiente de desenvolvimento. E LibreOffice sem fonte instalada renderiza
caixas no lugar dos acentos, defeito que só aparece no PDF final.

**As variáveis de ambiente passam a ser suas.** `OMNIROUTE_ROUTING_ENABLED`
deixa de depender do espelhamento de Secrets do Streamlit Cloud para
`os.environ` — mecanismo que funciona, mas só **depois** que algo lê
`st.secrets`, e que eu tive que medir para poder afirmar.

---

## Decisões registradas

**Docker + Caddy, não systemd + nginx.** O `packages.txt` vira camada da
imagem, o LibreOffice fica declarado, e o TLS é automático. Com nginx, o
WebSocket do Streamlit (`/_stcore/stream`) exige `Upgrade`/`Connection`
na mão e falha de um jeito cruel quando alguém esquece: a página carrega
e nenhum botão responde.

**A porta 8501 não é publicada no host.** É a decisão de segurança mais
importante do `docker-compose.yml`. Com `ports: "8501:8501"`, o app ficaria
acessível em `http://<ip-do-vps>:8501` — sem TLS, sem domínio,
contornando o Caddy e todos os cabeçalhos dele. O site continuaria
funcionando pelo domínio, então ninguém notaria. Há prova, e a mutação
que publica a porta derruba duas.

**O contentor não roda como root**, e não carrega `supabase/`, `scripts/`
nem `tests/`. Imagem de produção que carrega migração é imagem que um dia
aplica migração sozinha.

**Sem CSP no Caddy, de propósito.** O Streamlit injeta script e estilo em
linha; uma CSP restritiva quebraria o app, e uma que precisa de
`unsafe-inline` para funcionar não protege de quase nada e **parece** que
protege. Se um dia valer a pena, o caminho é `nonce`, e é trabalho de
verdade.

**HSTS sem `preload` nem `includeSubDomains`.** Preload é praticamente
irreversível, e você ainda pode querer um subdomínio em HTTP durante
alguma migração.

**O volume dos certificados é nomeado.** Sem ele, cada `docker compose
down` descartaria os certificados e o Let's Encrypt seria consultado de
novo na subida seguinte — até bater o limite por domínio e o site ficar
sem HTTPS por uma semana. É o erro clássico de Caddy em contentor, e há
prova contra ele.

---

## O que este documento NÃO resolve

**Backup.** O banco continua no Supabase, que tem o backup do plano
contratado. O VPS não guarda estado — o que ele perde numa reinstalação é
só a configuração, que está aqui. Mas ninguém verificou se o backup do
Supabase está de fato ativo e com que retenção.

**Monitoramento.** Continua não havendo rastreamento de erro em produção.
Se o app cair às 2h, você descobre quando alguém contar. O
`restart: unless-stopped` religa o contentor, e o healthcheck tira do ar
um app mudo — mas nada avisa.

**A chave de servidor.** Ela vai passar a existir também em
`/etc/govdocs/env`, num servidor a mais. Isso não é um defeito desta
migração, mas aumenta a superfície: o achado de rotação de credencial,
aberto desde setembro, fica um pouco mais caro de adiar.
