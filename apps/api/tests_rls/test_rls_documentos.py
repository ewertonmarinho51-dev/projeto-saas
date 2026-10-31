"""
WordCraft Workspace (Issue #137) contra Postgres + GoTrue + PostgREST reais.

O que é do banco: quem enxerga o processo e a cabeça nativa do documento.
A pilha não tem o runtime aprovado do WordCraft (nem a credencial
documental da ADR-011), então abrir o canvas responde 503 — e isso também
se prova: a falha é fechada e vem DEPOIS do RLS, nunca no lugar dele.
"""

from __future__ import annotations

import pytest

import pilha as modulo_pilha


def _h(conta):
    return {"Authorization": f"Bearer {conta.token}"}


@pytest.fixture(scope="module")
def api_editor(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url, "SUPABASE_KEY": pilha.anon,
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000", "GOVCONECT_WORDCRAFT_WORKSPACE": "1"})
    return TestClient(criar_app(config), raise_server_exceptions=False)


@pytest.fixture(scope="module")
def editor(pilha):
    return modulo_pilha.semear_editor(pilha, dono="a1")


def test_dono_ve_o_nativo_e_o_legado_do_proprio_processo(api_editor, pilha, editor):
    r = api_editor.get(f"/api/v1/processos/{editor['processo']}/documentos", headers=_h(pilha.contas["a1"]))
    assert r.status_code == 200, r.text
    docs = {d["tipo"]: d for d in r.json()["documentos"]}
    assert docs["etp"]["id"] == editor["etp"] and docs["etp"]["nativo"] is True and docs["etp"]["revisao"] == 1
    assert docs["dfd"]["id"] == editor["dfd"] and docs["dfd"]["nativo"] is False and docs["dfd"]["legado"] is True
    assert r.json()["escrita"] is False, "sem a credencial documental nada se grava"


def test_outro_municipio_fora_do_canario_e_404_de_modulo_e_dentro_e_404_de_dado(api_editor, pilha, editor):
    import psycopg

    b1 = pilha.contas["b1"]
    caminho = f"/api/v1/processos/{editor['processo']}/documentos"
    r = api_editor.get(caminho, headers=_h(b1))
    assert r.status_code == 404 and r.json()["code"] == "MODULE_UNAVAILABLE"
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        c.execute("insert into public.tenant_modulos (tenant_id, modulo, habilitado) values "
                  "(%s, 'wordcraft_editor', true) on conflict (tenant_id, modulo) do update "
                  "set habilitado = true", (b1.tenant_id,))
    from src import db

    # Os módulos do tenant ficam 60 s em cache no domínio: a primeira leitura
    # do B (fora do canário) não pode valer para a segunda.
    db._modulos_do_tenant_em.clear()
    try:
        r = api_editor.get(caminho, headers=_h(b1))
        assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND", r.text
        r = api_editor.post(f"/api/v1/documentos/{editor['etp']}/sessoes", headers=_h(b1),
                            json={"processo_id": editor["processo"]})
        assert r.status_code == 404, "o RLS decide antes do motor"
    finally:
        with psycopg.connect(pilha.dsn, autocommit=True) as c:
            c.execute("delete from public.tenant_modulos where tenant_id = %s and modulo = 'wordcraft_editor'",
                      (b1.tenant_id,))
        db._modulos_do_tenant_em.clear()


def test_documentos_nunca_mais_visiveis_que_o_processo(api_editor, pilha, editor):
    # Outra secretaria e colega do mesmo município: quem decide é o RLS de
    # `processos`; o editor só acompanha.
    for rotulo in ("a2", "a1_colega", "admin_a"):
        conta = pilha.contas[rotulo]
        processo = api_editor.get(f"/api/v1/processos/{editor['processo']}", headers=_h(conta)).status_code
        docs = api_editor.get(f"/api/v1/processos/{editor['processo']}/documentos", headers=_h(conta)).status_code
        assert (processo, docs) in {(200, 200), (404, 404)}, (rotulo, processo, docs)


def test_sem_runtime_abrir_falha_fechado(api_editor, pilha, editor):
    r = api_editor.post(f"/api/v1/documentos/{editor['etp']}/sessoes", headers=_h(pilha.contas["a1"]),
                        json={"processo_id": editor["processo"]})
    assert r.status_code == 503 and r.json()["code"] == "WORDCRAFT_RUNTIME_UNAVAILABLE"


def test_conta_revogada_nao_abre(api_editor, pilha, editor):
    r = api_editor.get(f"/api/v1/processos/{editor['processo']}/documentos",
                       headers=_h(pilha.contas["a1_revogado"]))
    assert r.status_code in (401, 403)


def test_titular_confirma_os_fatos_e_o_colega_nao(api_editor, pilha, editor):
    dono, colega = pilha.contas["a1"], pilha.contas["a1_colega"]
    base = f"/api/v1/processos/{editor['processo']}/fatos-canonicos"
    fatos = api_editor.post(f"{base}/sincronizacao", headers=_h(dono))
    assert fatos.status_code == 200, fatos.text
    pendentes = [f["id"] for f in fatos.json()["pendentes"]]
    assert pendentes and fatos.json()["pronto"] is False

    r = api_editor.post(f"{base}/confirmacao", headers=_h(colega), json={"ids": pendentes})
    assert r.status_code in (403, 404), r.text

    r = api_editor.post(f"{base}/confirmacao", headers=_h(dono), json={"ids": pendentes})
    assert r.status_code == 200, r.text
    assert r.json()["pronto"] is True and r.json()["pendentes"] == []

    # A mesma lista de novo: já não está em `extraido`, e nada muda.
    r = api_editor.post(f"{base}/confirmacao", headers=_h(dono), json={"ids": pendentes})
    assert r.status_code == 409 and r.json()["code"] == "FACTS_CHANGED"
