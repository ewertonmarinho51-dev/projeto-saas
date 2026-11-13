"""
Consultas repetidas entre as fases da expansão (13/11/2026).

A fase seguinte (`expansao.Plano`) chama a fonte com os termos de antes
MAIS os novos. Com a memória da execução (`fontes.com_memoria`, e por URL no
Compras.gov), só as variantes NOVAS vão à fonte; a exceção não é guardada.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.precos import fontes
from src.precos.compras_gov import ComprasGovAdapter
from src.precos.fontes import Consulta, ResultadoBusca
from src.precos.pncp_indice import PNCPIndice


def test_memoria_devolve_a_mesma_resposta_sem_repetir():
    chamadas = []

    def buscar(termos, *, uf=None, limite=50):
        chamadas.append(list(termos))
        return [{"id": len(chamadas)}]

    memo = fontes.com_memoria(buscar)
    a = memo(["cimento", "portland"], uf="PA", limite=50)
    b = memo(["cimento", "portland"], limite=50, uf="PA")
    c = memo(["cimento"], uf="PA", limite=50)
    assert a == b == [{"id": 1}] and c == [{"id": 2}]
    assert chamadas == [["cimento", "portland"], ["cimento"]]
    assert memo.reaproveitadas == 1
    a.append("mexido")                       # quem chama não estraga a memória
    assert memo(["cimento", "portland"], uf="PA", limite=50) == [{"id": 1}]


def test_memoria_nao_guarda_falha():
    estado = {"n": 0}

    def buscar(termos):
        estado["n"] += 1
        if estado["n"] == 1:
            raise RuntimeError("fora do ar")
        return ["ok"]

    memo = fontes.com_memoria(buscar)
    with pytest.raises(RuntimeError):
        memo(["x"])
    assert memo(["x"]) == ["ok"] and estado["n"] == 2


def test_indice_pncp_na_segunda_fase_so_consulta_a_variante_nova():
    grupos = []

    def buscar(termos, *, uf=None, desde=None, ate=None, limite=50):
        grupos.append(tuple(termos))
        return []

    fonte = PNCPIndice(buscar)
    janela = dict(data_inicial=date(2025, 11, 13), data_final=date(2026, 11, 13))
    fonte.pesquisar(Consulta(descricao="Analisador bioquímico", **janela))
    fonte.pesquisar(Consulta(descricao="Analisador bioquímico",
                             termos_alternativos=("analisador de bioquímica",),
                             **janela))
    assert len(grupos) == 2                  # 1ª fase: descrição; 2ª: só a variante
    assert len(set(grupos)) == 2


def test_compras_gov_nao_repete_a_mesma_url_na_execucao():
    urls = []

    def abrir(url):
        urls.append(url)
        return json.dumps({"resultado": [], "totalRegistros": 0})

    adapter = ComprasGovAdapter(abrir_url=abrir)
    r = ResultadoBusca(fonte=adapter.fonte)
    primeira = adapter._obter("/modulo-pesquisa-preco/1_consultarMaterial",
                              {"codigoItemCatalogo": 275111, "pagina": 1}, r)
    segunda = adapter._obter("/modulo-pesquisa-preco/1_consultarMaterial",
                             {"codigoItemCatalogo": 275111, "pagina": 1}, r)
    assert primeira == segunda and len(urls) == 1
    assert adapter.reaproveitadas == 1 and r.chamadas == 1
    # outra instância (outra execução) vai à fonte de novo
    ComprasGovAdapter(abrir_url=abrir)._obter(
        "/modulo-pesquisa-preco/1_consultarMaterial",
        {"codigoItemCatalogo": 275111, "pagina": 1}, r)
    assert len(urls) == 2
