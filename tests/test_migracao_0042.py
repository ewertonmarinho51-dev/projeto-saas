"""
A 0042 (índice do PNCP) aplicada de verdade, num PostgreSQL descartável.

O que ela promete: dado público sem tenant; `authenticated` LÊ os resultados
e nada mais; `anon` não alcança nada; só a credencial de servidor escreve, e
nem ela apaga; a busca roda como quem chama. E a conferência morde quando
uma dessas garantias some.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0042_precos_pncp_indice.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_pncp_cursores", "precos_pncp_contratacoes", "precos_pncp_resultados")
FUNCAO = "public.precos_pncp_buscar(text[], text, date, date, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0042 —")
    assert "ESTADO: NÃO APLICADA EM PRODUÇÃO" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO


@pytest.mark.parametrize("tabela", TABELAS)
def test_cada_tabela_nasce_fechada(tabela):
    assert re.search(rf"alter table public\.{tabela}\s+enable row level security", SQL)
    assert re.search(rf"revoke all on public\.{tabela}\s+from anon, authenticated, public", SQL)
    assert re.search(rf"revoke delete, truncate, references, trigger on public\.{tabela}\s+"
                     r"from service_role", SQL)


def test_leitura_so_dos_resultados_e_so_para_authenticated():
    concessoes = re.findall(r"^\s*grant\s+(.+?);", SQL, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    a_authenticated = [c for c in concessoes if "to authenticated" in c]
    assert sorted(" ".join(c.split()) for c in a_authenticated) == [
        f"execute on function {FUNCAO} to authenticated",
        "select on public.precos_pncp_resultados to authenticated"]
    assert len(re.findall(r"create policy", SQL, re.IGNORECASE)) == 1
    assert "for select to authenticated using (true)" in SQL


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+public\b", r"all\s+functions", r"default\s+privileges",
    r"\bsecurity\s+definer\b", r"disable\s+row\s+level\s+security", r"\btenant_id\b",
    r"grant\s+[^;]*\b(delete|truncate)\b", r"\bdrop\s+table\b",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_busca_roda_como_quem_chama_com_search_path_vazio():
    corpo = SQL[SQL.index("create or replace function public.precos_pncp_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0042 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0042_precos_pncp_indice.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
CONTROLE = "05832977000199-1-000024/2025"
USUARIO = claims("u-a", papel="usuario")
BUSCA = ("select id_externo, valor_unitario from public.precos_pncp_buscar("
         "%s::text[], %s, %s::date, %s::date, %s)")


@pytest.fixture(scope="module")
def cenario(banco):
    from psycopg.types.json import Jsonb

    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        c.execute("insert into public.precos_pncp_contratacoes (numero_controle, uf, estado) "
                  "values (%s, 'PA', 'coletada') on conflict do nothing", (CONTROLE,))
        for n, (descricao, valor, uf, data) in enumerate((
                ("cimento cp 2 f", "39.0", "PA", "2025-05-08"),
                ("cimento cp 3", "41.5", "PA", "2026-09-01"),
                ("acucar cristal 1kg", "5.2", "RS", "2026-09-01")), start=1):
            c.execute(
                "insert into public.precos_pncp_resultados (id_externo, numero_controle, "
                "numero_item, descricao, descricao_busca, unidade, quantidade, valor_unitario, "
                "data_resultado, uf, bruto, hash_linha, versao_coletor) "
                "values (%s, %s, %s, %s, %s, 'UN', 10, %s, %s, %s, %s, 'h', 'v') "
                "on conflict (id_externo) do update set valor_unitario = excluded.valor_unitario",
                (f"{CONTROLE}#{n}#1", CONTROLE, n, descricao.upper(), descricao, valor, data,
                 uf, Jsonb({})))
        # cancelado depois da coleta: guardado, fora da busca
        c.execute(
            "insert into public.precos_pncp_resultados (id_externo, numero_controle, "
            "numero_item, descricao, descricao_busca, unidade, quantidade, valor_unitario, "
            "data_resultado, uf, bruto, hash_linha, versao_coletor, vigente, "
            "invalidado_motivo) values (%s, %s, 4, 'CIMENTO CP 4', 'cimento cp 4', 'UN', 10, "
            "40, '2026-10-01', 'PA', %s, 'h', 'v', false, 'revisita') "
            "on conflict (id_externo) do nothing",
            (f"{CONTROLE}#4#1", CONTROLE, Jsonb({})))
        voltar_a_ser_servidor(c)
    banco.commit()
    return {}


def _como(banco, sql, parametros=(), papel="authenticated", jwt=USUARIO):
    """(sqlstate ou None, linhas), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, jwt, papel)
        try:
            c.execute(sql, parametros)
            return None, (c.fetchall() if c.description else [])
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), []


@requer_pg
def test_usuario_busca_por_termos_com_ou_e_relevancia(banco, cenario):
    erro, linhas = _como(banco, BUSCA, (["cimento", "grampeador"], None, None, None, 10))
    assert erro is None
    assert [l[0] for l in linhas] == [f"{CONTROLE}#2#1", f"{CONTROLE}#1#1"]   # mais recente primeiro


@requer_pg
def test_filtros_de_uf_e_janela(banco, cenario):
    assert _como(banco, BUSCA, (["acucar"], "pa", None, None, 10)) == (None, [])
    erro, linhas = _como(banco, BUSCA, (["acucar"], "rs", None, None, 10))
    assert erro is None and len(linhas) == 1
    erro, linhas = _como(banco, BUSCA, (["cimento"], None, "2026-01-01", "2026-12-31", 10))
    assert [l[0] for l in linhas] == [f"{CONTROLE}#2#1"]
    assert _como(banco, BUSCA, ([], None, None, None, 10)) == (None, [])
    assert _como(banco, BUSCA, (["'); drop table x; --"], None, None, None, 10))[0] is None
    erro, linhas = _como(banco, BUSCA, (["cimento"], None, None, None, 1))
    assert erro is None and len(linhas) == 1


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    # 24 termos no máximo: o 25º não alcança a busca (custo da RPC exposta)
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _como(banco, BUSCA, (vinte_e_quatro + ["cimento"], None, None, None, 10)) == (None, [])
    erro, linhas = _como(banco, BUSCA, (vinte_e_quatro[:23] + ["cimento"], None, None, None, 10))
    assert erro is None and len(linhas) == 2
    erro, linhas = _como(banco, BUSCA, (["x" * 5000], None, None, None, 10))
    assert erro is None and linhas == []


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, (["cimento"], None, None, None, 10), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_pncp_contratacoes",
    "select 1 from public.precos_pncp_cursores",
    "insert into public.precos_pncp_cursores (uf, modalidade_id, data_inicial, data_final) "
    "values ('PA', 6, '2026-01-01', '2026-01-02')",
    "update public.precos_pncp_resultados set valor_unitario = 1",
    "delete from public.precos_pncp_resultados",
])
def test_usuario_so_le_os_resultados(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 3 vigentes + a invalidada na revisita: o usuário LÊ a tabela inteira
    assert _como(banco, "select count(*) from public.precos_pncp_resultados") == (None, [(4,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


MUTACOES = [
    ("alter table public.precos_pncp_resultados disable row level security", "rls_desligado"),
    ("grant select on public.precos_pncp_resultados to anon", "anon_alcanca"),
    ("grant select (uf) on public.precos_pncp_contratacoes to anon", "anon_alcanca"),
    ("grant update on public.precos_pncp_resultados to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_pncp_resultados to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_pncp_contratacoes to authenticated",
     "authenticated_le_controle_da_coleta"),
    ("revoke select on public.precos_pncp_resultados from authenticated", "authenticated_sem_leitura"),
    ("grant truncate on public.precos_pncp_cursores to service_role", "service_role_apaga"),
    ("grant delete on public.precos_pncp_resultados to service_role", "service_role_apaga"),
    ("revoke insert on public.precos_pncp_resultados from service_role", "service_role_sem_escrita"),
    ("grant trigger on public.precos_pncp_resultados to service_role", "service_role_gatilho_ou_fk"),
    ("grant references on public.precos_pncp_contratacoes to service_role", "service_role_gatilho_ou_fk"),
    ("create policy p on public.precos_pncp_contratacoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_pncp_resultados_leitura on public.precos_pncp_resultados",
     "politica_fora_do_previsto"),
    (f"alter function {FUNCAO} security definer", "security_definer"),
    (f"alter function {FUNCAO} volatile", "nao_estavel"),
    (f"alter function {FUNCAO} reset search_path", "sem_search_path_vazio"),
    (f"revoke execute on function {FUNCAO} from authenticated", "authenticated_sem_execute"),
    (f"grant execute on function {FUNCAO} to anon", "anon_executa"),
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
