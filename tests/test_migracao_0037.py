"""
A 0037 (substituir e confirmar fato canônico por RPC) aplicada de verdade,
num PostgreSQL descartável.

O que ela promete: o JWT segue sem UPDATE na tabela; quem transiciona é só
quem já podia lançar fato (titular ou admin, no tenant do JWT); o único
caminho de `confirmado` parte de `extraido`; `confirmado_por` vem do banco; e
lista que não bate inteira não muda nada.
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
            / "supabase" / "migrations" / "0037_fatos_canonicos_transicao_por_rpc.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
RPC = "select public.fatos_canonicos_transicionar(%s, %s::uuid[], %s::uuid[])"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


def test_nao_abre_update_na_tabela():
    assert not re.search(r"grant\s+[^;]*\b(update|delete)\b[^;]*\bon\s+(table\s+)?public\.fatos", SQL, re.I)


@pytest.mark.parametrize("proibido", [r"\bto\s+anon\b", r"using\s*\(\s*true\s*\)",
                                       r"disable\s+row\s+level\s+security", r"\bdrop\s+table\b"])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0037 não cumpriu o que afirma" in SQL and SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0037_fatos_canonicos_transicao_por_rpc.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


def _conta(c, d, rotulo, tenant, papel="usuario", ativo=True, secretaria="s1"):
    meta = json.loads(claims("0", papel=papel, tenant=d[f"tenant_{tenant}"], secretaria=d.get(secretaria)))
    c.execute("insert into auth.users (email, raw_app_meta_data) values (%s, %s::jsonb) returning id",
              (f"{uuid.uuid4().hex}@example.invalid", json.dumps(meta["app_metadata"])))
    uid = str(c.fetchone()[0])
    c.execute("insert into usuarios (nome, login, senha_hash, papel, ativo, tenant_id, secretaria_id, auth_user_id) "
              "values (%s, %s, 'sem-uso', %s, %s, %s, %s, %s) returning id",
              (rotulo, uuid.uuid4().hex, papel, ativo, d[f"tenant_{tenant}"], d.get(secretaria), uid))
    d[f"usuario_{rotulo}"] = str(c.fetchone()[0])
    d[f"uid_{rotulo}"] = uid
    meta["sub"] = uid
    d[rotulo] = json.dumps(meta)


@pytest.fixture(scope="module")
def cenario(banco):
    d: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"f-{chave}-{uuid.uuid4().hex[:8]}", f"Prefeitura {chave}"))
            d[f"tenant_{chave}"] = str(c.fetchone()[0])
        c.execute("insert into secretarias (tenant_id, nome) values (%s, 'S1') returning id", (d["tenant_a"],))
        d["s1"] = str(c.fetchone()[0])
        _conta(c, d, "titular", "a")
        _conta(c, d, "colega", "a")
        _conta(c, d, "admin", "a", papel="admin")
        _conta(c, d, "inativa", "a", ativo=False)
        _conta(c, d, "admin_b", "b", papel="admin", secretaria="nenhuma")
        c.execute("insert into processos (tenant_id, secretaria_id, auth_user_id, orgao, objeto) "
                  "values (%s, %s, %s, 'P', 'O') returning id", (d["tenant_a"], d["s1"], d["uid_titular"]))
        d["processo"] = str(c.fetchone()[0])
        c.execute("insert into processos (tenant_id, secretaria_id, auth_user_id, orgao, objeto) "
                  "values (%s, %s, %s, 'P', 'O') returning id", (d["tenant_a"], d["s1"], d["uid_inativa"]))
        d["outro"] = str(c.fetchone()[0])
    banco.commit()
    return d


class _Banco:
    def __init__(self, conexao, cursor, d):
        self.conexao, self.c, self.d = conexao, cursor, d

    def fato(self, processo=None, status="extraido"):
        voltar_a_ser_servidor(self.c)
        self.c.execute("insert into fatos_canonicos (tenant_id, processo_id, path, status) "
                       "values (%s, %s, %s, %s) returning id",
                       (self.d["tenant_a"], processo or self.d["processo"], f"p.{uuid.uuid4().hex[:6]}", status))
        return str(self.c.fetchone()[0])

    def ler(self, fato):
        voltar_a_ser_servidor(self.c)
        self.c.execute("select status, confirmado_por::text from fatos_canonicos where id = %s", (fato,))
        return self.c.fetchone()

    def rpc(self, jwt, processo, substituir=(), confirmar=()):
        voltar_a_ser_servidor(self.c)
        como(self.c, jwt)
        self.c.execute(RPC, (processo, list(substituir), list(confirmar)))
        return self.c.fetchone()[0]

    def falha(self, jwt, processo, substituir=(), confirmar=()):
        try:
            with self.conexao.transaction():
                self.rpc(jwt, processo, substituir, confirmar)
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro")
        return None


@pytest.fixture
def b(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        yield _Banco(banco, c, cenario)


@requer_pg
def test_titular_confirma_e_o_autor_vem_do_banco(b, cenario):
    fato = b.fato()
    assert b.rpc(cenario["titular"], cenario["processo"], confirmar=[fato]) == 1
    assert b.ler(fato) == ("confirmado", cenario["usuario_titular"])


@requer_pg
def test_substituir_e_confirmar_na_mesma_transacao(b, cenario):
    velho, novo = b.fato(status="confirmado"), b.fato()
    assert b.rpc(cenario["admin"], cenario["processo"], substituir=[velho], confirmar=[novo]) == 2
    assert b.ler(velho)[0] == "substituido"
    assert b.ler(novo) == ("confirmado", cenario["usuario_admin"])


@requer_pg
@pytest.mark.parametrize("quem", ["colega", "admin_b", "inativa"])
def test_quem_nao_pode_lancar_fato_nao_transiciona(b, cenario, quem):
    fato = b.fato()
    assert b.falha(cenario[quem], cenario["processo"], confirmar=[fato]) == "42501"
    assert b.ler(fato) == ("extraido", None)


@requer_pg
def test_conta_inativa_nem_no_proprio_processo(b, cenario):
    fato = b.fato(cenario["outro"])
    assert b.falha(cenario["inativa"], cenario["outro"], confirmar=[fato]) == "42501"


@requer_pg
def test_processo_inexistente_tem_a_mesma_resposta(b, cenario):
    assert b.falha(cenario["titular"], str(uuid.uuid4())) == "42501"


@requer_pg
def test_lista_que_nao_bate_nao_muda_nada(b, cenario):
    meu, alheio = b.fato(), b.fato(cenario["outro"])
    assert b.falha(cenario["titular"], cenario["processo"], confirmar=[meu, alheio]) == "PT409"
    assert b.ler(meu) == ("extraido", None)


@requer_pg
def test_ja_confirmado_e_disputado_nao_passam(b, cenario):
    for status in ("confirmado", "disputado", "substituido"):
        assert b.falha(cenario["titular"], cenario["processo"], confirmar=[b.fato(status=status)]) == "PT409"


@requer_pg
def test_lista_ambigua_e_recusada(b, cenario):
    fato = b.fato()
    assert b.falha(cenario["titular"], cenario["processo"], confirmar=[fato, fato]) == "22023"
    assert b.falha(cenario["titular"], cenario["processo"], substituir=[fato], confirmar=[fato]) == "22023"


@requer_pg
def test_update_direto_segue_recusado(b, cenario):
    fato = b.fato()
    voltar_a_ser_servidor(b.c)
    como(b.c, cenario["titular"])
    try:
        with b.conexao.transaction():
            b.c.execute("update fatos_canonicos set status = 'confirmado' where id = %s", (fato,))
    except Exception as erro:  # noqa: BLE001
        assert getattr(erro, "sqlstate", "") == "42501"
    else:
        pytest.fail("UPDATE direto passou")
