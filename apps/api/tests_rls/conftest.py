"""
Pilha descartável REAL para provar autorização da API — nada simulado.

PostgreSQL efêmero com o schema inteiro do repositório (o mesmo ensaio
das provas da raiz), GoTrue v2.197.0 oficial (o mesmo binário pinado do
`auth-real.yml`), PostgREST 12.2.12 e o gateway local que imita
`<projeto>.supabase.co`. A API sobe com a configuração de produção:
verificação por JWKS, ES256.

Por que ES256 e não o segredo HS256 que o `auth-real.yml` usa: o projeto
de produção assina com ES256 (JWKS conferido em 22/10/2026). Uma prova
feita no modo HS256 provaria um caminho que a API em produção não usa.

Só infraestrutura é cunhada aqui (chaves `anon` e `service_role`, para o
PostgREST e para a Admin API criar contas). TODO token de usuário vem de
login por senha no GoTrue.

Sem a pilha: com `GOVCONECT_EXIGIR_RLS=1` (CI) é ERRO; sem a variável,
pula — "não consegui verificar" nunca vira "verificado".
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import subprocess
import sys
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest

RAIZ_API = Path(__file__).resolve().parent.parent
RAIZ_REPO = RAIZ_API.parent.parent
for caminho in (RAIZ_API, RAIZ_REPO, RAIZ_REPO / "scripts"):
    if str(caminho) not in sys.path:
        sys.path.insert(0, str(caminho))

VARIAVEIS = ("GOVCONECT_RLS_PG_DSN", "GOVCONECT_GOTRUE_TAR", "GOVCONECT_POSTGREST_BIN")


def _b64(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).decode().rstrip("=")


def _chaves_es256() -> tuple[dict, dict]:
    """(JWK privada para o GoTrue assinar, JWK pública para o PostgREST)."""
    from cryptography.hazmat.primitives.asymmetric import ec

    privada = ec.generate_private_key(ec.SECP256R1())
    numeros = privada.private_numbers()
    kid = str(uuid.uuid4())
    publica = {"kty": "EC", "crv": "P-256", "kid": kid, "alg": "ES256",
               "use": "sig", "key_ops": ["verify"],
               "x": _b64(numeros.public_numbers.x.to_bytes(32, "big")),
               "y": _b64(numeros.public_numbers.y.to_bytes(32, "big"))}
    return ({**publica, "key_ops": ["sign", "verify"],
             "d": _b64(numeros.private_value.to_bytes(32, "big"))}, publica)


def _http(url: str, *, metodo="GET", token=None, apikey=None, corpo=None) -> dict:
    cabecalhos = {"Content-Type": "application/json"}
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    if apikey:
        cabecalhos["apikey"] = apikey
    pedido = urllib.request.Request(
        url, method=metodo, headers=cabecalhos,
        data=json.dumps(corpo).encode() if corpo is not None else None)
    with urllib.request.urlopen(pedido, timeout=15) as resposta:
        return json.loads(resposta.read() or b"null")


@dataclass
class Conta:
    rotulo: str
    auth_user_id: str
    token: str
    tenant_id: str
    secretaria_id: str | None
    papel: str


@dataclass
class Pilha:
    url: str
    anon: str
    dsn: str
    segredo_hs256: str = field(repr=False)
    contas: dict[str, Conta] = field(default_factory=dict)


@pytest.fixture(scope="session")
def pilha():
    faltando = [v for v in VARIAVEIS if not os.getenv(v)]
    if faltando:
        if os.getenv("GOVCONECT_EXIGIR_RLS") == "1":
            pytest.fail(f"pilha RLS exigida e ausente: {', '.join(faltando)}")
        pytest.skip("pilha RLS ausente (rode no job api-rls do CI)")

    import psycopg
    from psycopg import sql

    import ensaio_auth_real as ar
    import ensaio_local as sql_harness
    import homologacao_stack

    dsn_admin = os.environ["GOVCONECT_RLS_PG_DSN"]
    config_pg = ar._local_connection(dsn_admin)
    trabalho = Path(os.environ.get("RUNNER_TEMP", RAIZ_API)) / f"pilha-rls-{uuid.uuid4().hex}"
    trabalho.mkdir(parents=True, mode=0o700)
    binario = ar.stage_auth(Path(os.environ["GOVCONECT_GOTRUE_TAR"]), trabalho / "auth-bin")
    ar._verify_auth_version(binario, trabalho)

    processos, logins, banco = [], [], None
    antigo = homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST
    try:
        dsn, banco = sql_harness.criar_banco_descartavel(dsn_admin)
        login_auth, login_rest = "auth_" + uuid.uuid4().hex, "rest_" + uuid.uuid4().hex
        senha_auth, senha_rest, segredo = (secrets.token_urlsafe(48) for _ in range(3))
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(sql_harness.PREAMBULO_ANTES_AUTH)
            for nome, senha in ((login_auth, senha_auth), (login_rest, senha_rest)):
                c.execute(sql.SQL("create role {} login noinherit password {}")
                          .format(sql.Identifier(nome), sql.Literal(senha)))
                logins.append(nome)
            c.execute(sql.SQL("alter schema auth owner to {}").format(sql.Identifier(login_auth)))
            c.execute(sql.SQL("grant usage, create on schema public to {}")
                      .format(sql.Identifier(login_auth)))
            c.execute(sql.SQL("grant authenticator to {}").format(sql.Identifier(login_rest)))

        p_auth, p_rest, p_gw = ar._available_port(), ar._available_port(), ar._available_port()
        privada, publica = _chaves_es256()
        amb_auth = ar.auth_environment(
            database_url=ar._database_url(config_pg, database=banco, user=login_auth,
                                          password=senha_auth),
            secret=segredo, port=p_auth, gateway_port=p_gw)
        amb_auth.update({"GOTRUE_JWT_KEYS": json.dumps([privada]),
                         "GOTRUE_JWT_KEY_ID": privada["kid"],
                         "GOTRUE_JWT_VALID_METHODS": "HS256,ES256",
                         "GOTRUE_JWT_EXP": "600"})
        migrou = subprocess.run([str(binario), "migrate"], env=amb_auth, cwd=trabalho,
                                capture_output=True, timeout=90, check=False)
        assert migrou.returncode == 0, "GoTrue migrate falhou"
        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute(sql.SQL("revoke create on schema public from {}")
                      .format(sql.Identifier(login_auth)))
            c.execute(sql.SQL("alter role {} in database {} set search_path = auth, public")
                      .format(sql.Identifier(login_auth), sql.Identifier(banco)))
            sql_harness.preparar(c, auth_real=True)

        processos.append(subprocess.Popen([str(binario), "serve"], cwd=trabalho, env=amb_auth,
                                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        homologacao_stack._esperar_porta(p_auth, processo=processos[-1])

        # O PostgREST verifica as DUAS formas: ES256 (usuário, como em
        # produção) e HS256 (as chaves de infraestrutura cunhadas aqui).
        jwks_pgrst = json.dumps({"keys": [publica, {"kty": "oct", "alg": "HS256",
                                                    "k": _b64(segredo.encode())}]})
        homologacao_stack.BINARIO_PGRST = os.environ["GOVCONECT_POSTGREST_BIN"]
        homologacao_stack.PORTA_PGRST = p_rest
        processos.append(homologacao_stack.subir_postgrest(
            ar._database_url(config_pg, database=banco, user=login_rest, password=senha_rest),
            jwks_pgrst))
        processos.append(subprocess.Popen(
            [sys.executable, str(RAIZ_REPO / "scripts/gateway_supabase.py"),
             "--porta", str(p_gw), "--destino", f"http://127.0.0.1:{p_rest}",
             "--destino-auth", f"http://127.0.0.1:{p_auth}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        homologacao_stack._esperar_porta(p_gw, processo=processos[-1])

        url = f"http://127.0.0.1:{p_gw}"
        anon = homologacao_stack.cunhar_jwt("anon", segredo, validade_s=3600)
        servidor = homologacao_stack.cunhar_jwt("service_role", segredo, validade_s=3600)
        jwks = _http(f"{url}/auth/v1/.well-known/jwks.json")
        assert [k.get("kid") for k in jwks.get("keys", [])] == [privada["kid"]], \
            "GoTrue não publicou a chave ES256"

        pilha = Pilha(url=url, anon=anon, dsn=dsn, segredo_hs256=segredo)
        _semear(pilha, dsn, servidor)
        yield pilha
    finally:
        ar._stop_children(processos)
        homologacao_stack.BINARIO_PGRST, homologacao_stack.PORTA_PGRST = antigo
        if banco is not None:
            sql_harness.descartar_banco(dsn_admin, banco)
        if logins:
            with psycopg.connect(dsn_admin, autocommit=True) as c:
                for nome in reversed(logins):
                    c.execute(sql.SQL("drop role if exists {}").format(sql.Identifier(nome)))


# Município A tem duas secretarias; B, uma. Cada conta é uma pergunta de
# autorização diferente — o nome diz qual.
CONTAS = (
    ("a1", "A", "A1", "usuario", True),
    ("a1_colega", "A", "A1", "usuario", True),
    ("a2", "A", "A2", "usuario", True),
    ("admin_a", "A", "A1", "admin", True),
    ("b1", "B", "B1", "usuario", True),
    ("a1_revogado", "A", "A1", "usuario", False),
)


def _semear(pilha: Pilha, dsn: str, servidor: str) -> None:
    import psycopg

    with psycopg.connect(dsn, autocommit=True) as c:
        tenants = {}
        for t in ("A", "B"):
            tenants[t] = str(c.execute(
                "insert into public.tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                (f"rls-{t.lower()}-{uuid.uuid4().hex[:8]}", f"Município {t}")).fetchone()[0])
        secretarias = {}
        for s in ("A1", "A2", "B1"):
            secretarias[s] = str(c.execute(
                "insert into public.secretarias (tenant_id, nome, sigla) values (%s, %s, %s) "
                "returning id", (tenants[s[0]], f"Secretaria {s}", s)).fetchone()[0])

        for rotulo, t, s, papel, ativo in CONTAS:
            email = f"{rotulo}-{uuid.uuid4().hex[:8]}@example.invalid"
            senha = secrets.token_urlsafe(24)
            meta = {"tenant_id": tenants[t], "secretaria_id": secretarias[s], "papel": papel}
            criado = _http(f"{pilha.url}/auth/v1/admin/users", metodo="POST", token=servidor,
                           apikey=servidor, corpo={"email": email, "password": senha,
                                                   "email_confirm": True, "app_metadata": meta})
            uid = criado["id"]
            c.execute("insert into public.usuarios (nome, login, senha_hash, papel, ativo, "
                      "tenant_id, secretaria_id, auth_user_id) values "
                      "(%s, %s, 'nao-e-credencial', %s, %s, %s, %s, %s)",
                      (rotulo, email, papel, ativo, tenants[t], secretarias[s], uid))
            sessao = _http(f"{pilha.url}/auth/v1/token?grant_type=password", metodo="POST",
                           apikey=pilha.anon, corpo={"email": email, "password": senha})
            token = sessao["access_token"]
            cabecalho = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
            assert cabecalho["alg"] == "ES256", "GoTrue não assinou o usuário com ES256"
            pilha.contas[rotulo] = Conta(rotulo, uid, token, tenants[t], secretarias[s], papel)


@pytest.fixture(scope="session")
def api(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url,
                       "SUPABASE_KEY": pilha.anon,
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)
