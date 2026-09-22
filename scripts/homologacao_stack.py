#!/usr/bin/env python3
"""
Sobe a pilha inteira de HOMOLOGAÇÃO isolada, num processo só.

    python scripts/homologacao_stack.py --segurar        # sobe e espera
    python scripts/homologacao_stack.py --executar "pytest tests/x.py"

    # ou, de dentro de um roteiro de navegação:
    from homologacao_stack import pilha
    with pilha() as info:
        driver.goto(info.url_app)

A PILHA

    PostgreSQL local  (socket unix, cluster descartável)
        ↑
    PostgREST 12.x    (127.0.0.1:3000, JWT HS256 com segredo efêmero)
        ↑
    adaptador /rest/v1 (127.0.0.1:3001)
        ↑
    Streamlit         (127.0.0.1:8502, com o bloqueio de custo instalado)

POR QUE TUDO NUM PROCESSO SÓ

Porque processos em segundo plano não sobrevivem entre os turnos deste
ambiente — o PostgreSQL já morreu cinco vezes durante esta auditoria. Uma
bateria que dependa de "o servidor que subi da última vez ainda está
lá" não é reproduzível, e o §20 pede evidência reproduzível.

Aqui a pilha inteira nasce, serve e morre dentro da mesma invocação. O
banco é a única coisa que persiste, de propósito: o §5 manda salvar um
processo, fechar e REABRIR.

NENHUMA CREDENCIAL REAL

O segredo de JWT é sorteado a cada subida e morre com ela. As chaves
`anon` e `service_role` são cunhadas aqui, contra esse segredo. Não há,
em nenhum ponto deste caminho, chave de produção, de projeto Supabase
ou de provedor de LLM.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import dataclasses
import hashlib
import hmac
import json
import os
import pathlib
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

RAIZ = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = RAIZ / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import homologacao_local  # noqa: E402

SOCKET_PG = "/tmp/pgens"
DSN_ADMIN = f"postgresql://postgres@/postgres?host={SOCKET_PG}"
BANCO = "homologacao"

PORTA_PGRST = 3000
PORTA_ADAPTADOR = 3001
PORTA_APP = 8502

BINARIO_PGRST = os.environ.get("POSTGREST_BIN", "/tmp/postgrest")


class ErroPilha(RuntimeError):
    """A pilha não subiu. É erro, nunca um teste que 'pula'."""


@dataclasses.dataclass(frozen=True)
class Pilha:
    url_app: str
    url_supabase: str
    dsn: str
    chave_servidor: str
    chave_publica: str

    def ambiente_do_app(self) -> dict:
        """As variáveis que o app enxerga. Serve para inspeção no laudo."""
        return {"SUPABASE_URL": self.url_supabase,
                "GOVDOCS_AMBIENTE": "homologacao"}


# ---------------------------------------------------------------------------
# JWT HS256 sem dependência
#
# São três campos em base64url com um HMAC no fim. Escrever à mão evita
# arrastar uma biblioteca para dentro do caminho de teste — e deixa
# visível que o token é cunhado AQUI, contra um segredo desta execução,
# e não obtido de lugar nenhum.
# ---------------------------------------------------------------------------
def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def cunhar_jwt(papel: str, segredo: str, validade_s: int = 6 * 3600) -> str:
    agora = int(time.time())
    cabecalho = {"alg": "HS256", "typ": "JWT"}
    corpo = {"role": papel, "iss": "homologacao-local",
             "iat": agora, "exp": agora + validade_s}
    parte = f"{_b64(json.dumps(cabecalho).encode())}." \
            f"{_b64(json.dumps(corpo).encode())}"
    assinatura = hmac.new(segredo.encode(), parte.encode(),
                          hashlib.sha256).digest()
    return f"{parte}.{_b64(assinatura)}"


# ---------------------------------------------------------------------------
# Subida de cada peça
# ---------------------------------------------------------------------------
def _porta_livre(porta: int) -> bool:
    with socket.socket() as sonda:
        return sonda.connect_ex(("127.0.0.1", porta)) != 0


def _esperar_porta(porta: int, segundos: float = 30.0,
                   processo: subprocess.Popen | None = None) -> None:
    limite = time.time() + segundos
    while time.time() < limite:
        if processo is not None and processo.poll() is not None:
            raise ErroPilha(
                f"o processo da porta {porta} morreu com código "
                f"{processo.returncode} antes de atender")
        with socket.socket() as sonda:
            if sonda.connect_ex(("127.0.0.1", porta)) == 0:
                return
        time.sleep(0.25)
    raise ErroPilha(f"porta {porta} não atendeu em {segundos:.0f}s")


def subir_postgres() -> None:
    """
    Garante o cluster de pé. Já morreu entre turnos; reerguer é rotina.
    """
    binario = "/usr/lib/postgresql/16/bin/pg_ctl"
    pronto = ["sudo", "-u", "pgtest", "/usr/lib/postgresql/16/bin/pg_isready",
              "-h", SOCKET_PG]
    if subprocess.run(pronto, capture_output=True).returncode == 0:
        return
    # Socket órfão de um cluster morto impede a subida sem dizer por quê.
    for resto in pathlib.Path(SOCKET_PG).glob(".s.PGSQL.*"):
        with contextlib.suppress(OSError):
            resto.unlink()
    subprocess.run(
        ["sudo", "-u", "pgtest", binario, "-D", "/tmp/pgdata",
         "-o", f"-k {SOCKET_PG} -h ''", "-l", "/tmp/pgens.log", "start"],
        capture_output=True)
    for _ in range(40):
        if subprocess.run(pronto, capture_output=True).returncode == 0:
            return
        time.sleep(0.25)
    raise ErroPilha("PostgreSQL de ensaio não subiu — veja /tmp/pgens.log")


def subir_postgrest(dsn: str, segredo: str) -> subprocess.Popen:
    if not pathlib.Path(BINARIO_PGRST).exists():
        raise ErroPilha(
            f"postgrest não encontrado em {BINARIO_PGRST}. Baixe o binário "
            "estático da release 12.x e aponte POSTGREST_BIN para ele.")
    if not _porta_livre(PORTA_PGRST):
        raise ErroPilha(f"porta {PORTA_PGRST} ocupada")

    ambiente = dict(os.environ)
    ambiente.update({
        "PGRST_DB_URI": dsn,
        "PGRST_DB_SCHEMAS": "public",
        "PGRST_DB_ANON_ROLE": "anon",
        "PGRST_JWT_SECRET": segredo,
        "PGRST_SERVER_HOST": "127.0.0.1",
        "PGRST_SERVER_PORT": str(PORTA_PGRST),
        "PGRST_DB_POOL": "6",
        # Sem isto, uma mudança de schema exige reiniciar o PostgREST —
        # e a bateria cria tabela nenhuma, mas cria dados o tempo todo.
        "PGRST_DB_CONFIG": "false",
    })
    processo = subprocess.Popen(
        [BINARIO_PGRST], env=ambiente,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _esperar_porta(PORTA_PGRST, processo=processo)
    return processo


def subir_adaptador() -> subprocess.Popen:
    if not _porta_livre(PORTA_ADAPTADOR):
        raise ErroPilha(f"porta {PORTA_ADAPTADOR} ocupada")
    processo = subprocess.Popen(
        [sys.executable, str(SCRIPTS / "gateway_supabase.py"),
         "--porta", str(PORTA_ADAPTADOR),
         "--destino", f"http://127.0.0.1:{PORTA_PGRST}"],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _esperar_porta(PORTA_ADAPTADOR, processo=processo)
    return processo


def subir_streamlit(pilha: Pilha) -> subprocess.Popen:
    if not _porta_livre(PORTA_APP):
        raise ErroPilha(f"porta {PORTA_APP} ocupada")

    ambiente = dict(os.environ)
    # O `sitecustomize` do bloqueio de custo precisa entrar ANTES de
    # qualquer import do app — por isso PYTHONPATH, e não um import
    # dentro do `app.py`.
    ambiente["PYTHONPATH"] = os.pathsep.join(
        [str(SCRIPTS / "bloqueio_de_custo"), str(SCRIPTS), str(RAIZ)]
        + ([ambiente["PYTHONPATH"]] if ambiente.get("PYTHONPATH") else []))
    ambiente.update({
        "SUPABASE_URL": pilha.url_supabase,
        # LEGADA de propósito. `SUPABASE_SECRET_KEY` só aceita o
        # formato `sb_secret_…`, que é emitido pelo Supabase e não se
        # cunha aqui. O slot legado aceita um JWT que DECLARE
        # `role=service_role` — e conferir isso pelo papel, não pela
        # forma, é o que o `db.credencial_invalida` faz de certo.
        #
        # Consequência registrada para o laudo: a homologação roda com
        # o aviso de descontinuação ligado, exatamente como rodaria uma
        # instalação que ainda não trocou a chave.
        "SUPABASE_SERVICE_KEY": pilha.chave_servidor,
        "SUPABASE_KEY": pilha.chave_publica,
        "GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR": "1",
        "GOVDOCS_AMBIENTE": "homologacao",
        "GOVDOCS_LIVRO_SEM_LLM": os.environ.get(
            "GOVDOCS_LIVRO_SEM_LLM", "/tmp/govdocs_sem_llm.jsonl"),
    })

    # A chave é o INTERRUPTOR do caminho de IA, e os dois estados
    # precisam ser exercitados:
    #
    #   sem `GOVDOCS_IA_SIMULADA` → campo vazio. `motores_disponiveis()`
    #       devolve lista vazia e a geração recusa com a mensagem que
    #       fala do Modo Demonstração. É um caminho de produção real —
    #       o de quem ainda não configurou provedor.
    #
    #   com `GOVDOCS_IA_SIMULADA` → chave de FORMATO plausível e valor
    #       falso. Nada sai para a rede: quem atende é a fixture no
    #       transporte. O valor não é segredo, é literal de teste.
    simulacao = os.environ.get("GOVDOCS_IA_SIMULADA", "")
    chave_de_ensaio = "sk-ensaio-sem-custo-nao-e-credencial" if simulacao else ""
    ambiente.update({
        "GOVDOCS_IA_SIMULADA": simulacao,
        "GOVDOCS_LIVRO_IA_SIMULADA": os.environ.get(
            "GOVDOCS_LIVRO_IA_SIMULADA", "/tmp/govdocs_ia_simulada.jsonl"),
        "OPENAI_API_KEY": chave_de_ensaio,
        "GOOGLE_API_KEY": "",
        "OPENROUTER_API_KEY": "",
    })

    _exigir_bloqueio_de_custo(ambiente)

    processo = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(RAIZ / "app.py"),
         "--server.headless=true", f"--server.port={PORTA_APP}",
         "--server.address=127.0.0.1",
         "--browser.gatherUsageStats=false",
         "--server.fileWatcherType=none"],
        cwd=str(RAIZ), env=ambiente,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    _esperar_porta(PORTA_APP, segundos=90, processo=processo)
    _esperar_saude()
    return processo


def _exigir_bloqueio_de_custo(ambiente: dict) -> None:
    """
    Confere, NO MESMO ambiente do app, que o guarda do §3 entra sozinho.

    Sem isto a garantia "zero chamadas pagas" dependeria de o
    `sitecustomize` ter sido de fato encontrado — e um `PYTHONPATH`
    errado falharia em silêncio, com a bateria inteira rodando
    desprotegida e o relatório afirmando o contrário.

    A prova é o efeito colateral do `instalar()`: `socket.getaddrinfo`
    deixa de ser a função do módulo `socket`. Um processo filho com o
    mesmo ambiente é a medição mais próxima possível do processo real.
    """
    sonda = (
        "import socket, sem_llm, sys;"
        "instalado = socket.getaddrinfo.__module__ != 'socket';"
        "tentou = False;"
        "\nimport contextlib\n"
        "with contextlib.suppress(Exception):\n"
        "    socket.getaddrinfo('api.openai.com', 443)\n"
        "print('OK' if instalado and sem_llm.tentativas() == 1 else 'FALHA')"
    )
    resultado = subprocess.run([sys.executable, "-c", sonda], env=ambiente,
                               capture_output=True, text=True, timeout=60)
    if resultado.stdout.strip() != "OK":
        raise ErroPilha(
            "o bloqueio de chamadas pagas (§3) NÃO está ativo no ambiente do "
            f"app: {resultado.stdout.strip()!r} {resultado.stderr.strip()[:300]!r}. "
            "A bateria não sobe sem ele.")


def _esperar_saude(segundos: float = 60.0) -> None:
    """A porta abre antes de o app servir. `/_stcore/health` é o sinal."""
    limite = time.time() + segundos
    endereco = f"http://127.0.0.1:{PORTA_APP}/_stcore/health"
    while time.time() < limite:
        try:
            with urllib.request.urlopen(endereco, timeout=2) as resposta:
                if resposta.status == 200:
                    return
        except (urllib.error.URLError, OSError):
            pass
        time.sleep(0.5)
    raise ErroPilha("Streamlit subiu a porta mas não respondeu /_stcore/health")


def _encerrar(processo: subprocess.Popen | None) -> None:
    if processo is None or processo.poll() is not None:
        return
    processo.send_signal(signal.SIGTERM)
    try:
        processo.wait(timeout=10)
    except subprocess.TimeoutExpired:
        processo.kill()


@contextlib.contextmanager
def pilha(recriar_banco: bool = False):
    """Sobe tudo, entrega os endereços, e derruba tudo no fim."""
    subir_postgres()
    relatorio = homologacao_local.montar(DSN_ADMIN, BANCO, recriar_banco)
    dsn_app = relatorio["dsn"].replace("postgresql://postgres@",
                                       "postgresql://authenticator@")

    segredo = secrets.token_urlsafe(48)
    info = Pilha(
        url_app=f"http://127.0.0.1:{PORTA_APP}",
        url_supabase=f"http://127.0.0.1:{PORTA_ADAPTADOR}",
        dsn=relatorio["dsn"],
        chave_servidor=cunhar_jwt("service_role", segredo),
        chave_publica=cunhar_jwt("anon", segredo),
    )

    pgrst = adaptador = app = None
    try:
        pgrst = subir_postgrest(dsn_app, segredo)
        adaptador = subir_adaptador()
        app = subir_streamlit(info)
        yield info
    finally:
        _encerrar(app)
        _encerrar(adaptador)
        _encerrar(pgrst)


def principal(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument("--recriar-banco", action="store_true")
    analisador.add_argument("--segurar", action="store_true",
                            help="sobe e fica de pé até Ctrl-C")
    analisador.add_argument("--executar",
                            help="comando a rodar com a pilha de pé")
    argumentos = analisador.parse_args(argv)

    with pilha(argumentos.recriar_banco) as info:
        print(f"app:      {info.url_app}")
        print(f"supabase: {info.url_supabase}  (adaptador -> PostgREST)")
        print(f"banco:    {BANCO} em {SOCKET_PG}")
        print("chaves:   cunhadas nesta execução, efêmeras, não impressas")

        if argumentos.executar:
            # O comando recebe as MESMAS credenciais que o app: é o que
            # permite a um roteiro de teste conferir no banco, pela
            # mesma porta, o que a interface acabou de gravar. São
            # chaves efêmeras desta execução — não há segredo real aqui.
            ambiente = dict(os.environ)
            ambiente["PYTHONPATH"] = os.pathsep.join(
                [str(SCRIPTS / "bloqueio_de_custo"), str(SCRIPTS), str(RAIZ)]
                + ([os.environ["PYTHONPATH"]]
                   if os.environ.get("PYTHONPATH") else []))
            ambiente.update({
                "GOVDOCS_URL_APP": info.url_app,
                "OPENAI_API_KEY": (
                    "sk-ensaio-sem-custo-nao-e-credencial"
                    if os.environ.get("GOVDOCS_IA_SIMULADA") else ""),
                "SUPABASE_URL": info.url_supabase,
                "SUPABASE_SERVICE_KEY": info.chave_servidor,
                "SUPABASE_KEY": info.chave_publica,
                "GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR": "1",
                "GOVDOCS_AMBIENTE": "homologacao",
                "GOVDOCS_DSN_HOMOLOGACAO": info.dsn,
            })
            concluido = subprocess.run(argumentos.executar, shell=True,
                                       cwd=str(RAIZ), env=ambiente)
            return concluido.returncode
        if argumentos.segurar:
            print("de pé; Ctrl-C para derrubar", flush=True)
            with contextlib.suppress(KeyboardInterrupt):
                while True:
                    time.sleep(1)
    return 0


if __name__ == "__main__":
    if shutil.which("sudo") is None:  # pragma: no cover
        print("sudo ausente: o cluster de ensaio roda como `pgtest`",
              file=sys.stderr)
    raise SystemExit(principal())
