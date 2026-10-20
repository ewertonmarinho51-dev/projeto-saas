"""
Segunda auditoria das fontes de preços (18/10/2026) — fase 3.

Textos e números REAIS dos registros de produção que a auditoria conferiu
(docs/auditoria-fontes-precos/segunda-auditoria/), não exemplo inventado:

* N-03 — o Jev gravou "especificação diferente" para o clipe 4/0 na cesta
  do clipe 2/0, e o aviso de emissão recalculava a triagem sem o parecer;
* N-06 — papel A4 "EMB" com capacidade 25 (ou 10: uma caixa de 10
  pacotes lida como 10 folhas) normalizado a R$ 495,00 e R$ 14.029,00 o
  pacote, dentro da cesta;
* N-09 — o caminho que recupera o zero da UASG pelo `idCompraItem` não
  tinha prova: o mutante que o remove sobrevivia.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.precos import busca, ciencia, estatistica, links
from src.precos import repositorio as repo
from src.precos import saneamento, unidades
from src.precos.fontes import ResultadoBusca
from src.precos.modelo import Fonte, NaturezaValor, Referencia, StatusReferencia
from src.precos.perfil import obter as obter_perfil
from src.precos.saneamento import POLITICA_PADRAO

D = Decimal

PAPEL_A4 = ("PAPEL A4 BRANCO. ESPECIFICAÇÃO: Papel sulfite branco, formato A4 "
            "(210 x 297 mm), gramatura 75 g/m², próprio para impressão a laser "
            "e jato de tinta, pacote contendo 500 folhas.")
CLIPE_2_0 = ("CLIPES METÁLICOS Nº 2/0. ESPECIFICAÇÃO: Clipes para papel, "
             "tamanho 2/0, em arame de aço galvanizado, resistentes à oxidação, "
             "acabamento uniforme, caixa contendo 100 unidades.")

# referência 331044bb: EMB, capacidade 25, R$ 24,75 → R$ 495,00 o pacote
A4_EMB_25 = ("Papel Para Impressão Formatado tipo: sulfite/apergaminhado/ofício, "
             "tamanho (c x l): 297 x 210, gramatura: 75, cor: branco, "
             "característica adicional: ph alcalino Papel tamanho A4, cor "
             "branca, gramatura 75\ngramas/metro quadrado, com selo FSC e ou "
             "CERFLOR.\nPacote com 500 folhas. Conforme TR")
# referência bc4c170f: EMB, capacidade 10, R$ 280,58 → R$ 14.029,00
A4_CAIXA_10 = ("Papel Para Impressão Formatado tipo: offset, tamanho (c x l): "
               "297 x 210, gramatura: 75, cor: branco, característica "
               "adicional: personalizado Caixa com 10 unidades de Papel A4, "
               "Ofício, gramatura : 75 g/mZ , cor branco , Comprimento: 297 "
               "MM, Largura: 210 MM pacote com 500 und")
A4_BRANCO = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE/APERGAMINHADO/"
             "OFÍCIO, TAMANHO (C X L): 297 X 210 MM, GRAMATURA: 75 G/M2, COR: "
             "BRANCO")
# referências na cesta do clipe 2/0 com parecer do Jev gravado
CLIPE_4_0 = ("Clipe aplicação: material de expediente, formato: paralelo, "
             "material: arame de aço, tamanho: 4/0, tratamento superficial: "
             "galvanizado CLIPES Nº 4/0 NIQUELADO, CAIXA COM 100 UNIDADES")
CLIPE_2_0_FONTE = ("Clipe aplicação: material de expediente, formato: "
                   "paralelo, material: arame de aço, tamanho: 2/0, tratamento "
                   "superficial: galvanizado CLIPES Nº 2/0 NIQUELADO, CAIXA "
                   "COM 100 UNIDADES")

FONTE = Fonte(id="compras_gov_precos", nome="Compras.gov.br — Preços Praticados",
              tipo="sistema_oficial")


# ---------------------------------------------------------------------------
# N-06 — fator de conversão extremo
# ---------------------------------------------------------------------------
def test_fator_extremo_nos_casos_reais_e_nos_limites():
    assert unidades.fator_extremo("24.75", "495") == D("0.05")
    assert unidades.fator_extremo("280.58", "14029") == D("0.02")
    # os limites entram: 10× e 0,1×
    assert unidades.fator_extremo("50", "5") == D("10")
    assert unidades.fator_extremo("5", "50") == D("0.1")
    # perto do limite, não
    assert unidades.fator_extremo("49.95", "5") is None
    assert unidades.fator_extremo("5", "49.95") is None
    # EMB de 500 folhas no pacote de 500: fator 1
    assert unidades.fator_extremo("24.10", "24.10") is None
    for ruim in (None, "", "abc", "0", "-3"):
        assert unidades.fator_extremo(ruim, "10") is None
        assert unidades.fator_extremo("10", ruim) is None


def test_a_conversao_real_do_papel_da_o_fator_extremo():
    """A conta do `normalizar` que pôs R$ 14.029,00 na cesta."""
    ref = Referencia(fonte=FONTE, id_externo="bc4c170f", bruto={},
                     descricao_original=A4_CAIXA_10, unidade_original="EMB",
                     capacidade_embalagem=D("10"),
                     valor_unitario_original=D("280.58"),
                     natureza_valor=NaturezaValor.PRATICADO)
    unidades.normalizar(ref, "PACOTE", unidades.conteudo_declarado(PAPEL_A4))
    assert ref.valor_unitario_normalizado == D("14029")
    assert unidades.fator_extremo(ref.valor_unitario_original,
                                  ref.valor_unitario_normalizado) == D("0.02")


class _Fonte:
    fonte = FONTE

    def __init__(self, linhas):
        self._linhas = linhas   # (texto, preço, capacidade)

    def pesquisar(self, consulta) -> ResultadoBusca:
        return ResultadoBusca(fonte=FONTE, referencias=[
            Referencia(fonte=FONTE, id_externo=f"R{i}", bruto={"i": i},
                       descricao_original=texto, unidade_original="EMB",
                       capacidade_embalagem=D(capacidade),
                       quantidade_original=D("10"),
                       valor_unitario_original=D(preco),
                       natureza_valor=NaturezaValor.PRATICADO,
                       orgao=f"ORGAO {i}", ni_fornecedor=f"F{i}", uf="PA",
                       data_compra=date.today() - timedelta(days=10 + i),
                       referencia_externa=f"C{i}")
            for i, (texto, preco, capacidade) in enumerate(self._linhas)])


ITEM_PAPEL = {"id": "it", "numero": 2, "descricao": PAPEL_A4,
              "unidade": "PACOTE", "quantidade": "10"}
NORMAIS = [(A4_BRANCO, p, "500") for p in
           ("24.10", "25.00", "25.46", "26.00", "23.90", "24.80")]


REGRA = ("fator ≥ 10× ou ≤ 0,1× só entra na cesta automática se houver ao "
         "menos 3 referências sem conversão no item e o valor convertido "
         "ficar entre 1/3 e 3× da mediana delas")


def _selecionar(item, fontes, saneamento_ligado, texto_item):
    coleta = busca.coletar(item, fontes, filtros={})
    # piso 0: o texto curto da fonte não alcança o piso de comparabilidade,
    # e aqui só a conversão está em prova
    return coleta, estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil("in_65_2021"), D("0"), teto=15,
        saneamento=POLITICA_PADRAO if saneamento_ligado else None,
        texto_item=texto_item)


@pytest.mark.parametrize("saneamento_ligado", [True, False])
@pytest.mark.parametrize("texto,preco,capacidade,fator,de,para", [
    (A4_EMB_25, "24.75", "25", "0,05", "24,75", "495,00"),
    (A4_CAIXA_10, "280.58", "10", "0,02", "280,58", "14.029,00")])
def test_papel_convertido_longe_dos_pares_vai_para_revisao_n06(
        saneamento_ligado, texto, preco, capacidade, fator, de, para):
    _, escolha = _selecionar(
        ITEM_PAPEL, [_Fonte(NORMAIS + [(texto, preco, capacidade)])],
        saneamento_ligado, PAPEL_A4)
    assert texto not in {r.descricao_original for r in escolha.selecionadas}
    assert len(escolha.selecionadas) == 6
    [retida] = [r for r in escolha.retidas if r.descricao_original == texto]
    assert retida.status == StatusReferencia.REVISAO_MANUAL
    [motivo] = [m for m in retida.motivos if "[conversão extrema]" in m]
    assert f"preço convertido pelo fator {fator} (R$ {de} na unidade da "         f"fonte → R$ {para} na unidade do item)" in motivo
    assert REGRA in motivo
    # os 6 pares estão no pacote de 500 (fator 1): mediana R$ 24,90
    assert "aqui, 6 sem conversão, mediana R$ 24,90" in motivo


def _pasta(sem_as_primeiras: int = 0):
    from tests import saneamento_apoio as apoio

    [item] = [i for i in apoio.itens() if i["item_id"] == "ITEM_03"]
    item = {**item, "quotes": item["quotes"][sem_as_primeiras:]}
    return apoio.item_do_banco(item, 3), apoio.FonteDaFixture(item),         item["description"]


@pytest.mark.parametrize("saneamento_ligado", [True, False])
def test_caixa_com_10_entre_pares_a_6_reais_continua_na_cesta_n06(
        saneamento_ligado):
    """CX com 10 de R$ 60,00 → R$ 6,00, entre 4 pares sem conversão a
    R$ 5,90–6,20: fator 10, legítimo, com respaldo."""
    item, fonte, texto = _pasta()
    coleta, escolha = _selecionar(item, [fonte], saneamento_ligado, texto)
    caixa = next(r for r, _ in coleta.referencias if r.id_externo == "Q03_05")
    assert unidades.fator_extremo(caixa.valor_unitario_original,
                                  caixa.valor_unitario_normalizado) == D("10")
    assert caixa in escolha.selecionadas
    assert not any("[conversão extrema]" in m for m in caixa.motivos)


def test_sem_3_pares_sem_conversao_a_caixa_vai_para_revisao_n06():
    """A mesma caixa, com só 2 referências sem conversão no item."""
    item, fonte, texto = _pasta(sem_as_primeiras=2)
    coleta, escolha = _selecionar(item, [fonte], True, texto)
    caixa = next(r for r, _ in coleta.referencias if r.id_externo == "Q03_05")
    assert caixa not in escolha.selecionadas and caixa in escolha.retidas
    assert caixa.status == StatusReferencia.REVISAO_MANUAL
    [motivo] = [m for m in caixa.motivos if "[conversão extrema]" in m]
    assert REGRA in motivo
    assert "aqui, 2 sem conversão, mediana R$ 6,05" in motivo


def test_respaldo_dos_pares_nos_limites_n06():
    pares = ["6", "6", "6"]
    # dentro da faixa, nos dois limites: 1/3 e 3× da mediana
    assert unidades.conversao_extrema("20", "2", pares) is None
    assert unidades.conversao_extrema("180", "18", pares) is None
    # fora da faixa
    assert unidades.conversao_extrema("19.9", "1.99", pares) is not None
    assert unidades.conversao_extrema("181", "18.1", pares) is not None
    # dois pares não bastam; e só convertidas, nenhum
    assert unidades.conversao_extrema("60", "6", pares[:2]).pares == 2
    sem = unidades.conversao_extrema("60", "6", [])
    assert sem.pares == 0 and sem.mediana is None
    assert "aqui, nenhuma referência sem conversão" in sem.motivo()
    # fator comum não depende de par nenhum
    assert unidades.conversao_extrema("9", "1", []) is None


def _linha(rid, texto, original, normalizado, i, status="selected"):
    return {"id": rid, "fonte_id": "compras_gov_precos", "id_externo": rid,
            "status": status, "descricao_original": texto,
            "valor_unitario_original": original,
            "valor_unitario_normalizado": normalizado,
            "unidade_normalizada": "PACOTE",
            "natureza_valor": NaturezaValor.PRATICADO.value,
            "orgao": f"ORGAO {i}", "ni_fornecedor": f"F{i}",
            "referencia_externa": f"C{i}", "motivos": [],
            "fonte_nome": "Compras.gov.br"}


def test_cesta_antiga_com_fator_extremo_alerta_na_emissao_n06():
    linhas = [_linha(f"n{i}", A4_BRANCO, p, p, i)
              for i, (_, p, _) in enumerate(NORMAIS)]
    linhas.append(_linha("bc4c170f", A4_CAIXA_10, "280.58", "14029", 9))
    alertas = saneamento.alertas_da_cesta(
        [ITEM_PAPEL], {"it": linhas})
    [alerta] = [a for a in alertas if a.referencia_id == "bc4c170f"]
    assert saneamento.FATOR_EXTREMO in alerta.codigos
    assert ("preço convertido pelo fator 0,02 (R$ 280,58 na unidade da fonte "
            "→ R$ 14.029,00 na unidade do item) sem o respaldo de 3 "
            "referências sem conversão na faixa de 1/3 a 3× da mediana (6 sem "
            "conversão, mediana R$ 24,90)") in alerta.mensagem
    # os preços sem conversão não ganham o código
    assert not any(saneamento.FATOR_EXTREMO in a.codigos for a in alertas
                   if a.referencia_id != "bc4c170f")


def test_cesta_so_de_convertidas_alerta_na_emissao_n06():
    """Sem variação estatística e sem par sem conversão, o alerta vem só
    do fator — não depende da triagem achar o preço atípico."""
    linhas = [_linha(f"x{i}", A4_EMB_25, p, str(D(p) * 20), i)
              for i, (_, p, _) in enumerate(NORMAIS)]
    alertas = saneamento.alertas_da_cesta([ITEM_PAPEL], {"it": linhas})
    assert {a.referencia_id for a in alertas} == {l["id"] for l in linhas}
    assert all(a.codigos == [saneamento.FATOR_EXTREMO] for a in alertas)


# ---------------------------------------------------------------------------
# N-03 — parecer "diferente" do Jev no aviso de emissão
# ---------------------------------------------------------------------------
ITEM_CLIPE = {"id": "ic", "numero": 4, "descricao": CLIPE_2_0,
              "unidade": "CAIXA", "quantidade": "20"}


def _cesta_do_clipe():
    precos = ("7.12", "7.95", "7.40", "7.80", "7.30", "7.70")
    linhas = [_linha(f"c{i}", CLIPE_2_0_FONTE, p, p, i)
              for i, p in enumerate(precos)]
    linhas.append(_linha("clipe40", CLIPE_4_0, "7.60", "7.60", 9))
    return linhas


def test_sem_parecer_o_clipe_4_0_passa_calado():
    """O estado de antes: preço no meio da faixa, nenhum alerta."""
    assert saneamento.alertas_da_cesta([ITEM_CLIPE],
                                       {"ic": _cesta_do_clipe()}) == []


@pytest.mark.parametrize("escolha,frase", [
    ("different_specification", "especificação diferente"),
    ("different_product", "produto diferente")])
def test_parecer_diferente_gravado_vira_alerta_de_emissao_n03(escolha, frase):
    linhas = _cesta_do_clipe()
    [alerta] = saneamento.alertas_da_cesta(
        [ITEM_CLIPE], {"ic": linhas}, pareceres={"clipe40": escolha})
    assert alerta.referencia_id == "clipe40" and alerta.numero == 4
    assert saneamento.DIVERGENCIA_JEV in alerta.codigos
    assert f"o Jev registrou parecer de {frase} do item" in alerta.mensagem
    assert "parecer da IA, não decisão" in alerta.mensagem
    # a IA não decide: a referência continua na cesta, como estava
    assert [l["status"] for l in linhas] == ["selected"] * 7


@pytest.mark.parametrize("escolha", ["compatible", "insufficient_information",
                                     "different_unit", ""])
def test_outro_parecer_nao_vira_alerta(escolha):
    assert saneamento.alertas_da_cesta(
        [ITEM_CLIPE], {"ic": _cesta_do_clipe()},
        pareceres={"clipe40": escolha}) == []


def test_vale_o_parecer_mais_recente_de_cada_referencia():
    class _Trilha:
        def pareceres_jev(self, pesquisa_id):
            assert pesquisa_id == "p1"
            return [   # do mais novo ao mais velho, como o banco devolve
                {"referencia_id": "a", "escolha": "compatible"},
                {"referencia_id": "a", "escolha": "different_product"},
                {"referencia_id": "b", "escolha": "different_specification"},
                {"referencia_id": "c", "escolha": None},
                {"referencia_id": "d", "escolha": "inventada"},
                {"referencia_id": None, "escolha": "different_product"}]

    assert ciencia.pareceres_do_jev("p1", _Trilha()) == {
        "a": "compatible", "b": "different_specification"}
    assert ciencia.pareceres_do_jev("p1", object()) == {}


def test_emissao_exige_ciencia_do_parecer_gravado_na_trilha_n03(monkeypatch):
    """Ponta a ponta no banco falso: o evento que `decisoes` grava chega
    à exigência do servidor e à confirmação, com a mesma assinatura."""
    from tests.test_ciencia_emissao import _cotacao, _registrar, _tudo

    _, pesquisa, iid = _cotacao(monkeypatch, ("20.00", "22.00", "24.00",
                                              "26.00", "28.00"))
    pid = str(pesquisa["id"])
    itens, refs = _tudo(pid)
    assert ciencia.exigir(pesquisa, itens, refs, ator="u1",
                          repositorio=repo) is None
    alvo = next(l for l in refs[iid] if l["status"] == "selected")
    repo.registrar_evento(
        pid, "busca_concluida", item_id=iid, automatico=True,
        descricao="Análise de comparabilidade registrada para revisão humana.",
        payload={"pesquisa_id": pid, "item_id": iid,
                 "referencia_id": str(alvo["id"]), "status": "manual_review",
                 "response": {"answers": {"price_reference_mismatch": {
                     "choice": "different_product"}}}},
        idempotency_key="jev:result:prova-n03")
    assert repo.pareceres_jev(pid) == [
        {"criado_em": None, "referencia_id": str(alvo["id"]),
         "escolha": "different_product"}]

    with pytest.raises(ciencia.CienciaNecessaria) as pedido:
        ciencia.exigir(pesquisa, itens, refs, ator="u1", repositorio=repo)
    [alerta] = pedido.value.preparo.alertas
    assert alerta.referencia_id == str(alvo["id"])
    assert saneamento.DIVERGENCIA_JEV in alerta.codigos
    # o aviso da tela lê os mesmos pareceres e chega à mesma assinatura
    aviso = ciencia.preparar(pesquisa, itens, refs, pareceres=ciencia
                             .pareceres_do_jev(pid, repo))
    assert aviso.assinatura == pedido.value.preparo.assinatura
    _registrar(pesquisa, pedido.value.preparo)
    assert ciencia.exigir(pesquisa, itens, refs, ator="u1",
                          repositorio=repo) is not None
    # a referência continua na cesta: só uma pessoa a retira
    assert any(l["id"] == alvo["id"] and l["status"] == "selected"
               for l in repo.listar_referencias(iid))


# ---------------------------------------------------------------------------
# N-09 — o zero da UASG recuperado pelo idCompraItem
# ---------------------------------------------------------------------------
def test_id_compra_recupera_o_zero_so_pelo_id_compra_item_n09():
    # registro do STM sem `codigoUasg`: o único caminho é o idCompraItem
    so_item = {"idCompra": 6000105001912026,
               "idCompraItem": "0600010500191202600193"}
    assert links.id_compra_oficial(so_item) == "06000105001912026"
    r = links.resolver({"fonte_id": "compras_gov_precos", "bruto": so_item})
    assert r.contratacao_url.endswith("?compra=06000105001912026")
    # o idCompraItem também chega com espaço em volta
    assert links.id_compra_oficial(
        {**so_item, "idCompraItem": " 0600010500191202600193 "}) == \
        "06000105001912026"
    # número (não texto) no idCompraItem já perdeu o zero: não serve
    assert links.id_compra_oficial(
        {**so_item, "idCompraItem": 600010500191202600193}) == ""
