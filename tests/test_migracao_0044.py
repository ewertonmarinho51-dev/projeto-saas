"""
A 0044 (índice do BPS) aplicada de verdade, num PostgreSQL descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só as linhas
VIGENTES dos registros; as versões são do servidor; `anon` não alcança nada;
só a credencial de servidor escreve, e nem ela apaga; com CATMAT a busca é
só pelo código; uma versão vigente por ano. E a conferência morde quando
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
            / "supabase" / "migrations" / "0044_precos_bps_indice.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_bps_versoes", "precos_bps_registros")
FUNCAO = "public.precos_bps_buscar(text[], text, text, date, date, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0044 —")
    assert "ESTADO: NÃO APLICADA EM PRODUÇÃO" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO


@pytest.mark.parametrize("tabela", TABELAS)
def test_cada_tabela_nasce_fechada(tabela):
    assert re.search(rf"alter table public\.{tabela}\s+enable row level security", SQL)
    assert re.search(rf"revoke all on public\.{tabela}\s+from anon, authenticated, public", SQL)
    assert re.search(rf"revoke delete, truncate, references, trigger on public\.{tabela}\s+"
                     r"from service_role", SQL)


def test_leitura_so_dos_registros_vigentes_e_so_para_authenticated():
    concessoes = re.findall(r"^\s*grant\s+(.+?);", SQL, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    a_authenticated = [" ".join(c.split()) for c in concessoes if "to authenticated" in c]
    assert sorted(a_authenticated) == [
        f"execute on function {FUNCAO} to authenticated",
        "select on public.precos_bps_registros to authenticated"]
    assert len(re.findall(r"create policy", SQL, re.IGNORECASE)) == 1
    assert "for select to authenticated using (vigente)" in SQL


@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+public\b", r"all\s+functions", r"default\s+privileges",
    r"\bsecurity\s+definer\b", r"disable\s+row\s+level\s+security", r"\btenant_id\b",
    r"grant\s+[^;]*\b(delete|truncate|references|trigger)\b", r"\bdrop\s+table\b",
    r"using\s*\(\s*true\s*\)",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_busca_roda_como_quem_chama_com_search_path_vazio_e_teto():
    corpo = SQL[SQL.index("create or replace function public.precos_bps_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0044 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0044_precos_bps_indice.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B = "a" * 64, "b" * 64
URL = "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/BPS/csv/2026_csv.zip"
API = "https://apidadosabertos.saude.gov.br/economia-da-saude/bps?codigoCatmat="
BUSCA = ("select registro_id, valor_unitario from public.precos_bps_buscar("
         "%s::text[], %s, %s, %s::date, %s::date, %s)")
INSERIR = (
    "insert into public.precos_bps_registros (registro_id, co_seq_bps, ano, arquivo_sha256, "
    "vigente, catmat, descricao, descricao_busca, unidade, quantidade, valor_unitario, "
    "data_compra, uf, esfera, url_evidencia, url_arquivo, hash_linha, versao_parser) "
    "values (%s, %s, 2026, %s, %s, %s, %s, %s, 'COMPRIMIDO', 100, %s, %s, %s, 'MUNICIPAL', "
    "%s, %s, 'h', 'v') on conflict (registro_id) do nothing")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for sha, estado, vigente in ((SHA_A, "publicado", True), (SHA_B, "importando", False)):
            c.execute("insert into public.precos_bps_versoes (ano, sha256, estado, vigente, url) "
                      "values (2026, %s, %s, %s, %s) on conflict do nothing",
                      (sha, estado, vigente, URL))
        for ident, sha, vigente, catmat, descricao, valor, data, uf in (
                ("bps-1", SHA_A, True, "267502", "dipirona sodica dosagem 500 mg", "0.18",
                 "2026-09-23", "PB"),
                ("bps-2", SHA_A, True, "267502", "dipirona sodica dosagem 500 mg", "0.11",
                 "2026-07-30", "MG"),
                ("bps-3", SHA_A, True, "267077", "bezafibrato dosagem 200 mg", "1.04",
                 "2026-05-05", "RS"),
                # versão em importação: gravada, ainda invisível
                ("bps-4", SHA_B, False, "267502", "dipirona sodica dosagem 500 mg", "0.09",
                 "2026-10-01", "PA")):
            c.execute(INSERIR, (ident, ident[4:], sha, vigente, catmat, descricao.upper(),
                                descricao, valor, data, uf, API + catmat, URL))
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


def _ids(resposta):
    erro, linhas = resposta
    assert erro is None, erro
    return [l[0] for l in linhas]


@requer_pg
def test_busca_por_termos_so_do_que_esta_vigente(banco, cenario):
    achados = _ids(_como(banco, BUSCA, (["dipirona", "grampeador"], None, None, None, None, 10)))
    assert achados == ["bps-1", "bps-2"]                 # mais recente primeiro; bps-4 invisível
    assert _ids(_como(banco, BUSCA, (["bezafibrato"], None, "rs", None, None, 10))) == ["bps-3"]
    assert _ids(_como(banco, BUSCA, (["bezafibrato"], None, "pa", None, None, 10))) == []
    assert _ids(_como(banco, BUSCA, (["dipirona"], None, None, "2026-08-01", "2026-12-31",
                                     10))) == ["bps-1"]
    assert _ids(_como(banco, BUSCA, ([], None, None, None, None, 10))) == []
    assert _ids(_como(banco, BUSCA, (["'); drop table x; --"], None, None, None, None, 10))) == []
    assert len(_ids(_como(banco, BUSCA, (["dipirona"], None, None, None, None, 1)))) == 1


@requer_pg
def test_com_catmat_a_busca_e_so_pelo_codigo(banco, cenario):
    # os termos casariam com a dipirona; o código manda
    assert _ids(_como(banco, BUSCA, (["dipirona"], "267077", None, None, None, 10))) == ["bps-3"]
    assert _ids(_como(banco, BUSCA, ([], "267502", None, None, None, 10))) == ["bps-1", "bps-2"]
    assert _ids(_como(banco, BUSCA, (["dipirona"], "999999", None, None, None, 10))) == []
    # código vazio é "sem código": volta aos termos
    assert _ids(_como(banco, BUSCA, (["bezafibrato"], "", None, None, None, 10))) == ["bps-3"]


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, (vinte_e_quatro + ["dipirona"], None, None, None, None,
                                     10))) == []
    assert len(_ids(_como(banco, BUSCA, (vinte_e_quatro[:23] + ["dipirona"], None, None, None,
                                         None, 10)))) == 2


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, (["dipirona"], None, None, None, None, 10), papel="anon",
                 jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_bps_versoes",
    "insert into public.precos_bps_versoes (ano, sha256, url) "
    f"values (2025, '{'c' * 64}', 'https://exemplo.gov.br/x.zip')",
    "update public.precos_bps_registros set vigente = true",
    "update public.precos_bps_registros set valor_unitario = 1",
    "delete from public.precos_bps_registros",
])
def test_usuario_so_le_os_registros_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 3 vigentes; a linha da versão em importação existe e o usuário não a vê
    assert _como(banco, "select count(*) from public.precos_bps_registros") == (None, [(3,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_importa_e_publica_a_versao(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `bps_servico.ArmazemSupabase.publicar`
        c.execute("update public.precos_bps_registros set vigente = true "
                  "where ano = 2026 and arquivo_sha256 = %s", (SHA_B,))
        c.execute("update public.precos_bps_registros set vigente = false "
                  "where ano = 2026 and arquivo_sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_bps_versoes set vigente = false "
                  "where ano = 2026 and sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_bps_versoes set vigente = true, estado = 'publicado' "
                  "where ano = 2026 and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, (["dipirona"], None, None, None, None, 10))
        assert [l[0] for l in c.fetchall()] == ["bps-4"]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas versões vigentes no mesmo ano
    (f"update public.precos_bps_versoes set vigente = true, estado = 'publicado' "
     f"where sha256 = '{SHA_B}'", "23505"),
    # vigente sem estar publicada
    (f"update public.precos_bps_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    # registro de versão que não existe
    ("update public.precos_bps_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 'bps-1'", "23503"),
    # esfera que não é pública
    ("update public.precos_bps_registros set esfera = 'PRIVADA' where registro_id = 'bps-1'",
     "23514"),
    ("update public.precos_bps_registros set valor_unitario = 0 where registro_id = 'bps-1'",
     "23514"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_bps_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_bps_registros to anon", "anon_alcanca"),
    ("grant select (ano) on public.precos_bps_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_bps_registros to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_bps_registros to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_bps_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_bps_registros from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_bps_versoes to service_role", "service_role_apaga"),
    ("grant delete on public.precos_bps_registros to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_bps_registros to service_role", "service_role_gatilho_ou_fk"),
    ("revoke insert on public.precos_bps_registros from service_role", "service_role_sem_escrita"),
    ("create policy p on public.precos_bps_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_bps_registros_leitura on public.precos_bps_registros",
     "politica_fora_do_previsto"),
    ("alter policy precos_bps_registros_leitura on public.precos_bps_registros using (true)",
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
