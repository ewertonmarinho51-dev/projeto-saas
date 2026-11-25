"""
A 0048 (remuneração da Tabela Unificada do SUS, SIGTAP) aplicada de verdade,
num PostgreSQL descartável.

O que ela promete: dado público sem tenant; `authenticated` lê só os
procedimentos VIGENTES; as versões são do servidor; `anon` não alcança nada;
só a credencial de servidor escreve, e nem ela apaga; valor maior ou igual a
zero (zero é dado da tabela); código de 10 dígitos; arquivo com o nome
oficial; com código a busca é só pelo código; sem competência, a mais
recente; filtro por modalidade; uma versão vigente por competência. E a
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
            / "supabase" / "migrations" / "0048_precos_sigtap_referencia.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))
TABELAS = ("precos_sigtap_versoes", "precos_sigtap_procedimentos")
FUNCAO = "public.precos_sigtap_buscar(text[], text, text, text, integer)"

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
def test_cabecalho_diz_o_estado():
    assert TEXTO.startswith("-- ## 0048 —")
    assert "ESTADO: NÃO APLICADA EM PRODUÇÃO" in TEXTO
    assert "O QUE ESTA MIGRAÇÃO NÃO RESOLVE" in TEXTO
    assert "CATEGORIA PRÓPRIA" in TEXTO
    assert "referencia_sus_sigtap" in TEXTO


@pytest.mark.parametrize("tabela", TABELAS)
def test_cada_tabela_nasce_fechada(tabela):
    assert re.search(rf"alter table public\.{tabela}\s+enable row level security", SQL)
    assert re.search(rf"revoke all on public\.{tabela}\s+from anon, authenticated, public", SQL)
    assert re.search(rf"revoke delete, truncate, references, trigger on public\.{tabela}\s+"
                     r"from service_role", SQL)


def test_leitura_so_dos_procedimentos_vigentes_e_so_para_authenticated():
    concessoes = re.findall(r"^\s*grant\s+(.+?);", SQL, re.IGNORECASE | re.MULTILINE | re.DOTALL)
    a_authenticated = [" ".join(c.split()) for c in concessoes if "to authenticated" in c]
    assert sorted(a_authenticated) == [
        f"execute on function {FUNCAO} to authenticated",
        "select on public.precos_sigtap_procedimentos to authenticated"]
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
    corpo = SQL[SQL.index("create or replace function public.precos_sigtap_buscar"):]
    cabecalho = corpo[:corpo.index("as $$")]
    assert "security invoker" in cabecalho and "set search_path = ''" in cabecalho
    assert "stable" in cabecalho
    assert "least(greatest(coalesce(p_limite, 50), 1), 200)" in corpo
    assert "where n <= 24" in corpo and "left(t, 60)" in corpo
    assert "r.vigente" in corpo


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0048 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")
    assert "notify pgrst, 'reload schema'" in SQL


def test_esta_na_sequencia_do_ensaio_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    assert "0048_precos_sigtap_referencia.sql" in SEQUENCIA_EM_ENSAIO
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
USUARIO = claims("u-a", papel="usuario")
SHA_A, SHA_B, SHA_C = "a" * 64, "b" * 64, "c" * 64
ARQ_11 = "TabelaUnificada_202611_v2611051737.zip"
ARQ_11B = "TabelaUnificada_202611_v2611201200.zip"
ARQ_10 = "TabelaUnificada_202610_v2610061200.zip"
BUSCA = ("select registro_id, valor_sh from public.precos_sigtap_buscar("
         "%s::text[], %s, %s, %s, %s)")
INSERIR = (
    "insert into public.precos_sigtap_procedimentos (registro_id, chave_linha, competencia, "
    "arquivo_sha256, vigente, codigo, nome, nome_busca, valor_sa, valor_sh, valor_sp, "
    "modalidades, linha_arquivo, arquivo, hash_linha, versao_parser) "
    "values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, 'h', 'v') "
    "on conflict (registro_id) do nothing")


@pytest.fixture(scope="module")
def cenario(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for competencia, sha, estado, vigente, arquivo in (
                ("2026-11", SHA_A, "publicado", True, ARQ_11),
                ("2026-11", SHA_B, "importando", False, ARQ_11B),
                ("2026-10", SHA_C, "publicado", True, ARQ_10)):
            c.execute("insert into public.precos_sigtap_versoes (competencia, sha256, estado, "
                      "vigente, arquivo, versao_arquivo) values (%s, %s, %s, %s, %s, %s) "
                      "on conflict do nothing",
                      (competencia, sha, estado, vigente, arquivo, arquivo[-14:-4]))
        for ident, comp, sha, vigente, codigo, nome, sa, sh, sp, modalidades in (
                ("p-1", "2026-11", SHA_A, True, "0411010034", "operacao cesariana",
                 "0", "395.68", "150.05", ["Hospitalar"]),
                ("p-2", "2026-11", SHA_A, True, "0202010473", "dosagem de glicose",
                 "1.85", "0", "0", ["Ambulatorial", "Hospital Dia", "Hospitalar"]),
                ("p-3", "2026-11", SHA_A, True, "0301010072",
                 "consulta medica em atencao especializada", "10", "0", "0", ["Ambulatorial"]),
                ("p-4", "2026-11", SHA_A, True, "0101010010",
                 "atividade educativa orientacao em grupo", "0", "0", "0", ["Ambulatorial"]),
                # versão em importação: gravada, ainda invisível
                ("p-5", "2026-11", SHA_B, False, "0411010035", "operacao cesariana com laqueadura",
                 "0", "500", "200", ["Hospitalar"]),
                # competência anterior
                ("p-6", "2026-10", SHA_C, True, "0411010034", "operacao cesariana",
                 "0", "390.00", "150.05", ["Hospitalar"])):
            c.execute(INSERIR, (ident, f"{comp}:{codigo}", comp, sha, vigente, codigo,
                                nome.upper(), nome, sa, sh, sp, modalidades,
                                ARQ_11 if sha == SHA_A else ARQ_11B if sha == SHA_B else ARQ_10))
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


def _b(termos, codigo=None, competencia=None, modalidade=None, limite=10):
    return (termos, codigo, competencia, modalidade, limite)


@requer_pg
def test_busca_por_termos_na_competencia_mais_recente_e_so_vigente(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["cesariana", "grampeador"]))) == ["p-1"]
    assert _ids(_como(banco, BUSCA, _b(["cesariana"], competencia="2026-10"))) == ["p-6"]
    assert _ids(_como(banco, BUSCA, _b(["glicose", "consulta"]))) == ["p-2", "p-3"]
    assert _ids(_como(banco, BUSCA, _b([]))) == []
    assert _ids(_como(banco, BUSCA, _b(["'); drop table x; --"]))) == []
    assert len(_ids(_como(banco, BUSCA, _b(["glicose", "consulta"], limite=1)))) == 1


@requer_pg
def test_filtra_por_modalidade(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["glicose", "consulta"], modalidade="Hospitalar"))) \
        == ["p-2"]
    assert _ids(_como(banco, BUSCA, _b(["consulta"], modalidade="Hospitalar"))) == []
    assert _ids(_como(banco, BUSCA, _b(["consulta"], modalidade=""))) == ["p-3"]


@requer_pg
def test_com_codigo_a_busca_e_so_pelo_codigo(banco, cenario):
    assert _ids(_como(banco, BUSCA, _b(["glicose"], codigo="0411010034"))) == ["p-1"]
    assert _ids(_como(banco, BUSCA, _b([], codigo="0411010035"))) == []   # invisível
    assert _ids(_como(banco, BUSCA, _b(["glicose"], codigo=""))) == ["p-2"]
    # valor zero é dado da tabela e aparece
    assert _ids(_como(banco, BUSCA, _b([], codigo="0101010010"))) == ["p-4"]


@requer_pg
def test_busca_tem_teto_de_termos(banco, cenario):
    vinte_e_quatro = [f"inexistente{n}" for n in range(24)]
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro + ["glicose"]))) == []
    assert _ids(_como(banco, BUSCA, _b(vinte_e_quatro[:23] + ["glicose"]))) == ["p-2"]


@requer_pg
def test_anon_nao_le_nem_executa(banco, cenario):
    assert _como(banco, BUSCA, _b(["cesariana"]), papel="anon", jwt="{}")[0] == "42501"
    for tabela in TABELAS:
        assert _como(banco, f"select 1 from public.{tabela}", papel="anon", jwt="{}")[0] == "42501"


@requer_pg
@pytest.mark.parametrize("sql", [
    "select 1 from public.precos_sigtap_versoes",
    "insert into public.precos_sigtap_versoes (competencia, sha256, arquivo, versao_arquivo) "
    f"values ('2026-08', '{'d' * 64}', 'TabelaUnificada_202608_v2608010000.zip', '2608010000')",
    "update public.precos_sigtap_procedimentos set vigente = true",
    "update public.precos_sigtap_procedimentos set valor_sh = 1",
    "delete from public.precos_sigtap_procedimentos",
])
def test_usuario_so_le_os_procedimentos_vigentes(banco, cenario, sql):
    assert _como(banco, sql)[0] == "42501"
    # 5 vigentes; o da versão em importação existe e o usuário não o vê
    assert _como(banco, "select count(*) from public.precos_sigtap_procedimentos") == (None, [(5,)])


@requer_pg
@pytest.mark.parametrize("sql", [f"delete from public.{t}" for t in TABELAS]
                         + [f"truncate public.{t} cascade" for t in TABELAS])
def test_nem_a_credencial_de_servidor_apaga(banco, cenario, sql):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == "42501"


@requer_pg
def test_servidor_importa_e_publica_a_versao(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, "{}", "service_role")
        # os mesmos quatro passos de `sigtap_servico.ArmazemSupabase.publicar`
        c.execute("update public.precos_sigtap_procedimentos set vigente = true "
                  "where competencia = '2026-11' and arquivo_sha256 = %s", (SHA_B,))
        c.execute("update public.precos_sigtap_procedimentos set vigente = false "
                  "where competencia = '2026-11' and arquivo_sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_sigtap_versoes set vigente = false "
                  "where competencia = '2026-11' and sha256 <> %s", (SHA_B,))
        c.execute("update public.precos_sigtap_versoes set vigente = true, estado = 'publicado' "
                  "where competencia = '2026-11' and sha256 = %s", (SHA_B,))
        como(c, USUARIO)
        c.execute(BUSCA, _b(["cesariana"]))
        assert [l[0] for l in c.fetchall()] == ["p-5"]


@requer_pg
@pytest.mark.parametrize("sql, sqlstate", [
    # duas versões vigentes na mesma competência
    (f"update public.precos_sigtap_versoes set vigente = true, estado = 'publicado' "
     f"where sha256 = '{SHA_B}'", "23505"),
    # vigente sem estar publicada
    (f"update public.precos_sigtap_versoes set vigente = true where sha256 = '{SHA_B}'", "23514"),
    # arquivo fora do nome oficial
    (f"update public.precos_sigtap_versoes set arquivo = 'x.zip' where sha256 = '{SHA_A}'",
     "23514"),
    ("update public.precos_sigtap_procedimentos set arquivo = '../x.zip' "
     "where registro_id = 'p-1'", "23514"),
    # procedimento de versão que não existe
    ("update public.precos_sigtap_procedimentos set arquivo_sha256 = repeat('f', 64) "
     "where registro_id = 'p-1'", "23503"),
    # valor negativo, código fora dos 10 dígitos, linha zero
    ("update public.precos_sigtap_procedimentos set valor_sp = -1 where registro_id = 'p-1'",
     "23514"),
    ("update public.precos_sigtap_procedimentos set codigo = '041101003' "
     "where registro_id = 'p-1'", "23514"),
    ("update public.precos_sigtap_procedimentos set linha_arquivo = 0 "
     "where registro_id = 'p-1'", "23514"),
    # a mesma linha duas vezes no mesmo arquivo
    ("update public.precos_sigtap_procedimentos set chave_linha = '2026-11:0202010473' "
     "where registro_id = 'p-1'", "23505"),
])
def test_o_banco_recusa_o_que_o_importador_nao_pode_gravar(banco, cenario, sql, sqlstate):
    assert _como(banco, sql, papel="service_role", jwt="{}")[0] == sqlstate


MUTACOES = [
    ("alter table public.precos_sigtap_procedimentos disable row level security",
     "rls_desligado"),
    ("grant select on public.precos_sigtap_procedimentos to anon", "anon_alcanca"),
    ("grant select (competencia) on public.precos_sigtap_versoes to anon", "anon_alcanca"),
    ("grant update on public.precos_sigtap_procedimentos to authenticated",
     "authenticated_escreve"),
    ("grant delete on public.precos_sigtap_procedimentos to authenticated",
     "authenticated_apaga"),
    ("grant select on public.precos_sigtap_versoes to authenticated",
     "authenticated_le_controle_da_importacao"),
    ("revoke select on public.precos_sigtap_procedimentos from authenticated",
     "authenticated_sem_leitura"),
    ("grant truncate on public.precos_sigtap_versoes to service_role", "service_role_apaga"),
    ("grant delete on public.precos_sigtap_procedimentos to service_role", "service_role_apaga"),
    ("grant trigger on public.precos_sigtap_procedimentos to service_role",
     "service_role_gatilho_ou_fk"),
    ("grant references (codigo) on public.precos_sigtap_procedimentos to service_role",
     "service_role_gatilho_ou_fk"),
    ("create role zz_outro; grant select on public.precos_sigtap_versoes to zz_outro",
     "grant_a_papel_inesperado"),
    ("create role zz_outro; grant select (competencia) on public.precos_sigtap_versoes "
     "to zz_outro", "grant_a_papel_inesperado"),
    ("grant select (codigo) on public.precos_sigtap_procedimentos to public",
     "grant_a_papel_inesperado"),
    ("create function public.zz_gatilho() returns trigger language plpgsql "
     "as 'begin return new; end'; create trigger zz before insert on "
     "public.precos_sigtap_procedimentos for each row execute function public.zz_gatilho()",
     "gatilho"),
    ("revoke insert on public.precos_sigtap_procedimentos from service_role",
     "service_role_sem_escrita"),
    ("create policy p on public.precos_sigtap_versoes for select to authenticated using (true)",
     "politica_fora_do_previsto"),
    ("drop policy precos_sigtap_procedimentos_leitura on public.precos_sigtap_procedimentos",
     "politica_fora_do_previsto"),
    ("alter policy precos_sigtap_procedimentos_leitura on public.precos_sigtap_procedimentos "
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
