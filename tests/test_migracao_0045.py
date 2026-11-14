"""
A 0045 (fila durável do importador nacional do PNCP) aplicada de verdade,
num PostgreSQL descartável.

O que ela promete: a fila e o controle são só do servidor; reserva entrega
cada tarefa a UM dono, com token; só o token confirma; lease vencido volta
à fila; pausa trava a reserva; um líder por vez; e a conferência morde.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0045_precos_pncp_fila.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")
FUNCOES = ("precos_pncp_reservar", "precos_pncp_renovar", "precos_pncp_concluir",
           "precos_pncp_liderar")


def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0045 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 13/11/2026 (registro 20261113234247" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+authenticated\b", r"\bto\s+public\b", r"create\s+policy",
    r"default\s+privileges", r"\bsecurity\s+definer\b", r"disable\s+row\s+level\s+security",
    r"grant\s+[^;]*\b(truncate|delete)\b", r"\bdrop\s+table\b",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


@pytest.mark.parametrize("funcao", FUNCOES)
def test_cada_rpc_revoga_de_public_e_concede_so_ao_servidor(funcao):
    assert re.search(rf"revoke all on function public\.{funcao}\([^)]*\) "
                     r"from public, anon, authenticated;", SQL)
    assert re.search(rf"grant execute on function public\.{funcao}\([^)]*\) to service_role;",
                     SQL)


def test_reserva_usa_skip_locked_e_o_token_e_exigido():
    reservar = SQL[SQL.index("function public.precos_pncp_reservar"):]
    reservar = reservar[:reservar.index("$$;")]
    assert "for update skip locked" in reservar
    for funcao in ("precos_pncp_renovar", "precos_pncp_concluir"):
        corpo = SQL[SQL.index(f"function public.{funcao}"):]
        corpo = corpo[:corpo.index("$$;")]
        assert "token = p_token" in corpo and "estado = 'em_execucao'" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0045 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_esta_na_sequencia_do_ensaio_depois_da_0044():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert SEQUENCIA_EM_ENSAIO.index("0045_precos_pncp_fila.sql") == \
        SEQUENCIA_EM_ENSAIO.index("0044_precos_bps_indice.sql") + 1
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


def test_o_codigo_usa_os_mesmos_nomes():
    from src.precos import pncp_integral

    assert set(pncp_integral.FONTES) <= {"comprasgov_lote", "pncp_descoberta", "pncp_contratacao"}
    for estado in pncp_integral.ESTADOS_FINAIS:
        assert f"'{estado}'" in SQL


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)
        c.execute(TEXTO)  # idempotente
        voltar_a_ser_servidor(c)
    banco.commit()
    return {}


def _como(banco, sql, parametros=(), papel="service_role", jwt="{}"):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(sql, parametros)
            return None, (c.fetchall() if c.description else [])
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), []


@requer_pg
@pytest.mark.parametrize("papel,jwt", [("authenticated", USUARIO), ("anon", "{}")])
@pytest.mark.parametrize("sql", [
    "select * from public.precos_pncp_tarefas",
    "select * from public.precos_pncp_controle",
    "insert into public.precos_pncp_tarefas (campanha, fonte, particao) "
    "values ('c-1', 'comprasgov_lote', '2026-10-29')",
    "update public.precos_pncp_controle set pausado = true",
    "select * from public.precos_pncp_reservar('x', array['comprasgov_lote'], 1, 60)",
    "select public.precos_pncp_liderar('x', 60)",
])
def test_usuario_nao_alcanca_fila_nem_rpc(banco, cenario, papel, jwt, sql):
    assert _como(banco, sql, papel=papel, jwt=jwt)[0] == "42501"


@requer_pg
def test_servidor_nao_apaga_nem_trunca(banco, cenario):
    assert _como(banco, "delete from public.precos_pncp_tarefas")[0] == "42501"
    assert _como(banco, "truncate public.precos_pncp_tarefas")[0] == "42501"
    assert _como(banco, "delete from public.precos_pncp_controle")[0] == "42501"


def _ciclo(c, sql, parametros=()):
    c.execute(sql, parametros)
    return c.fetchall() if c.description else []


@requer_pg
def test_reserva_lease_token_e_pausa(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        _ciclo(c, "insert into public.precos_pncp_tarefas (campanha, fonte, particao, prioridade) "
                  "values ('c-1', 'comprasgov_lote', '2026-10-29', 10), "
                  "('c-1', 'comprasgov_lote', '2026-10-28', 20)")
        a = _ciclo(c, "select id, token, particao from public.precos_pncp_reservar("
                      "'w1', array['comprasgov_lote'], 1, 60)")
        assert [x[2] for x in a] == ["2026-10-29"]          # prioridade primeiro
        b = _ciclo(c, "select id, token, particao from public.precos_pncp_reservar("
                      "'w2', array['comprasgov_lote'], 5, 60)")
        assert [x[2] for x in b] == ["2026-10-28"]          # nunca a mesma
        assert _ciclo(c, "select * from public.precos_pncp_reservar("
                         "'w3', array['comprasgov_lote'], 5, 60)") == []
        # token alheio não confirma; o dono confirma
        assert _ciclo(c, "select public.precos_pncp_concluir(%s, gen_random_uuid(), "
                         "'concluida', null, null, '', null)", (a[0][0],)) == [(False,)]
        assert _ciclo(c, "select public.precos_pncp_concluir(%s, %s, 'concluida', "
                         "'{\"pagina\": 23}', '{\"linhas\": 11369}', '', null)",
                      (a[0][0], a[0][1])) == [(True,)]
        # lease vencido volta à fila com OUTRO token
        _ciclo(c, "update public.precos_pncp_tarefas set lease_ate = now() - interval '1 s' "
                  "where id = %s", (b[0][0],))
        de_novo = _ciclo(c, "select id, token from public.precos_pncp_reservar("
                            "'w3', array['comprasgov_lote'], 5, 60)")
        assert de_novo[0][0] == b[0][0] and de_novo[0][1] != b[0][1]
        # o dono antigo não confirma mais
        assert _ciclo(c, "select public.precos_pncp_concluir(%s, %s, 'concluida', null, null, "
                         "'', null)", (b[0][0], b[0][1])) == [(False,)]
        # pausa trava a reserva
        _ciclo(c, "insert into public.precos_pncp_tarefas (campanha, fonte, particao) "
                  "values ('c-1', 'comprasgov_lote', '2026-10-27')")
        _ciclo(c, "update public.precos_pncp_controle set pausado = true")
        assert _ciclo(c, "select * from public.precos_pncp_reservar("
                         "'w4', array['comprasgov_lote'], 5, 60)") == []


@requer_pg
def test_concluida_nunca_volta_e_pendente_futuro_so_na_data(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        _ciclo(c, "insert into public.precos_pncp_tarefas (campanha, fonte, particao, estado, "
                  "proxima_em) values ('c-3', 'comprasgov_lote', 'a', 'concluida', "
                  "now() - interval '1 day'), ('c-3', 'comprasgov_lote', 'b', 'pendente', "
                  "now() + interval '7 days'), ('c-3', 'comprasgov_lote', 'c', 'pendente', "
                  "now() - interval '1 s')")
        pegas = _ciclo(c, "select particao from public.precos_pncp_reservar("
                          "'w', array['comprasgov_lote'], 10, 60) where campanha = 'c-3'")
        assert [p[0] for p in pegas] == ["c"]


@requer_pg
def test_limite_nulo_reserva_uma(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        _ciclo(c, "insert into public.precos_pncp_tarefas (campanha, fonte, particao) "
                  "select 'c-4', 'pncp_contratacao', 'x' || g from generate_series(1, 5) g")
        assert len(_ciclo(c, "select * from public.precos_pncp_reservar("
                             "'w', array['pncp_contratacao'], null, 60)")) == 1


@requer_pg
def test_estado_invalido_nao_confirma(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        _ciclo(c, "insert into public.precos_pncp_tarefas (campanha, fonte, particao) "
                  "values ('c-2', 'pncp_descoberta', 'mod6:2026-10')")
        t = _ciclo(c, "select id, token from public.precos_pncp_reservar("
                      "'w1', array['pncp_descoberta'], 1, 60)")
        assert _ciclo(c, "select public.precos_pncp_concluir(%s, %s, 'apagada', null, null, "
                         "'', null)", (t[0][0], t[0][1])) == [(False,)]


@requer_pg
def test_um_lider_por_vez(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        _ciclo(c, "update public.precos_pncp_controle set lider = null, lider_ate = null")
        assert _ciclo(c, "select public.precos_pncp_liderar('vps-a', 120)") == [(True,)]
        assert _ciclo(c, "select public.precos_pncp_liderar('vps-b', 120)") == [(False,)]
        assert _ciclo(c, "select public.precos_pncp_liderar('vps-a', 120)") == [(True,)]
        _ciclo(c, "update public.precos_pncp_controle set lider_ate = now() - interval '1 s'")
        assert _ciclo(c, "select public.precos_pncp_liderar('vps-b', 120)") == [(True,)]


MUTACOES = [
    ("alter table public.precos_pncp_tarefas disable row level security", "rls_desligado"),
    ("grant select on public.precos_pncp_tarefas to anon", "usuario_alcanca"),
    ("grant select (pausado) on public.precos_pncp_controle to authenticated", "usuario_alcanca"),
    ("grant delete on public.precos_pncp_tarefas to service_role", "service_role_apaga_ou_amarra"),
    ("grant truncate on public.precos_pncp_controle to service_role",
     "service_role_apaga_ou_amarra"),
    ("revoke update on public.precos_pncp_tarefas from service_role",
     "service_role_sem_o_necessario"),
    ("create policy p on public.precos_pncp_tarefas for select to authenticated using (true)",
     "politica_inesperada"),
    ("grant execute on function public.precos_pncp_reservar(text, text[], integer, integer) "
     "to public", "usuario_executa"),
    ("revoke execute on function public.precos_pncp_concluir(bigint, uuid, text, jsonb, jsonb, "
     "text, timestamptz) from service_role", "servidor_nao_executa"),
    ("alter function public.precos_pncp_liderar(text, integer) security definer",
     "security_definer"),
    ("alter function public.precos_pncp_renovar(bigint, uuid, integer) reset search_path",
     "search_path_solto"),
    ("grant usage on sequence public.precos_pncp_tarefas_id_seq to authenticated",
     "usuario_alcanca_sequencia"),
]


@requer_pg
@pytest.mark.parametrize("mutacao,denuncia", MUTACOES)
def test_a_conferencia_morde(banco, cenario, mutacao, denuncia):
    import psycopg

    conferencia = TEXTO[TEXTO.rindex("do $$"):]
    with pytest.raises(psycopg.errors.RaiseException, match=denuncia):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(mutacao)
            c.execute(conferencia)


@requer_pg
def test_a_conferencia_passa_no_estado_certo(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO[TEXTO.rindex("do $$"):])
