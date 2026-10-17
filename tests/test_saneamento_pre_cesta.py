"""
Saneamento pré-cesta (pacote Jev de 17/10/2026, objetivo A).

T01–T15 do plano de testes do pacote e a massa SINTÉTICA de 15 itens,
pelo caminho real: `busca.coletar` (procedência, deduplicação,
`unidades.normalizar`, comparabilidade) → `estatistica.selecionar_cesta`
com a política de saneamento → `cotacoes.pesquisar_item` no banco falso.
Nenhuma rede, nenhuma IA: o Jev entra como resposta simulada no contrato
fechado (`decisoes.MOTIVOS`).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.precos import busca, cotacoes, estatistica, saneamento, seletor
from src.precos import repositorio as repo
from src.precos.perfil import obter as obter_perfil
from src.precos.saneamento import (DESCONSIDERADA, ELEGIVEL, REVISAO,
                                   Observacao, avaliar)
from tests import saneamento_apoio as apoio
from tests.cotacoes_apoio import ligar_banco_falso

D = Decimal


def _obs(valores, *, origens=None, textos=None, dup=None, jev=None):
    """Observações independentes (uma origem cada, salvo `origens`)."""
    saida = []
    for i, v in enumerate(valores):
        valor = None if v is None else D(str(v))
        saida.append(Observacao(
            id=f"q{i}", valor=valor if valor is None or valor > 0 else valor,
            valor_original=valor,
            origem=(origens or {}).get(i, f"orgao{i}|forn{i}"),
            duplicidade=(dup or {}).get(i),
            texto=(textos or {}).get(i, "PRODUTO"),
            jev=(jev or {}).get(i, "")))
    return saida


def _desfechos(triagem) -> list[str]:
    return [a.desfecho for a in triagem.avaliacoes]


# ---------------------------------------------------------------------------
# T01–T15
# ---------------------------------------------------------------------------
def test_t01_extremo_corroborado_e_desconsiderado_so_ele():
    t = avaliar(_obs(["10", "10.20", "9.80", "10.10", "45"]))
    assert _desfechos(t) == [ELEGIVEL] * 4 + [DESCONSIDERADA]
    extremo = t.avaliacoes[-1]
    assert saneamento.EXTREMO in extremo.codigos
    assert saneamento.CORROBORADO in extremo.codigos
    # métrica efetiva conferida, não ilustrativa: mediana 10,10; MAD 0,10
    assert extremo.metricas["mediana"] == "10.1"
    assert extremo.metricas["mad"] == "0.1"
    assert D(extremo.metricas["z_modificado"]) == \
        (D("0.6745") * (D("45") - D("10.10")) / D("0.10")).quantize(D("0.0001"))


def test_t02_caixa_de_dez_e_normalizada_e_nao_descartada():
    [item] = [i for i in apoio.itens() if i["item_id"] == "ITEM_03"]
    coleta = busca.coletar(apoio.item_do_banco(item, 3),
                           [apoio.FonteDaFixture(item)], filtros={})
    caixa = next(r for r, _ in coleta.referencias if r.id_externo == "Q03_05")
    assert caixa.valor_unitario_normalizado == D("6")
    cesta = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil(None),
        saneamento=saneamento.POLITICA_PADRAO, texto_item=item["description"])
    assert caixa in cesta.selecionadas


def test_t03_total_como_unitario_sem_fator_vai_para_revisao():
    """Sem quantitativo comprovado o preço não é convertido nem descartado
    em definitivo: revisão (a fonte pode ter o fator)."""
    obs = _obs(["6", "6.10", "5.90", "6.20"]) + [Observacao(
        id="total", valor=None, valor_original=D("600"), origem="o9|f9",
        unidade_recuperavel=True)]
    t = avaliar(obs)
    assert t.por_id()["total"].desfecho == REVISAO
    assert saneamento.UNIDADE_NAO_CONVERSIVEL in t.por_id()["total"].codigos


def test_t04_escopo_incompativel_hora_por_mes_e_desconsiderado():
    [item] = [i for i in apoio.itens() if i["item_id"] == "ITEM_04"]
    coleta = busca.coletar(apoio.item_do_banco(item, 4),
                           [apoio.FonteDaFixture(item)], filtros={})
    cesta = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil(None),
        saneamento=saneamento.POLITICA_PADRAO, texto_item=item["description"])
    hora = next(r for r, _ in coleta.referencias if r.id_externo == "Q04_05")
    assert hora not in cesta.selecionadas
    # unidade incompatível já ficava fora antes: com teto, só contada
    assert hora not in cesta.retidas
    assert hora.status.value == "rejected"
    assert any(m.startswith(saneamento.ROTULO_DESCONSIDERADA)
               for m in hora.motivos)
    assert cesta.triagem.por_id()[hora.chave_dedupe].codigos == \
        [saneamento.UNIDADE_NAO_CONVERSIVEL]


def test_t05_mesma_linha_do_documento_conta_uma_vez_e_fica_preservada():
    t = avaliar(_obs(["45", "46", "47", "44", "46"],
                     dup={1: "DOC|L1|46", 4: "DOC|L1|46"}))
    assert _desfechos(t) == [ELEGIVEL] * 4 + [DESCONSIDERADA]
    assert t.avaliacoes[-1].codigos == [saneamento.DUPLICIDADE]
    assert t.serie["n"] == 4, "a duplicata não entra na estatística"


def test_t06_mad_zero_sem_divisao_por_zero_e_com_corroboracao():
    t = avaliar(_obs(["10", "10", "10", "10", "200"]))
    assert t.serie["mad"] == "0"
    extremo = t.avaliacoes[-1]
    assert extremo.desfecho == DESCONSIDERADA
    assert extremo.metricas["z_modificado"] is None
    assert "mad_zero" in extremo.metricas["criterios"]
    # e sem descarte aleatório: os iguais à mediana ficam
    assert _desfechos(t)[:4] == [ELEGIVEL] * 4


def test_t07_dois_precos_distantes_nao_descartam_vao_a_revisao():
    t = avaliar(_obs(["10", "80"]))
    assert _desfechos(t) == [REVISAO, REVISAO]
    assert all(saneamento.DISPERSAO_INCONCLUSIVA in a.codigos
               for a in t.avaliacoes)


@pytest.mark.parametrize("valor", ["0", "-4"])
def test_t08_zero_ou_negativo_nao_entra(valor):
    t = avaliar(_obs(["7", "7.2", "6.8", valor]))
    assert t.avaliacoes[-1].desfecho == DESCONSIDERADA
    assert t.avaliacoes[-1].codigos == [saneamento.VALOR_INVALIDO]


def test_t08_texto_invalido_nao_vira_preco():
    assert saneamento._decimal("abc") is None
    assert saneamento._decimal("NaN") is None
    t = avaliar([Observacao("x", None, valor_original=None)])
    assert t.avaliacoes[0].codigos == [saneamento.VALOR_INVALIDO]


def test_t09_condicao_comercial_diferente_vai_a_revisao():
    t = avaliar(_obs(["1000", "1020", "980", "1010", "1600"],
                     textos={4: "ENTREGA — 500KM ADICIONAIS"}),
                texto_item="SERVICO DE ENTREGA LOCAL")
    assert t.avaliacoes[-1].desfecho == REVISAO
    assert saneamento.CONTEXTO_COMERCIAL in t.avaliacoes[-1].codigos
    assert "quilometragem" in t.avaliacoes[-1].explicacao


def test_t10_premium_legitimo_nao_e_eliminado_pela_distancia():
    t = avaliar(_obs(["100", "102", "98", "101", "400"],
                     textos={4: "CADEIRA MODELO PREMIUM"}))
    assert t.avaliacoes[-1].desfecho == REVISAO
    assert saneamento.CONTEXTO_COMERCIAL in t.avaliacoes[-1].codigos


def test_t10_desvio_pequeno_em_serie_apertada_nao_e_descartado():
    """z e IQR altos, mas 4% acima: dispersão, não erro — fica na cesta."""
    t = avaliar(_obs(["100", "100.5", "101", "100.2", "104"]))
    assert t.avaliacoes[-1].desfecho != DESCONSIDERADA


def test_t11_quinze_itens_simultaneos_sem_vazamento_de_amostra():
    """Cada item com a SUA série; nenhuma referência de um item aparece
    na estatística de outro (15 itens ≠ 15 preços)."""
    series = {}
    for numero, item in enumerate(apoio.itens(), start=1):
        coleta = busca.coletar(apoio.item_do_banco(item, numero),
                               [apoio.FonteDaFixture(item)], filtros={})
        cesta = estatistica.selecionar_cesta(
            coleta.referencias, obter_perfil(None),
            saneamento=saneamento.POLITICA_PADRAO,
            texto_item=item["description"])
        ids = {a.id for a in cesta.triagem.avaliacoes}
        assert all(i.startswith(f"compras_gov_precos:Q{item['item_id'][-2:]}_")
                   for i in ids), item["item_id"]
        series[item["item_id"]] = cesta.triagem.serie.get("mediana")
    assert series["ITEM_07"] == "59"
    assert series["ITEM_01"] != series["ITEM_02"]
    assert len(series) == 15


def test_t13_versao_da_politica_e_gravada_e_mudar_limiar_exige_versao():
    t = avaliar(_obs(["10", "10", "10", "10", "45"]))
    assert t.versao == saneamento.VERSAO_POLITICA
    outra = saneamento.PoliticaSaneamento(versao="teste.v2",
                                         autoexclusao_estatistica=False)
    t2 = avaliar(_obs(["10", "10", "10", "10", "45"]), outra)
    assert t2.versao == "teste.v2"
    assert t2.avaliacoes[-1].desfecho == REVISAO, \
        "política sem autoexclusão: revisão, nunca descarte"


def test_t14_nenhuma_cotacao_utilizavel_nao_inventa_preco():
    t = avaliar(_obs([None, "0", "-1"]))
    assert ELEGIVEL not in _desfechos(t)
    assert t.serie == {}
    cesta = estatistica.Cesta()
    assert estatistica.estimar(cesta).valor_unitario is None


def test_t15_centavos_em_decimal_sem_float():
    t = avaliar(_obs(["1234.56", "1234.57", "1234.55", "1234.56", "1234.58"]))
    assert all(isinstance(a.valor, Decimal) for a in t.avaliacoes)
    assert t.serie["mediana"] == "1234.56"
    registro = json.dumps(t.para_registro(so_retidas=False))
    assert "1234.56" in registro and "e-" not in registro


def test_poucos_precos_com_um_destoante_so_ele_vai_a_revisao():
    t = avaliar(_obs(["10", "10.5", "80"]))
    assert _desfechos(t) == [ELEGIVEL, ELEGIVEL, REVISAO]
    assert saneamento.AMOSTRA_PEQUENA in t.avaliacoes[-1].codigos


def test_extremo_sem_origens_independentes_vai_a_revisao():
    """Quatro preços do MESMO órgão e fornecedor não corroboram nada."""
    t = avaliar(_obs(["10", "10.1", "9.9", "10", "45"],
                     origens={0: "o|f", 1: "o|f", 2: "o|f", 3: "o|f"}))
    assert t.avaliacoes[-1].desfecho == REVISAO
    assert saneamento.SEM_CORROBORACAO in t.avaliacoes[-1].codigos


def test_jev_sozinho_nunca_descarta():
    t = avaliar(_obs(["10", "10.1", "9.9", "10", "10.2"],
                     jev={2: "different_product"}))
    assert t.avaliacoes[2].desfecho == REVISAO
    assert saneamento.DIVERGENCIA_JEV in t.avaliacoes[2].codigos
    assert DESCONSIDERADA not in _desfechos(t)


def test_jev_mais_estatistica_corroborada_desconsidera():
    t = avaliar(_obs(["3450", "3520", "3490", "3510", "9000"],
                     jev={4: "different_specification"}))
    assert t.avaliacoes[-1].desfecho == DESCONSIDERADA
    assert {saneamento.DIVERGENCIA_JEV, saneamento.CORROBORADO} <= \
        set(t.avaliacoes[-1].codigos)


def test_jev_duvida_de_informacao_leva_a_revisao_sem_descartar():
    t = avaliar(_obs(["10", "10.1", "9.9", "10", "45"],
                     jev={4: "insufficient_information"}))
    # extremo corroborado continua desconsiderado; a dúvida do Jev não o salva
    assert t.avaliacoes[-1].desfecho == DESCONSIDERADA
    t2 = avaliar(_obs(["10", "10.1", "9.9", "10", "10.3"],
                      jev={4: "insufficient_information"}))
    assert t2.avaliacoes[-1].desfecho == REVISAO


def test_linguagem_nao_afirma_sobrepreco_nem_inexequibilidade():
    t = avaliar(_obs(["10", "10", "10", "10", "200"]))
    texto = " ".join(a.explicacao for a in t.avaliacoes).lower()
    assert "inexequ" not in texto and "sobrepreço" not in texto
    assert "ilegal" not in texto


def test_seletor_guarda_a_escolha_fechada_do_jev():
    registro = {"called": True, "response": {"answers": {
        "price_reference_mismatch": {"choice": "different_specification"}}}}
    assert seletor._escolha(registro) == "different_specification"
    assert seletor._escolha({"response": {"answers": {
        "price_reference_mismatch": {"choice": "invente"}}}}) == ""


# ---------------------------------------------------------------------------
# A massa de 15 itens — pelo caminho real, item a item
# ---------------------------------------------------------------------------
def _triagem_do_item(item: dict, numero: int):
    coleta = busca.coletar(apoio.item_do_banco(item, numero),
                           [apoio.FonteDaFixture(item)], filtros={})
    cesta = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil(None),
        saneamento=saneamento.POLITICA_PADRAO, texto_item=item["description"])
    por_id = cesta.triagem.por_id()
    desfechos = {}
    for ref, _ in coleta.referencias:
        avaliacao = por_id.get(ref.chave_dedupe)
        escolha = apoio.JEV_SIMULADO.get(ref.id_externo)
        if avaliacao is not None and escolha:
            avaliacao = saneamento.reavaliar_com_jev(avaliacao, escolha)
        desfechos[ref.id_externo] = (avaliacao.desfecho if avaliacao
                                     else "fora_do_piso")
    return desfechos, coleta


@pytest.mark.parametrize("numero,item", list(enumerate(apoio.itens(), start=1)),
                         ids=[i["item_id"] for i in apoio.itens()])
def test_massa_de_15_itens_confere_com_o_esperado(numero, item):
    desfechos, coleta = _triagem_do_item(item, numero)
    esperado = apoio.esperado(item)
    for cotacao in esperado["prebasket_exclude_if_verified"]:
        assert desfechos[cotacao] == DESCONSIDERADA, cotacao
    for cotacao in esperado["needs_review_or_alert"]:
        assert desfechos[cotacao] == REVISAO, cotacao
    for cotacao in esperado["normalization_or_keep"]:
        assert desfechos[cotacao] == ELEGIVEL, cotacao
        ref = next(r for r, _ in coleta.referencias if r.id_externo == cotacao)
        assert ref.valor_unitario_normalizado is not None
    citadas = set(esperado["prebasket_exclude_if_verified"]) | \
        set(esperado["needs_review_or_alert"])
    for cotacao, desfecho in desfechos.items():
        if cotacao not in citadas:
            assert desfecho == ELEGIVEL, (cotacao, desfecho)


def test_item_05_pacote_de_500_vira_preco_por_folha():
    [item] = [i for i in apoio.itens() if i["item_id"] == "ITEM_05"]
    _, coleta = _triagem_do_item(item, 5)
    pacote = next(r for r, _ in coleta.referencias if r.id_externo == "Q05_05")
    assert pacote.valor_unitario_normalizado == D("1")


# ---------------------------------------------------------------------------
# Integração: cotacoes.pesquisar_item no banco falso (T12, retenção, Jev)
# ---------------------------------------------------------------------------
CTX = cotacoes.Contexto(auth_user_id="u1")


def _cotacao(monkeypatch, item_fixture: dict):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Saneamento"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), {
        "descricao": item_fixture["description"],
        "unidade": item_fixture["target_unit"], "quantidade": "10"})
    return cliente, str(c["id"]), str(item["id"])


def _item(item_id: str) -> dict:
    return next(i for i in apoio.itens() if i["item_id"] == item_id)


def test_integracao_retem_com_fundamento_e_nao_poe_na_cesta(monkeypatch):
    fixture = _item("ITEM_01")
    cliente, cid, iid = _cotacao(monkeypatch, fixture)
    resultado = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[apoio.FonteDaFixture(fixture)],
        triagem=saneamento.POLITICA_PADRAO)
    linhas = repo.listar_referencias(iid)
    extremo = next(l for l in linhas if l["id_externo"] == "Q01_05")
    assert extremo["status"] == "rejected"
    assert saneamento.desconsiderada_pelo_jev(extremo)
    assert "190" in str(extremo["valor_unitario_original"]), "dado bruto preservado"
    assert resultado.consideradas == 4
    item = repo.obter_item(iid)
    assert D(str(item["preco_estimado"])) == D("25.28")   # (25+24,80+26+25,30)/4
    [evento] = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == "busca_concluida"]
    triagem = evento["payload"]["saneamento"]
    assert triagem["versao"] == saneamento.VERSAO_POLITICA
    assert triagem["contagem"][DESCONSIDERADA] == 1
    assert triagem["resumo"] == {"encontrados": 5, "incluidos": 4,
                                 "desconsiderados": 1, "revisao": 0}
    [retida] = triagem["avaliacoes"]
    assert retida["metricas"]["mediana"] and retida["codigos"]


def test_integracao_com_teto_grava_a_retida_e_nao_a_rebaixa(monkeypatch):
    from src.precos import cotacoes as mod

    fixture = _item("ITEM_09")
    _, cid, iid = _cotacao(monkeypatch, fixture)
    monkeypatch.setattr(mod, "politica_automatica",
                        lambda: estatistica.POLITICA_AUTOMATICA)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            triagem=saneamento.POLITICA_PADRAO)
    # segunda rodada: a retida continua retida (não volta a candidata)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            triagem=saneamento.POLITICA_PADRAO)
    linhas = repo.listar_referencias(iid)
    assert len(linhas) == 5, "T12: reexecutar não duplica referência"
    extremo = next(l for l in linhas if l["id_externo"] == "Q09_05")
    assert extremo["status"] == "rejected"


def test_integracao_jev_simulado_desconsidera_objeto_distinto(monkeypatch):
    fixture = _item("ITEM_06")
    _, cid, iid = _cotacao(monkeypatch, fixture)

    def jev(cotacao, item, linhas):
        # resposta simulada no contrato do seletor (`Proposta.para_evento`)
        return {"analises": [
            {"referencia_id": str(l["id"]),
             "escolha": apoio.JEV_SIMULADO.get(l["id_externo"], "compatible")}
            for l in linhas]}

    resultado = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico", fontes=[apoio.FonteDaFixture(fixture)],
        seletor=jev, triagem=saneamento.POLITICA_PADRAO)
    workstation = next(l for l in repo.listar_referencias(iid)
                       if l["id_externo"] == "Q06_05")
    assert workstation["status"] == "rejected"
    assert saneamento.DIVERGENCIA_JEV in " ".join(workstation["motivos"])
    assert resultado.saneamento["pos_jev"][0]["escolha_jev"] == \
        "different_specification"


def test_integracao_jev_nao_toca_decisao_de_pessoa(monkeypatch):
    fixture = _item("ITEM_07")
    _, cid, iid = _cotacao(monkeypatch, fixture)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            triagem=saneamento.POLITICA_PADRAO)
    alvo = repo.listar_referencias(iid)[0]
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=True, motivo="conferi na fonte")

    def jev(cotacao, item, linhas):
        return {"analises": [{"referencia_id": str(l["id"]),
                              "escolha": "different_product"} for l in linhas]}

    from src.precos import cotacoes as mod
    monkeypatch.setattr(mod, "politica_automatica",
                        lambda: estatistica.POLITICA_AUTOMATICA)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            seletor=jev, triagem=saneamento.POLITICA_PADRAO)
    depois = next(l for l in repo.listar_referencias(iid)
                  if l["id"] == alvo["id"])
    assert depois["status"] == "selected", "inclusão humana é preservada"


def test_sem_flag_a_selecao_e_a_de_antes(monkeypatch):
    fixture = _item("ITEM_01")
    _, cid, iid = _cotacao(monkeypatch, fixture)
    from src import db
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    resultado = cotacoes.pesquisar_item(
        CTX, cid, iid, modo="automatico",
        fontes=[apoio.FonteDaFixture(fixture)])
    assert resultado.consideradas == 5, "flag desligada: nada muda"
    assert resultado.saneamento == {}


def test_reincluir_desconsiderada_entra_sinalizada_com_trilha(monkeypatch):
    fixture = _item("ITEM_01")
    cliente, cid, iid = _cotacao(monkeypatch, fixture)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            triagem=saneamento.POLITICA_PADRAO)
    extremo = next(l for l in repo.listar_referencias(iid)
                   if l["id_externo"] == "Q01_05")
    with pytest.raises(cotacoes.ErroCotacao, match="motivo da inclusão"):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(extremo["id"]),
                                           incluir=True)
    cotacoes.alterar_status_referencia(
        CTX, cid, iid, str(extremo["id"]), incluir=True,
        motivo="fonte conferida: preço de lote com frete")
    depois = next(l for l in repo.listar_referencias(iid)
                  if l["id"] == extremo["id"])
    assert depois["status"] == "warning"
    [evento] = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == "referencia_incluida"]
    assert evento["payload"]["operacao"] == "reinstated"
    assert evento["payload"]["de"] == "rejected"
