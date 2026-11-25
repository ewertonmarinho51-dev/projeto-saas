"""
A 0047 (referência de custos da SEOP-PA) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só os registros
VIGENTES; as versões são do servidor; `anon` não alcança nada; só o servidor
escreve, e nem ele apaga; valor zero não é gravado; versão publicada sem quem
aprovou é recusada pelo próprio banco; sem competência pedida vale a mais
recente; com código, só o código. E a conferência morde quando uma dessas
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
            / "supabase" / "migrations" / "0047_precos_seop_referencia.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_seop_versoes", "precos_seop_registros")
FUNCAO = "public.precos_seop_buscar(text[], text, text, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0047 —")
    assert "ESTADO: APLICADA EM PRODUÇÃO em 25/11/2026" in TEXTO
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
        "select on public.precos_seop_registros to authenticated"]
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
    corpo = SQL[SQL.index("create or replace function public.precos_seop_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_publicacao_exige_quem_aprovou():
    assert "constraint precos_seop_versoes_publicacao_aprovada" in SQL
    assert "check (estado <> 'publicado' or (length(trim(coalesce(aprovado_por, ''))) >= 3" in SQL
    assert "valor numeric(22, 6) not null check (valor > 0)" in SQL


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0047 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0047_precos_seop_referencia.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO.index("0047_precos_seop_referencia.sql") > \
        SEQUENCIA_EM_ENSAIO.index("0046_precos_sinapi_referencia.sql")
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
RAIZ = "https://seop.pa.gov.br/sites/default/files/"
URL = RAIZ + "plainha_padrao_outubro_2026.pdf"
URL_09 = RAIZ + "planilha_padrao_seop_setembro_2026.pdf"
BUSCA = "select registro_id, valor from public.precos_seop_buscar(%s::text[], %s, %s, %s)"
INSERIR = (
    "insert into public.precos_seop_registros (registro_id, chave_linha, competencia, "
    "arquivo_sha256, vigente, item, codigo, descricao, descricao_busca, unidade, valor, "
    "pagina, url_arquivo, hash_linha, versao_parser) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'm²', %s, %s, %s, 'h', 'v') "
    "on conflict (registro_id) do nothing")
LINHAS = (
    ("s-1", "2026-10", SHA_A, True, "1.3", "010006", "andaime de madeira", "31.89", 1, URL),
    ("s-2", "2026-10", SHA_A, True, "1.1", "011450",
     "aluguel de andaime metalico tipo fachadeiro", "30.28", 1, URL),
    ("s-3", "2026-10", SHA_A, True, "8.4", "060046", "alvenaria tijolo de barro a cutelo",
     "141.99", 7, URL),
    # republicação em conferência: gravada, invisível
    ("s-4", "2026-10", SHA_B, False, "1.3", "010006", "andaime de madeira", "32.00", 1, URL),
    # competência anterior, vigente para ela
    ("s-5", "2026-09", SHA_C, True, "1.3", "010006", "andaime de madeira", "31.50", 1, URL_09),
)


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for comp, sha, estado, vigente, url, por in (
                ("2026-10", SHA_A, "publicado", True, URL, "Ana Souza"),
                ("2026-10", SHA_B, "em_conferencia", False, URL, None),
                ("2026-09", SHA_C, "publicado", True, URL_09, "Ana Souza")):
            c.execute("insert into public.precos_seop_versoes (competencia, sha256, estado, "
                      "vigente, url, aprovado_por, aprovado_em) values (%s, %s, %s, %s, %s, %s, "
                      "case when %s::text is null then null else now() end) on conflict do nothing",
                      (comp, sha, estado, vigente, url, por, por))
        for ident, comp, sha, vigente, item, codigo, descricao, valor, pagina, url in LINHAS:
            c.execute(INSERIR, (ident, f"{comp}:{codigo}", comp, sha, vigente, item, codigo,
                                descricao.upper(), descricao, valor, pagina, url))
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
def test_sem_competencia_vale_a_mais_recente_vigente(banco, cenario):
    # s-4 está em conferência; s-5 é de 09/2026
    assert sorted(_ids(_como(banco, BUSCA, (["andaime"], None, None, 10))))  == ["s-1", "s-2"]
    assert _ids(_como(banco, BUSCA, (["andaime"], None, "2026-09", 10))) == ["s-5"]


@requer_pg
def test_codigo_termos_e_teto(banco, cenario):
    assert _ids(_como(banco, BUSCA, (["andaime"], "060046", None, 10))) == ["s-3"]
    assert _ids(_como(banco, BUSCA, ([], "010006", None, 10))) == ["s-1"]
    assert _ids(_como(banco, BUSCA, ([], None, None, 10))) == []
    assert _ids(_como(banco, BUSCA, (["'); drop table x; --"], None, None, 10))) == []
    assert len(_ids(_como(banco, BUSCA, (["andaime"], None, None, 1)))) == 1
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, (vinte_e_quatro + ["andaime"], None, None, 10))) == []


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, (["andaime"], None, None, 10), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_seop_versoes",
    f"update public.precos_seop_versoes set aprovado_por = 'eu' where sha256 = '{SHA_B}'",
    "update public.precos_seop_registros set vigente = true",
    "update public.precos_seop_registros set valor = 1",
    "delete from public.precos_seop_registros",
])
def test_usuario_so_le_os_registros_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    assert _como(banco, "select count(*) from public.precos_seop_registros") == (None, [(4,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_publica_a_versao_aprovada(banco, cenario):
    filtro = "competencia = '2026-10'"
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `seop_servico.ArmazemSupabase.publicar`
        c.execute(f"update public.precos_seop_registros set vigente = true "
                  f"where {filtro} and arquivo_sha256 = %s", (SHA_B,))
        c.execute(f"update public.precos_seop_registros set vigente = false "
                  f"where {filtro} and arquivo_sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_seop_versoes set vigente = false "
                  f"where {filtro} and sha256 <> %s", (SHA_B,))
        c.execute(f"update public.precos_seop_versoes set vigente = true, estado = 'publicado', "
                  f"aprovado_por = 'Ana Souza', aprovado_em = now() "
                  f"where {filtro} and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, ([], "010006", None, 10))
        assert [(l[0], str(l[1])) for l in c.fetchall()] == [("s-4", "32.000000")]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # publicar sem quem aprovou
    (f"update public.precos_seop_versoes set estado = 'publicado' where sha256 = '{SHA_B}'",
     "23514"),
    (f"update public.precos_seop_versoes set estado = 'publicado', aprovado_por = '  ', "
     f"aprovado_em = now() where sha256 = '{SHA_B}'", "23514"),
    # duas vigentes na mesma competência
    (f"update public.precos_seop_versoes set vigente = true, estado = 'publicado', "
     f"aprovado_por = 'Ana Souza', aprovado_em = now() where sha256 = '{SHA_B}'", "23505"),
    # vigente sem estar publicada
    (f"update public.precos_seop_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    ("update public.precos_seop_registros set valor = 0 where registro_id = 's-1'", "23514"),
    ("update public.precos_seop_registros set codigo = '10006' where registro_id = 's-1'", "23514"),
    ("update public.precos_seop_registros set url_arquivo = 'https://exemplo.com/x.pdf' "
     "where registro_id = 's-1'", "23514"),
    ("update public.precos_seop_registros set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 's-1'", "23503"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_seop_registros disable row level security", "rls_desligado"),
    ("grant select on public.precos_seop_registros to anon", "anon_alcanca"),
    ("grant select (competencia) on public.precos_seop_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_seop_registros to authenticated", "authenticated_escreve"),
    ("grant delete on public.precos_seop_registros to authenticated", "authenticated_apaga"),
    ("grant select on public.precos_seop_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_seop_registros from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_seop_versoes to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_seop_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("grant references (codigo) on public.precos_seop_registros to service_role",
     "service_role_gatilho_ou_fk"),
    ("create role zz_outro; grant select on public.precos_seop_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("create function public.zz_gatilho() returns trigger language plpgsql "
     "as 'begin return new; end'; create trigger zz before insert on "
     "public.precos_seop_registros for each row execute function public.zz_gatilho()",
     "gatilho"),
    ("revoke insert on public.precos_seop_registros from service_role",
     "service_role_sem_escrita"),
    ("create policy p on public.precos_seop_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("alter policy precos_seop_registros_leitura on public.precos_seop_registros using (true)",
     "politica_fora_do_previsto"),
    ("alter table public.precos_seop_versoes drop constraint "
     "precos_seop_versoes_publicacao_aprovada", "publicacao_sem_aprovacao"),
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
