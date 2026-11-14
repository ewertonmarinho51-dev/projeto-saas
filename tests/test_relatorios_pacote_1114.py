"""
Relatórios — pacote de 14/11/2026 (RF-R01, RF-R02).

Resumido (Relatório de Cotação, PDF/DOCX): sem "Memória de cálculo", sem
o rol de retiradas e sem "Alertas e ressalvas"; com o extrato fixo e só as
fontes dos preços CONSIDERADOS. Completo (Relatório Analítico Integral):
recebe o que saiu do resumido e ganha a participação financeira por item
com a rosca Top 5 + Demais, em Decimal.
"""
from __future__ import annotations

import io
import re
import zipfile
from decimal import Decimal
from types import SimpleNamespace

from src.precos import documento_cotacao as dc
from src.precos import relatorio_view as rv

from tests.test_revisao02_relatorio import MOMENTO, _cotacao


def _texto(docx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    return " ".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def _ref(fonte_id, fonte, data, *, url=None):
    return SimpleNamespace(fonte_id=fonte_id, fonte=fonte, data=data,
                           contratacao_url=url, link=None)


def _vista(itens, fontes=()):
    return SimpleNamespace(itens=itens, fontes=list(fontes))


# --- fontes utilizadas -----------------------------------------------------
def test_fontes_usadas_so_as_dos_precos_considerados_deduplicadas():
    # consultadas A, B e C; a cesta considerou A e C — B não entra
    item1 = SimpleNamespace(id="i1", considerada_lista=(
        _ref("a", "Fonte A", "10/03/2026", url="https://pncp.gov.br/x"),
        _ref("c", "Fonte C", "02/01/2026")))
    item2 = SimpleNamespace(id="i2", considerada_lista=(
        _ref("a", "Fonte A", "15/08/2026"),))
    fontes = [SimpleNamespace(id=k, enquadramento=f"inc. {k}") for k in "abc"]
    usadas = dc.fontes_usadas(_vista([item1, item2], fontes))
    assert [f.nome for f in usadas] == ["Fonte A", "Fonte C"]
    a = usadas[0]
    assert (a.precos, a.itens, a.desde, a.ate, a.com_link) == (
        2, 2, "10/03/2026", "15/08/2026", 1)
    assert a.enquadramento == "inc. a"


def test_sem_preco_considerado_nao_inventa_fonte():
    item = SimpleNamespace(id="i1", considerada_lista=())
    assert dc.fontes_usadas(_vista([item])) == []


def test_data_ausente_nao_vira_periodo_inventado():
    item = SimpleNamespace(id="i1", considerada_lista=(
        _ref("a", "Fonte A", rv.NAO_INFORMADO),))
    f = dc.fontes_usadas(_vista([item]))[0]
    assert f.desde == f.ate == rv.NAO_INFORMADO


# --- participação ------------------------------------------------------------
def _itens(*totais, concluido=True):
    return [SimpleNamespace(numero=n, titulo=f"Item {n}", concluido=concluido,
                            preco_total=Decimal(t)) for n, t in
            enumerate(totais, start=1)]


def test_top5_e_demais_com_percentual_exato():
    linhas, fatias, total = dc.participacao(_vista(_itens(
        "50", "30", "10", "5", "3", "2")))
    assert total == Decimal("100")
    assert [f.percentual for f in linhas] == [Decimal(x) for x in (
        "50.00", "30.00", "10.00", "5.00", "3.00", "2.00")]
    assert [f.rotulo for f in fatias][-1] == "Demais"
    assert fatias[-1].valor == Decimal("2") and len(fatias) == 6


def test_ate_cinco_itens_nao_tem_demais_e_ordem_desempata_pelo_numero():
    linhas, fatias, _ = dc.participacao(_vista(_itens("10", "40", "10")))
    assert "Demais" not in [f.rotulo for f in fatias]
    assert [f.rotulo for f in linhas] == ["02 · Item 2", "01 · Item 1",
                                          "03 · Item 3"]


def test_total_zero_ou_sem_concluido_e_nao_aplicavel():
    assert dc.participacao(_vista(_itens("0", "0")))[0] == []
    assert dc.participacao(_vista(_itens("10", concluido=False)))[0] == []


def test_arredondamento_por_linha_nao_e_forcado_a_100():
    linhas, _, total = dc.participacao(_vista(_itens("1", "1", "1")))
    assert [f.percentual for f in linhas] == [Decimal("33.33")] * 3
    assert sum(f.valor for f in linhas) == total     # o total é exato


def test_rosca_e_png_valido():
    from PIL import Image
    _, fatias, _ = dc.participacao(_vista(_itens("50", "30", "10", "5", "3", "2")))
    with Image.open(io.BytesIO(dc.rosca_png(fatias))) as img:
        assert img.format == "PNG" and img.size == (900, 900)


# --- documentos -----------------------------------------------------------
def test_resumido_sem_memoria_exclusoes_e_alertas_com_extrato():
    p, itens, refs = _cotacao(concluido=True)
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto = _texto(dc.relatorio_de_cotacao_docx(v))
    for fora in ("Memória de cálculo", "Alertas e ressalvas",
                 "Desconsiderados da série", "Retirada da cesta pelo servidor",
                 "Fontes consultadas", "Participação financeira"):
        assert fora not in texto, fora
    assert dc.TITULO_EXTRATO in texto
    assert "não constitui, por si só, uma fonte originária de preços" in texto
    assert dc.TITULO_FONTES_USADAS in texto
    # metodologia e quadro continuam
    assert "Resumo da cotação" in texto and "Método e critérios" in texto


def test_completo_recebe_o_que_saiu_e_a_participacao():
    p, itens, refs = _cotacao(concluido=True)
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    texto = _texto(dc.relatorio_analitico_docx(v))
    assert "Participação financeira dos itens na contratação" in texto
    assert "Participação por item" in texto and "100,00%" in texto
    assert "Alertas e ressalvas" in texto and "Fontes consultadas" in texto
    assert "Desconsiderados da série" in texto


def test_fontes_do_resumido_saem_da_mesma_cesta_do_calculo():
    p, itens, refs = _cotacao(concluido=True)
    v = rv.projetar(p, itens, refs, emitido_em=MOMENTO)
    consideradas = {r.fonte for i in v.itens for r in i.considerada_lista}
    assert {f.nome for f in dc.fontes_usadas(v)} == consideradas
    so_consultadas = {f.nome for f in v.fontes} - consideradas
    texto = _texto(dc.relatorio_de_cotacao_docx(v))
    extrato = texto.split(dc.TITULO_FONTES_USADAS, 1)[1]
    for nome in so_consultadas:
        assert nome not in extrato
