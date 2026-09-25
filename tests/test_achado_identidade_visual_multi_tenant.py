"""
ACHADO DE SEGURANÇA (§11/§17): a identidade visual atravessava prefeituras.

O §11 manda testar deliberadamente a tentativa de alcançar timbrado,
portaria ou servidor de outra prefeitura, e é explícito sobre onde a
resposta tem de estar: "a ausência de bloqueio no backend constitui
achado de segurança, mesmo que o frontend esconda a opção".

O QUE FOI ENCONTRADO

`config_orgaos` — a tabela da identidade visual (cabeçalho, rodapé,
marca d'água e as imagens que vão no timbrado dos documentos) — ganhou
`tenant_id` na migração 0006. Os três acessos a ela em `db.py` nunca
passaram a usá-lo:

    listar_orgaos()  →  sem filtro: devolvia a identidade de TODAS as
                        prefeituras, e é essa lista que alimenta o
                        seletor de timbrado;
    salvar_orgao()   →  ao marcar uma identidade como padrão, limpava a
                        marca `padrao` de TODAS as outras linhas da
                        tabela, de qualquer prefeitura — escrita
                        cruzando o tenant, não só leitura. E a inserção
                        não carimbava `tenant_id`, então a identidade
                        nova nascia na prefeitura do DEFAULT da coluna;
    excluir_orgao()  →  apagava por id, sem conferir a prefeitura. O id
                        vinha de graça pela listagem acima.

POR QUE O RLS NÃO SALVAVA

Porque o app não opera como `authenticated`: ele opera com a credencial
de SERVIDOR, e `service_role` tem BYPASSRLS. As 82 políticas do banco
protegem contra uma chave publicável vazada — não contra uma consulta
do próprio app que esqueceu o `where`. Neste caminho, o `.eq("tenant_id",
…)` do `db.py` É a contenção.

A tabela irmã `secretarias`, mais nova, sempre filtrou — inclusive
dentro do mesmo `salvar_orgao`, no espelhamento. O legado ficou para
trás sozinho.

SITUAÇÃO EM PRODUÇÃO, medida em 24/09/2026: uma única prefeitura
cadastrada, então não houve exposição real. Mas `flag_multi_prefeituras`
está LIGADA, e a segunda prefeitura cadastrada encontraria a porta
aberta.

COMO ESTAS PROVAS MEDEM

Contra o PostgREST de verdade da pilha de homologação, com duas
prefeituras semeadas — que é a camada onde o defeito vive. Um dublê de
cliente provaria que a consulta carrega o filtro; só o banco prova que
o filtro devolve o que deve.
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

TENANT_A = "11111111-1111-1111-1111-111111111111"   # o do default da coluna
TENANT_B = "22222222-2222-2222-2222-222222222222"


@pytest.fixture
def duas_prefeituras():
    """
    Semeia a segunda prefeitura e duas identidades — uma de cada — e
    limpa tudo no fim.

    Escreve por SQL direto, e não pelo `db.py`: semear pelo código que
    está sob suspeita faria a preparação herdar o próprio defeito.
    """
    import psycopg

    dsn = os.environ["GOVDOCS_DSN_HOMOLOGACAO"]
    marca = uuid.uuid4().hex[:8]
    identidades = {}
    with psycopg.connect(dsn, autocommit=True) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "insert into public.tenants (id, nome, slug) "
                "values (%s, %s, %s) on conflict (id) do nothing",
                (TENANT_B, f"Prefeitura B {marca}", f"prefeitura-b-{marca}"))
            for rotulo, tenant in (("a", TENANT_A), ("b", TENANT_B)):
                cursor.execute(
                    "insert into public.config_orgaos "
                    "(tenant_id, orgao, cabecalho, padrao) "
                    "values (%s, %s, %s, true) returning id",
                    (tenant, f"Orgao {rotulo} {marca}",
                     f"BRASAO DA PREFEITURA {rotulo.upper()} {marca}"))
                identidades[rotulo] = str(cursor.fetchone()[0])
    try:
        yield {"marca": marca, **identidades}
    finally:
        with psycopg.connect(dsn, autocommit=True) as conexao:
            with conexao.cursor() as cursor:
                cursor.execute(
                    "delete from public.secretarias where nome like %s",
                    (f"%{marca}%",))
                cursor.execute(
                    "delete from public.config_orgaos where orgao like %s",
                    (f"%{marca}%",))
                cursor.execute(
                    "delete from public.config_orgaos where tenant_id = %s",
                    (TENANT_B,))
                cursor.execute("delete from public.tenants where id = %s",
                               (TENANT_B,))


@pytest.fixture
def como_prefeitura_b(monkeypatch):
    from src import db

    monkeypatch.setattr(db, "tenant_atual", lambda: TENANT_B)
    return db


# ---------------------------------------------------------------------------
# 1) LEITURA
# ---------------------------------------------------------------------------
def test_a_lista_de_timbrados_nao_mostra_o_de_outra_prefeitura(
        duas_prefeituras, como_prefeitura_b):
    db = como_prefeitura_b
    listados = db.listar_orgaos()

    alheios = [o for o in listados if o.get("tenant_id") != TENANT_B]
    assert not alheios, (
        f"{len(alheios)} identidade(s) de outra prefeitura na lista — é ela "
        "que alimenta o seletor de timbrado dos documentos: "
        f"{[o.get('orgao') for o in alheios][:3]}")
    assert any(o["id"] == duas_prefeituras["b"] for o in listados), (
        "o filtro escondeu também a identidade da própria prefeitura")


# ---------------------------------------------------------------------------
# 2) ESCRITA — a parte pior
# ---------------------------------------------------------------------------
def test_marcar_padrao_nao_desmarca_o_da_outra_prefeitura(
        duas_prefeituras, como_prefeitura_b):
    """
    A varredura de `padrao = false` rodava sem `where tenant_id`. Um
    administrador da prefeitura B marcando a própria identidade como
    padrão apagava a marca da prefeitura A — e a A descobriria pelos
    documentos saindo sem timbrado.
    """
    import psycopg

    db = como_prefeitura_b
    db.salvar_orgao({"orgao": f"Novo B {duas_prefeituras['marca']}",
                     "cabecalho": "BRASAO NOVO B", "padrao": True})

    with psycopg.connect(os.environ["GOVDOCS_DSN_HOMOLOGACAO"]) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "select padrao from public.config_orgaos where id = %s",
                (duas_prefeituras["a"],))
            (padrao_da_a,) = cursor.fetchone()
    assert padrao_da_a is True, (
        "a identidade padrão da prefeitura A foi desmarcada pela operação "
        "da prefeitura B")


def test_a_identidade_nova_nasce_na_prefeitura_de_quem_a_criou(
        duas_prefeituras, como_prefeitura_b):
    """
    Sem carimbar `tenant_id`, a inserção caía no DEFAULT da coluna — que
    é a PRIMEIRA prefeitura. A identidade da B nascia dentro da A.
    """
    import psycopg

    db = como_prefeitura_b
    nome = f"Carimbo {duas_prefeituras['marca']}"
    db.salvar_orgao({"orgao": nome, "cabecalho": "BRASAO"})

    with psycopg.connect(os.environ["GOVDOCS_DSN_HOMOLOGACAO"]) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "select tenant_id from public.config_orgaos where orgao = %s",
                (nome,))
            linha = cursor.fetchone()
    assert linha, "a identidade não foi criada"
    assert str(linha[0]) == TENANT_B, (
        f"identidade criada pela prefeitura B nasceu em {linha[0]}")


def test_excluir_nao_alcanca_a_identidade_de_outra_prefeitura(
        duas_prefeituras, como_prefeitura_b):
    """
    O id vinha de graça pela listagem. Com a listagem fechada, a exclusão
    por id direto continua sendo um caminho — e o §11 manda tratar o
    backend como se o frontend não existisse.
    """
    import psycopg

    db = como_prefeitura_b
    db.excluir_orgao(duas_prefeituras["a"])

    with psycopg.connect(os.environ["GOVDOCS_DSN_HOMOLOGACAO"]) as conexao:
        with conexao.cursor() as cursor:
            cursor.execute(
                "select count(*) from public.config_orgaos where id = %s",
                (duas_prefeituras["a"],))
            (restantes,) = cursor.fetchone()
    assert restantes == 1, (
        "a prefeitura B apagou a identidade visual da prefeitura A")
