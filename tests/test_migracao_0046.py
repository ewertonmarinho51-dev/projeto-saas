"""
A 0046 (índice do SINAPI) aplicada de verdade, num PostgreSQL descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só as linhas
VIGENTES dos registros; as versões são do servidor; `anon` não alcança nada;
só a credencial de servidor escreve, e nem ela apaga; preço em branco ou zero
não é gravado; sem competência pedida vale a mais recente vigente da UF; com
código a busca é só pelo código; uma versão vigente por competência e UF. E a
conferência morde quando uma dessas garantias some.
"""

from __future__ import annotations

import pathlib
import re
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0046_precos_sinapi_indice.sql")
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


def test_o_que_nao_e_preco_nao_tem_lugar_na_tabela():
    assert "valor numeric(22, 6) not null check (valor > 0)" in SQL
    assert ("url_arquivo text not null check (url_arquivo like "
            "'https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/%')") in SQL


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0046 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0046_precos_sinapi_indice.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
RAIZ = "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
URL = RAIZ + "SINAPI-2026-10-formato-xlsx.zip"
URL_09 = RAIZ + "SINAPI-2026-09-formato-xlsx.zip"
BUSCA = ("select registro_id, valor from public.precos_sinapi_buscar("
         "%s::text[], %s, %s, %s, %s, %s, %s)")
INSERIR = (
    "insert into public.precos_sinapi_registros (registro_id, chave_linha, competencia, uf, "
    "arquivo_sha256, vigente, tipo, regime, codigo, descricao, descricao_busca, unidade, "
    "valor, aba, linha_planilha, url_arquivo, hash_linha, versao_parser) "
    "values (%s, %s, %s, 'PA', %s, %s, %s, 'sem_desoneracao', %s, %s, %s, 'KG', %s, %s, "
    "%s, %s, 'h', 'v') on conflict (registro_id) do nothing")
LINHAS = (
    ("s-1", "2026-10", SHA_A, True, "insumo", "1379",
     "cimento portland composto cp ii-32", "1.08", "ISD", 1169, URL),
    ("s-2", "2026-10", SHA_A, True, "insumo", "13284",
     "cimento portland de alto forno cp iii-40", "0.97", "ISD", 1170, URL),
    ("s-3", "2026-10", SHA_A, True, "composicao", "104658",
     "piso podotatil de alerta de concreto", "189.32", "CSD", 11, URL),
    # a retificação em importação: gravada, ainda invisível
    ("s-4", "2026-10", SHA_B, False, "insumo", "1379",
     "cimento portland composto cp ii-32", "1.12", "ISD", 1169, URL),
    # competência anterior, vigente para ela
    ("s-5", "2026-09", SHA_C, True, "insumo", "1379",
     "cimento portland composto cp ii-32", "1.05", "ISD", 1169, URL_09),
)


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for comp, sha, estado, vigente, url in (
                ("2026-10", SHA_A, "publicado", True, URL),
                ("2026-10", SHA_B, "importando", False, URL),
                ("2026-09", SHA_C, "publicado", True, URL_09)):
            c.execute("insert into public.precos_sinapi_versoes (competencia, uf, sha256, "
                      "estado, vigente, url) values (%s, 'PA', %s, %s, %s, %s) "
                      "on conflict do nothing", (comp, sha, estado, vigente, url))
        for ident, comp, sha, vigente, tipo, codigo, descricao, valor, aba, linha, url in LINHAS:
            c.execute(INSERIR, (ident, f"{comp}:PA:{tipo}:sem_desoneracao:{codigo}", comp, sha,
                                vigente, tipo, codigo, descricao.upper(), descricao, valor,
                                aba, linha, url))
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


def _busca(termos, codigo=None, uf="PA", competencia=None, tipo=None, regime=None, limite=10):
    return (termos, codigo, uf, competencia, tipo, regime, limite)


@requer_pg
def test_sem_competencia_vale_a_mais_recente_vigente(banco, cenario):
    # s-4 é da versão em importação; s-5 é de 09/2026
    assert sorted(_ids(_como(banco, BUSCA, _busca(["cimento"])))) == ["s-1", "s-2"]
    assert _ids(_como(banco, BUSCA, _busca(["cimento"], uf="pa", competencia="2026-09"))) \
        == ["s-5"]
    assert _ids(_como(banco, BUSCA, _busca(["cimento"], uf="SP"))) == []


@requer_pg
def test_filtros_de_tipo_regime_e_codigo(banco, cenario):
    assert _ids(_como(banco, BUSCA, _busca(["piso", "cimento"], tipo="composicao"))) == ["s-3"]
    assert _ids(_como(banco, BUSCA, _busca(["cimento"], regime="com_desoneracao"))) == []
    # com código, só o código: os termos casariam com os dois cimentos
    assert _ids(_como(banco, BUSCA, _busca(["cimento"], codigo="13284"))) == ["s-2"]
    assert _ids(_como(banco, BUSCA, _busca([], codigo="1379"))) == ["s-1"]
    assert _ids(_como(banco, BUSCA, _busca([]))) == []
    assert _ids(_como(banco, BUSCA, _busca(["'); drop table x; --"]))) == []
    assert len(_ids(_como(banco, BUSCA, _busca(["cimento"], limite=1)))) == 1


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, _busca(vinte_e_quatro + ["cimento"]))) == []
    assert len(_ids(_como(banco, BUSCA, _busca(vinte_e_quatro[:23] + ["cimento"])))) == 2


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, _busca(["cimento"]), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_sinapi_versoes",
    "insert into public.precos_sinapi_versoes (competencia, uf, sha256, url) "
    f"values ('2026-08', 'PA', '{'d' * 64}', '{URL}')",
    "update public.precos_sinapi_registros set vigente = true",
    "update public.precos_sinapi_registros set valor = 1",
    "delete from public.precos_sinapi_registros",
])
def test_usuario_so_le_os_registros_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 4 vigentes; a linha da versão em importação existe e o usuário não a vê
    assert _como(banco, "select count(*) from public.precos_sinapi_registros") == (None, [(4,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_publica_a_retificacao(banco, cenario):
    filtro = "competencia = '2026-10' and uf = 'PA'"
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `sinapi_servico.ArmazemSupabase.publicar`
        c.execute(f"update public.precos_sinapi_registros set vigente = true "
                  f"where {filtro} and arquivo_sha256 = %s", (SHA_B,))
        c.execute(f"update public.precos_sinapi_registros set vigente = false "
                  f"where {filtro} and arquivo_sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_sinapi_versoes set vigente = false "
                  f"where {filtro} and sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_sinapi_versoes set vigente = true, "
                  f"estado = 'publicado' where {filtro} and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, _busca(["cimento"]))
        assert [(l[0], str(l[1])) for l in c.fetchall()] == [("s-4", "1.120000")]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas versões vigentes na mesma competência e UF
    (f"update public.precos_sinapi_versoes set vigente = true, estado = 'publicado' "
     f"where sha256 = '{SHA_B}'", "23505"),
    # vigente sem estar publicada
    (f"update public.precos_sinapi_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    # registro de versão que não existe
    ("update public.precos_sinapi_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 's-1'", "23503"),
    # preço zero, código que não é número, aba que não existe
    ("update public.precos_sinapi_registros set valor = 0 where registro_id = 's-1'", "23514"),
    ("update public.precos_sinapi_registros set codigo = 'A1' where registro_id = 's-1'", "23514"),
    ("update public.precos_sinapi_registros set aba = 'XYZ' where registro_id = 's-1'", "23514"),
    # arquivo de fora dos relatórios mensais da CAIXA
    ("update public.precos_sinapi_registros set url_arquivo = 'https://exemplo.com/x.zip' "
     "where registro_id = 's-1'", "23514"),
    (f"update public.precos_sinapi_versoes set competencia = '2026-13' "
     f"where sha256 = '{SHA_C}'", "23514"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_sinapi_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_sinapi_registros to anon", "anon_alcanca"),
    ("grant select (uf) on public.precos_sinapi_versoes to anon", "anon_alcanca"),
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
    ("create role zz_outro; grant select (uf) on public.precos_sinapi_versoes to zz_outro",
     "grant_a_papel_inesperado"),
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
