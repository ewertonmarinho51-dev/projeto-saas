"""
Revisão 02 — links públicos de contratação e relatório de cotação
(06_FONTES_E_LINKS, 05_RELATORIO_PDF, 08_COMPLIANCE e matriz AC-13 a AC-23,
AC-30 a AC-34).

As rotas públicas foram conferidas no navegador em 17/10/2026 (ver
`src/precos/links.py`); aqui só se prova a MONTAGEM, sem rede.
"""

from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.precos import documento_cotacao as dc
from src.precos import links, relatorio_view as rv

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "precos"
MOMENTO = datetime(2026, 10, 17, 18, 58, tzinfo=timezone.utc)


def _bruto(nome: str) -> dict:
    return json.loads((FIXTURES / f"{nome}.json").read_text(
        encoding="utf-8"))["resultado" if nome.startswith("compras") else "data"][0]


# ---------------------------------------------------------------------------
# Resolvedor de links
# ---------------------------------------------------------------------------
def test_compras_gov_precos_abre_o_acompanhamento_da_compra_ac17():
    bruto = _bruto("compras_precos_praticados")
    r = links.resolver({"fonte_id": "compras_gov_precos", "bruto": bruto})
    assert r.contratacao_url == (
        "https://cnetmobile.estaleiro.serpro.gov.br/comprasnet-web/public/"
        "compras/acompanhamento-compra?compra=10210305900092025")
    assert r.identificacao == "10210305900092025"
    assert "Compras.gov.br" in r.contratacao_rotulo
    # o endpoint JSON continua disponível, mas como DADOS, não contratação
    assert r.dados_url and links.eh_tecnico(r.dados_url)
    assert not links.eh_tecnico(r.contratacao_url)


def test_itens_de_contratacao_abrem_o_edital_no_pncp_ac17():
    bruto = _bruto("compras_itens_contratacoes")
    r = links.resolver({"fonte_id": "compras_gov_itens", "bruto": bruto})
    assert r.contratacao_url == \
        "https://pncp.gov.br/app/editais/17220203000196/2025/119"
    assert r.identificacao == "17220203000196-1-000119/2025"


def test_pncp_monta_cnpj_ano_sequencial_sem_zeros():
    assert links.contratacao_pncp("90483058000126-1-000078/2025") == \
        "https://pncp.gov.br/app/editais/90483058000126/2025/78"


@pytest.mark.parametrize("entrada", ["", "123", "9298420500002202600007",
                                     "abc/2025", None])
def test_sem_identificador_oficial_nao_ha_link_ac21(entrada):
    r = links.resolver({"fonte_id": "compras_gov_precos",
                        "bruto": {"idCompra": entrada}})
    assert r.contratacao_url is None and r.identificacao == ""
    assert links.contratacao_pncp(entrada) is None


def test_fonte_desconhecida_ou_cotacao_direta_sem_link_nem_ata_ac19():
    for fonte in ("cotacao_direta", "outra"):
        r = links.resolver({"fonte_id": fonte, "bruto": {}})
        assert r == links.Links()


@pytest.mark.parametrize("url", [
    "http://pncp.gov.br/app/editais/1/2025/1",          # sem TLS
    "javascript:alert(1)", "file:///c:/x.pdf",
    "https://evil.example/pncp.gov.br",                  # host estranho
    "https://user:senha" + "@pncp.gov.br/app/editais/1/2025/1",  # credencial na URL
])
def test_so_https_e_host_oficial_viram_link(url):
    assert links.seguro(url) is None


# ---------------------------------------------------------------------------
# Relatório — a partir de uma cotação sintética mínima
# ---------------------------------------------------------------------------
def _linha(valor, ident, *, status="selected", motivos=(), fonte="compras_gov_precos",
           bruto=None, orgao="CAMARA MUNICIPAL DE SANTA MARIA"):
    return {
        "id": f"id-{ident}", "item_id": "it-1", "fonte_id": fonte,
        "fonte_nome": "Compras.gov.br — Preços Praticados",
        "fonte_tipo": "sistema_oficial", "id_externo": ident,
        "raw_hash": "h" * 64, "bruto": bruto if bruto is not None else {
            "idCompra": "92984205000022026", "modalidade": 5,
            "numeroItemCompra": 7, "niFornecedor": "12345678000199",
            "objetoCompra": "Objeto: Pregão Eletrônico - Material de expediente",
            "codigoItemCatalogo": 1},
        "descricao_original": "PAPEL A4", "unidade_original": "PACOTE",
        "unidade_normalizada": "PACOTE",
        "valor_unitario_original": str(valor),
        "valor_unitario_normalizado": str(valor), "natureza_valor": "praticado",
        "status": status, "motivos": list(motivos), "orgao": orgao, "uf": "RS",
        "fornecedor": "PAPELARIA SINTETICA LTDA", "ni_fornecedor": "12345678000199",
        "data_compra": "2026-10-15", "coletado_em": "2026-10-17T03:01:00+00:00",
        "score": "0.9"}


def _cotacao(*, concluido=True):
    pesquisa = {"id": "pesq-1", "nome": "Material de expediente (sintético)",
                "objeto": "Aquisição de papel", "versao": 1, "estado": "completed",
                "perfil_normativo": "in_65_2021", "data_base": "2026-10-17",
                "criado_em": "2026-10-17", "versao_regras": "2026-10-15.media-aritmetica",
                "filtros": {"janela_dias": 180}}
    refs = [_linha(v, f"9298420500002202600{n:03d}") for n, v in
            enumerate(["19.03", "22.00", "25.46", "28.20", "45.20"], start=1)]
    refs.append(_linha("190.00", "ext-1", status="rejected", motivos=[
        "desconsiderada pelo Jev antes da cesta: preço extremo frente a 9 "
        "referências comparáveis de 9 origens independentes que corroboram a "
        "faixa; preço de R$ 190,00 contra mediana de R$ 25,46 "
        "[STATISTICAL_EXTREME, PRICE_VARIATION_REQUIRES_ATTENTION, "
        "INDEPENDENT_REFERENCES_CORROBORATE; política 2026-10-17.saneamento-v2]"]))
    refs.append(_linha("30.00", "ret-1", status="rejected",
                       motivos=["retirada da cesta pelo usuário"]))
    refs += [_linha("5.00", f"uni-{i}", status="rejected", motivos=[
        "unidade da referência não consta do dicionário de unidades — "
        "conversão não tentada"]) for i in range(40)]
    memoria = ("método padrão: média aritmética simples dos preços unitários "
               "considerados (soma R$ 139,89 ÷ 5)\n"
               "IN SEGES/ME nº 65/2021: estimativa apoiada exclusivamente em "
               "sistema oficial de preços não supera a mediana da amostra — "
               "valor ajustado de R$ 27,98 para R$ 25,46\n"
               "valor PROVISÓRIO até a análise crítica: 1 preço(s) atípico(s) "
               "aguardam decisão: remover da cesta ou manter o preço\n"
               "conclusão do revisor: conferido na fonte")
    item = {"id": "it-1", "numero": 1, "descricao": "PAPEL A4 BRANCO",
            "unidade": "PACOTE", "quantidade": "500", "codigo": "1",
            "tipo_catalogo": None,
            "estado": "complete" if concluido else "review",
            "metodo": "media", "preco_estimado": "25.46",
            "preco_total": "12730.00", "justificativa": memoria,
            "estatisticas": {"consideradas": 5, "pendencias": [
                "1 preço(s) atípico(s) aguardam decisão: remover da cesta ou "
                "manter o preço"], "anomalias": [],
                "ajuste_teto": {"pelo_metodo": "27.98", "adotado": "25.46"}}}
    return pesquisa, [item], {"it-1": refs}


def _docx_texto(view) -> tuple[str, str]:
    bruto = dc.relatorio_de_cotacao_docx(view)
    with zipfile.ZipFile(io.BytesIO(bruto)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
        rels = zf.read("word/_rels/document.xml.rels").decode("utf-8")
    import re
    texto = " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))
    return texto, rels


def test_relatorio_mostra_todas_as_usadas_com_link_da_contratacao_ac17_ac34():
    p, itens, refs = _cotacao()
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto, rels = _docx_texto(v)
    assert "Preços usados (5)" in texto
    for valor in ("R$ 19,03", "R$ 22,00", "R$ 25,46", "R$ 28,20", "R$ 45,20"):
        assert valor in texto, "todas as usadas aparecem, não 5 de 15"
    import re
    # o número da contratação, como palavra inteira (o `idCompraItem`
    # impresso abaixo começa com ele)
    assert len(re.findall(r"\b92984205000022026\b", texto)) == 5
    assert "acompanhamento-compra?compra=92984205000022026" in rels
    # auditoria de 20/10/2026 (A1/N-07): o registro na API vai TAMBÉM,
    # rotulado como tal — a contratação continua apontando a página (D08)
    assert texto.count("Registro na API (dados abertos):") == 5
    assert "tamanhoPagina=500" in rels
    assert "Fornecedor: PAPELARIA SINTETICA LTDA (12.345.678/0001-99)" in texto
    assert "vencedor" not in texto.lower(), "AC-23: sem rótulo de vencedor"
    assert "Pregão" in texto and "item 7" in texto


def test_relatorio_sem_inventario_e_com_autoria_certa_ac15_ac16():
    p, itens, refs = _cotacao()
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto, _ = _docx_texto(v)
    assert "Não consideradas (" not in texto
    assert "excluída pelo revisor" not in texto.lower()
    assert "Desconsiderados da série (2)" in texto
    assert "Desconsiderada pela triagem automática" in texto
    assert "Retirada da cesta pelo servidor" in texto
    # o critério sem códigos internos (STATISTICAL_EXTREME…) nem política
    assert "STATISTICAL_EXTREME" not in texto
    assert "40 resultado(s) da busca não entraram" in texto


def test_concluido_nao_sai_provisorio_e_teto_explicado_ac32_ac33():
    p, itens, refs = _cotacao(concluido=True)
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto, _ = _docx_texto(v)
    assert "PROVISÓRIO" not in texto and "aguardam decisão" not in texto
    assert "conclusão do revisor: conferido na fonte" in texto
    assert "R$ 27,98" in texto and "adotada a mediana, R$ 25,46" in texto
    assert "Catálogo 1" not in texto, "número da planilha não é catálogo"
    p, itens, refs = _cotacao(concluido=False)
    texto, _ = _docx_texto(rv.projetar(p, itens, refs, emitido_em=MOMENTO))
    assert "(em revisão)" in texto


def test_horario_de_brasilia_no_corpo_ac12():
    p, itens, refs = _cotacao()
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto, _ = _docx_texto(v)
    assert "17/10/2026 15:58 (horário de Brasília)" in texto
    assert "17/10/2026 00:01 (horário de Brasília)" in texto   # coleta 03:01 UTC


def test_links_da_vista_principal_x_analitico():
    p, itens, refs = _cotacao()
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    principal = dc.links_da_vista(v)
    # a contratação → a página pública (D08), nunca o JSON
    assert principal["92984205000022026"] == \
        links.acompanhamento_compra("92984205000022026")
    # o item da compra → o registro na API (auditoria de 20/10/2026, A1)
    tecnicos = {k: u for k, u in principal.items() if links.eh_tecnico(u)}
    # um por linha impressa em "Preços usados (5)" — e só elas
    assert len(tecnicos) == 5 == len(principal) - 1
    assert all(k.startswith("92984205000022026") and len(k) == 22
               for k in tecnicos)
    analitico = dc.links_da_vista(v, analitico=True)
    assert all(not links.eh_tecnico(u) or k.startswith(("uni", "ext", "ret"))
               for k, u in analitico.items())


def test_carimbo_de_link_sobre_o_numero_impresso():
    """O conversor de produção descarta hyperlink do DOCX: o carimbo põe a
    URL da contratação sobre o número impresso no PDF."""
    import pymupdf

    doc = pymupdf.open()
    pagina = doc.new_page()
    pagina.insert_text((72, 72), "Compra 92984205000022026 no PDF")
    pdf = dc.carimbar_links(doc.tobytes(), {"92984205000022026":
                                            "https://pncp.gov.br/app/editais/1/2025/1"})
    marcados = [l["uri"] for p in pymupdf.open(stream=pdf, filetype="pdf")
                for l in p.get_links()]
    assert marcados == ["https://pncp.gov.br/app/editais/1/2025/1"]


def test_ciencia_no_pdf_sem_nome_e_sem_bloquear_ac13():
    p, itens, refs = _cotacao()
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO, ciencia={
        "alertas": [{"x": 1}], "por": "Fulano de Tal",
        "registrada_em": "2026-10-17T18:58:00+00:00", "assinatura": "a" * 64})
    texto, _ = _docx_texto(v)
    assert "Conferência antes da emissão" in texto
    assert "Fulano de Tal" not in texto
