"""
ACHADO P0 (§11/§17): os processos atravessavam prefeituras.

É o mesmo defeito da identidade visual, na TABELA CENTRAL. `processos`
ganhou `tenant_id` na migração 0006 e os acessos em `db.py` nunca
passaram a usá-lo.

O CAMINHO, exatamente como a interface o percorre

`src/ui/processos_ui.py` decide o filtro assim:

    # Administrador vê os processos do município; servidor vê os seus.
    filtro = None if auth.eh_admin() else (usuario or {}).get("id")
    lista = db.listar_processos(usuario_id=filtro)

O comentário diz "do município". O código passa `None`, e
`listar_processos` sem `usuario_id` não filtrava NADA — devolvia os 50
processos mais recentes de TODAS as prefeituras. Objeto, justificativa,
valores, documentos gerados.

E o que a lista entrega são ids. Com um id em mãos:

    carregar_processo(id)   abria o processo alheio;
    renomear_processo(id)   renomeava o processo alheio;
    excluir_processo(id)    APAGAVA o processo alheio;
    salvar_processo(id, …)  sobrescrevia o processo alheio, e a criação
                            não carimbava `tenant_id`, de modo que o
                            processo novo nascia na prefeitura do
                            DEFAULT da coluna.

POR QUE O RLS NÃO COBRIA

O app opera com a credencial de SERVIDOR, e `service_role` tem
BYPASSRLS. As políticas da 0020 protegem contra chave publicável
vazada; contra a consulta do próprio app sem `where`, não há política
que valha. Aqui o `.eq("tenant_id", …)` É a contenção.

SITUAÇÃO EM PRODUÇÃO, medida em 24/09/2026: uma prefeitura, seis
processos, dois usuários, todos no mesmo `tenant_id`. Não houve
exposição real — e `flag_multi_prefeituras` está LIGADA, então a
segunda prefeitura cadastrada encontraria a porta aberta.

As provas rodam contra o PostgREST de verdade, com duas prefeituras
semeadas: é a camada onde o defeito vive, e um dublê de cliente provaria
apenas que a consulta carrega o filtro.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("GOVDOCS_DSN_HOMOLOGACAO"),
    reason="exige a pilha de homologação de pé: rode por "
           "`scripts/homologacao_stack.py --executar`",
)

TENANT_A = "11111111-1111-1111-1111-111111111111"
TENANT_B = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def dois_municipios():
    import psycopg

    dsn = os.environ["GOVDOCS_DSN_HOMOLOGACAO"]
    marca = uuid.uuid4().hex[:8]
    ids = {}
    with psycopg.connect(dsn, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "insert into public.tenants (id, nome, slug) "
                "values (%s, %s, %s) on conflict (id) do nothing",
                (TENANT_B, f"Municipio B {marca}", f"municipio-b-{marca}"))
            for rotulo, tenant in (("a", TENANT_A), ("b", TENANT_B)):
                cursor.execute(
                    "insert into public.processos "
                    "(tenant_id, orgao, objeto, etapa, dados, documentos, "
                    " aprovados) "
                    "values (%s, %s, %s, 0, '{}'::jsonb, '{}'::jsonb, "
                    "'{}'::text[]) returning id",
                    (tenant, f"Orgao {rotulo} {marca}",
                     f"OBJETO SIGILOSO {rotulo.upper()} {marca}"))
                ids[rotulo] = str(cursor.fetchone()[0])
    try:
        yield {"marca": marca, **ids}
    finally:
        with psycopg.connect(dsn, autocommit=True) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    "delete from public.processos where objeto like %s",
                    (f"%{marca}%",))
                cursor.execute(
                    "delete from public.processos where tenant_id = %s",
                    (TENANT_B,))
                cursor.execute("delete from public.tenants where id = %s",
                               (TENANT_B,))


@pytest.fixture
def como_municipio_b(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "tenant_atual", lambda: TENANT_B)
    return db


def _uma_linha(dsn: str, sql: str, parametros: tuple):
    import psycopg

    with psycopg.connect(dsn) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(sql, parametros)
            return cursor.fetchone()


# ---------------------------------------------------------------------------
# LEITURA
# ---------------------------------------------------------------------------
def test_a_lista_do_administrador_para_no_proprio_municipio(
        dois_municipios, como_municipio_b):
    """
    Sem `usuario_id` — que é como a interface chama para administrador —
    a listagem devolvia os 50 processos mais recentes do banco inteiro.
    """
    db = como_municipio_b
    lista = db.listar_processos()

    alheios = [p for p in lista
               if dois_municipios["marca"] in (p.get("objeto") or "")
               and p["id"] != dois_municipios["b"]]
    assert not alheios, (
        f"{len(alheios)} processo(s) de outra prefeitura na lista do "
        f"administrador: {[p.get('objeto') for p in alheios][:3]}")
    assert any(p["id"] == dois_municipios["b"] for p in lista), (
        "o filtro escondeu também os processos da própria prefeitura")


def test_carregar_por_id_nao_alcanca_processo_de_outra_prefeitura(
        dois_municipios, como_municipio_b):
    db = como_municipio_b
    assert db.carregar_processo(dois_municipios["a"]) is None, (
        "processo de outra prefeitura foi carregado por id")
    assert db.carregar_processo(dois_municipios["b"]) is not None, (
        "o filtro trancou a prefeitura para fora dos próprios processos")


# ---------------------------------------------------------------------------
# ESCRITA
# ---------------------------------------------------------------------------
def test_excluir_nao_alcanca_processo_de_outra_prefeitura(
        dois_municipios, como_municipio_b):
    db = como_municipio_b
    db.excluir_processo(dois_municipios["a"])

    (restantes,) = _uma_linha(
        os.environ["GOVDOCS_DSN_HOMOLOGACAO"],
        "select count(*) from public.processos where id = %s",
        (dois_municipios["a"],))
    assert restantes == 1, (
        "uma prefeitura apagou o processo de outra — é perda de dado "
        "definitiva, não leitura indevida")


def test_renomear_nao_alcanca_processo_de_outra_prefeitura(
        dois_municipios, como_municipio_b):
    db = como_municipio_b
    try:
        db.renomear_processo(dois_municipios["a"], "Renomeado pela vizinha")
    except db.ErroBanco:
        pass  # recusar com erro também é bloquear

    (nome,) = _uma_linha(
        os.environ["GOVDOCS_DSN_HOMOLOGACAO"],
        "select coalesce(nome, '') from public.processos where id = %s",
        (dois_municipios["a"],))
    assert nome != "Renomeado pela vizinha", (
        "uma prefeitura renomeou o processo de outra")


def test_salvar_nao_sobrescreve_processo_de_outra_prefeitura(
        dois_municipios, como_municipio_b):
    db = como_municipio_b
    db.salvar_processo(dois_municipios["a"],
                       {"orgao": "INVASOR", "objeto": "SOBRESCRITO"},
                       {}, set(), 0)

    (objeto,) = _uma_linha(
        os.environ["GOVDOCS_DSN_HOMOLOGACAO"],
        "select objeto from public.processos where id = %s",
        (dois_municipios["a"],))
    assert objeto != "SOBRESCRITO", (
        "uma prefeitura sobrescreveu o processo de outra")


def test_o_processo_novo_nasce_na_prefeitura_de_quem_o_criou(
        dois_municipios, como_municipio_b):
    """
    Sem carimbar `tenant_id`, a inserção caía no DEFAULT da coluna — que
    é a PRIMEIRA prefeitura. O processo da B nascia dentro da A.
    """
    db = como_municipio_b
    objeto = f"NASCIDO EM B {dois_municipios['marca']}"
    novo = db.salvar_processo(None, {"orgao": "B", "objeto": objeto},
                              {}, set(), 0)

    (tenant,) = _uma_linha(
        os.environ["GOVDOCS_DSN_HOMOLOGACAO"],
        "select tenant_id from public.processos where id = %s", (novo,))
    assert str(tenant) == TENANT_B, (
        f"processo criado pela prefeitura B nasceu em {tenant}")
