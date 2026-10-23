"""
Pilha descartável REAL para provar autorização — nada simulado.

PostgreSQL efêmero com o schema inteiro do repositório (o mesmo ensaio
das provas da raiz), GoTrue v2.197.0 oficial (o mesmo binário pinado do
`auth-real.yml`), PostgREST 12.2.12 e o gateway local que imita
`<projeto>.supabase.co`.

Assinatura ES256, e não o segredo HS256 que o `auth-real.yml` usa: o
projeto de produção assina com ES256 (JWKS conferido em 22/10/2026). Uma
prova feita em HS256 provaria um caminho que a produção não usa.

Só infraestrutura é cunhada aqui (chaves `anon` e `service_role`, para o
PostgREST e para a Admin API criar contas). TODO token de usuário vem de
login por senha no GoTrue.

Dois usos:
  * `subir()` — gerenciador de contexto, para o pytest (`conftest.py`);
  * linha de comando — para o E2E do web (job `web-e2e`):

        python tests_rls/pilha.py --estado /tmp/pilha.json

    sobe, semeia, grava o JSON (URL, chave publicável, contas com senha
    de TESTE) e fica de pé até receber SIGTERM ou o stdin fechar.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import secrets
import signal
import subprocess
import sys
import threading
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path

RAIZ_API = Path(__file__).resolve().parent.parent
RAIZ_REPO = RAIZ_API.parent.parent
for caminho in (RAIZ_API, RAIZ_REPO, RAIZ_REPO / "scripts"):
    if str(caminho) not in sys.path:
        sys.path.insert(0, str(caminho))

VARIAVEIS = ("GOVCONECT_RLS_PG_DSN", "GOVCONECT_GOTRUE_TAR", "GOVCONECT_POSTGREST_BIN")

# Município A tem duas secretarias; B, uma. Cada conta é uma pergunta de
# autorização diferente — o rótulo diz qual.
CONTAS = (
    ("a1", "A", "A1", "usuario", True),
    ("a1_colega", "A", "A1", "usuario", True),
    ("a2", "A", "A2", "usuario", True),
    ("admin_a", "A", "A1", "admin", True),
    ("b1", "B", "B1", "usuario", True),
    ("a1_revogado", "A", "A1", "usuario", False),
)


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
    token: str = field(repr=False)
    tenant_id: str
    secretaria_id: str | None
    papel: str
    email: str = ""
    # Senha de TESTE, gerada aqui, de uma conta que morre com o banco.
    senha: str = field(default="", repr=False)


@dataclass
class Pilha:
    url: str
    anon: str
    dsn: str
    segredo_hs256: str = field(repr=False)
    contas: dict[str, Conta] = field(default_factory=dict)


def faltando() -> list[str]:
    return [v for v in VARIAVEIS if not os.getenv(v)]


@contextmanager
def subir():
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
            email = f"{rotulo.replace('_', '-')}-{uuid.uuid4().hex[:8]}@example.invalid"
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
            pilha.contas[rotulo] = Conta(rotulo, uid, token, tenants[t], secretarias[s], papel,
                                         email=email, senha=senha)


def semear_precos(pilha: Pilha) -> dict:
    """Pesquisa de preços da conta `a1`, gravada direto no banco (como o
    Streamlit grava hoje). Valor global que NÃO cabe em float, um item
    ativo, um retirado da cotação (0029) e uma referência do PNCP."""
    import psycopg
    from psycopg.types.json import Jsonb

    a1 = pilha.contas["a1"]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        def pesquisa(nome):
            return str(c.execute(
                "insert into public.pesquisas_preco (tenant_id, secretaria_id, auth_user_id, "
                "nome, estado, valor_global, idempotency_key) values (%s,%s,%s,%s,'review',"
                "12345678901234.5678,%s) returning id",
                (a1.tenant_id, a1.secretaria_id, a1.auth_user_id, nome,
                 uuid.uuid4().hex)).fetchone()[0])
        pesquisa_a = pesquisa("Luvas E2E")
        pesquisa_vazia = pesquisa("Sem itens")
        item = str(c.execute(
            "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, codigo, "
            "tipo_catalogo, descricao, unidade, quantidade, estado, metodo, preco_estimado, "
            "preco_total) values (%s,%s,1,'451234','CATMAT','Luva nitrílica','CX',1500,"
            "'review','mediana',2.3450,3517.5000) returning id",
            (pesquisa_a, a1.tenant_id)).fetchone()[0])
        # Item retirado da cotação: continua no banco, sai da leitura.
        c.execute(
            "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, "
            "descricao, quantidade, preco_estimado, removido_em) values "
            "(%s,%s,2,'Item retirado',1,999.9900,now())", (pesquisa_a, a1.tenant_id))
        c.execute(
            "insert into public.pesquisa_preco_referencias (item_id, tenant_id, fonte_id, "
            "fonte_nome, fonte_tipo, id_externo, raw_hash, descricao_original, "
            "valor_unitario_original, valor_unitario_normalizado, natureza_valor, status, bruto) "
            "values (%s,%s,'pncp','PNCP','sistema_oficial','ext-1','h1','Luva',2.3456,2.3456,"
            "'homologado','selected',%s)",
            (item, a1.tenant_id, Jsonb({"numeroControlePNCP": "12345678000190-1-000123/2025"})))
    return {"pesquisa": pesquisa_a, "vazia": pesquisa_vazia, "item": item}


def semear_coleta(pilha: Pilha) -> str:
    """Pesquisa de `a1` com dois itens PENDENTES: o que a coleta processa."""
    import psycopg

    a1 = pilha.contas["a1"]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        pid = str(c.execute(
            "insert into public.pesquisas_preco (tenant_id, secretaria_id, auth_user_id, nome, "
            "estado, idempotency_key) values (%s,%s,%s,'Coleta E2E','draft',%s) returning id",
            (a1.tenant_id, a1.secretaria_id, a1.auth_user_id, uuid.uuid4().hex)).fetchone()[0])
        for n in (1, 2):
            c.execute("insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, "
                      "descricao, unidade, quantidade) values (%s,%s,%s,%s,'UN',10)",
                      (pid, a1.tenant_id, n, f"Item {n} da coleta"))
    return pid


FLAGS_DA_EMISSAO = ("flag_precos_ciencia_emissao", "flag_precos_relatorio_visual")


def ligar_flags_da_emissao(pilha: Pilha) -> None:
    """As flags que a produção tem ligadas para a emissão (v1.9.6+). A API
    as lê por `flags_do_app()` (0033), com o token do usuário."""
    import psycopg

    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        for chave in FLAGS_DA_EMISSAO:
            c.execute("insert into public.config_app (chave, valor) values (%s, 'on') "
                      "on conflict (chave) do update set valor = 'on'", (chave,))


def semear_emissao(pilha: Pilha, dono: str = "a1") -> str:
    """Pesquisa de `dono` com um item EM REVISÃO e uma referência na cesta:
    a pendência "preço não confirmado pelo revisor" faz a emissão pedir
    ciência — o caminho que importa provar.

    O E2E usa outra conta (`admin_a`): o login do web limita 5 entradas
    por IP + e-mail a cada 15 min, e a `a1` já entra em vários specs."""
    import psycopg
    from psycopg.types.json import Jsonb

    ligar_flags_da_emissao(pilha)
    a1 = pilha.contas[dono]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        pid = str(c.execute(
            "insert into public.pesquisas_preco (tenant_id, secretaria_id, auth_user_id, nome, "
            "objeto, estado, valor_global, idempotency_key) values (%s,%s,%s,'Emissão E2E',"
            "'Material de expediente','review',351.75,%s) returning id",
            (a1.tenant_id, a1.secretaria_id, a1.auth_user_id, uuid.uuid4().hex)).fetchone()[0])
        item = str(c.execute(
            "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, codigo, "
            "tipo_catalogo, descricao, unidade, quantidade, estado, metodo, preco_estimado, "
            "preco_total) values (%s,%s,1,'451234','CATMAT','Caneta esferográfica azul','UN',150,"
            "'review','mediana',2.3450,351.7500) returning id",
            (pid, a1.tenant_id)).fetchone()[0])
        c.execute(
            "insert into public.pesquisa_preco_referencias (item_id, tenant_id, fonte_id, "
            "fonte_nome, fonte_tipo, id_externo, raw_hash, descricao_original, "
            "valor_unitario_original, valor_unitario_normalizado, natureza_valor, status, bruto) "
            "values (%s,%s,'pncp','PNCP','sistema_oficial','ext-e1','he1','Caneta azul',2.3450,"
            "2.3450,'homologado','selected',%s)",
            (item, a1.tenant_id, Jsonb({"numeroControlePNCP": "12345678000190-1-000124/2025"})))
    return pid


def semear_aplicacao(pilha: Pilha, dono: str = "a1") -> dict:
    """Processo de `dono` com planilha de um item e DFD/ETP gerados (DFD
    aprovado), e uma pesquisa CONCLUÍDA vinculada a ele com o mesmo item
    concluído — o que a aplicação ao processo precisa para ter efeito."""
    import psycopg
    from psycopg.types.json import Jsonb

    conta = pilha.contas[dono]
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        processo = str(c.execute(
            "insert into public.processos (tenant_id, secretaria_id, auth_user_id, orgao, objeto, "
            "etapa, dados, documentos, aprovados) values (%s,%s,%s,'Prefeitura','Canetas',2,%s,%s,"
            "'{dfd}') returning id",
            (conta.tenant_id, conta.secretaria_id, conta.auth_user_id,
             Jsonb({"objeto": "Canetas", "valor_estimado": 300.0,
                    "itens": [{"codigo": "451234", "descricao": "Caneta esferográfica azul",
                               "unidade": "UN", "quantidade": 150, "valor_unitario": 2.0}]}),
             Jsonb({"dfd": "## DFD", "etp": "## ETP"}))).fetchone()[0])
        pesquisa = str(c.execute(
            "insert into public.pesquisas_preco (tenant_id, secretaria_id, auth_user_id, nome, "
            "estado, processo_id, idempotency_key) values (%s,%s,%s,'Aplicação E2E','completed',%s,%s) "
            "returning id",
            (conta.tenant_id, conta.secretaria_id, conta.auth_user_id, processo,
             uuid.uuid4().hex)).fetchone()[0])
        c.execute(
            "insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, codigo, "
            "tipo_catalogo, descricao, unidade, quantidade, estado, metodo, preco_estimado, "
            "preco_total) values (%s,%s,1,'451234','CATMAT','Caneta esferográfica azul','UN',150,"
            "'complete','mediana',2.3450,351.7500)", (pesquisa, conta.tenant_id))
    return {"processo": processo, "pesquisa": pesquisa}


def gravar_planilha_e2e(pasta: Path) -> Path:
    """A planilha que o E2E importa: dois itens, um com quantidade decimal."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Código", "Descrição", "Unidade", "Quantidade"])
    ws.append(["451234", "Caneta esferográfica azul", "UN", 150])
    ws.append(["", "Papel A4 75 g/m²", "RESMA", "12,5"])
    caminho = pasta / "itens-e2e.xlsx"
    wb.save(caminho)
    return caminho


def principal() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--estado", required=True, type=Path,
                        help="JSON gravado quando a pilha estiver pronta")
    args = parser.parse_args()
    if falta := faltando():
        print(f"variáveis ausentes: {', '.join(falta)}", file=sys.stderr)
        return 2
    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    with subir() as pilha:
        estado = {"url": pilha.url, "anon": pilha.anon,
                  "precos": semear_precos(pilha),
                  "coleta": semear_coleta(pilha),
                  "emissao": semear_emissao(pilha, dono="admin_a"),
                  # P04e: pesquisa própria para concluir/reabrir (não mexe na
                  # da emissão) e uma planilha XLSX real para importar.
                  "escrita": semear_emissao(pilha, dono="admin_a"),
                  "planilha": str(gravar_planilha_e2e(args.estado.parent)),
                  "aplicacao": semear_aplicacao(pilha, dono="admin_a"),
                  "contas": {r: {k: v for k, v in asdict(c).items() if k != "token"}
                             for r, c in pilha.contas.items()}}
        temporario = args.estado.with_suffix(".tmp")
        temporario.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
        os.chmod(temporario, 0o600)
        temporario.replace(args.estado)   # aparece inteiro, nunca pela metade
        print("pilha pronta", flush=True)
        parar.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
