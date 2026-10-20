"""
Pesquisa de Preços: janela de 180 dias e CATMAT (14/10/2026).

A pesquisa travava ~2 min por item e terminava em erro: o número da
planilha ("1") ia à API como CATMAT, e o caminho por descrição pedia a
janela inteira de contratações (365 dias, 51 s; 180 dias, >100 s). Com o
CATMAT, 180 dias de preços praticados voltam em ~1,5 s.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src import db
from src.precos import catalogo, execucao, repositorio
from src.precos.estados import EstadoItem


# ---------------------------------------------------------------------------
# janela de 180 dias
# ---------------------------------------------------------------------------
def test_janela_padrao_e_a_validade_das_cotacoes():
    assert execucao.JANELA_PADRAO_DIAS == 180
    assert execucao.janela_efetiva({}) == 180


def test_pesquisa_gravada_com_365_dias_consulta_180():
    assert execucao.janela_efetiva({"janela_dias": 365}) == 180
    assert execucao.janela_efetiva({"janela_dias": 90}) == 90


def test_a_consulta_leva_a_janela_efetiva():
    consulta = execucao.consulta_do_item(
        {"descricao": "CANETA", "codigo": "275111", "tipo_catalogo": "CATMAT"},
        {"janela_dias": 365, "data_base": "2026-10-14"})
    assert consulta.data_final == date(2026, 10, 14)
    assert (consulta.data_final - consulta.data_inicial).days == 180


# ---------------------------------------------------------------------------
# o código da planilha nem sempre é CATMAT
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("item,esperado", [
    ({"codigo": "1"}, None),                                  # nº da planilha
    ({"codigo": "12"}, None),
    ({"codigo": ""}, None),
    ({"codigo": "275111"}, "275111"),                         # forma de CATMAT
    ({"codigo": "3379", "tipo_catalogo": "CATSER"}, "3379"),  # tipo declarado
    ({"codigo": "ABC-12"}, None),
])
def test_codigo_de_catalogo(item, esperado):
    assert execucao.codigo_de_catalogo(item) == esperado


def test_numero_da_planilha_nao_vai_a_api_como_catmat():
    consulta = execucao.consulta_do_item({"descricao": "CANETA", "codigo": "1"})
    assert not consulta.tem_codigo


# ---------------------------------------------------------------------------
# sugestão de CATMAT (catálogo oficial, determinística)
# ---------------------------------------------------------------------------
def _catalogo_falso(tmp_path, chamadas):
    pdms = {"resultado": [
        {"codigoPdm": 1, "nomePdm": "CANETA ESFEROGRÁFICA", "nomeClasse": "ESCRITÓRIO"},
        {"codigoPdm": 2, "nomePdm": "CARTUCHO CANETA TINTEIRO", "nomeClasse": "ESCRITÓRIO"},
        {"codigoPdm": 3, "nomePdm": "GRAMPEADOR", "nomeClasse": "ESCRITÓRIO"},
    ], "totalPaginas": 1}
    itens = {
        "1": [{"codigoItem": 275111, "descricaoItem":
               "CANETA ESFEROGRÁFICA, MATERIAL: PLÁSTICO, COR TINTA: AZUL, "
               "ESPESSURA ESCRITA: MÉDIA 1,0 MM"},
              {"codigoItem": 279314, "descricaoItem":
               "CANETA ESFEROGRÁFICA, MATERIAL: PLÁSTICO, COR TINTA: PRETA"}],
        "2": [{"codigoItem": 100001, "descricaoItem": "CARTUCHO CANETA TINTEIRO"}],
        "3": [{"codigoItem": 274954, "descricaoItem": "GRAMPEADOR, TIPO: MESA"}],
    }

    def abrir(url):
        chamadas.append(url)
        if "3_consultarPdmMaterial" in url:
            return json.dumps(pdms)
        pdm = url.split("codigoPdm=")[1].split("&")[0]
        return json.dumps({"resultado": itens.get(pdm, [])})

    return catalogo.Catalogo(abrir_url=abrir,
                             arquivo_indice=str(tmp_path / "pdms.json"))


def test_sugere_o_catmat_mais_aderente_primeiro(tmp_path):
    chamadas: list[str] = []
    candidatos = _catalogo_falso(tmp_path, chamadas).sugerir(
        "CANETA ESFEROGRÁFICA AZUL, tinta azul, ponta média de 1,0 mm")
    assert candidatos[0].codigo == "275111"
    assert candidatos[0].pdm == "CANETA ESFEROGRÁFICA"
    assert all(c.codigo != "274954" for c in candidatos), "grampeador não"


def test_o_indice_de_pdms_fica_em_disco(tmp_path):
    chamadas: list[str] = []
    _catalogo_falso(tmp_path, chamadas).sugerir("GRAMPEADOR de mesa")
    pdms_antes = sum("3_consultarPdmMaterial" in u for u in chamadas)
    _catalogo_falso(tmp_path, chamadas).sugerir("GRAMPEADOR de mesa")
    assert sum("3_consultarPdmMaterial" in u for u in chamadas) == pdms_antes


def test_termo_curto_com_digito_conta(tmp_path):
    """"A4" sumia no tokenizador e o papel A4 virava papel almaço."""
    assert "A4" in catalogo._termos("PAPEL A4 sulfite 75 g/m2")


def test_catalogo_fora_do_ar_vira_erro_claro_e_nao_candidato(tmp_path):
    def cai(_url):
        raise TimeoutError("lento")

    with pytest.raises(catalogo.ErroCatalogo, match="não respondeu"):
        catalogo.Catalogo(abrir_url=cai,
                          arquivo_indice=str(tmp_path / "x.json")).sugerir(
            "CANETA AZUL")


# ---------------------------------------------------------------------------
# gravar a escolha do servidor
# ---------------------------------------------------------------------------
def test_definir_catalogo_recusa_codigo_nao_numerico():
    with pytest.raises(db.ErroBanco):
        repositorio.definir_catalogo({"id": "i1", "estado": "pending"}, "abc")


def test_definir_catalogo_devolve_item_incompleto_a_fila(monkeypatch):
    movidos = []
    monkeypatch.setattr(repositorio, "mover_item",
                        lambda item_id, destino, atual, **campos:
                        movidos.append((item_id, destino, atual, campos)) or {})
    repositorio.definir_catalogo(
        {"id": "i1", "estado": EstadoItem.INCOMPLETO.value}, "275111")
    item_id, destino, atual, campos = movidos[0]
    assert destino is EstadoItem.BUSCANDO and atual is EstadoItem.INCOMPLETO
    assert campos["codigo"] == "275111" and campos["tipo_catalogo"] == "CATMAT"


def test_a_triagem_pede_catalogo_quando_o_codigo_e_o_numero_da_planilha():
    import inspect

    from src.precos import decisoes

    fonte = inspect.getsource(decisoes)
    assert "codigo_de_catalogo(item)" in fonte
