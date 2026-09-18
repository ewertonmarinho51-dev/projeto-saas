"""
Isolamento entre prefeituras, EXECUTADO contra um PostgreSQL de verdade.

A 0025 afirma que uma prefeitura não alcança a outra. Afirmação em
comentário de SQL não é contenção: estas provas aplicam o schema REAL num
cluster descartável, assumem a identidade de um usuário autenticado com o
JWT injetado em `request.jwt.claims` — que é o que o PostgREST faz — e
medem cada fronteira.

FRONTEIRA, a mesma de `test_precos_fase3_rls.py`: isto prova o BANCO. Não
prova PostgREST, GoTrue nem `supabase-py`.

Como rodar:

    GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/postgres?host=/tmp/pgens" \\
        python -m pytest tests/test_multi_prefeituras_rls.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import (  # noqa: E402
    NEGADO,
    claims,
    classificar_sql,
    como,
    voltar_a_ser_servidor,
)

requer_pg = pytest.mark.usefixtures("ensaio_sql")

# As dez tabelas que a 0025 cria. A lista fica aqui e não é derivada do
# arquivo: se alguém remover uma tabela da migração, esta prova precisa
# falhar, não se adaptar em silêncio.
TABELAS_NOVAS = (
    "tenant_modulos", "secretaria_modulos", "servidores",
    "servidor_vinculos", "funcoes_administrativas", "servidor_funcoes",
    "portarias", "portaria_membros",
    "documento_identidades", "documento_signatarios",
)

SNAPSHOTS = ("documento_identidades", "documento_signatarios")


@pytest.fixture(scope="module")
def cenario(banco):
    """
    Duas prefeituras, cada uma com uma secretaria, um servidor e uma
    portaria. É o mínimo para que "A não vê B" signifique alguma coisa:
    com uma prefeitura só, toda consulta volta vazia e toda prova passa.
    """
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)

        for chave, rotulo in (("tenant_a", "Prefeitura Alfa"),
                              ("tenant_b", "Prefeitura Beta")):
            c.execute("insert into tenants (slug, nome, uf) "
                      "values (%s, %s, 'PA') returning id",
                      (f"{chave}-{uuid.uuid4().hex[:8]}", rotulo))
            dados[chave] = c.fetchone()[0]

        for chave, tenant, nome in (("sec_a", "tenant_a", "Administração"),
                                    ("sec_b", "tenant_b", "Educação")):
            c.execute("insert into secretarias (tenant_id, nome, sigla) "
                      "values (%s, %s, %s) returning id",
                      (dados[tenant], nome, nome[:6].upper()))
            dados[chave] = c.fetchone()[0]

        for chave, tenant, nome in (("serv_a", "tenant_a", "Antonio Alfa"),
                                    ("serv_b", "tenant_b", "Beatriz Beta")):
            c.execute("insert into servidores (tenant_id, nome, cargo) "
                      "values (%s, %s, 'Agente') returning id",
                      (dados[tenant], nome))
            dados[chave] = c.fetchone()[0]

        for chave, tenant, sec, numero in (
                ("port_a", "tenant_a", "sec_a", "003"),
                ("port_b", "tenant_b", "sec_b", "007")):
            c.execute(
                "insert into portarias (tenant_id, secretaria_id, numero, "
                "ano, data_inicio_vigencia, status) "
                "values (%s, %s, %s, 2026, '2026-01-15', 'ATIVA') returning id",
                (dados[tenant], dados[sec], numero))
            dados[chave] = c.fetchone()[0]

        c.execute(
            "insert into portaria_membros (portaria_id, servidor_id, "
            "tenant_id, funcao) values (%s, %s, %s, 'EQUIPE_PLANEJAMENTO')",
            (dados["port_a"], dados["serv_a"], dados["tenant_a"]))

    banco.commit()

    # `psycopg` devolve `uuid.UUID`, e `claims()` serializa em JSON — o
    # que estoura em `TypeError` antes de chegar ao banco. O JWT que o
    # PostgREST injeta carrega strings, então converter aqui é ficar
    # fiel ao que a política de fato recebe em produção.
    dados = {k: (str(v) if isinstance(v, uuid.UUID) else v)
             for k, v in dados.items()}

    dados["jwt_a"] = claims("u-alfa", papel="admin", tenant=dados["tenant_a"],
                            secretaria=dados["sec_a"])
    dados["jwt_b"] = claims("u-beta", papel="admin", tenant=dados["tenant_b"],
                            secretaria=dados["sec_b"])
    dados["jwt_a_comum"] = claims("u-alfa-comum", papel="usuario",
                                  tenant=dados["tenant_a"],
                                  secretaria=dados["sec_a"])
    return dados


def _contar(banco, jwt, sql, params=()):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt)
        c.execute(sql, params)
        return c.fetchone()[0]


def _tentar(banco, jwt, sql, params=()):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt)
        try:
            c.execute(sql, params)
            return "PERMITIDO"
        except Exception as erro:  # noqa: BLE001
            return classificar_sql(erro)


# ---------------------------------------------------------------------------
# A prova de que as outras não são vazias
# ---------------------------------------------------------------------------
@requer_pg
def test_as_dez_tabelas_existem_com_rls(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select relname, relrowsecurity from pg_class "
                  "where relname = any(%s) and relkind = 'r'",
                  (list(TABELAS_NOVAS),))
        estado = dict(c.fetchall())
    assert set(estado) == set(TABELAS_NOVAS), f"tabela faltando: {estado}"
    assert all(estado.values()), f"RLS desligado em: {estado}"


# ---------------------------------------------------------------------------
# PREFEITURA A NÃO VÊ PREFEITURA B (§5, §45)
# ---------------------------------------------------------------------------
@requer_pg
def test_a_prefeitura_nao_ve_servidor_da_outra(banco, cenario):
    assert _contar(banco, cenario["jwt_a"],
                   "select count(*) from servidores") == 1
    assert _contar(banco, cenario["jwt_a"],
                   "select count(*) from servidores where id = %s",
                   (cenario["serv_b"],)) == 0


@requer_pg
def test_a_prefeitura_nao_ve_portaria_da_outra(banco, cenario):
    assert _contar(banco, cenario["jwt_b"],
                   "select count(*) from portarias") == 1
    assert _contar(banco, cenario["jwt_b"],
                   "select count(*) from portarias where id = %s",
                   (cenario["port_a"],)) == 0


@requer_pg
def test_a_prefeitura_nao_ve_membro_de_portaria_da_outra(banco, cenario):
    assert _contar(banco, cenario["jwt_b"],
                   "select count(*) from portaria_membros") == 0
    assert _contar(banco, cenario["jwt_a"],
                   "select count(*) from portaria_membros") == 1


@requer_pg
def test_a_prefeitura_nao_ve_secretaria_da_outra(banco, cenario):
    assert _contar(banco, cenario["jwt_a"],
                   "select count(*) from secretarias where id = %s",
                   (cenario["sec_b"],)) == 0


# ---------------------------------------------------------------------------
# E NÃO ESCREVE NA OUTRA (§5)
# ---------------------------------------------------------------------------
@requer_pg
def test_admin_de_alfa_nao_cadastra_servidor_em_beta(banco, cenario):
    """
    A fronteira que mais importa: não basta não LER a outra prefeitura.
    Um `tenant_id` digitado à mão no insert não pode atravessar.
    """
    assert _tentar(
        banco, cenario["jwt_a"],
        "insert into servidores (tenant_id, nome) values (%s, 'Infiltrado')",
        (cenario["tenant_b"],)) == NEGADO


@requer_pg
def test_admin_de_alfa_nao_cria_portaria_em_beta(banco, cenario):
    assert _tentar(
        banco, cenario["jwt_a"],
        "insert into portarias (tenant_id, secretaria_id, numero, ano, "
        "data_inicio_vigencia) values (%s, %s, '999', 2026, '2026-01-01')",
        (cenario["tenant_b"], cenario["sec_b"])) == NEGADO


@requer_pg
def test_usuario_comum_nao_cadastra_servidor(banco, cenario):
    """
    §46: administrar servidores é do admin municipal. Um servidor comum
    lê a lista — precisa, para escolher signatário — e não escreve nela.
    """
    assert _tentar(
        banco, cenario["jwt_a_comum"],
        "insert into servidores (tenant_id, nome) values (%s, 'Auto-cadastro')",
        (cenario["tenant_a"],)) == NEGADO


@requer_pg
def test_usuario_comum_le_servidores_da_propria_prefeitura(banco, cenario):
    """O contrapositivo: esconder a lista quebraria a escolha de signatário."""
    assert _contar(banco, cenario["jwt_a_comum"],
                   "select count(*) from servidores") == 1


# ---------------------------------------------------------------------------
# SNAPSHOT É IMUTÁVEL (§33)
# ---------------------------------------------------------------------------
@requer_pg
def test_ninguem_altera_nem_apaga_snapshot(banco):
    """
    Documento assinado não muda de signatário nem de timbrado depois de
    emitido. A correção de um erro é emissão NOVA, com `versao` maior.

    Medido no catálogo porque é onde a decisão vive: sem GRANT, não há
    comando possível — nem com política, nem sem ela.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(
            "select table_name, grantee, privilege_type "
            "from information_schema.role_table_grants "
            "where table_schema = 'public' and table_name = any(%s) "
            "and privilege_type in ('UPDATE', 'DELETE', 'TRUNCATE') "
            "and grantee in ('anon', 'authenticated', 'service_role', 'PUBLIC')",
            (list(SNAPSHOTS),))
        assert c.fetchall() == []


@requer_pg
def test_anon_nao_alcanca_nenhuma_tabela_nova(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select table_name, privilege_type "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' and table_name = any(%s) "
                  "and grantee in ('anon', 'PUBLIC')",
                  (list(TABELAS_NOVAS),))
        assert c.fetchall() == []


@requer_pg
def test_o_dominio_de_funcoes_e_do_produto_e_nao_da_prefeitura(banco, cenario):
    """
    Toda prefeitura LÊ as funções — são o vocabulário do sistema. Nenhuma
    ESCREVE: deixar uma delas renomear `EQUIPE_PLANEJAMENTO` quebraria o
    código que casa por esse código, e quebraria para todas as outras.
    """
    assert _contar(banco, cenario["jwt_a"],
                   "select count(*) from funcoes_administrativas") == 10
    assert _tentar(
        banco, cenario["jwt_a"],
        "insert into funcoes_administrativas (codigo, rotulo) "
        "values ('CHEFE_SUPREMO', 'Chefe')") == NEGADO
