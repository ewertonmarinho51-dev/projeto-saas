"""
A 0041 (destinatário da pesquisa de preços) aplicada de verdade, num PostgreSQL
descartável.

O que ela promete: a secretaria destinatária é do MESMO município da pesquisa
(a chave estrangeira sozinha aceitaria a de outro); secretaria e órgão externo
não convivem; a revisão copia o destinatário; nenhum privilégio novo. E a
conferência morde quando uma dessas garantias some.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import uuid

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

MIGRACAO = (pathlib.Path(__file__).resolve().parent.parent
            / "supabase" / "migrations" / "0041_pesquisa_destinatario.sql")
TEXTO = MIGRACAO.read_text(encoding="utf-8")
SQL = "\n".join(linha for linha in TEXTO.splitlines() if not linha.strip().startswith("--"))

requer_pg = pytest.mark.usefixtures("ensaio_sql")


# ---------------------------------------------------------------------------
# Leitura do arquivo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("proibido", [
    r"\bto\s+anon\b", r"\bto\s+public\b", r"all\s+tables", r"all\s+functions",
    r"default\s+privileges", r"disable\s+row\s+level\s+security", r"using\s*\(\s*true\s*\)",
    r"create\s+policy", r"drop\s+table", r"drop\s+column", r"\bcascade\b", r"\btruncate\b",
])
def test_nao_abre_o_que_nao_deve(proibido):
    assert not re.search(proibido, SQL, re.IGNORECASE), proibido


def test_unico_grant_e_o_que_a_0029_ja_dava():
    concessoes = re.findall(r"^\s*grant\b[^;]*;", SQL, re.IGNORECASE | re.MULTILINE)
    assert [" ".join(c.split()) for c in concessoes] == [
        "grant execute on function public.revisar_pesquisa_preco(uuid, text) "
        "to authenticated, service_role;"]


def test_termina_com_conferencia_que_falha_sozinha():
    assert "A 0041 não cumpriu o que afirma" in SQL
    assert SQL.rstrip().endswith("$$;")


def test_recarrega_o_esquema_do_postgrest():
    assert "notify pgrst, 'reload schema'" in SQL


def test_cabecalho_diz_que_nao_foi_aplicada():
    assert "NÃO aplicada em produção" in TEXTO.splitlines()[1]


def test_esta_na_sequencia_do_ensaio_depois_da_0029_e_antes_da_0027():
    from ensaio_local import SEQUENCIA_EM_ENSAIO

    nome = "0041_pesquisa_destinatario.sql"
    assert SEQUENCIA_EM_ENSAIO.index(nome) > SEQUENCIA_EM_ENSAIO.index("0029_cotacoes_unificadas.sql")
    assert SEQUENCIA_EM_ENSAIO[-1] == "0027_service_role_sem_delete_na_trilha.sql"


def test_revisao_da_0041_e_a_da_0029_mais_o_destinatario():
    """A RPC foi redefinida inteira: nada da 0029 pode ter ficado para trás."""
    def corpo(texto: str) -> str:
        inicio = texto.index("create or replace function public.revisar_pesquisa_preco(")
        fim = texto.index("end $$;", inicio)
        return " ".join(texto[inicio:fim].split())

    anterior = (MIGRACAO.parent / "0029_cotacoes_unificadas.sql").read_text(encoding="utf-8")
    novo = corpo(TEXTO)
    sem_destinatario = (novo.replace(", destinatario_secretaria_id, destinatario_externo", "")
                        .replace(", v_origem.destinatario_secretaria_id, v_origem.destinatario_externo", ""))
    assert sem_destinatario == corpo(anterior)
    assert "v_origem.destinatario_secretaria_id" in novo


# ---------------------------------------------------------------------------
# Banco de verdade
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def cenario(banco):
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO)  # idempotência: reaplicar não muda nada
        for chave in ("a", "b"):
            c.execute("insert into tenants (slug, nome, uf) values (%s, %s, 'PA') returning id",
                      (f"t41-{chave}-{uuid.uuid4().hex[:8]}", chave))
            dados[f"tenant_{chave}"] = str(c.fetchone()[0])
            c.execute("insert into secretarias (tenant_id, nome) values (%s, %s) returning id",
                      (dados[f"tenant_{chave}"], f"Secretaria {chave}"))
            dados[f"sec_{chave}"] = str(c.fetchone()[0])
        metadados = {"papel": "usuario", "tenant_id": dados["tenant_a"],
                     "secretaria_id": dados["sec_a"]}
        c.execute("insert into auth.users (email, raw_app_meta_data) values (%s, %s) returning id",
                  (f"dono41-{uuid.uuid4().hex[:8]}@ensaio.invalid", json.dumps(metadados)))
        dados["dono"] = str(c.fetchone()[0])
        c.execute("insert into pesquisas_preco (tenant_id, secretaria_id, auth_user_id, nome) "
                  "values (%s, %s, %s, 'Cotação 0041') returning id",
                  (dados["tenant_a"], dados["sec_a"], dados["dono"]))
        dados["pesquisa"] = str(c.fetchone()[0])
    banco.commit()
    dados["jwt"] = claims(dados["dono"], "usuario", dados["tenant_a"], dados["sec_a"])
    return dados


def _como_dono(banco, cenario, sql, params=()):
    """(sqlstate ou None, linhas), sempre desfeito."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["jwt"])
        try:
            c.execute(sql, params)
            return None, (c.fetchall() if c.description else c.rowcount)
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", "erro"), None


ATUALIZA = ("update public.pesquisas_preco set destinatario_secretaria_id = %s, "
            "destinatario_externo = %s where id = %s")


@requer_pg
def test_dono_grava_secretaria_do_proprio_municipio(banco, cenario):
    erro, linhas = _como_dono(banco, cenario, ATUALIZA, (cenario["sec_a"], "", cenario["pesquisa"]))
    assert (erro, linhas) == (None, 1)


@requer_pg
def test_dono_grava_outro_orgao(banco, cenario):
    erro, linhas = _como_dono(banco, cenario, ATUALIZA, (None, "Prefeitura X", cenario["pesquisa"]))
    assert (erro, linhas) == (None, 1)


@requer_pg
def test_secretaria_de_outro_municipio_e_recusada(banco, cenario):
    erro, _ = _como_dono(banco, cenario, ATUALIZA, (cenario["sec_b"], "", cenario["pesquisa"]))
    assert erro == "42501"


@requer_pg
def test_recusa_mesmo_para_o_servidor(banco, cenario):
    # O gatilho não é do RLS: quem atravessa o RLS também não grava timbrado alheio.
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        with pytest.raises(Exception) as erro:
            c.execute(ATUALIZA, (cenario["sec_b"], "", cenario["pesquisa"]))
    assert getattr(erro.value, "sqlstate", None) == "42501"


@requer_pg
def test_os_dois_juntos_sao_recusados(banco, cenario):
    erro, _ = _como_dono(banco, cenario, ATUALIZA, (cenario["sec_a"], "Prefeitura X", cenario["pesquisa"]))
    assert erro == "23514"


@requer_pg
def test_nome_longo_demais_e_recusado(banco, cenario):
    erro, _ = _como_dono(banco, cenario, ATUALIZA, (None, "x" * 201, cenario["pesquisa"]))
    assert erro == "23514"


@requer_pg
def test_revisao_copia_o_destinatario(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, cenario["jwt"])
        c.execute(ATUALIZA, (None, "Prefeitura de Ulianópolis", cenario["pesquisa"]))
        c.execute("select public.revisar_pesquisa_preco(%s, 'ensaio 0041')", (cenario["pesquisa"],))
        nova = c.fetchone()[0]
        c.execute("select destinatario_secretaria_id, destinatario_externo, versao "
                  "from public.pesquisas_preco where id = %s", (nova,))
        assert c.fetchone() == (None, "Prefeitura de Ulianópolis", 2)


# Cada ramo da conferência, quebrado de propósito.
MUTACOES = [
    ("alter table public.pesquisas_preco drop constraint pesquisas_preco_destinatario_coerente",
     "sem_check"),
    ("alter table public.pesquisas_preco disable trigger pesquisas_preco_destinatario", "sem_gatilho"),
    ("drop trigger pesquisas_preco_destinatario on public.pesquisas_preco", "sem_gatilho"),
    ("alter function public.trg_pesquisa_preco_destinatario() reset search_path",
     "gatilho_sem_search_path"),
    ("grant execute on function public.trg_pesquisa_preco_destinatario() to anon",
     "anon_executa_gatilho"),
    ("grant execute on function public.revisar_pesquisa_preco(uuid, text) to anon", "anon_revisa"),
    ("revoke execute on function public.revisar_pesquisa_preco(uuid, text) from authenticated",
     "authenticated_nao_revisa"),
    ("revoke update on public.pesquisas_preco from authenticated", "authenticated_nao_grava"),
    ("revoke insert on public.pesquisas_preco from authenticated", "authenticated_nao_grava"),
    ("revoke execute on function public.revisar_pesquisa_preco(uuid, text) from service_role",
     "service_role_nao_revisa"),
    ("alter function public.revisar_pesquisa_preco(uuid, text) reset search_path",
     "revisao_sem_search_path"),
    ("alter function public.revisar_pesquisa_preco(uuid, text) security invoker",
     "revisao_sem_search_path"),
    ("alter function public.trg_pesquisa_preco_destinatario() security invoker",
     "gatilho_nao_confere_municipio"),
    ("create or replace function public.trg_pesquisa_preco_destinatario() returns trigger "
     "language plpgsql security definer set search_path = '' as $f$ begin return new; end $f$",
     "gatilho_nao_confere_municipio"),
    ("drop trigger pesquisas_preco_destinatario on public.pesquisas_preco; "
     "create trigger pesquisas_preco_destinatario after update on public.pesquisas_preco "
     "for each row execute function public.trg_pesquisa_preco_destinatario()", "sem_gatilho"),
    ("drop trigger pesquisas_preco_destinatario on public.pesquisas_preco; "
     "create trigger pesquisas_preco_destinatario before insert on public.pesquisas_preco "
     "for each row execute function public.trg_pesquisa_preco_destinatario()", "sem_gatilho"),
    ("grant select (id) on public.pesquisas_preco to anon", "anon_le_tabela"),
    ("alter table public.pesquisas_preco disable row level security", "rls_desligado"),
    ("alter table public.pesquisas_preco alter column destinatario_externo drop not null",
     "sem_coluna_externo"),
    ("alter table public.pesquisas_preco alter column destinatario_externo drop default",
     "sem_coluna_externo"),
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
def test_a_conferencia_morde_quando_a_revisao_perde_o_destinatario(banco, cenario):
    import psycopg

    corpo_0029 = (MIGRACAO.parent / "0029_cotacoes_unificadas.sql").read_text(encoding="utf-8")
    inicio = corpo_0029.index("create or replace function public.revisar_pesquisa_preco(")
    fim = corpo_0029.index("end $$;", inicio) + len("end $$;")
    with pytest.raises(psycopg.errors.RaiseException, match="revisao_nao_copia"):
        with banco.transaction(force_rollback=True), banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(corpo_0029[inicio:fim])
            c.execute(TEXTO[TEXTO.rindex("do $$"):])


@requer_pg
def test_a_conferencia_passa_no_estado_certo(banco, cenario):
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(TEXTO[TEXTO.rindex("do $$"):])
