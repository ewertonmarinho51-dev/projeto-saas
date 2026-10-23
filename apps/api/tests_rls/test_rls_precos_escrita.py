"""
Escrita da pesquisa de preços contra a pilha real (P04e).

Domínio, banco e RLS verdadeiros: a pesquisa nasce pela API com o dono
certo; a planilha XLSX real vira itens com quantidade exata (Decimal no
banco); reimportar a mesma planilha não duplica; concluir e reabrir
seguem a máquina de estados com If-Match; colega e outro município não
escrevem.
"""

from __future__ import annotations

import io
import uuid
from decimal import Decimal

import pytest

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _api(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url, "SUPABASE_KEY": pilha.anon,
                       "PRICE_RESEARCH_ENABLED": "1", "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)


def _h(conta, **extra):
    return {"Authorization": f"Bearer {conta.token}", **extra}


def _planilha():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Código", "Descrição", "Unidade", "Quantidade"])
    ws.append(["451234", "Caneta esferográfica azul", "UN", 150])
    ws.append(["", "Papel A4 75 g/m²", "RESMA", "12,5"])
    saida = io.BytesIO()
    wb.save(saida)
    return saida.getvalue()


def _criar(api, conta, nome="Expediente E2E"):
    r = api.post("/api/v1/precos/pesquisas", json={"nome": nome, "objeto": "Material"},
                 headers=_h(conta, **{"Idempotency-Key": f"nova-{uuid.uuid4().hex}"}))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _importar(api, conta, pid, confirmar=False, plano=None):
    cab = _h(conta, **{"Content-Type": XLSX})
    if plano:
        cab["If-Match"] = f'"{plano}"'
    return api.post(f"/api/v1/precos/pesquisas/{pid}/importacao"
                    + ("?confirmar=true" if confirmar else ""), headers=cab, content=_planilha())


def test_criar_e_importar_planilha_real(pilha):
    import psycopg

    api, a1 = _api(pilha), pilha.contas["a1"]
    pid = _criar(api, a1)
    with psycopg.connect(pilha.dsn) as c:
        dono, estado = c.execute("select auth_user_id::text, estado from public.pesquisas_preco "
                                 "where id=%s", (pid,)).fetchone()
    assert (dono, estado) == (a1.auth_user_id, "draft")

    conferido = _importar(api, a1, pid)
    assert conferido.status_code == 200, conferido.text
    assert conferido.json()["resumo"]["novo"] == 2 and conferido.json()["gravado"] is False
    with psycopg.connect(pilha.dsn) as c:
        assert c.execute("select count(*) from public.pesquisa_preco_itens where pesquisa_id=%s",
                         (pid,)).fetchone() == (0,), "conferir não grava"

    r = _importar(api, a1, pid, confirmar=True, plano=conferido.json()["plano"])
    assert r.status_code == 200 and r.json()["gravado"] is True, r.text
    with psycopg.connect(pilha.dsn) as c:
        itens = c.execute("select numero, descricao, unidade, quantidade, estado from "
                          "public.pesquisa_preco_itens where pesquisa_id=%s order by numero",
                          (pid,)).fetchall()
    assert [(n, q) for n, _, _, q, _ in itens] == [(1, Decimal("150")), (2, Decimal("12.5"))]
    assert {e for *_, e in itens} == {"pending"}

    # A mesma planilha de novo: nada a fazer, nada duplicado.
    de_novo = _importar(api, a1, pid)
    assert de_novo.json()["resumo"] == {"novo": 0, "atualizar": 0, "igual": 2, "refaz_busca": 0}


def test_colega_e_outro_municipio_nao_escrevem(pilha):
    api, a1 = _api(pilha), pilha.contas["a1"]
    pid = _criar(api, a1, "Do a1")
    assert _importar(api, pilha.contas["a1_colega"], pid).status_code == 403
    assert _importar(api, pilha.contas["b1"], pid).status_code == 404


def test_concluir_e_reabrir_item_com_if_match(pilha):
    import pilha as modulo_pilha

    api, a1 = _api(pilha), pilha.contas["a1"]
    pid = modulo_pilha.semear_emissao(pilha)          # um item em revisão, um preço na cesta
    pesquisa = api.get(f"/api/v1/precos/pesquisas/{pid}", headers=_h(a1)).json()
    item = pesquisa["itens"][0]
    base = f"/api/v1/precos/pesquisas/{pid}/itens/{item['id']}"

    velho = api.post(f"{base}/conclusao", headers=_h(a1, **{"If-Match": f'"{item["revisao"] + 7}"'}),
                     json={"justificativa": "Conferido na fonte oficial (E2E)."})
    assert velho.status_code == 409, velho.text

    feito = api.post(f"{base}/conclusao", headers=_h(a1, **{"If-Match": f'"{item["revisao"]}"'}),
                     json={"justificativa": "Conferido na fonte oficial (E2E)."})
    assert feito.status_code == 200, feito.text
    assert feito.json()["estado"] == "complete"

    curto = api.post(f"{base}/reabertura", headers=_h(a1), json={"motivo": "x"})
    assert curto.status_code == 422
    reaberto = api.post(f"{base}/reabertura", headers=_h(a1), json={"motivo": "faltou um preço"})
    assert reaberto.status_code == 200 and reaberto.json()["estado"] == "review"

    colega = api.post(f"{base}/reabertura", headers=_h(pilha.contas["a1_colega"]),
                      json={"motivo": "não posso"})
    assert colega.status_code == 403
