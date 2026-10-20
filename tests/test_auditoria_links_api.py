"""
Auditoria da cotação automática de 200 itens (20/10/2026) — links.

Registros REAIS da rodada auditada (Compras.gov.br, Preços Praticados):

* A1 (o N-07 da segunda auditoria) — 4 de 50 páginas do portal abriram
  "Compra não encontrada" para compra que existe; o preço estava na API
  oficial. Caso real: tomada tripla da Penitenciária Jairo Almeida Bueno
  de Itapetininga (UASG 380135, compra 38013506000822026, item 13,
  R$ 24,20). O relatório passa a imprimir TAMBÉM o registro na API;
* A2 — o link técnico pedia 10 linhas por página; a compra
  45323005901552026 (Prefeitura de Joinville) tem 43 itens do mesmo
  CATMAT, e o mocho (item 60, R$ 129,00) ficava fora.
"""

from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pymupdf

from src.precos import compras_gov, links
from src.precos import documento_cotacao as dc

TOMADA = {"idCompra": 38013506000822026, "idCompraItem": "3801350600082202600013",
          "codigoItemCatalogo": 244238, "precoUnitario": 24.2,
          "codigoUasg": "380135",
          "nomeUasg": "ESP-PENIT. JAIRO ALMEIDA BUENO DE ITAPETINING",
          "numeroItemCompra": 13}
MOCHO = {"idCompra": 45323005901552026, "idCompraItem": "4532300590155202600060",
         "codigoItemCatalogo": 637209, "precoUnitario": 129.0,
         "codigoUasg": "453230", "nomeUasg": "PREFEITURA MUNICIPAL DE JOINVILLE - SC",
         "numeroItemCompra": 60}


def _linha(bruto):
    return {"fonte_id": "compras_gov_precos", "bruto": bruto,
            "referencia_externa": str(bruto["idCompra"])}


def test_link_tecnico_pede_a_pagina_inteira_a2():
    url = compras_gov.url_de_verificacao(MOCHO)
    q = parse_qs(urlparse(url).query)
    assert q["tamanhoPagina"] == ["500"]          # 43 itens cabem na página
    assert q["codigo"] == ["637209"] and q["idCompra"] == ["45323005901552026"]
    assert links.seguro(url) == url


def _ref(bruto, **kw):
    lk = links.resolver(_linha(bruto))
    base = dict(contratacao_url=lk.contratacao_url, identificacao=lk.identificacao,
                contratacao_rotulo=lk.contratacao_rotulo, dados_url=lk.dados_url,
                id_externo=bruto["idCompraItem"])
    base.update(kw)
    return SimpleNamespace(**base)


def test_celula_imprime_a_contratacao_e_o_registro_na_api_a1():
    ref = _ref(TOMADA)
    partes = dc._celula_contratacao(ref)
    textos = [t.texto for t in partes]
    assert textos == ["38013506000822026",
                      "Acompanhar contratação (Compras.gov.br)",
                      "Registro na API (dados abertos):",
                      "3801350600082202600013"]
    # a contratação aponta a PÁGINA; o item aponta o REGISTRO na API
    assert partes[0].link == links.acompanhamento_compra("38013506000822026")
    assert not links.eh_tecnico(partes[0].link)
    assert partes[3].link == ref.dados_url and links.eh_tecnico(partes[3].link)
    assert "idCompra=38013506000822026" in partes[3].link
    assert partes[2].link is None                 # o rótulo não é link


def test_sem_url_de_dados_nao_inventa_linha_de_api():
    sem_codigo = {**TOMADA, "codigoItemCatalogo": None}
    textos = [t.texto for t in dc._celula_contratacao(_ref(sem_codigo))]
    assert "Registro na API (dados abertos):" not in textos
    sem_item = _ref(TOMADA, id_externo=dc.NAO_INFORMADO)
    assert "Registro na API (dados abertos):" not in \
        [t.texto for t in dc._celula_contratacao(sem_item)]
    # sem página pública, o número continua impresso e a API vai junto
    sem_pagina = _ref(TOMADA, contratacao_url=None)
    assert [t.texto for t in dc._celula_contratacao(sem_pagina)] == [
        "38013506000822026", "Página pública não localizada pelo sistema",
        "Registro na API (dados abertos):", "3801350600082202600013"]


def test_carimbo_poe_cada_link_no_seu_numero_a1():
    """Como o LibreOffice 7.4 da produção entrega: PDF sem link nenhum.
    O carimbo põe a página sobre o número da compra e o registro da API
    sobre o número do item — que começa com o da compra."""
    tomada, mocho = _ref(TOMADA), _ref(MOCHO)
    mapa = {tomada.identificacao: tomada.contratacao_url,
            tomada.id_externo: tomada.dados_url,
            mocho.identificacao: mocho.contratacao_url,
            mocho.id_externo: mocho.dados_url}
    doc = pymupdf.open()
    pagina = doc.new_page()
    y = 72
    for texto in (tomada.identificacao, "Registro na API (dados abertos):",
                  tomada.id_externo, mocho.identificacao, mocho.id_externo):
        pagina.insert_text((72, y), texto, fontsize=7)
        y += 14
    carimbado = pymupdf.open(stream=dc.carimbar_links(doc.tobytes(), mapa))
    achados = {}
    for p in carimbado:
        for link in p.get_links():
            achados[p.get_textbox(link["from"]).strip()] = link["uri"]
    assert achados == mapa
