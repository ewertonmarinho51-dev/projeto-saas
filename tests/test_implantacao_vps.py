"""
A implantação no VPS, medida — não lida.

POR QUE UM ARQUIVO DE ARTEFATO DE INFRA TEM PROVA

Porque os defeitos aqui são silenciosos por natureza. Um
`.dockerignore` no diretório errado não avisa: a build passa, a
imagem sobe, e o `secrets.toml` entrou no contexto. Uma porta
publicada por engano não avisa: o site funciona pelo domínio E
pelo IP em texto claro. Um volume de certificado esquecido não
avisa até o Let's Encrypt recusar a emissão e o site ficar sem
HTTPS por uma semana.

São todos erros que só aparecem em produção, e este repositório
já decidiu há muito tempo que descobrir em produção não conta.

FRONTEIRA, dita antes que alguém confie demais: isto lê os
ARQUIVOS. Não constrói a imagem, não sobe contentor, não fala com
o VPS — não há Docker neste ambiente nem rota para a porta 22.
O que estas provas pegam é contradição e regressão nos artefatos;
o que elas NÃO pegam é o servidor ter subido.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
IMPLANTACAO = RAIZ / "implantacao"

DOCKERFILE = IMPLANTACAO / "Dockerfile"
COMPOSE = IMPLANTACAO / "docker-compose.yml"
CADDYFILE = IMPLANTACAO / "Caddyfile"
ENV_EXEMPLO = IMPLANTACAO / "env.exemplo"
DOCKERIGNORE = RAIZ / ".dockerignore"


def _texto(caminho: Path) -> str:
    assert caminho.exists(), f"artefato de implantação ausente: {caminho}"
    return caminho.read_text(encoding="utf-8")


def _sem_comentario(texto: str) -> str:
    """
    O texto sem as linhas de comentário.

    ISTO NÃO É DETALHE — é a terceira vez que este repositório
    tropeça na mesma pedra. O inventário de segurança leu a prosa
    da 0025 e cadastrou uma tabela chamada `if`; aqui a primeira
    versão da prova de porta leu o comentário que EXPLICA por que
    `ports: "8501:8501"` é proibido e reprovou o arquivo por
    conter a explicação.

    Medir configuração exige separar o que é instrução do que é
    prosa sobre a instrução. Consertar o comentário — apagá-lo, ou
    escrevê-lo com a porta disfarçada — seria calar a explicação
    para agradar a prova, que é o remédio errado.
    """
    return "\n".join(l for l in texto.splitlines()
                     if not l.lstrip().startswith("#"))


# ---------------------------------------------------------------------------
# 1) O `.dockerignore` no lugar CERTO
# ---------------------------------------------------------------------------
def test_o_dockerignore_esta_na_raiz_do_contexto():
    """
    O Docker procura `.dockerignore` na raiz do CONTEXTO de build,
    não junto do Dockerfile. A primeira versão desta entrega o pôs
    em `implantacao/`, onde ele seria ignorado EM SILÊNCIO — e o
    silêncio é o problema: a build funciona, e o segredo entra.
    """
    assert DOCKERIGNORE.exists(), (
        ".dockerignore não está na raiz do repositório, que é o contexto "
        "de build declarado no compose — ele seria ignorado em silêncio")
    assert not (IMPLANTACAO / ".dockerignore").exists(), (
        "há um .dockerignore em implantacao/, onde o Docker não o lê; "
        "duas cópias divergem caladas")


def test_o_contexto_de_build_e_a_raiz_que_o_dockerignore_protege():
    """
    A prova acima vale por causa desta: se alguém mudar o `context`
    do compose, o `.dockerignore` da raiz deixa de ser o do
    contexto e a proteção evapora sem que nada mude de aparência.
    """
    compose = _sem_comentario(_texto(COMPOSE))
    assert re.search(r"context:\s*\.\.", compose), (
        "o contexto de build deixou de ser a raiz — reveja onde o "
        ".dockerignore precisa estar")


@pytest.mark.parametrize("padrao", [
    ".streamlit/secrets.toml",
    ".env",
    "*.pem",
    "*.key",
    "contas-auth.json",
    ".git",
])
def test_o_dockerignore_barra_o_que_nao_pode_entrar_na_imagem(padrao):
    """
    Camada de imagem é distribuível. O que a build enxerga pode
    viajar — inclusive `.git`, que carrega o histórico inteiro e,
    com ele, qualquer coisa já removida por commit.

    A COMPARAÇÃO É POR LINHA INTEIRA, e a primeira versão desta
    prova não era. Ela checava substring, então apagar a regra
    `.streamlit/secrets.toml` não a derrubava: a linha vizinha
    `.streamlit/secrets.toml.*` contém o mesmo texto e a satisfazia.
    O arquivo de segredo mais importante teria voltado ao contexto
    de build com a suíte verde — a mutação provou isso.

    Regra de ignore é linha, não trecho. Medir como trecho é o
    mesmo erro de `lstrip` receber um conjunto de caracteres
    quando se queria um prefixo.
    """
    regras = {l.strip() for l in _texto(DOCKERIGNORE).splitlines()
              if l.strip() and not l.lstrip().startswith("#")}
    assert padrao in regras, (
        f"{padrao!r} não é uma REGRA do .dockerignore — pode estar só "
        f"como parte de outra linha, que não protege nada")


# ---------------------------------------------------------------------------
# 2) A porta do app NÃO é publicada no host
# ---------------------------------------------------------------------------
def test_o_streamlit_nao_fica_exposto_direto_na_internet():
    """
    ESTA É A PROVA DE SEGURANÇA DESTE ARQUIVO.

    Com `ports: "8501:8501"` no serviço do app, o Streamlit
    responderia em http://<ip>:8501 — sem TLS, sem domínio,
    contornando o Caddy e todos os cabeçalhos dele. O site
    continuaria funcionando pelo domínio, então ninguém notaria.

    Só o Caddy publica porta.
    """
    compose = _sem_comentario(_texto(COMPOSE))
    servico_app = compose.split("caddy:")[0]

    assert "8501:8501" not in servico_app, (
        "a porta do Streamlit foi publicada no host: o app fica alcançável "
        "por IP em texto claro, contornando o Caddy")
    assert re.search(r"expose:\s*\n\s*-\s*\"?8501", servico_app), (
        "o app deixou de expor 8501 na rede interna — o Caddy não o alcança")


def test_so_o_caddy_publica_porta():
    compose = _sem_comentario(_texto(COMPOSE))
    publicadas = set(re.findall(r'^\s+-\s*"(\d+):', compose, re.M))
    assert publicadas <= {"80", "443"}, (
        f"portas publicadas além de 80/443: {sorted(publicadas - {'80', '443'})}")


# ---------------------------------------------------------------------------
# 3) Os certificados sobrevivem a um `down`
# ---------------------------------------------------------------------------
def test_os_certificados_persistem_entre_subidas():
    """
    Sem volume em `/data`, cada `docker compose down` descarta os
    certificados e o Let's Encrypt é consultado de novo na subida
    seguinte — até bater o limite por domínio e o site ficar sem
    HTTPS por uma semana. É o erro clássico de Caddy em contentor.
    """
    compose = _sem_comentario(_texto(COMPOSE))
    assert "caddy_data:/data" in compose, (
        "o volume de certificados sumiu: cada `down` reemitiria o "
        "certificado até o Let's Encrypt recusar")
    assert re.search(r"^volumes:\s*$", compose, re.M), (
        "`caddy_data` é usado mas não está declarado em `volumes:`")


# ---------------------------------------------------------------------------
# 4) NENHUM SEGREDO nos arquivos versionados
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("arquivo", [
    "Dockerfile", "docker-compose.yml", "Caddyfile", "env.exemplo"])
def test_nenhum_artefato_de_implantacao_carrega_valor_de_segredo(arquivo):
    """
    `env.exemplo` é versionado e existe justamente para NÃO ter
    valor. As chaves aparecem pelo NOME, sempre com o lado direito
    vazio — quem preencher o de verdade preenche em
    `/etc/govdocs/env`, que não está no repositório.
    """
    texto = _texto(IMPLANTACAO / arquivo)

    for linha in texto.splitlines():
        limpa = linha.strip()
        if limpa.startswith("#") or "=" not in limpa:
            continue
        nome, _, valor = limpa.partition("=")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", nome.strip()):
            continue  # não é atribuição de variável de ambiente
        sensivel = any(p in nome for p in
                       ("KEY", "SECRET", "TOKEN", "PASSWORD", "SENHA"))
        if sensivel:
            assert valor.strip() == "", (
                f"{arquivo}: {nome.strip()} veio com valor preenchido")

    # A forma dos segredos conhecidos, caso apareçam soltos no texto.
    for forma in (r"sb_secret_\w", r"sk-proj-\w", r"AIza[\w-]{10}",
                  r"eyJ[\w-]{20}"):
        assert not re.search(forma, texto), (
            f"{arquivo} contém algo com forma de credencial ({forma})")


def test_nenhum_artefato_publica_ip_de_servidor_nem_endereco_pessoal():
    """
    ESTE REPOSITÓRIO É PÚBLICO, e isso muda o que pode ser escrito
    aqui.

    A primeira versão desta entrega trazia o e-mail pessoal do
    operador no `Caddyfile` e `root@<ip>` no runbook. Nenhum dos
    dois é segredo no sentido estrito — e os dois seriam
    publicados: um endereço para quem varre GitHub atrás de
    e-mail, e um convite dizendo "há SSH de root neste IP".

    Foi o varredor de segredos que pegou, e a correção foi
    parametrizar, não silenciar o varredor com allowlist.

    O DOMÍNIO pode aparecer: DNS é público por natureza.
    """
    ipv4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
    email = re.compile(r"[\w.+-]+@[\w-]+\.[A-Za-z]{2,}")

    for caminho in list(IMPLANTACAO.iterdir()) + [DOCKERIGNORE]:
        if not caminho.is_file():
            continue
        texto = caminho.read_text(encoding="utf-8")
        for achado in ipv4.findall(texto):
            # `0.0.0.0` é endereço de escuta, não de servidor.
            assert achado in ("0.0.0.0", "127.0.0.1"), (
                f"{caminho.name} publica o IP {achado} num repositório "
                f"público — parametrize")
        assert not email.search(texto), (
            f"{caminho.name} publica um endereço de e-mail num "
            f"repositório público — use uma variável de ambiente")


def test_o_env_exemplo_nomeia_o_que_o_codigo_realmente_le():
    """
    Um modelo de ambiente que esquece uma variável produz o pior
    tipo de estreia: o app sobe e falha na primeira ação que
    dependia dela.
    """
    exemplo = _texto(ENV_EXEMPLO)
    for obrigatoria in ("SUPABASE_URL", "SUPABASE_KEY",
                        "GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR",
                        "GOVDOCS_EXIGIR_SUPABASE_AUTH"):
        assert obrigatoria in exemplo, (
            f"{obrigatoria} não aparece no modelo de ambiente")


def test_o_modo_aberto_nao_vem_ligado_no_modelo():
    """
    `GOVDOCS_MODO_ABERTO` é o modo SEM LOGIN, de desenvolvimento.
    Ligado num servidor com domínio público, abre o sistema
    inteiro. Ele pode ser citado em comentário — e é, com o aviso —
    mas nunca atribuído.
    """
    for linha in _texto(ENV_EXEMPLO).splitlines():
        limpa = linha.strip()
        if limpa.startswith("#"):
            continue
        assert not limpa.startswith("GOVDOCS_MODO_ABERTO="), (
            "o modelo de ambiente atribui GOVDOCS_MODO_ABERTO — "
            "o modo sem login não pode chegar ligado ao servidor")


def test_os_portoes_de_falha_fechada_vem_ligados():
    """
    O contrário do teste acima: estes dois PRECISAM chegar ligados.
    Um servidor público que aceita subir sem credencial, ou sem
    exigir autenticação, é o defeito que a 0018 e a 0019 existiram
    para fechar.
    """
    exemplo = _texto(ENV_EXEMPLO)
    for portao in ("GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR",
                   "GOVDOCS_EXIGIR_SUPABASE_AUTH"):
        assert re.search(rf"^{portao}=1\s*$", exemplo, re.M), (
            f"{portao} não vem ligado no modelo — produção deve mantê-lo")


# ---------------------------------------------------------------------------
# 5) A POLÍTICA DE ROTEAMENTO NÃO PODE SE PERDER NA MUDANÇA DE CASA
# ---------------------------------------------------------------------------
def test_a_politica_de_roteamento_atravessa_a_migracao():
    """
    `OMNIROUTE_ROUTING_ENABLED` foi ligada à mão no Streamlit
    Cloud. Trocar de hospedagem sem levá-la junto devolveria, em
    silêncio, o comportamento que ela existe para impedir: um
    edital caindo para motor não homologado quando a OpenAI falha.

    É o tipo de regressão que uma migração de infraestrutura causa
    sem tocar numa linha de código.
    """
    assert re.search(r"^OMNIROUTE_ROUTING_ENABLED=true\s*$",
                     _texto(ENV_EXEMPLO), re.M), (
        "a política de roteamento não foi levada para o novo ambiente")


# ---------------------------------------------------------------------------
# 6) A imagem entrega o que o Streamlit Cloud entregava
# ---------------------------------------------------------------------------
def test_a_imagem_instala_o_motor_institucional_de_pdf():
    """
    `packages.txt` pedia `libreoffice` ao Streamlit Cloud. A imagem
    nomeia `libreoffice-writer`, que é o pacote que a conversão
    DOCX→PDF de fato usa — a distinção que fazia o ensaio local
    cair no fallback `fpdf2` sem avisar.
    """
    dockerfile = _texto(DOCKERFILE)
    assert "libreoffice-writer" in dockerfile, (
        "a imagem não instala o Writer: o PDF institucional sairia pelo "
        "fallback, com a geometria errada")
    assert "fonts-" in dockerfile, (
        "sem fonte instalada o LibreOffice renderiza caixas no lugar de "
        "acentos, e só se descobre no PDF final")


def test_a_imagem_nao_carrega_migracao_nem_ferramenta():
    """
    Imagem de produção que carrega migração é imagem que um dia
    aplica migração sozinha. `supabase/` e `scripts/` ficam fora.
    """
    dockerfile = _texto(DOCKERFILE)
    for fora in ("COPY supabase", "COPY scripts", "COPY tests"):
        assert fora not in dockerfile, (
            f"a imagem copia {fora.split()[1]}/, que é de desenvolvimento")


def test_o_contentor_nao_roda_como_root():
    dockerfile = _texto(DOCKERFILE)
    assert re.search(r"^USER\s+govdocs\s*$", dockerfile, re.M), (
        "o contentor roda como root")
    assert dockerfile.index("USER govdocs") > dockerfile.index("COPY"), (
        "o USER vem antes das cópias — os arquivos ficariam sem dono certo")


def test_ha_healthcheck_no_endpoint_do_streamlit():
    """
    Sem ele, o Docker dá o contentor por saudável enquanto o
    processo subiu e o app não responde — e o Caddy passa a mandar
    tráfego para uma porta muda.
    """
    assert "_stcore/health" in _texto(DOCKERFILE), (
        "o healthcheck não consulta o endpoint de saúde do Streamlit")


# ---------------------------------------------------------------------------
# 7) O Caddy atende o domínio certo e fala WebSocket
# ---------------------------------------------------------------------------
def test_o_caddy_atende_o_dominio_e_o_www():
    caddy = _texto(CADDYFILE)
    assert "govconect.com" in caddy
    assert "www.govconect.com" in caddy, (
        "o www não é atendido, e a zona tem um CNAME apontando para lá")


def test_o_caddy_encaminha_para_o_servico_interno_e_nao_para_o_host():
    """
    `reverse_proxy localhost:8501` é o engano natural de quem
    escreve isto fora de contentor: dentro do Caddy, `localhost` é
    o próprio Caddy. O destino é o NOME do serviço no compose.
    """
    caddy = _sem_comentario(_texto(CADDYFILE))
    assert re.search(r"reverse_proxy\s+app:8501", caddy), (
        "o proxy não aponta para o serviço `app` da rede interna")
    assert "localhost:8501" not in caddy


def test_o_caddy_repassa_o_esquema_original():
    """
    Sem `X-Forwarded-Proto`, o Streamlit monta URLs com http:// e o
    navegador recusa o conteúdo misto numa página https.
    """
    assert "X-Forwarded-Proto" in _texto(CADDYFILE)
