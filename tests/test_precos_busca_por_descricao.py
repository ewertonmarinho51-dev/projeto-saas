"""
Pesquisa de preços só pela descrição e especificação (sem CATMAT).

Caminho: descrição → grupo do catálogo (PDM) → preços praticados do
grupo na janela → comparabilidade contra a descrição e as medidas.
Ensaio real em 14/10/2026 com os 5 itens de material de expediente da
produção: todos com estimativa, ~2 s por item.
"""

from __future__ import annotations

import json
from decimal import Decimal

from src.precos import catalogo, execucao, matching, unidades
from src.precos.compras_gov import ComprasGovAdapter
from src.precos.fontes import Consulta
from src.precos.modelo import Referencia

PDMS = [
    {"codigoPdm": 11, "nomePdm": "CLIPE", "nomeClasse": "ESCRITÓRIO"},
    {"codigoPdm": 55, "nomePdm": "ARAME", "nomeClasse": "METAIS"},
    {"codigoPdm": 19746, "nomePdm": "PAPEL PARA IMPRESSÃO FORMATADO",
     "nomeClasse": "PAPEL"},
    {"codigoPdm": 10393, "nomePdm": "PAPEL IMPRESSÃO LIVRO", "nomeClasse": "PAPEL"},
    {"codigoPdm": 27, "nomePdm": "GRAMPEADOR", "nomeClasse": "ESCRITÓRIO"},
]


def _compra(pdm, preco, descricao, unidade="CX", capacidade=0.0):
    return {"idCompraItem": f"{pdm}-{preco}-{capacidade}", "codigoPdm": pdm,
            "codigoItemCatalogo": 1, "precoUnitario": preco,
            "descricaoItem": descricao, "siglaUnidadeFornecimento": unidade,
            "capacidadeUnidadeFornecimento": capacidade,
            "dataCompra": "2026-10-01", "nomeOrgao": "ORGAO",
            "criterioJulgamento": "Menor Preço", "estado": "PA"}


def _api(compras_por_pdm, urls):
    def abrir(url):
        urls.append(url)
        if "3_consultarPdmMaterial" in url:
            return json.dumps({"resultado": PDMS, "totalPaginas": 1})
        if "tipo=codigoPdm" in url:
            pdm = url.split("codigo=")[1].split("&")[0]
            compras = compras_por_pdm.get(pdm, [])
            return json.dumps({"resultado": compras,
                               "totalRegistros": len(compras)})
        return json.dumps({"resultado": [], "totalRegistros": 0})
    return abrir


# ---------------------------------------------------------------------------
# catálogo: o grupo certo, pelo substantivo
# ---------------------------------------------------------------------------
def _cat(urls):
    return catalogo.Catalogo(abrir_url=_api({}, urls), arquivo_indice=None)


def test_plural_da_planilha_casa_com_o_singular_do_catalogo():
    assert catalogo._termos("CLIPES METÁLICOS") == {"CLIPE", "METALICO"}


def test_o_grupo_exige_o_mesmo_substantivo():
    """"CLIPES … em arame de aço" é CLIPE, nunca ARAME."""
    pdms = _cat([]).pdms_para(
        "CLIPES METÁLICOS Nº 2/0. Clipes para papel, tamanho 2/0, em arame "
        "de aço galvanizado, caixa contendo 100 unidades.")
    assert [p["nome"] for p in pdms] == ["CLIPE"]


def test_radical_leva_o_papel_a4_ao_grupo_formatado():
    pdms = _cat([]).pdms_para(
        "PAPEL A4 BRANCO. Papel sulfite branco, formato A4, 75 g/m², "
        "impressão a laser, pacote contendo 500 folhas.")
    assert pdms[0]["nome"] == "PAPEL PARA IMPRESSÃO FORMATADO"


# ---------------------------------------------------------------------------
# adapter: sem código, pesquisa pelo grupo inteiro
# ---------------------------------------------------------------------------
def test_sem_codigo_pesquisa_os_precos_do_grupo_pela_descricao():
    urls: list[str] = []
    compras = {"11": [_compra(11, 2.10, "CLIPE, TAMANHO: 2/0, MATERIAL: METAL")]}
    resultado = ComprasGovAdapter(abrir_url=_api(compras, urls)).pesquisar(
        Consulta(descricao="CLIPES METÁLICOS Nº 2/0, caixa contendo 100 unidades"))
    assert len(resultado.referencias) == 1
    assert resultado.pdms_inferidos == ["11"]
    assert any("tipo=codigoPdm" in u and "codigo=11" in u for u in urls)
    assert not resultado.houve_falha
    assert any("grupo(s) do catálogo" in o for o in resultado.ocorrencias)


def test_descricao_sem_grupo_no_catalogo_orienta_sem_falhar():
    resultado = ComprasGovAdapter(abrir_url=_api({}, [])).pesquisar(
        Consulta(descricao="SERVIÇO DE CONSULTORIA ESPECIALIZADA"))
    assert not resultado.referencias and not resultado.houve_falha
    assert any("grupo do catálogo" in o for o in resultado.ocorrencias)


# ---------------------------------------------------------------------------
# comparabilidade: o grupo é evidência, as medidas discriminam
# ---------------------------------------------------------------------------
def _ref(descricao, pdm="11"):
    return Referencia(fonte=None, id_externo="x", bruto={},
                      descricao_original=descricao, codigo_pdm=pdm,
                      valor_unitario_original=Decimal("2"),
                      valor_unitario_normalizado=Decimal("2"),
                      unidade_original="CX")


ITEM = ("CLIPES METÁLICOS Nº 2/0. Clipes para papel, tamanho 2/0, arame de "
        "aço galvanizado, caixa contendo 100 unidades.")


def test_mesmo_grupo_e_mesma_medida_reforcam_a_identidade():
    ref = _ref("CLIPE, TAMANHO: 2/0, MATERIAL: METAL, FORMATO: PARALELO")
    sem = matching.comparar(ref, descricao=ITEM)
    com = matching.comparar(ref, descricao=ITEM, pdms_item=frozenset({"11"}))
    assert com.identidade > sem.identidade
    assert any("mesmo grupo do catálogo" in f.explicacao for f in com.fatores)


def test_medida_contraditoria_nao_ganha_o_reforco():
    """Clipe 8/0 não é clipe 2/0, mesmo sendo do mesmo grupo."""
    ref = _ref("CLIPE, TAMANHO: 8/0, MATERIAL: METAL")
    sem = matching.comparar(ref, descricao=ITEM)
    com = matching.comparar(ref, descricao=ITEM, pdms_item=frozenset({"11"}))
    assert com.identidade == sem.identidade


def test_outro_grupo_nao_ganha_o_reforco():
    ref = _ref("ARAME GALVANIZADO 2/0", pdm="55")
    com = matching.comparar(ref, descricao=ITEM, pdms_item=frozenset({"11"}))
    assert com.identidade == matching.comparar(ref, descricao=ITEM).identidade


# ---------------------------------------------------------------------------
# unidades: embalagem para embalagem pela quantidade declarada
# ---------------------------------------------------------------------------
def test_conteudo_declarado_na_especificacao():
    assert unidades.conteudo_declarado("pacote contendo 500 folhas") == 500
    assert unidades.conteudo_declarado("caixa com 50 unidades") == 50
    assert unidades.conteudo_declarado("caneta azul") is None


def test_emb_de_100_folhas_vale_um_quinto_do_pacote_de_500():
    fator, _ = unidades.fator_de_conversao(
        "EMB", "PACOTE", Decimal(100), Decimal(500))
    assert fator == Decimal("0.2")


def test_caixas_de_conteudos_diferentes_sao_ajustadas():
    fator, _ = unidades.fator_de_conversao(
        "CX", "CAIXA", Decimal(12), Decimal(50))
    assert fator == Decimal("0.24")


def test_sem_quantidade_dos_dois_lados_a_conversao_e_recusada():
    fator, motivo = unidades.fator_de_conversao("EMB", "PACOTE", Decimal(0),
                                                Decimal(500))
    assert fator is None and "não informou" in motivo


# ---------------------------------------------------------------------------
# pipeline inteiro, sem CATMAT
# ---------------------------------------------------------------------------
def test_item_sem_catmat_sai_com_estimativa():
    compras = {"19746": [
        _compra(19746, 29.0, "PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE, "
                "TAMANHO: A4, GRAMATURA: 75 G/M2, COR: BRANCO", "EMB", 500.0),
        _compra(19746, 6.0, "PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE, "
                "TAMANHO: A4, GRAMATURA: 75 G/M2, COR: BRANCO", "EMB", 100.0),
        _compra(19746, 28.0, "PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE, "
                "TAMANHO: A4, GRAMATURA: 75 G/M2, COR: BRANCO", "EMB", 500.0),
    ]}
    item = {"id": "i1", "numero": 1, "codigo": "1", "unidade": "PACOTE",
            "quantidade": "500",
            "descricao": "PAPEL A4 BRANCO. Papel sulfite branco, formato A4, "
                         "gramatura 75 g/m², impressão a laser, pacote "
                         "contendo 500 folhas."}
    resultado = execucao.pesquisar_item(
        item, [ComprasGovAdapter(abrir_url=_api(compras, []))],
        filtros={"data_base": "2026-10-14"})
    estimativa = resultado.estimativa
    assert estimativa and estimativa.valor_unitario is not None
    # EMB de 100 folhas a R$ 6 vira R$ 30 o pacote de 500
    valores = sorted(estimativa.cesta.valores)
    assert valores == [Decimal("28"), Decimal("29"), Decimal("30")]
