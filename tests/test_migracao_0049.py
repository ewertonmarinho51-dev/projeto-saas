"""
A 0049 (referência de custos SICRO) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só as linhas
VIGENTES; as versões são do servidor; `anon` não alcança nada; só a
credencial de servidor escreve, e nem ela apaga; valor > 0; código na forma
do tipo e regime amarrado ao tipo; endereço só da árvore do SICRO; com
código a busca é só pelo código; material aparece em qualquer regime; sem
competência, a mais recente da UF; uma versão vigente por (competência, UF).
E a conferência morde quando uma dessas garantias some.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0049_precos_sicro_referencia.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_sicro_versoes", "precos_sicro_registros")
FUNCAO = "public.precos_sicro_buscar(text[], text, text, text, text, text, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0049 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 25/11/2026" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO
    assert "CATEGORIA PRÓPRIA" in TEXTO and "referencia_custos_sicro" in TEXTO


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
        "select on public.precos_sicro_registros to authenticated"]
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
    corpo = SQL[SQL.index("create or replace function public.precos_sicro_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0049 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0049_precos_sicro_referencia.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C, SHA_D = "a" * 64, "b" * 64, "c" * 64, "d" * 64
BASE = ("https://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/"
        "sistemas-de-custos/sicro/relatorios/relatorios-sicro/norte/")
URL_07 = BASE + "para/2026/julho/pa-07-2026.7z"
URL_07R = BASE + "para/2026/julho/pa-07-2026-revisado.7z"
URL_04 = BASE + "para/2026/abril/pa-04-2026.7z"
URL_AP = BASE + "amapa/2026/julho/ap-07-2026.7z"
BUSCA = ("select registro_id, valor from public.precos_sicro_buscar("
         "%s::text[], %s, %s, %s, %s, %s, %s)")
INSERIR = (
    "insert into public.precos_sicro_registros (registro_id, chave_linha, competencia, uf, "
    "arquivo_sha256, vigente, tipo, regime, codigo, descricao, descricao_busca, unidade, valor, "
    "valor_improdutivo, planilha, linha_planilha, url_arquivo, arquivo, hash_linha, versao_parser) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'un', %s, %s, "
    "'PA 07-2026 Relatório Sintético de Materiais.xlsx', 2, %s, %s, 'h', 'v') "
    "on conflict (registro_id) do nothing")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for competencia, uf, sha, estado, vigente, url in (
                ("2026-07", "PA", SHA_A, "publicado", True, URL_07),
                ("2026-07", "PA", SHA_B, "importando", False, URL_07R),
                ("2026-04", "PA", SHA_C, "publicado", True, URL_04),
                ("2026-07", "AP", SHA_D, "publicado", True, URL_AP)):
            c.execute("insert into public.precos_sicro_versoes (competencia, uf, sha256, estado, "
                      "vigente, arquivo, url) values (%s, %s, %s, %s, %s, %s, %s) "
                      "on conflict do nothing",
                      (competencia, uf, sha, estado, vigente, url.rsplit("/", 1)[-1], url))
        for ident, comp, uf, sha, vig, tipo, regime, codigo, descricao, valor, ocioso, url in (
                ("s-1", "2026-07", "PA", SHA_A, True, "composicao", "sem_desoneracao", "1106050",
                 "lancamento de concreto usinado", "65.12", None, URL_07),
                ("s-2", "2026-07", "PA", SHA_A, True, "material", "nao_se_aplica", "M0004",
                 "aco ca 50", "6.5605", None, URL_07),
                ("s-3", "2026-07", "PA", SHA_A, True, "mao_de_obra", "sem_desoneracao", "P9801",
                 "ajudante", "24.8197", None, URL_07),
                ("s-4", "2026-07", "PA", SHA_A, True, "mao_de_obra", "com_desoneracao", "P9801",
                 "ajudante", "23.6691", None, URL_07),
                ("s-5", "2026-07", "PA", SHA_A, True, "equipamento", "sem_desoneracao", "E9009",
                 "embarcacao rebocadora", "489.8398", "149.9339", URL_07),
                # versão em importação: gravada, ainda invisível
                ("s-6", "2026-07", "PA", SHA_B, False, "material", "nao_se_aplica", "M0004",
                 "aco ca 50", "7.5", None, URL_07R),
                # trimestre anterior e outra UF
                ("s-7", "2026-04", "PA", SHA_C, True, "material", "nao_se_aplica", "M0004",
                 "aco ca 50", "6.40", None, URL_04),
                ("s-8", "2026-07", "AP", SHA_D, True, "material", "nao_se_aplica", "M0004",
                 "aco ca 50", "6.90", None, URL_AP)):
            c.execute(INSERIR, (ident, f"{comp}:{uf}:{tipo}:{regime}:{codigo}:{ident}", comp, uf,
                                sha, vig, tipo, regime, codigo, descricao.upper(), descricao,
                                valor, ocioso, url, url.rsplit("/", 1)[-1]))
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
def test_busca_por_termos_na_competencia_mais_recente_da_uf_e_so_vigente(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["aco"], uf="pa"))) == ["s-2"]
    assert _ids(_como(banco, BUSCA, _b(["aco"], uf="PA", competencia="2026-04"))) == ["s-7"]
    assert _ids(_como(banco, BUSCA, _b(["aco"], uf="AP"))) == ["s-8"]
    assert _ids(_como(banco, BUSCA, _b([], uf="PA"))) == []
    assert _ids(_como(banco, BUSCA, _b(["'); drop table x; --"], uf="PA"))) == []


@requer_pg
def test_regime_filtra_mas_material_aparece_nos_dois(banco, cenario):
    sem = _ids(_como(banco, BUSCA, _b(["ajudante", "aco", "concreto"], uf="PA",
                                      regime="sem_desoneracao")))
    com = _ids(_como(banco, BUSCA, _b(["ajudante", "aco", "concreto"], uf="PA",
                                      regime="com_desoneracao")))
    assert sem == ["s-1", "s-2", "s-3"] and com == ["s-2", "s-4"]
    assert _ids(_como(banco, BUSCA, _b(["ajudante", "aco"], uf="PA", tipo="material"))) == ["s-2"]


@requer_pg
def test_com_codigo_a_busca_e_so_pelo_codigo(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["ajudante"], codigo="e9009", uf="PA"))) == ["s-5"]
    assert _ids(_como(banco, BUSCA, _b(["aco"], codigo="", uf="PA"))) == ["s-2"]


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro + ["ajudante"], uf="PA",
                                       regime="sem_desoneracao"))) == []
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro[:23] + ["ajudante"], uf="PA",
                                       regime="sem_desoneracao"))) == ["s-3"]


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, _b(["aco"]), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_sicro_versoes",
    "insert into public.precos_sicro_versoes (competencia, uf, sha256, arquivo, url) "
    f"values ('2026-01', 'PA', '{'e' * 64}', 'pa-01-2026.7z', '{BASE}x.7z')",
    "update public.precos_sicro_registros set vigente = true",
    "update public.precos_sicro_registros set valor = 1",
    "delete from public.precos_sicro_registros",
])
def test_usuario_so_le_os_registros_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 7 vigentes; a linha da versão em importação existe e o usuário não a vê
    assert _como(banco, "select count(*) from public.precos_sicro_registros") == (None, [(7,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_importa_e_publica_a_versao(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `sicro_servico.ArmazemSupabase.publicar`
        filtro = "competencia = '2026-07' and uf = 'PA'"
        c.execute(f"update public.precos_sicro_registros set vigente = true "
                  f"where {filtro} and arquivo_sha256 = %s", (SHA_B,))
        c.execute(f"update public.precos_sicro_registros set vigente = false "
                  f"where {filtro} and arquivo_sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_sicro_versoes set vigente = false "
                  f"where {filtro} and sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_sicro_versoes set vigente = true, estado = 'publicado' "
                  f"where {filtro} and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, _b(["aco"], uf="PA"))
        assert [l[0] for l in c.fetchall()] == ["s-6"]
        c.execute(BUSCA, _b(["aco"], uf="AP"))
        assert [l[0] for l in c.fetchall()] == ["s-8"]          # a outra UF não muda


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas versões vigentes na mesma (competência, UF)
    (f"update public.precos_sicro_versoes set vigente = true, estado = 'publicado' "
     f"where sha256 = '{SHA_B}'", "23505"),
    (f"update public.precos_sicro_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    # endereço fora da árvore oficial, ou com volta de pasta
    (f"update public.precos_sicro_versoes set url = 'https://exemplo.com/pa-07-2026.7z' "
     f"where sha256 = '{SHA_A}'", "23514"),
    (f"update public.precos_sicro_registros set url_arquivo = '{BASE}../../x.7z' "
     "where registro_id = 's-1'", "23514"),
    (f"update public.precos_sicro_registros set url_arquivo = '{BASE}%%2e%%2e/x.7z' "
     "where registro_id = 's-1'", "23514"),
    (f"update public.precos_sicro_versoes set url = '{BASE}%%2E%%2E/pa-07-2026.7z' "
     f"where sha256 = '{SHA_A}'", "23514"),
    ("update public.precos_sicro_versoes set arquivo = 'x.zip' "
     f"where sha256 = '{SHA_A}'", "23514"),
    # registro de versão que não existe
    ("update public.precos_sicro_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 's-1'", "23503"),
    # custo zerado; código fora da forma do tipo; regime fora do que o DNIT publica
    ("update public.precos_sicro_registros set valor = 0 where registro_id = 's-1'", "23514"),
    ("update public.precos_sicro_registros set codigo = 'M0004' where registro_id = 's-1'",
     "23514"),
    ("update public.precos_sicro_registros set regime = 'com_desoneracao' "
     "where registro_id = 's-1'", "23514"),
    ("update public.precos_sicro_registros set regime = 'sem_desoneracao' "
     "where registro_id = 's-2'", "23514"),
    ("update public.precos_sicro_registros set regime = 'nao_se_aplica' "
     "where registro_id = 's-3'", "23514"),
    ("update public.precos_sicro_registros set valor_improdutivo = 1 where registro_id = 's-2'",
     "23514"),
    ("update public.precos_sicro_registros set planilha = 'x.xlsx' where registro_id = 's-2'",
     "23514"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_sicro_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_sicro_registros to anon", "anon_alcanca"),
    ("grant select (competencia) on public.precos_sicro_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_sicro_registros to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_sicro_registros to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_sicro_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_sicro_registros from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_sicro_versoes to service_role", "service_role_apaga"),
    ("grant delete on public.precos_sicro_registros to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_sicro_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("grant references (codigo) on public.precos_sicro_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("create role zz_outro; grant select on public.precos_sicro_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("create role zz_outro; grant select (competencia) on public.precos_sicro_versoes "
     "to zz_outro", "grant_a_papel_inesperado"),
    ("grant select (codigo) on public.precos_sicro_registros to public",
     "grant_a_papel_inesperado"),
    ("create function public.zz_gatilho() returns trigger language plpgsql "
     "as 'begin return new; end'; create trigger zz before insert on "
     "public.precos_sicro_registros for each row execute function public.zz_gatilho()",
     "gatilho"),
    ("revoke insert on public.precos_sicro_registros from service_role",
     "service_role_sem_escrita"),
    ("create policy p on public.precos_sicro_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_sicro_registros_leitura on public.precos_sicro_registros",
     "politica_fora_do_previsto"),
    ("alter policy precos_sicro_registros_leitura on public.precos_sicro_registros "
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
