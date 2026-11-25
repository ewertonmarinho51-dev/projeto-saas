"""
A 0046 (referência de custos SINAPI) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só as linhas
VIGENTES dos registros; as versões são do servidor; `anon` não alcança nada;
só a credencial de servidor escreve, e nem ela apaga; valor sempre maior que
zero; com código a busca é só pelo código; sem competência, a mais recente;
uma versão vigente por competência. E a conferência morde quando uma dessas
garantias some.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0046_precos_sinapi_referencia.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_sinapi_versoes", "precos_sinapi_registros")
FUNCAO = "public.precos_sinapi_buscar(text[], text, text, text, text, text, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0046 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 23/11/2026" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO
    assert "CATEGORIA PRÓPRIA" in TEXTO


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
        "select on public.precos_sinapi_registros to authenticated"]
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
    corpo = SQL[SQL.index("create or replace function public.precos_sinapi_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0046 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0046_precos_sinapi_referencia.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
BASE = "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
URL_10 = BASE + "SINAPI-2026-10-formato-xlsx.zip"
URL_09 = BASE + "SINAPI-2026-09-formato-xlsx.zip"
BUSCA = ("select registro_id, valor from public.precos_sinapi_buscar("
         "%s::text[], %s, %s, %s, %s, %s, %s)")
INSERIR = (
    "insert into public.precos_sinapi_registros (registro_id, competencia, arquivo_sha256, "
    "vigente, tipo, regime, codigo, descricao, descricao_busca, unidade, uf, valor, aba, "
    "linha_planilha, url_arquivo, hash_linha, versao_parser) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'KG', %s, %s, %s, 11, %s, 'h', 'v') "
    "on conflict (registro_id) do nothing")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for competencia, sha, estado, vigente, url in (
                ("2026-10", SHA_A, "publicado", True, URL_10),
                ("2026-10", SHA_B, "importando", False, URL_10),
                ("2026-09", SHA_C, "publicado", True, URL_09)):
            c.execute("insert into public.precos_sinapi_versoes (competencia, sha256, estado, "
                      "vigente, url) values (%s, %s, %s, %s, %s) on conflict do nothing",
                      (competencia, sha, estado, vigente, url))
        for ident, comp, sha, vigente, tipo, regime, codigo, descricao, uf, valor, aba in (
                ("s-1", "2026-10", SHA_A, True, "insumo", "sem_desoneracao", "1379",
                 "cimento portland composto cp ii-32", "PA", "1.08", "ISD"),
                ("s-2", "2026-10", SHA_A, True, "insumo", "com_desoneracao", "1379",
                 "cimento portland composto cp ii-32", "PA", "1.08", "ICD"),
                ("s-3", "2026-10", SHA_A, True, "composicao", "sem_desoneracao", "104658",
                 "piso podotatil de alerta de concreto", "PA", "189.32", "CSD"),
                ("s-4", "2026-10", SHA_A, True, "insumo", "sem_desoneracao", "1379",
                 "cimento portland composto cp ii-32", "SP", "0.95", "ISD"),
                # versão em importação: gravada, ainda invisível
                ("s-5", "2026-10", SHA_B, False, "insumo", "sem_desoneracao", "1380",
                 "cimento portland cp iii", "PA", "1.10", "ISD"),
                # competência anterior
                ("s-6", "2026-09", SHA_C, True, "insumo", "sem_desoneracao", "1379",
                 "cimento portland composto cp ii-32", "PA", "1.05", "ISD")):
            c.execute(INSERIR, (ident, comp, sha, vigente, tipo, regime, codigo,
                                descricao.upper(), descricao, uf, valor, aba,
                                URL_10 if comp == "2026-10" else URL_09))
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


def _b(termos, codigo=None, uf=None, competencia=None, regime=None, tipo=None, limite=10):
    return (termos, codigo, uf, competencia, regime, tipo, limite)


@requer_pg
def test_busca_por_termos_na_competencia_mais_recente_e_so_vigente(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["cimento", "grampeador"], uf="pa"))) == ["s-1", "s-2"]
    assert _ids(_como(banco, BUSCA, _b(["cimento"], uf="PA", regime="sem_desoneracao"))) \
        == ["s-1"]
    assert _ids(_como(banco, BUSCA, _b(["cimento"], uf="PA", competencia="2026-09"))) \
        == ["s-6"]
    assert _ids(_como(banco, BUSCA, _b(["piso"], uf="PA", tipo="composicao"))) == ["s-3"]
    assert _ids(_como(banco, BUSCA, _b(["piso"], uf="PA", tipo="insumo"))) == []
    assert _ids(_como(banco, BUSCA, _b([], uf="PA"))) == []
    assert _ids(_como(banco, BUSCA, _b(["'); drop table x; --"]))) == []
    assert len(_ids(_como(banco, BUSCA, _b(["cimento"], uf="PA", limite=1)))) == 1


@requer_pg
def test_com_codigo_a_busca_e_so_pelo_codigo(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["piso"], codigo="1379", uf="PA",
                                       regime="sem_desoneracao"))) == ["s-1"]
    assert _ids(_como(banco, BUSCA, _b([], codigo="1380", uf="PA"))) == []   # invisível
    assert _ids(_como(banco, BUSCA, _b(["cimento"], codigo="", uf="SP"))) == ["s-4"]


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro + ["piso"], uf="PA"))) == []
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro[:23] + ["piso"], uf="PA"))) == ["s-3"]


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, _b(["cimento"]), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_sinapi_versoes",
    "insert into public.precos_sinapi_versoes (competencia, sha256, url) "
    f"values ('2026-08', '{'d' * 64}', '{BASE}x.zip')",
    "update public.precos_sinapi_registros set vigente = true",
    "update public.precos_sinapi_registros set valor = 1",
    "delete from public.precos_sinapi_registros",
])
def test_usuario_so_le_os_registros_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 5 vigentes; a linha da versão em importação existe e o usuário não a vê
    assert _como(banco, "select count(*) from public.precos_sinapi_registros") == (None, [(5,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_importa_e_publica_a_versao(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `sinapi_servico.ArmazemSupabase.publicar`
        c.execute("update public.precos_sinapi_registros set vigente = true "
                  "where competencia = '2026-10' and arquivo_sha256 = %s", (SHA_B,))
        c.execute("update public.precos_sinapi_registros set vigente = false "
                  "where competencia = '2026-10' and arquivo_sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_sinapi_versoes set vigente = false "
                  "where competencia = '2026-10' and sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_sinapi_versoes set vigente = true, estado = 'publicado' "
                  "where competencia = '2026-10' and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, _b(["cimento"], uf="PA"))
        assert [l[0] for l in c.fetchall()] == ["s-5"]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas versões vigentes na mesma competência
    (f"update public.precos_sinapi_versoes set vigente = true, estado = 'publicado' "
     f"where sha256 = '{SHA_B}'", "23505"),
    # vigente sem estar publicada
    (f"update public.precos_sinapi_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    # endereço fora da pasta oficial
    (f"update public.precos_sinapi_versoes set url = 'https://exemplo.com/x.zip' "
     f"where sha256 = '{SHA_A}'", "23514"),
    # registro de versão que não existe
    ("update public.precos_sinapi_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 's-1'", "23503"),
    # custo zerado, tipo e regime fora da lista, código com letra
    ("update public.precos_sinapi_registros set valor = 0 where registro_id = 's-1'", "23514"),
    ("update public.precos_sinapi_registros set tipo = 'servico' where registro_id = 's-1'",
     "23514"),
    ("update public.precos_sinapi_registros set regime = 'outro' where registro_id = 's-1'",
     "23514"),
    ("update public.precos_sinapi_registros set codigo = '1379a' where registro_id = 's-1'",
     "23514"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_sinapi_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_sinapi_registros to anon", "anon_alcanca"),
    ("grant select (competencia) on public.precos_sinapi_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_sinapi_registros to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_sinapi_registros to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_sinapi_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_sinapi_registros from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_sinapi_versoes to service_role", "service_role_apaga"),
    ("grant delete on public.precos_sinapi_registros to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_sinapi_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("grant references (codigo) on public.precos_sinapi_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("create role zz_outro; grant select on public.precos_sinapi_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("create role zz_outro; grant select (competencia) on public.precos_sinapi_versoes "
     "to zz_outro", "grant_a_papel_inesperado"),
    ("grant select (codigo) on public.precos_sinapi_registros to public",
     "grant_a_papel_inesperado"),
    ("create function public.zz_gatilho() returns trigger language plpgsql "
     "as 'begin return new; end'; create trigger zz before insert on "
     "public.precos_sinapi_registros for each row execute function public.zz_gatilho()",
     "gatilho"),
    ("revoke insert on public.precos_sinapi_registros from service_role",
     "service_role_sem_escrita"),
    ("create policy p on public.precos_sinapi_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_sinapi_registros_leitura on public.precos_sinapi_registros",
     "politica_fora_do_previsto"),
    ("alter policy precos_sinapi_registros_leitura on public.precos_sinapi_registros "
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
