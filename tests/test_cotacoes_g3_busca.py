"""
G3 — busca completa: nada de elegível inventado, fontes rastreáveis e
quatro diagnósticos que não se confundem (pacote, `07_GATES` G3; dossiê
BP J15: 11 "aparentados" para um item fictício).

Banco falso e fontes dublês; o motor semântico é um dublê que devolve
palavras — nenhuma chamada de IA.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.precos import cotacoes, filtros
from src.precos import repositorio as repo
from src.precos.modelo import Fonte, NaturezaValor, Referencia
from tests.cotacoes_apoio import ligar_banco_falso, linha, referencia
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte
from tests.test_precos_fase4 import _FonteFalsa

PRECOS = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
               "sistema_oficial")
PNCP = Fonte("pncp", "PNCP", "sistema_oficial")


def _cotacao(monkeypatch, item=ITEM):
    cliente = ligar_banco_falso(monkeypatch)
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "G3"})
    criado = cotacoes.salvar_item(CTX, str(cotacao["id"]), item)
    return cliente, str(cotacao["id"]), str(criado["id"])


class _MotorDuble:
    """Sugere sinônimos 'generosos' — o pior caso para falso positivo."""

    def __init__(self, termos):
        self.termos = termos
        self.chamadas = 0


def test_item_ficticio_com_11_vizinhos_da_zero_elegiveis(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch, {
        "descricao": "PARAFUSO TITANIO XQ9Z", "unidade": "UNIDADE",
        "quantidade": "10"})
    vizinhos = [referencia(f"{1 + i / 10:.2f}", f"v{i}", unidade="UNIDADE",
                           descricao=d)
                for i, d in enumerate([
                    "PARAFUSO SEXTAVADO ZINCADO M6", "PARAFUSO 9X-6380",
                    "ESPATULA TITANIO N 9", "PARAFUSO FENDA FERRO",
                    "BUCHA NYLON 8MM", "PORCA SEXTAVADA M8",
                    "ARRUELA LISA ZINCADA", "PARAFUSO AUTOATARRAXANTE",
                    "BROCA TITANIO 6MM", "PARAFUSO ALLEN M5",
                    "PREGO COM CABECA 17X21"])]
    for modo in ("automatico", "manual"):
        r = cotacoes.pesquisar_item(
            CTX, cid, iid, modo=modo, fontes=[_FonteFalsa(PRECOS, vizinhos)])
        assert r.unicas == 11
        assert r.elegiveis == 0, "vizinho não é elegível"
        assert r.consideradas == 0
        assert r.diagnostico == "sem_comparaveis"
    assert not [x for x in repo.listar_referencias(iid)
                if x["status"] == "selected"]
    assert repo.obter_item(iid)["preco_estimado"] is None


def test_ampliacao_semantica_so_quando_nao_literal_e_registrada(monkeypatch):
    from src.precos import semantica

    chamadas = []

    def sugerir(motor, item, limite=8):
        chamadas.append(item["descricao"])
        return ["PAPEL A4", "PAPEL OFICIO"]

    monkeypatch.setattr(semantica, "sugerir_termos", sugerir)
    cliente, cid, iid = _cotacao(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[_fonte()],
                            filtros={"literal": True}, motor_semantico=object())
    assert chamadas == []
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[_fonte()],
                                filtros={"literal": False},
                                motor_semantico=object())
    assert chamadas == [ITEM["descricao"]]
    assert r.termos == ["PAPEL A4", "PAPEL OFICIO"]
    ultimo = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
              if e["tipo"] == "busca_concluida"][-1]
    assert ultimo["payload"]["termos_extras"] == ["PAPEL A4", "PAPEL OFICIO"]
    assert ultimo["payload"]["filtros"]["literal"] is False


def _mesma_compra(fonte, ident, chave_compra):
    ref = referencia("30.00", ident)
    ref.fonte = fonte
    ref.ni_fornecedor = "12345678000199"
    ref.bruto = {chave_compra: "CMP-1", "id": ident}
    return ref


def test_mesma_compra_em_dois_portais_conta_uma_vez(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch)
    r = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[_FonteFalsa(PRECOS, [_mesma_compra(PRECOS, "a", "idCompra")]),
                _FonteFalsa(PNCP, [_mesma_compra(PNCP, "b", "idCompraOrigem")])])
    assert r.brutas == 2 and r.unicas == 1, "fundidas antes de contar"
    linhas = repo.listar_referencias(iid)
    assert len(linhas) == 1, "a cópia do outro portal não vira 2º preço"
    assert any("também publicada em PNCP" in m for m in linhas[0]["motivos"])
    assert any("mesma compra em dois portais" in o for o in r.ocorrencias)


def test_estimado_de_origem_nao_entra_na_cesta_nem_por_clique(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch)
    estimado = referencia("99.00", "est", natureza=NaturezaValor.ESTIMADO_ORIGEM)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[_FonteFalsa(PRECOS, [estimado])])
    [linha_est] = repo.listar_referencias(iid)
    assert linha_est["status"] != "selected"
    try:
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(linha_est["id"]),
                                           incluir=True, motivo="quero")
    except cotacoes.ErroCotacao as erro:
        assert "não é preço praticado" in str(erro)
    else:
        raise AssertionError("estimativa de outro órgão entrou na cesta")


def test_quatro_diagnosticos_distintos(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch)
    assert cotacoes.pesquisar_item(
        CTX, cid, iid, fontes=[_fonte(explode=True)]).diagnostico == \
        "fonte_indisponivel"
    assert cotacoes.pesquisar_item(
        CTX, cid, iid, fontes=[_FonteFalsa(PRECOS, [])]).diagnostico == \
        "zero_resultados"
    assert cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[_fonte(("20.00", "21.00"))]).diagnostico == "amostra_insuficiente"
    assert cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico", fontes=[_fonte()]).diagnostico == "ok"
    textos = {cotacoes.DIAGNOSTICOS[k] for k in
              ("fonte_indisponivel", "zero_resultados", "sem_comparaveis",
               "amostra_insuficiente")}
    assert len(textos) == 4


def test_uma_fonte_fora_nao_vira_falha_tecnica_do_item(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch)
    fora = _FonteFalsa(PNCP, explode=True)
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[_fonte(), fora])
    assert r.diagnostico == "ok"
    assert r.desfechos["pncp"] == "failure"
    assert any("PNCP: indisponível" in o for o in r.ocorrencias)
    assert repo.obter_item(iid)["desfechos"]["pncp"] == "failure"


def test_filtro_de_fontes_antes_da_busca(monkeypatch):
    _, cid, iid = _cotacao(monkeypatch)
    outra = _FonteFalsa(PNCP, [referencia("10.00", "p1")])
    principal = _fonte()
    cotacoes.pesquisar_item(CTX, cid, iid, fontes=[principal, outra],
                            filtros={"fontes": ["compras_gov_precos"]})
    assert principal.chamadas == 1 and outra.chamadas == 0


def test_filtros_pos_busca_natureza_preco_e_consideradas():
    linhas = [linha("10.00"), linha("20.00"), linha("30.00", "candidate"),
              linha("40.00", "selected", natureza="estimado_origem")]
    f = filtros.Filtros(naturezas={"estimado_origem"})
    assert [x["valor_unitario_normalizado"] for x in filtros.aplicar(linhas, f)] \
        == ["40.00"]
    f = filtros.Filtros(preco_minimo=Decimal("15"), preco_maximo=Decimal("35"))
    assert len(filtros.aplicar(linhas, f)) == 2
    f = filtros.Filtros(somente_consideradas=True)
    assert len(filtros.aplicar(linhas, f)) == 2
    assert len(linhas) == 4, "filtro esconde, nunca apaga"


def test_a_busca_registrada_reabre_com_horario_e_contagens(monkeypatch):
    cliente, cid, iid = _cotacao(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[_fonte()],
                            termo="papel a4")
    [evento] = [e for e in repo.listar_eventos(cid)
                if e["tipo"] == "busca_concluida"]
    p = evento["payload"]
    assert p["termo"] == "papel a4" and p["termos_extras"] == ["papel a4"]
    assert (p["brutas"], p["unicas"], p["consideradas"]) == (5, 5, 5)
    assert p["em"] and p["desfechos"]["compras_gov_precos"] == \
        "success_with_prices"
    assert evento["item_id"] == iid
