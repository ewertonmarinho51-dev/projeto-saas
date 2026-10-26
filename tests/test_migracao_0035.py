"""
A 0035 (cadastro institucional pelo admin, com o próprio JWT) aplicada de
verdade, num PostgreSQL descartável.

O que ela promete: o ADMIN edita os campos institucionais da PRÓPRIA
prefeitura — e só eles —, cria e edita secretarias e cria/exclui
identidades visuais no próprio tenant; usuário comum não escreve; outra
prefeitura não é alcançada; nada muda de tenant; secretaria não se apaga.
E a conferência morde em cada ramo.
"""

from __future__ import annotations

import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0035_cadastro_institucional_admin.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
CAMPOS = ("nome_oficial", "cnpj", "sigla", "cidade", "endereco", "telefone", "email", "site")

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_tenants_so_por_coluna_e_so_os_campos_institucionais():
    grant = re.search(r"grant update \(([^)]*)\)\s+on public\.tenants to authenticated;", SQL)
    assert grant, "o UPDATE em tenants precisa ser por coluna"
    assert tuple(c.strip() for c in grant.group(1).split(",")) == CAMPOS
    assert not re.search(r"grant\s+[^;(]*\bon\s+public\.tenants\b", SQL, re.IGNORECASE)


@pytest.mark.parametrize("proibido", [
    r"grant\s+[^;]*\bdelete\b[^;]*\bon\s+public\.(secretarias|tenants)\b",
    r"\bto\s+anon\b", r"using\s*\(\s*true\s*\)", r"with\s+check\s*\(\s*true\s*\)",
    r"disable\s+row\s+level\s+security", r"\bdrop\s+table\b", r"\bdelete\s+from\b", r"\btruncate\b\s+public",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0035 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0035_cadastro_institucional_admin.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    d: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"t-{chave}-{uuid.uuid4().hex[:8]}", f"Prefeitura {chave}"))
            d[f"tenant_{chave}"] = str(c.fetchone()[0])
            c.execute("insert into secretarias (tenant_id, nome) values (%s, %s) returning id",
                      (d[f"tenant_{chave}"], f"Secretaria {chave}"))
            d[f"sec_{chave}"] = str(c.fetchone()[0])
            c.execute("insert into config_orgaos (tenant_id, orgao) values (%s, %s) returning id",
                      (d[f"tenant_{chave}"], f"Órgão {chave}"))
            d[f"org_{chave}"] = str(c.fetchone()[0])
    banco.commit()
    d["admin_a"] = claims("u-admin-a", papel="admin", tenant=d["tenant_a"])
    d["comum_a"] = claims("u-comum-a", papel="usuario", tenant=d["tenant_a"])
    return d


def _executar(banco, jwt, sql, params=()):
    """(sqlstate ou None, linhas afetadas), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt)
        try:
            c.execute(sql, params)
            return None, c.rowcount
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), 0


@requer_pg
def test_admin_edita_os_campos_institucionais_da_propria_prefeitura(banco, cenario):
    sql = "update tenants set nome_oficial = 'Município A', cnpj = '00.000.000/0001-00' where id = %s"
    assert _executar(banco, cenario["admin_a"], sql, (cenario["tenant_a"],)) == (None, 1)


@pytest.mark.parametrize("coluna", ["slug", "nome", "uf", "ativo"])
@requer_pg
def test_admin_nao_mexe_na_identidade_da_prefeitura(banco, cenario, coluna):
    valor = "false" if coluna == "ativo" else "'x'"
    estado, _ = _executar(banco, cenario["admin_a"], f"update tenants set {coluna} = {valor} where id = %s",
                          (cenario["tenant_a"],))
    assert estado == "42501"


@requer_pg
def test_prefeitura_alheia_e_usuario_comum_nao_alcancam(banco, cenario):
    sql = "update tenants set cidade = 'x' where id = %s"
    assert _executar(banco, cenario["admin_a"], sql, (cenario["tenant_b"],)) == (None, 0)
    assert _executar(banco, cenario["comum_a"], sql, (cenario["tenant_a"],)) == (None, 0)


@requer_pg
def test_secretaria_criada_e_editada_so_no_proprio_tenant(banco, cenario):
    cria = "insert into secretarias (tenant_id, nome) values (%s, %s)"
    assert _executar(banco, cenario["admin_a"], cria, (cenario["tenant_a"], "Nova A")) == (None, 1)
    assert _executar(banco, cenario["admin_a"], cria, (cenario["tenant_b"], "Nova B"))[0] == "42501"
    assert _executar(banco, cenario["comum_a"], cria, (cenario["tenant_a"], "Nova C"))[0] == "42501"
    edita = "update secretarias set ativo = false where id = %s"
    assert _executar(banco, cenario["admin_a"], edita, (cenario["sec_a"],)) == (None, 1)
    assert _executar(banco, cenario["admin_a"], edita, (cenario["sec_b"],)) == (None, 0)
    assert _executar(banco, cenario["comum_a"], edita, (cenario["sec_a"],)) == (None, 0)


@requer_pg
def test_secretaria_nao_muda_de_prefeitura_nem_se_apaga(banco, cenario):
    estado, _ = _executar(banco, cenario["admin_a"], "update secretarias set tenant_id = %s where id = %s",
                          (cenario["tenant_b"], cenario["sec_a"]))
    assert estado == "42501"
    estado, _ = _executar(banco, cenario["admin_a"], "delete from secretarias where id = %s", (cenario["sec_a"],))
    assert estado == "42501"


@requer_pg
def test_origem_da_secretaria_so_de_identidade_do_proprio_tenant(banco, cenario):
    cria = "insert into secretarias (tenant_id, nome, origem_orgao_id) values (%s, %s, %s)"
    assert _executar(banco, cenario["admin_a"], cria,
                     (cenario["tenant_a"], "Espelho A", cenario["org_a"])) == (None, 1)
    estado, _ = _executar(banco, cenario["admin_a"], cria, (cenario["tenant_a"], "Furo", cenario["org_b"]))
    assert estado == "42501", "origem de outra prefeitura aceita"
    estado, _ = _executar(banco, cenario["admin_a"], "update secretarias set origem_orgao_id = %s where id = %s",
                          (cenario["org_a"], cenario["sec_a"]))
    assert estado == "42501", "origem mudou depois de criada"


@requer_pg
def test_id_e_criado_em_sao_do_banco(banco, cenario):
    estado, _ = _executar(banco, cenario["admin_a"], "insert into secretarias (id, tenant_id, nome) values (%s, %s, 'X')",
                          (str(uuid.uuid4()), cenario["tenant_a"]))
    assert estado == "42501"


@requer_pg
def test_admin_edita_a_prefeitura_com_returning(banco, cenario):
    """O caminho real: supabase-py faz UPDATE ... RETURNING *."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["admin_a"])
        c.execute("update tenants set cidade = 'X' where id = %s returning *", (cenario["tenant_a"],))
        assert len(c.fetchall()) == 1


@requer_pg
def test_identidade_criada_e_excluida_so_no_proprio_tenant(banco, cenario):
    cria = "insert into config_orgaos (tenant_id, orgao) values (%s, 'Nova')"
    assert _executar(banco, cenario["admin_a"], cria, (cenario["tenant_a"],)) == (None, 1)
    assert _executar(banco, cenario["admin_a"], cria, (cenario["tenant_b"],))[0] == "42501"
    assert _executar(banco, cenario["comum_a"], cria, (cenario["tenant_a"],))[0] == "42501"
    exclui = "delete from config_orgaos where id = %s"
    assert _executar(banco, cenario["admin_a"], exclui, (cenario["org_a"],)) == (None, 1)
    assert _executar(banco, cenario["admin_a"], exclui, (cenario["org_b"],)) == (None, 0)
    assert _executar(banco, cenario["comum_a"], exclui, (cenario["org_a"],)) == (None, 0)


# Cada ramo da conferência, quebrado de propósito.
MUTACOES = [
    ('drop policy "tenants_admin_edita" on public.tenants', "politica_tenants_admin_edita"),
    ('alter policy "secretarias_admin_cria" on public.secretarias to public', "politica_secretarias_admin_cria"),
    ('drop policy "config_orgaos_admin_exclui" on public.config_orgaos', "politica_config_orgaos_admin_exclui"),
    ("revoke update (cnpj) on public.tenants from authenticated", "grant_coluna_tenants_cnpj"),
    ("revoke insert (nome) on public.secretarias from authenticated", "grant_coluna_secretarias_insert_nome"),
    ("grant update (origem_orgao_id) on public.secretarias to authenticated",
     "secretarias_coluna_aberta_update_origem_orgao_id"),
    ("grant update on public.secretarias to authenticated", "secretarias_coluna_aberta_update_tenant_id"),
    ("create policy furo on public.config_orgaos for select to authenticated using (true)",
     "politica_aberta_config_orgaos_furo"),
    ("revoke delete on public.config_orgaos from authenticated", "grant_DELETE_config_orgaos"),
    ("grant update (slug) on public.tenants to authenticated", "tenants_coluna_aberta_slug"),
    ("grant insert on public.tenants to authenticated", "tenants_insert"),
    ("grant delete on public.secretarias to authenticated", "delete_em_secretarias"),
    ("grant truncate on public.config_orgaos to authenticated", "privilegio_largo_em_config_orgaos"),
    ("grant select (nome) on public.tenants to anon", "anon_em_tenants"),
    ("alter table public.secretarias disable row level security", "rls_desligado_em_secretarias"),
]


@requer_pg
@pytest.mark.parametrize("mutacao,denuncia", MUTACOES)
def test_a_conferencia_morde(banco, cenario, mutacao, denuncia):
    import psycopg

    conferencia = TEXTO[TEXTO.index("do $$"):]
    with pytest.raises(psycopg.errors.RaiseException, match=denuncia):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(mutacao)
            c.execute(conferencia)


@requer_pg
def test_a_conferencia_passa_no_estado_certo(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO[TEXTO.index("do $$"):])
