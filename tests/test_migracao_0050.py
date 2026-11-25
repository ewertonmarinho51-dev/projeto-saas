"""
A 0050 (teto CMED de medicamentos) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só a lista
VIGENTE; as versões são do servidor; `anon` não alcança nada; só a
credencial de servidor escreve, e nem ela apaga; GGREM de 15 dígitos; PF e
PMVG com as 26 colunas; endereço só da pasta de listas da CMED; uma lista
vigente no total; busca por GGREM, registro, EAN ou termos. E a conferência
morde quando uma dessas garantias some.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0050_precos_cmed_teto.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_cmed_versoes", "precos_cmed_registros")
FUNCAO = "public.precos_cmed_buscar(text[], text, integer)"
ALIQUOTAS = ("sem_impostos", "0", "12", "12_alc", "17", "17_alc", "17.5", "17.5_alc",
             "18", "18_alc", "19", "19_alc", "19.5", "19.5_alc", "20", "20_alc",
             "20.5", "20.5_alc", "21", "21_alc", "22", "22_alc", "22.5", "22.5_alc",
             "23", "23_alc")

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0050 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 25/11/2026" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO and "RETENÇÃO" in TEXTO
    assert "CATEGORIA PRÓPRIA" in TEXTO and "referencia_teto_cmed" in TEXTO


def test_as_26_aliquotas_do_check_sao_as_do_leitor():
    from src.precos import cmed

    assert cmed.ALIQUOTAS == ALIQUOTAS
    for lista in re.findall(r"\?& array\[(.*?)\]", SQL, re.DOTALL):
        assert tuple(re.findall(r"'([^']+)'", lista)) == ALIQUOTAS


@pytest.mark.parametrize("tabela", TABELAS)
def test_cada_tabela_nasce_fechada(tabela):
    assert re.search(rf"alter table public\.{tabela}\s+enable row level security", SQL)
    assert re.search(rf"revoke all on public\.{tabela}\s+from anon, authenticated, public", SQL)
    assert re.search(rf"revoke delete, truncate, references, trigger on public\.{tabela}\s+"
                     r"from service_role", SQL)


def test_leitura_so_da_lista_vigente_e_so_para_authenticated():
    concessoes = re.findall(r"^\s*grant\s+(.+?);", SQL, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    a_authenticated = [" ".join(c.split()) for c in concessoes if "to authenticated" in c]
    assert sorted(a_authenticated) == [
        f"execute on function {FUNCAO} to authenticated",
        "select on public.precos_cmed_registros to authenticated"]
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
    corpo = SQL[SQL.index("create or replace function public.precos_cmed_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0050 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0050_precos_cmed_teto.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
PASTA = "https://www.gov.br/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/"
LISTA = {SHA_A: "lista_pmvg_20261109_111901662.xlsx",
         SHA_B: "lista_pmvg_20261120_120000000.xlsx",
         SHA_C: "lista_pmvg_20261009_120000000.xlsx"}
VALORES = json.dumps({k: "10.00" for k in ALIQUOTAS})
BUSCA = "select registro_id from public.precos_cmed_buscar(%s::text[], %s, %s)"
COLUNAS = ("registro_id, chave_linha, publicada_em, arquivo_sha256, vigente, ggrem, registro, "
           "eans, substancia, laboratorio, produto, apresentacao, pf, pmvg, "
           "restricao_hospitalar, cap, confaz87, icms_0, comercializado, linha_planilha, "
           "descricao_busca, url_arquivo, arquivo, hash_linha, versao_parser")
INSERIR = (f"insert into public.precos_cmed_registros ({COLUNAS}) values "
           "(%s, %s, '2026-11-09T17:30:00-03:00', %s, %s, %s, %s, %s, %s, 'LAB', %s, 'APRES', "
           "%s::jsonb, %s::jsonb, false, %s, false, false, true, 2, %s, %s, %s, 'h', 'v') "
           "on conflict (registro_id) do nothing")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for sha, estado, vigente in ((SHA_A, "publicado", True), (SHA_B, "importando", False),
                                     (SHA_C, "publicado", False)):
            c.execute("insert into public.precos_cmed_versoes (sha256, estado, vigente, "
                      "publicada_em, arquivo, url) values (%s, %s, %s, now(), %s, %s) "
                      "on conflict do nothing",
                      (sha, estado, vigente, LISTA[sha], PASTA + LISTA[sha] + "/@@download/file"))
        for ident, sha, vig, ggrem, registro, eans, substancia, produto, cap in (
                ("c-1", SHA_A, True, "538912020009303", "1705600230032", ["7891106000956"],
                 "acetato de dexametasona", "BAYCUTEN N", False),
                ("c-2", SHA_A, True, "505113100020505", "1018003900078",
                 ["7896016808197", "7896016808198"], "abatacepte", "ORENCIA", True),
                ("c-3", SHA_A, True, "503424050027617", None, [], "dipirona sodica",
                 "DIPIRONA SODICA", False),
                # lista em importação e lista antiga: gravadas, invisíveis
                ("c-4", SHA_B, False, "538912020009303", None, [], "acetato de dexametasona",
                 "BAYCUTEN N", False),
                ("c-5", SHA_C, False, "503424050027617", None, [], "dipirona sodica",
                 "DIPIRONA SODICA", False)):
            c.execute(INSERIR, (ident, f"{ident}:{ggrem}", sha, vig, ggrem, registro, eans,
                                substancia, produto, VALORES, VALORES, cap,
                                f"{substancia} {produto.lower()}",
                                PASTA + LISTA[sha] + "/@@download/file", LISTA[sha]))
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
    return sorted(l[0] for l in linhas)


@requer_pg
def test_busca_por_termos_so_da_lista_vigente(banco, cenario):
    assert _ids(_como(banco, BUSCA, (["dipirona"], None, 10))) == ["c-3"]
    assert _ids(_como(banco, BUSCA, (["dexametasona", "abatacepte"], None, 10))) == ["c-1", "c-2"]
    assert _ids(_como(banco, BUSCA, ([], None, 10))) == []
    assert _ids(_como(banco, BUSCA, (["'); drop table x; --"], None, 10))) == []
    assert len(_ids(_como(banco, BUSCA, (["dexametasona", "abatacepte"], None, 1)))) == 1


@requer_pg
@pytest.mark.parametrize("codigo, esperado", [
    ("538912020009303", ["c-1"]), ("1018003900078", ["c-2"]), ("7896016808198", ["c-2"]),
    ("7891106000956", ["c-1"]), ("789110600095", []), ("", ["c-3"]),
])
def test_codigo_e_ggrem_registro_ou_qualquer_ean(banco, cenario, codigo, esperado):
    assert _ids(_como(banco, BUSCA, (["dipirona"], codigo, 10))) == esperado


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, (vinte_e_quatro + ["dipirona"], None, 10))) == []
    assert _ids(_como(banco, BUSCA, (vinte_e_quatro[:23] + ["dipirona"], None, 10))) == ["c-3"]


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, (["dipirona"], None, 10), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_cmed_versoes",
    "insert into public.precos_cmed_versoes (sha256, arquivo, url) values "
    f"('{'d' * 64}', 'lista_pmvg_20261201_000000000.xlsx', '{PASTA}x')",
    "update public.precos_cmed_registros set vigente = true",
    "update public.precos_cmed_registros set cap = true",
    "delete from public.precos_cmed_registros",
])
def test_usuario_so_le_a_lista_vigente(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    assert _como(banco, "select count(*) from public.precos_cmed_registros") == (None, [(3,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_importa_e_publica_a_lista_nova(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `cmed_servico.ArmazemSupabase.publicar`
        c.execute("update public.precos_cmed_registros set vigente = true "
                  "where arquivo_sha256 = %s", (SHA_B,))
        c.execute("update public.precos_cmed_registros set vigente = false "
                  "where vigente and arquivo_sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_cmed_versoes set vigente = false "
                  "where vigente and sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_cmed_versoes set vigente = true, estado = 'publicado' "
                  "where sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, (["dexametasona", "dipirona"], None, 10))
        assert [l[0] for l in c.fetchall()] == ["c-4"]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas listas vigentes
    (f"update public.precos_cmed_versoes set vigente = true where sha256 = '{SHA_C}'", "23505"),
    (f"update public.precos_cmed_versoes set vigente = true, estado = 'importando' "
     f"where sha256 = '{SHA_A}'", "23514"),
    # endereço e nome fora da publicação
    (f"update public.precos_cmed_versoes set url = 'https://exemplo.com/x' "
     f"where sha256 = '{SHA_A}'", "23514"),
    # `%%`: a consulta vai com parâmetros (vazios), e o psycopg lê `%` como marcador
    (f"update public.precos_cmed_registros set url_arquivo = '{PASTA}%%2e%%2e/x' "
     "where registro_id = 'c-1'", "23514"),
    (f"update public.precos_cmed_registros set url_arquivo = '{PASTA}../x' "
     "where registro_id = 'c-1'", "23514"),
    ("update public.precos_cmed_registros set arquivo = 'lista_pmc_20261109_111901662.xlsx' "
     "where registro_id = 'c-1'", "23514"),
    # GGREM, registro e linha fora da forma
    ("update public.precos_cmed_registros set ggrem = '53891202000930' "
     "where registro_id = 'c-1'", "23514"),
    ("update public.precos_cmed_registros set registro = 'ABC' where registro_id = 'c-1'",
     "23514"),
    ("update public.precos_cmed_registros set linha_planilha = 1 where registro_id = 'c-1'",
     "23514"),
    # PF e PMVG sem as 26 colunas
    ("update public.precos_cmed_registros set pf = pf - '19' where registro_id = 'c-1'", "23514"),
    ("update public.precos_cmed_registros set pmvg = '[]'::jsonb where registro_id = 'c-1'",
     "23514"),
    # a mesma apresentação duas vezes na mesma lista; versão que não existe
    ("update public.precos_cmed_registros set ggrem = '505113100020505' "
     "where registro_id = 'c-1'", "23505"),
    ("update public.precos_cmed_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 'c-1'", "23503"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_cmed_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_cmed_registros to anon", "anon_alcanca"),
    ("grant select (sha256) on public.precos_cmed_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_cmed_registros to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_cmed_registros to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_cmed_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_cmed_registros from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_cmed_versoes to service_role", "service_role_apaga"),
    ("grant delete on public.precos_cmed_registros to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_cmed_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("grant references (ggrem) on public.precos_cmed_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("create role zz_outro; grant select on public.precos_cmed_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("create role zz_outro; grant select (sha256) on public.precos_cmed_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("grant select (ggrem) on public.precos_cmed_registros to public",
     "grant_a_papel_inesperado"),
    ("create function public.zz_gatilho() returns trigger language plpgsql "
     "as 'begin return new; end'; create trigger zz before insert on "
     "public.precos_cmed_registros for each row execute function public.zz_gatilho()",
     "gatilho"),
    ("revoke insert on public.precos_cmed_registros from service_role",
     "service_role_sem_escrita"),
    ("create policy p on public.precos_cmed_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_cmed_registros_leitura on public.precos_cmed_registros",
     "politica_fora_do_previsto"),
    ("alter policy precos_cmed_registros_leitura on public.precos_cmed_registros "
     "using (true)", "politica_fora_do_previsto"),
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
