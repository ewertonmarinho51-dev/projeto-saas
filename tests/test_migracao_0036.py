"""
A 0036 (escrita da governança por RPC) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: o único caminho de escrita pelo JWT são as quatro RPCs;
quem pode cada ato é a matriz da 0020 (admins tudo; revisor jurídico só
aprova; publicador só publica/revoga; auditor e servidor comum nada); a
máquina de estados do Python vale no banco; publicar SUPERA a anterior;
editar tem trava otimista e só em rascunho/revisão; outro município não
alcança; e cada ato grava o evento com o ator verdadeiro. E a conferência
morde em cada ramo.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0036_governanca_escrita_por_rpc.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
HASH = "a" * 64

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_nenhum_grant_de_escrita_nas_tabelas():
    assert not re.search(r"grant\s+[^;]*\b(insert|update|delete)\b[^;]*\bon\s+(table\s+)?public\.governanca",
                         SQL, re.IGNORECASE)


@pytest.mark.parametrize("proibido", [r"\bto\s+anon\b", r"using\s*\(\s*true\s*\)",
                                       r"disable\s+row\s+level\s+security", r"\bdrop\s+table\b"])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0036 não cumpriu o que afirma" in SQL and SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0036_governanca_escrita_por_rpc.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


def test_tabela_de_transicoes_igual_a_do_python():
    from src import governanca

    pares = set(re.findall(r"\('([A-Z_]+)', '([A-Z_]+)'\)",
                           TEXTO[TEXTO.index("governanca_transicao_valida"):TEXTO.index("governanca_evento_da_transicao")]))
    esperados = {(de, para) for de, destinos in governanca._TRANSICOES_ARTEFATO.items() for para in destinos}
    assert pares == esperados


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    d: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"g-{chave}-{uuid.uuid4().hex[:8]}", f"Prefeitura {chave}"))
            d[f"tenant_{chave}"] = str(c.fetchone()[0])
        for sigla in ("s1", "s2"):
            c.execute("insert into secretarias (tenant_id, nome) values (%s, %s) returning id",
                      (d["tenant_a"], f"Secretaria {sigla}"))
            d[sigla] = str(c.fetchone()[0])
    banco.commit()

    def jwt(tenant, papel="usuario", governanca=None, secretaria="s1"):
        sub = str(uuid.uuid4())
        return claims(sub, papel=papel, tenant=d[f"tenant_{tenant}"],
                      secretaria=d.get(secretaria), papel_governanca=governanca)

    d["admin"] = jwt("a", "admin")
    # Com linha em `usuarios`: autor/revisor/aprovador apontam para ela.
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        meta = json.loads(d["admin"])
        c.execute("insert into auth.users (email, raw_app_meta_data) values (%s, %s::jsonb) returning id",
                  (f"{uuid.uuid4().hex}@example.invalid", json.dumps(meta["app_metadata"])))
        uid = c.fetchone()[0]
        c.execute("insert into usuarios (nome, login, senha_hash, papel, tenant_id, secretaria_id, auth_user_id) "
                  "values ('Admin', %s, 'sem-uso', 'admin', %s, %s, %s) returning id",
                  (uuid.uuid4().hex, d["tenant_a"], d["s1"], uid))
        d["usuario_admin"] = c.fetchone()[0]
        meta["sub"] = str(uid)
        d["admin"] = json.dumps(meta)
    banco.commit()
    d["admin_auditor"] = jwt("a", "admin", governanca="auditor")   # o papel do JWT manda
    d["revisor"] = jwt("a", governanca="revisor_juridico")
    d["publicador"] = jwt("a", governanca="publicador")
    d["auditor"] = jwt("a", governanca="auditor")
    d["comum"] = jwt("a")
    d["admin_b"] = jwt("b", "admin", secretaria=None)
    return d


class _Banco:
    """Uma transação desfeita, onde cada chamada troca de identidade e as
    falhas esperadas ficam num savepoint.

    `como` só GUARDA a identidade; ela é assumida na hora de executar. Em
    `b.como(jwt).falha(SQL, (_lido(b, v),))` o Python avalia `_lido` — que
    volta a ser servidor — DEPOIS de `como`: assumir na hora de `como` faria
    a chamada rodar sem JWT e a recusa sair pelo motivo errado (revisão de
    segurança, 28/10/2026)."""

    def __init__(self, conexao, cursor):
        self.conexao, self.c = conexao, cursor
        self._jwt = None
        self.mensagem = ""

    def como(self, jwt):
        self._jwt = jwt
        return self

    def _assumir(self):
        if self._jwt is not None:
            voltar_a_ser_servidor(self.c)
            como(self.c, self._jwt)
            self._jwt = None

    def rpc(self, sql, params=()):
        self._assumir()
        self.c.execute(sql, params)
        return self.c.fetchone()[0]

    def falha(self, sql, params=()):
        self._assumir()
        self.mensagem = ""
        try:
            with self.conexao.transaction():
                self.c.execute(sql, params)
        except Exception as erro:  # noqa: BLE001
            self.mensagem = str(getattr(getattr(erro, "diag", None), "message_primary", "") or erro)
            return getattr(erro, "sqlstate", "erro")
        return None


@pytest.fixture
def b(banco):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        yield _Banco(banco, c)


CRIAR = "select public.governanca_criar_versao('clausula', %s, %s::jsonb, %s, %s)"
DERIVAR = "select public.governanca_derivar_versao(%s, %s, %s)"
TRANS = "select public.governanca_transicionar(%s, %s, %s)"
EDITAR = "select public.governanca_editar_rascunho(%s, %s::jsonb, %s, %s)"
CAMINHO = ("UNDER_REVIEW", "APPROVED_FOR_SIMULATION", "SHADOW", "PUBLISHED")


def _criar(b, cenario, chave="clausula.tr.garantia"):
    return str(b.como(cenario["admin"]).rpc(CRIAR, (chave, json.dumps({"titulo": "Garantia"}), HASH, 1)))


def _lido(b, versao):
    voltar_a_ser_servidor(b.c)
    b.c.execute("select atualizado_em from governanca_versoes where id = %s", (versao,))
    return b.c.fetchone()[0]


def _mover(b, jwt, versao, status):
    """Transição pelo caminho da tela: com o `atualizado_em` que a pessoa leu."""
    lido = _lido(b, versao)
    return b.como(jwt).rpc(TRANS, (versao, status, lido))


def _negar(b, jwt, versao, status):
    lido = _lido(b, versao)
    return b.como(jwt).falha(TRANS, (versao, status, lido))


def _fabricado(b, tenant, secretaria):
    """Artefato da plataforma ou de secretaria, feito pelo servidor (as RPCs
    só criam o do município), já aprovado para simulação."""
    voltar_a_ser_servidor(b.c)
    b.c.execute("insert into governanca_artefatos (tenant_id, secretaria_id, tipo_artefato, chave_estavel) "
                "values (%s, %s, 'clausula', %s) returning id",
                (tenant, secretaria, f"clausula.fab.{uuid.uuid4().hex[:8]}"))
    artefato = b.c.fetchone()[0]
    b.c.execute("insert into governanca_versoes (artefato_id, versao, status, payload, hash) "
                "values (%s, 1, 'APPROVED_FOR_SIMULATION', '{}', %s) returning id", (artefato, HASH))
    return str(b.c.fetchone()[0])


def _status(b, versao):
    voltar_a_ser_servidor(b.c)
    b.c.execute("select status from governanca_versoes where id = %s", (versao,))
    return b.c.fetchone()[0]


@requer_pg
def test_admin_cria_versao_e_a_trilha_registra_o_ator(b, cenario):
    v = _criar(b, cenario)
    voltar_a_ser_servidor(b.c)
    b.c.execute("select v.status, v.versao, a.tenant_id from governanca_versoes v "
                "join governanca_artefatos a on a.id = v.artefato_id where v.id = %s", (v,))
    assert b.c.fetchone() == ("DRAFT", 1, uuid.UUID(cenario["tenant_a"]))
    b.c.execute("select tipo_evento from governanca_eventos where entidade_id = %s", (v,))
    assert [r[0] for r in b.c.fetchall()] == ["versao_criada"]


@pytest.mark.parametrize("quem", ["auditor", "comum", "revisor", "publicador"])
@requer_pg
def test_so_quem_cria_cria(b, cenario, quem):
    assert b.como(cenario[quem]).falha(CRIAR, ("clausula.x.y", "{}", HASH, 1)) == "42501"


@requer_pg
def test_separacao_de_funcoes_no_fluxo_inteiro(b, cenario):
    # Artefato DO MUNICÍPIO (sem secretaria): revisor e publicador da
    # secretaria s1 o alcançam — sem isso, só o admin faria tudo.
    v = _criar(b, cenario)
    assert _negar(b, cenario["revisor"], v, "UNDER_REVIEW") == "42501"   # sem porteiro: só quem cria
    _mover(b, cenario["admin"], v, "UNDER_REVIEW")
    assert _negar(b, cenario["publicador"], v, "APPROVED_FOR_SIMULATION") == "42501"
    _mover(b, cenario["revisor"], v, "APPROVED_FOR_SIMULATION")
    _mover(b, cenario["admin"], v, "SHADOW")
    assert _negar(b, cenario["revisor"], v, "PUBLISHED") == "42501"
    assert _negar(b, cenario["auditor"], v, "PUBLISHED") == "42501"
    assert _negar(b, cenario["admin_auditor"], v, "PUBLISHED") == "42501"   # o papel do JWT manda
    _mover(b, cenario["publicador"], v, "PUBLISHED")
    assert _status(b, v) == "PUBLISHED"
    assert _negar(b, cenario["revisor"], v, "REVOKED") == "42501"
    _mover(b, cenario["publicador"], v, "REVOKED")
    assert _status(b, v) == "REVOKED"
    voltar_a_ser_servidor(b.c)
    b.c.execute("select tipo_evento, ator is not null from governanca_eventos where entidade_id = %s", (v,))
    eventos = b.c.fetchall()
    assert {e[0] for e in eventos} == {"versao_criada", "versao_alterada", "versao_aprovada",
                                       "versao_publicada", "versao_revogada"}
    assert all(e[1] for e in eventos)


@requer_pg
def test_autor_e_aprovador_sao_a_pessoa_do_jwt(b, cenario):
    v = _criar(b, cenario)
    for status in CAMINHO:
        _mover(b, cenario["admin"], v, status)
    voltar_a_ser_servidor(b.c)
    b.c.execute("select autor, revisor, aprovador from governanca_versoes where id = %s", (v,))
    assert b.c.fetchone() == (cenario["usuario_admin"],) * 3


@requer_pg
def test_revisor_e_publicador_nao_editam_nem_derivam(b, cenario):
    v = _criar(b, cenario)
    for quem in ("revisor", "publicador"):
        assert b.como(cenario[quem]).falha(EDITAR, (v, '{"titulo":"x"}', HASH, _lido(b, v))) == "42501"
        assert "não pode versao_alterada" in b.mensagem, b.mensagem
    for status in CAMINHO:
        _mover(b, cenario["admin"], v, status)
    for quem in ("revisor", "publicador", "auditor"):
        assert b.como(cenario[quem]).falha(DERIVAR, (v, "c" * 64, 2)) == "42501"


@requer_pg
def test_alcance_por_secretaria_e_plataforma(b, cenario):
    da_s1 = _fabricado(b, cenario["tenant_a"], cenario["s1"])
    da_s2 = _fabricado(b, cenario["tenant_a"], cenario["s2"])
    da_plataforma = _fabricado(b, None, None)
    assert _negar(b, cenario["admin"], da_plataforma, "SHADOW") == "42501"
    _mover(b, cenario["admin"], da_s2, "SHADOW")             # papel amplo: o município inteiro
    _mover(b, cenario["admin"], da_s1, "SHADOW")
    assert _negar(b, cenario["publicador"], da_s2, "PUBLISHED") == "42501"
    _mover(b, cenario["publicador"], da_s1, "PUBLISHED")


@requer_pg
def test_aprova_o_texto_lido_nao_o_editado_no_meio(b, cenario):
    v = _criar(b, cenario)
    lido = _lido(b, v)
    b.como(cenario["admin"]).rpc(EDITAR, (v, '{"titulo":"trocado"}', "b" * 64, lido))
    assert b.como(cenario["admin"]).falha(TRANS, (v, "UNDER_REVIEW", lido)) == "PT409"
    assert "mudou desde a sua leitura" in b.mensagem, b.mensagem
    assert b.como(cenario["admin"]).falha(TRANS, (v, "UNDER_REVIEW", None)) == "PT409"
    _mover(b, cenario["admin"], v, "UNDER_REVIEW")


@requer_pg
def test_publicar_supera_a_anterior(b, cenario):
    v1 = _criar(b, cenario)
    for status in CAMINHO:
        _mover(b, cenario["admin"], v1, status)
    assert b.como(cenario["admin"]).falha(DERIVAR, (v1, "c" * 64, 3)) == "PT409"   # número errado
    v2 = str(b.como(cenario["admin"]).rpc(DERIVAR, (v1, "c" * 64, 2)))
    assert _status(b, v2) == "DRAFT"
    voltar_a_ser_servidor(b.c)
    b.c.execute("select payload from governanca_versoes where id = %s", (v2,))
    assert b.c.fetchone()[0] == {"titulo": "Garantia"}       # conteúdo do banco, não do cliente
    for status in CAMINHO:
        _mover(b, cenario["admin"], v2, status)
    assert (_status(b, v1), _status(b, v2)) == ("SUPERSEDED", "PUBLISHED")
    voltar_a_ser_servidor(b.c)
    b.c.execute("select tipo_evento from governanca_eventos where entidade_id = %s", (v1,))
    assert "versao_superada" in {r[0] for r in b.c.fetchall()}


@requer_pg
def test_so_deriva_de_publicada(b, cenario):
    v = _criar(b, cenario)
    assert b.como(cenario["admin"]).falha(DERIVAR, (v, "c" * 64, 2)) == "PT409"
    assert "publicada" in b.mensagem, b.mensagem


@requer_pg
def test_uma_publicada_por_artefato_ate_para_o_servidor(b, cenario):
    v1 = _criar(b, cenario)
    for status in CAMINHO:
        _mover(b, cenario["admin"], v1, status)
    voltar_a_ser_servidor(b.c)
    b.c.execute("select artefato_id from governanca_versoes where id = %s", (v1,))
    artefato = b.c.fetchone()[0]
    assert b.falha("insert into governanca_versoes (artefato_id, versao, status) values (%s, 9, 'PUBLISHED')",
                   (artefato,)) == "23505"


@requer_pg
def test_transicao_fora_da_maquina_e_recusada(b, cenario):
    v = _criar(b, cenario)
    assert _negar(b, cenario["admin"], v, "PUBLISHED") == "22023"     # DRAFT → PUBLISHED
    assert _negar(b, cenario["admin"], v, "SUPERSEDED") == "22023"    # só por efeito
    assert _negar(b, cenario["admin"], v, None) == "22023"
    assert _negar(b, cenario["admin"], v, "INVENTADO") == "22023"


@requer_pg
def test_editar_so_rascunho_e_com_trava(b, cenario):
    v = _criar(b, cenario)
    lido = _lido(b, v)
    assert b.como(cenario["admin"]).falha(EDITAR, (v, '{"titulo":"x"}', HASH, "2000-01-01")) == "PT409"
    b.como(cenario["admin"]).rpc(EDITAR, (v, '{"titulo":"novo"}', "b" * 64, lido))
    for status in CAMINHO:
        _mover(b, cenario["admin"], v, status)
    assert b.como(cenario["admin"]).falha(EDITAR, (v, '{"titulo":"y"}', HASH, _lido(b, v))) == "PT409"
    assert "imutável" in b.mensagem, b.mensagem


@requer_pg
def test_outro_municipio_e_versao_inexistente_dao_a_mesma_recusa(b, cenario):
    v = _criar(b, cenario)
    assert _negar(b, cenario["admin_b"], v, "UNDER_REVIEW") == "42501"
    assert b.como(cenario["admin"]).falha(TRANS, (str(uuid.uuid4()), "UNDER_REVIEW", _lido(b, v))) == "42501"
    assert b.como(cenario["admin_b"]).falha(DERIVAR, (v, "c" * 64, 2)) == "42501"
    assert b.como(cenario["admin_b"]).falha(EDITAR, (v, "{}", HASH, _lido(b, v))) == "42501"
    assert "fora do seu alcance" in b.mensagem, b.mensagem


@pytest.mark.parametrize("args", [
    (None, "clausula.a.b", "{}", HASH), ("processo", "clausula.a.b", "{}", HASH),
    ("clausula", None, "{}", HASH), ("clausula", "X", "{}", HASH),
    ("clausula", "clausula.a.b", None, HASH), ("clausula", "clausula.a.b", "[]", HASH),
    ("clausula", "clausula.a.b", "{}", None), ("clausula", "clausula.a.b", "{}", "curto"),
])
@requer_pg
def test_nulo_e_forma_invalida_sao_recusados(b, cenario, args):
    assert b.como(cenario["admin"]).falha(
        "select public.governanca_criar_versao(%s, %s, %s::jsonb, %s, 1)", args) == "22023"


@requer_pg
def test_escrita_direta_continua_negada(b, cenario):
    v = _criar(b, cenario)
    assert b.como(cenario["admin"]).falha("update governanca_versoes set status = 'PUBLISHED' where id = %s",
                                          (v,)) == "42501"
    assert b.como(cenario["admin"]).falha(
        "insert into governanca_artefatos (tenant_id, tipo_artefato, chave_estavel) values (%s, 'clausula', 'x.y.z')",
        (cenario["tenant_a"],)) == "42501"
    assert b.como(cenario["admin"]).falha("select public.governanca_exigir('versao_criada', null)") == "42501"
    assert b.como(cenario["admin"]).falha(
        "select public.governanca_evento('versao_publicada', %s, '{}')", (v,)) == "42501"


MUTACOES = [
    ("grant insert on public.governanca_versoes to authenticated", "escrita_direta_em_governanca_versoes"),
    ("grant execute on function public.governanca_exigir(text, uuid) to authenticated",
     "apoio_exposto_governanca_exigir"),
    ("grant insert on public.governanca_artefatos to authenticated", "escrita_direta_em_governanca_artefatos"),
    ("grant update (status) on public.governanca_versoes to authenticated", "escrita_direta_em_governanca_versoes"),
    ("grant truncate on public.governanca_eventos to authenticated", "escrita_direta_em_governanca_eventos"),
    ("grant execute on function public.governanca_evento(text, uuid, jsonb) to authenticated",
     "apoio_exposto_governanca_evento"),
    ("alter function public.governanca_transicionar(uuid, text, timestamptz, timestamptz) security invoker",
     "rpc_governanca_transicionar"),
    ("alter function public.governanca_criar_versao(text, text, jsonb, text, integer) reset search_path",
     "rpc_governanca_criar_versao"),
    ("revoke execute on function public.governanca_derivar_versao(uuid, text, integer) from authenticated",
     "rpc_governanca_derivar_versao"),
    ("grant execute on function public.governanca_editar_rascunho(uuid, jsonb, text, timestamptz) to public",
     "execucao_governanca_editar_rascunho_public"),
    ("grant select on public.governanca_versoes to anon", "anon_em_governanca_versoes"),
    ("drop index public.governanca_versoes_uma_publicada", "sem_indice_uma_publicada"),
    ("alter table public.governanca_versoes disable row level security", "rls_desligado_em_governanca_versoes"),
    ("drop index public.governanca_versoes_uma_publicada; create index governanca_versoes_uma_publicada "
     "on public.governanca_versoes (artefato_id)", "sem_indice_uma_publicada"),
    ("alter table public.governanca_eventos disable trigger evento_ator_confiavel; "
     "drop trigger evento_ator_confiavel on public.governanca_eventos", "sem_gatilho_ator_confiavel"),
    ("grant execute on function public.governanca_usuario_do_jwt() to authenticated",
     "apoio_exposto_governanca_usuario_do_jwt"),
    ("grant select on public.governanca_artefatos to anon", "anon_em_governanca_artefatos"),
    ("grant select (id) on public.governanca_versoes to anon", "anon_em_governanca_versoes"),
    ("grant execute on function public.governanca_transicionar(uuid, text, timestamptz, timestamptz) to anon",
     "execucao_governanca_transicionar_anon"),
    ("grant execute on function public.governanca_criar_versao(text, text, jsonb, text, integer) to anon",
     "execucao_governanca_criar_versao_anon"),
    ("grant select on public.governanca_eventos to anon", "anon_em_governanca_eventos"),
]


@requer_pg
@pytest.mark.parametrize("mutacao,denuncia", MUTACOES)
def test_a_conferencia_morde(banco, cenario, mutacao, denuncia):
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match=denuncia):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(mutacao)
            c.execute(TEXTO[TEXTO.index("do $$"):])
