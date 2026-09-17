"""
A 0024, EXECUTADA: a credencial de servidor não esvazia tabela.

O achado que originou a migração é do catálogo — `service_role` tinha
TRUNCATE em 26 das 32 tabelas de `public` em produção. Mas catálogo
limpo é afirmação sobre um `information_schema`, e o que o órgão
precisa é que o COMANDO seja recusado. Por isso as provas aqui vêm em
dois níveis, e o segundo é o que decide:

  1. o catálogo não concede TRUNCATE a papel de rede nenhum;
  2. `set role service_role; truncate governanca_eventos` leva 42501.

E vem um terceiro, que é a razão de a 0024 existir em vez de um
`revoke` avulso: uma tabela CRIADA DEPOIS de tudo nasce sem TRUNCATE.
Foi exatamente aí que a 0021 falhou — ela consertou as quatro tabelas
dela e deixou a fábrica intacta, então a tabela seguinte trouxe o
problema de volta.

A prova que protege o outro lado também está aqui: `service_role`
PRECISA continuar apagando linha em `processos`, `config_orgaos` e
`documentos_referencia`, porque é o que `src/db.py` e `src/rag.py`
fazem. Sem essa prova, a próxima rodada de endurecimento revoga DELETE
junto, e a descoberta acontece em produção.

FRONTEIRA, a mesma de `test_precos_fase3_rls.py`: isto prova o BANCO.
Não prova PostgREST, GoTrue nem `supabase-py`.

Como rodar:

    GOVDOCS_ENSAIO_PG_DSN="postgresql://postgres@/ensaio?host=/tmp/pgens" \\
        python -m pytest tests/test_truncate_service_role.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import voltar_a_ser_servidor  # noqa: E402

requer_pg = pytest.mark.usefixtures("ensaio_sql")

# Os papéis que chegam pela REDE. `postgres` fica de fora de propósito:
# é o dono das tabelas, tem tudo por construção do PostgreSQL, e
# revogar dele seria teatro — ele se reconcede no comando seguinte.
PAPEIS_DE_REDE = ("service_role", "authenticated", "anon", "PUBLIC")

# `42501` é insufficient_privilege. A prova executada exige ESTE código
# e não "alguma exceção": TRUNCATE numa tabela referenciada por chave
# estrangeira falha com `0A000` — recusa por outro motivo, que provaria
# o contrário do que o teste promete. `governanca_eventos` foi escolhida
# por não ter FK apontando para ela (medido em produção), mas a
# asserção no SQLSTATE é o que impede a prova de passar por engano.
PRIVILEGIO_INSUFICIENTE = "42501"

# A trilha de governança: o alvo mais caro e o mais fácil de esvaziar.
# Seu gatilho `evento_ator_confiavel` é `before insert` — um TRUNCATE
# passa por baixo dele e leva a trilha inteira sem disparar nada.
TRILHA = "governanca_eventos"

# Onde o aplicativo REALMENTE apaga, via `service_role`:
#   src/db.py:1385  config_orgaos
#   src/db.py:1402  processos
#   src/rag.py:447  documentos_referencia
ONDE_O_APP_APAGA = ("processos", "config_orgaos", "documentos_referencia")


def _como_service_role(banco, sql):
    """Roda `sql` com a identidade da credencial de servidor."""
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        c.execute("set local role service_role")
        try:
            c.execute(sql)
            return None
        except Exception as erro:  # noqa: BLE001
            return getattr(erro, "sqlstate", None)


# ---------------------------------------------------------------------------
# 0) A prova de que as outras provas não são vazias
# ---------------------------------------------------------------------------
@requer_pg
def test_o_schema_real_esta_de_pe(banco):
    """
    Esta prova existe por causa de como as outras falham.

    "Nenhuma linha concede TRUNCATE" é verdade num banco VAZIO. Se a
    preparação do ensaio parasse de aplicar as migrações — um glob que
    deixa de casar, uma sequência renomeada — todo o resto deste arquivo
    continuaria verde, afirmando contenção sobre um schema inexistente.
    A âncora é a contagem de tabelas, conferida contra a produção
    medida em 17/09/2026.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select count(*) from pg_class k "
                  "join pg_namespace n on n.oid = k.relnamespace "
                  "where n.nspname = 'public' and k.relkind = 'r'")
        quantas = c.fetchone()[0]
        c.execute("select count(*) from pg_class k "
                  "join pg_namespace n on n.oid = k.relnamespace "
                  "where n.nspname = 'public' and k.relkind = 'r' "
                  "and k.relname = any(%s)",
                  ([TRILHA, *ONDE_O_APP_APAGA],))
        nomeadas = c.fetchone()[0]
    assert quantas >= 30, f"o ensaio subiu com {quantas} tabelas em public"
    assert nomeadas == 4, "faltam as tabelas que este arquivo nomeia"


# ---------------------------------------------------------------------------
# 1) O estoque — o catálogo depois de todas as migrações
# ---------------------------------------------------------------------------
@requer_pg
def test_nenhum_papel_de_rede_tem_truncate_em_public(banco):
    """
    A afirmação central da 0024, medida sobre o schema INTEIRO.

    Sem `any(%s)` de tabelas: o ponto é justamente não haver lista. Uma
    tabela nova que escape entra nesta consulta sozinha, sem ninguém
    lembrar de acrescentá-la aqui.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select table_name, grantee "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' "
                  "and privilege_type = 'TRUNCATE' "
                  "and grantee = any(%s) order by 1, 2",
                  (list(PAPEIS_DE_REDE),))
        assert c.fetchall() == []


# ---------------------------------------------------------------------------
# 2) A fábrica — o default que rege as tabelas que ainda não existem
# ---------------------------------------------------------------------------
@requer_pg
def test_o_default_do_schema_nao_fabrica_mais_truncate(banco):
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select a.grantee::regrole::text "
                  "from pg_default_acl d, aclexplode(d.defaclacl) a "
                  "where d.defaclnamespace = 'public'::regnamespace "
                  "and d.defaclobjtype = 'r' "
                  "and a.privilege_type = 'TRUNCATE' "
                  "and a.grantee::regrole::text = any(%s)",
                  (list(PAPEIS_DE_REDE),))
        assert c.fetchall() == []


@requer_pg
def test_uma_tabela_criada_depois_nasce_sem_truncate(banco):
    """
    A prova com mais dente do arquivo — e a que a 0021 não tinha.

    Revogar nas tabelas existentes é o fácil. O que falhou da outra vez
    foi o depois: `alter default privileges ... grant all on tables`
    continuava de pé, e a primeira tabela criada em seguida trouxe o
    TRUNCATE de volta calada. Aqui a tabela é criada DENTRO da prova,
    com o schema já migrado, e medida.
    """
    nome = f"ensaio_0024_{uuid.uuid4().hex[:8]}"
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(f"create table public.{nome} (id int primary key)")  # noqa: S608
        try:
            c.execute("select grantee, privilege_type "
                      "from information_schema.role_table_grants "
                      "where table_schema = 'public' and table_name = %s "
                      "and privilege_type = 'TRUNCATE' "
                      "and grantee = any(%s)",
                      (nome, list(PAPEIS_DE_REDE)))
            assert c.fetchall() == []
        finally:
            c.execute(f"drop table public.{nome}")  # noqa: S608


# ---------------------------------------------------------------------------
# 3) O comando, recusado de verdade
# ---------------------------------------------------------------------------
@requer_pg
def test_service_role_nao_esvazia_a_trilha_de_governanca(banco):
    """
    Não é o catálogo que fala aqui — é o PostgreSQL recusando.

    `service_role` é `BYPASSRLS`: ele atravessa POLÍTICA de linha. O
    que o detém é o GRANT de tabela, e é isso que esta prova mede. Se
    algum dia alguém trocar o revoke por uma política, este teste cai —
    corretamente.
    """
    assert (_como_service_role(banco, f"truncate table public.{TRILHA}")
            == PRIVILEGIO_INSUFICIENTE)


@requer_pg
def test_service_role_nao_esvazia_em_cascata_tabelas_novas(banco):
    """
    CASCADE não é porta dos fundos — e a prova precisa DISCRIMINAR.

    A primeira versão deste teste era `truncate public.processos
    cascade`, e passava mesmo com a 0024 inteira removida: o fecho do
    CASCADE toca alguma tabela da 0021, que já negava desde antes. Um
    teste que passa pelo motivo errado é pior que nenhum — ele ocupa a
    vaga do que deveria estar medindo.

    Então o par nasce AQUI, depois de todas as migrações: se o default
    da 0024 não estiver de pé, as duas tabelas nascem com TRUNCATE para
    `service_role` e o comando passa. O único motivo de recusa possível
    é o que esta migração fez.
    """
    marca = uuid.uuid4().hex[:8]
    pai, filho = f"ensaio_pai_{marca}", f"ensaio_filho_{marca}"
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute(f"create table public.{pai} (id int primary key)")  # noqa: S608
        c.execute(f"create table public.{filho} (id int primary key, "  # noqa: S608
                  f"pai int references public.{pai}(id))")
    try:
        assert (_como_service_role(banco, f"truncate table public.{pai} cascade")
                == PRIVILEGIO_INSUFICIENTE)
    finally:
        with banco.cursor() as c:
            voltar_a_ser_servidor(c)
            c.execute(f"drop table public.{filho}, public.{pai}")  # noqa: S608


# ---------------------------------------------------------------------------
# 4) O outro lado: o que a 0024 NÃO pode ter quebrado
# ---------------------------------------------------------------------------
@requer_pg
@pytest.mark.parametrize("tabela", ONDE_O_APP_APAGA)
def test_service_role_continua_apagando_onde_o_app_apaga(banco, tabela):
    """
    Guarda contra o endurecimento que quebra o produto.

    A 0024 revoga TRUNCATE e NADA MAIS. `src/db.py` e `src/rag.py`
    apagam linha nestas três tabelas com a credencial de servidor; se
    uma rodada futura revogar DELETE junto "por simetria", a descoberta
    não pode ser um botão que para de funcionar em produção.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select count(*) "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' and table_name = %s "
                  "and grantee = 'service_role' "
                  "and privilege_type = 'DELETE'", (tabela,))
        assert c.fetchone()[0] == 1, (
            f"a 0024 (ou alguma migração depois dela) tirou o DELETE de "
            f"{tabela}, que o aplicativo usa")


@requer_pg
def test_o_dono_continua_podendo_truncar(banco):
    """
    `postgres` mantém TRUNCATE, e isso é desejado: é ele que roda
    migração e manutenção. Um arquivo que revogasse do dono estaria
    fingindo uma contenção que o PostgreSQL desfaz sozinho — o dono se
    reconcede quando quiser. Melhor a verdade escrita do que a ilusão.
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select count(*) "
                  "from information_schema.role_table_grants "
                  "where table_schema = 'public' "
                  "and grantee = 'postgres' "
                  "and privilege_type = 'TRUNCATE'")
        assert c.fetchone()[0] > 0
