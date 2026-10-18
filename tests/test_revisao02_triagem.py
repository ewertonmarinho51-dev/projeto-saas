"""
Revisão 02 — triagem antes da cesta, reposição até 15, cesta rápida e
alerta acionável (pacote `GovConect_Revisao_02_Jev_Cesta_Relatorio`,
02_JEV_TRIAGEM, 03_CESTA_E_TRILHA, 04_UX e a matriz de aceite).

Caminho real: `busca.coletar` (procedência, deduplicação, unidade,
comparabilidade) → `estatistica.selecionar_cesta` com a política v2 e o
teto de 15 → `cotacoes` no banco falso. Nenhuma rede, nenhuma IA. A massa
de 15 itens é a do pacote, TOTALMENTE SINTÉTICA.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from src.precos import busca, cesta, cotacoes, estatistica, saneamento
from src.precos import repositorio as repo
from src.precos.fontes import ResultadoBusca
from src.precos.modelo import Fonte, NaturezaValor, Referencia, StatusReferencia
from src.precos.perfil import obter as obter_perfil
from src.precos.saneamento import (DESCONSIDERADA, ELEGIVEL, REVISAO,
                                   Observacao)
from tests.cotacoes_apoio import ligar_banco_falso

D = Decimal
V2 = saneamento.POLITICA_PADRAO
TETO = estatistica.POLITICA_AUTOMATICA.teto
CTX = cotacoes.Contexto(auth_user_id="u1")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "precos" / \
    "revisao02_cenarios_15_itens.json"
FONTE = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
              "sistema_oficial")


# ---------------------------------------------------------------------------
# Adaptador da massa do pacote (SINTÉTICA) para o caminho real da busca
# ---------------------------------------------------------------------------
def _massa() -> dict:
    dados = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert "SINTETICO" in dados["_warning"]
    return dados


def _item(chave: str) -> dict:
    return next(i for i in _massa()["items"] if i["id"] == chave)


def _descricao_do_item(item: dict) -> str:
    """
    O item descrito como as próprias referências da massa o descrevem (a
    descrição mais frequente): comparabilidade é com a especificação, e a
    massa não traz a do item além do nome.
    """
    from collections import Counter

    descricoes = Counter(r["description"] for r in item["references"])
    return descricoes.most_common(1)[0][0] if descricoes else item["description"]


def _referencia(item: dict, r: dict, i: int) -> Referencia:
    """
    `same_origin_key` é o identificador oficial da contratação (duplicata =
    mesma contratação vista em dois portais); cada contratação conta como
    origem independente (órgão + processo).
    """
    capacidade = r.get("package_size")
    return Referencia(
        fonte=FONTE, id_externo=r["id"],
        bruto={"id": r["id"], "sintetico": True},
        descricao_original=r["description"], unidade_original=r["unit"],
        quantidade_original=D("10"),
        valor_unitario_original=D(r["price_original"]),
        capacidade_embalagem=None if capacidade in (None, 1)
        else D(str(capacidade)),
        natureza_valor=NaturezaValor.HOMOLOGADO,
        orgao=f"{r['organization']} {r['same_origin_key']}",
        ni_fornecedor=f"F-{r['same_origin_key']}", uf="PA",
        data_compra=date.today() - timedelta(days=10 + i),
        referencia_externa=r["same_origin_key"])


class FonteDaMassa:
    def __init__(self, item: dict):
        self.fonte = FONTE
        self._item = item

    def pesquisar(self, consulta) -> ResultadoBusca:
        return ResultadoBusca(fonte=self.fonte, referencias=[
            _referencia(self._item, r, i)
            for i, r in enumerate(self._item["references"])])


def _item_do_banco(item: dict) -> dict:
    return {"id": item["id"], "numero": item["number"],
            "descricao": _descricao_do_item(item), "unidade": item["unit"],
            "quantidade": str(item["quantity"])}


def _cesta(item: dict, *, politica=V2, teto=TETO):
    coleta = busca.coletar(_item_do_banco(item), [FonteDaMassa(item)],
                           filtros={})
    escolha = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil("in_65_2021"), teto=teto,
        saneamento=politica, texto_item=_descricao_do_item(item))
    return coleta, escolha


def _obs(valores, **kw):
    return [Observacao(id=f"q{i}", valor=D(v), valor_original=D(v),
                       origem=f"orgao{i}|forn{i}", texto="PRODUTO", **kw)
            for i, v in enumerate(valores)]


# ---------------------------------------------------------------------------
# Política v2 (02_JEV: faixas de n)
# ---------------------------------------------------------------------------
def test_politica_v2_e_versionada_e_a_v1_continua_reproduzivel():
    assert V2.versao == "2026-10-17.saneamento-v2"
    assert V2.minimo_para_autoexclusao == 8
    assert saneamento.POLITICA_V1.versao == saneamento.VERSAO_POLITICA_V1
    assert saneamento.POLITICA_V1.minimo_para_autoexclusao == 5


def test_n_entre_4_e_8_nao_elimina_so_por_variacao_ac06():
    t = saneamento.avaliar(_obs(["10", "10.2", "9.8", "10.1", "45"]), V2)
    extremo = t.avaliacoes[-1]
    assert extremo.desfecho == REVISAO
    assert saneamento.AMOSTRA_PEQUENA in extremo.codigos
    assert saneamento.fica_sinalizada_na_cesta(extremo, V2)


def test_n_maior_ou_igual_a_8_extremo_corroborado_e_desconsiderado_ac05():
    valores = ["10", "10.2", "9.8", "10.1", "9.9", "10.3", "10", "10.05", "45"]
    t = saneamento.avaliar(_obs(valores), V2)
    assert [a.desfecho for a in t.avaliacoes] == [ELEGIVEL] * 8 + \
        [DESCONSIDERADA]
    assert {saneamento.EXTREMO, saneamento.CORROBORADO} <= \
        set(t.avaliacoes[-1].codigos)


def test_n_menor_que_4_nao_usa_iqr():
    t = saneamento.avaliar(_obs(["10", "11", "13"]), V2)
    assert all("iqr" not in str(a.metricas.get("criterios") or "")
               for a in t.avaliacoes)


def test_mad_zero_e_limite_inferior_nunca_negativo_ac07():
    t = saneamento.avaliar(_obs(["10"] * 8 + ["200"]), V2)
    assert t.serie["mad"] == "0"
    assert t.avaliacoes[-1].desfecho == DESCONSIDERADA
    # a frase do detector de anomalias não mostra faixa negativa
    refs = [Referencia(fonte=FONTE, id_externo=f"x{i}", bruto={},
                       valor_unitario_original=D(v),
                       valor_unitario_normalizado=D(v))
            for i, v in enumerate(["1", "1.1", "1.2", "40", "45", "50", "300"])]
    est = estatistica.calcular([r.valor_unitario_normalizado for r in refs])
    assert est.q1 - estatistica.FATOR_IQR * est.iqr < 0
    textos = " ".join(a.motivo for a in
                      estatistica.detectar_anomalias(refs, est))
    assert "-R$" not in textos and "faixa usual de R$ 0,00" in textos


def test_preco_regional_alto_nao_e_excluido_so_por_ser_o_maior_ac08():
    t = saneamento.avaliar(_obs(["100", "104", "98", "101", "103", "99",
                                 "102", "100", "140"]), V2)
    # 40% acima numa série apertada é variação a conferir, nunca descarte
    assert t.avaliacoes[-1].desfecho != DESCONSIDERADA


# ---------------------------------------------------------------------------
# Massa do pacote, item a item, pelo caminho real
# ---------------------------------------------------------------------------
def test_papel_a4_duplicata_embalagem_e_extremo_ac01_a_ac04():
    item = _item("SYN-I01")
    coleta, escolha = _cesta(item)
    status = {r.id_externo: r.status for r, _ in coleta.referencias}
    # AC-04: a mesma contratação em dois portais conta uma vez
    assert status["SYN-I01-DUPLICATE"] == StatusReferencia.REJEITADA
    # AC-03: pacote sem quantidade de folhas não vira preço por palpite
    sem_qtd = next(r for r, _ in coleta.referencias
                   if r.id_externo == "SYN-I01-PACK-UNKNOWN")
    assert sem_qtd not in escolha.selecionadas
    # o extremo de R$ 253 não fica no cálculo
    assert all(r.id_externo != "SYN-I01-R16" for r in escolha.selecionadas)
    # AC-01/AC-02: no máximo 15, e usadas ≤ comparáveis ≤ encontradas
    assert len(escolha.selecionadas) <= TETO
    elegiveis = coleta.elegiveis(estatistica.PISO_COMPARABILIDADE)
    assert len(escolha.selecionadas) <= elegiveis <= coleta.brutas


def test_pasta_az_n4_fica_sinalizada_na_cesta_e_nao_descartada_ac06():
    item = _item("SYN-I03")
    _, escolha = _cesta(item)
    valores = sorted(r.valor_unitario_normalizado for r in escolha.selecionadas)
    assert valores == [D("16.07"), D("17.20"), D("22.00"), D("44.80")]
    pasta = next(r for r in escolha.selecionadas
                 if r.valor_unitario_normalizado == D("44.80"))
    assert pasta.status == StatusReferencia.ALERTA
    assert any(m.startswith(saneamento.ROTULO_SINALIZADA) for m in pasta.motivos)
    assert not escolha.retidas, "nada sai da cesta com n=4"


def test_grampeador_pool_de_12_reposicao_mantem_a_cesta_coerente_ac05():
    item = _item("SYN-I04")
    _, escolha = _cesta(item)
    usados = [r.valor_unitario_normalizado for r in escolha.selecionadas]
    assert D("29.77") not in usados or any(
        r.status == StatusReferencia.ALERTA for r in escolha.selecionadas
        if r.valor_unitario_normalizado == D("29.77")), \
        "o atípico ou sai da cesta ou fica nela SINALIZADO — nunca calado"


def test_reposicao_ate_o_teto_quando_a_cesta_formada_tem_destoante():
    """20 elegíveis: o destoante entre as 15 primeiras sai e a 16ª entra."""
    valores = ["50"] * 3 + ["200"] + ["50", "51", "49", "50.5", "49.5", "50",
                                      "51", "49", "50", "50.2", "49.8", "50.1",
                                      "49.9", "50.3", "49.7", "50"]
    massa = {"id": "R", "number": 1, "description": "PRODUTO TESTE",
             "unit": "UNIDADE", "package_size": 1, "quantity": 1,
             "references": [{"id": f"R{i:02d}", "same_origin_key": f"P{i}",
                             "description": "PRODUTO TESTE", "unit": "UNIDADE",
                             "package_size": 1, "price_original": v,
                             "source": "F", "organization": "ORG",
                             "source_url": None}
                            for i, v in enumerate(valores)]}
    _, escolha = _cesta(massa)
    assert len(escolha.selecionadas) == TETO
    assert all(r.valor_unitario_normalizado != D("200")
               for r in escolha.selecionadas)
    saiu = [r for r in escolha.retidas if r.valor_unitario_normalizado == D("200")]
    assert saiu, "o destoante fica GRAVADO, com motivo"
    assert escolha.recomposicao is not None


@pytest.mark.parametrize("chave", [f"SYN-I{n:02d}" for n in range(1, 16)])
def test_quinze_itens_invariantes(chave):
    item = _item(chave)
    coleta, escolha = _cesta(item)
    n = len(escolha.selecionadas)
    assert 0 <= n <= TETO
    assert n <= coleta.elegiveis(estatistica.PISO_COMPARABILIDADE) \
        <= coleta.unicas <= coleta.brutas
    # IDs e preços originais preservados (nada é reescrito)
    originais = {r["id"]: D(r["price_original"]) for r in item["references"]}
    for referencia, _ in coleta.referencias:
        assert referencia.valor_unitario_original == \
            originais[referencia.id_externo]
    estimativa = estatistica.estimar(escolha, perfil=obter_perfil("in_65_2021"),
                                     regras=estatistica.REGRAS_MEDIA_PADRAO)
    if estimativa.valor_unitario is not None:
        assert estimativa.valor_unitario == \
            estimativa.valor_unitario.quantize(D("0.01"))


# ---------------------------------------------------------------------------
# Cesta: remover sem justificativa, desfazer, manter (AC-09 a AC-11)
# ---------------------------------------------------------------------------
def _cotacao_com_cesta(monkeypatch, valores=("10", "10.5", "11", "10.2",
                                             "10.8", "40")):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Revisão 02"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), {
        "descricao": "PRODUTO TESTE", "unidade": "UNIDADE",
        "quantidade": "10"})
    massa = {"id": "R", "number": 1, "description": "PRODUTO TESTE",
             "unit": "UNIDADE", "package_size": 1, "quantity": 10,
             "references": [{"id": f"R{i}", "same_origin_key": f"P{i}",
                             "description": "PRODUTO TESTE",
                             "unit": "UNIDADE", "package_size": 1,
                             "price_original": v, "source": "F",
                             "organization": "ORG", "source_url": None}
                            for i, v in enumerate(valores)]}
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[FonteDaMassa(massa)],
                            triagem=V2)
    return cliente, str(c["id"]), str(item["id"])


def test_remover_sem_justificativa_e_desfazer_ac09(monkeypatch):
    cliente, cid, iid = _cotacao_com_cesta(monkeypatch)
    alvo = cesta.consideradas(repo.listar_referencias(iid))[0]
    antes = repo.obter_item(iid)["preco_estimado"]
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False)
    depois = next(l for l in repo.listar_referencias(iid)
                  if l["id"] == alvo["id"])
    assert depois["status"] == "rejected"
    assert repo.obter_item(iid)["preco_estimado"] != antes
    cotacoes.desfazer_retirada(CTX, cid, iid, str(alvo["id"]))
    volta = next(l for l in repo.listar_referencias(iid)
                 if l["id"] == alvo["id"])
    assert volta["status"] == alvo["status"]
    assert D(str(repo.obter_item(iid)["preco_estimado"])) == D(str(antes))
    operacoes = [e["payload"].get("operacao")
                 for e in cliente.tabelas["pesquisa_preco_eventos"]
                 if e["tipo"] in ("referencia_excluida", "referencia_incluida")]
    assert operacoes[-2:] == ["manual_removed", "undo_manual_removal"]


def test_desfazer_so_vale_para_a_propria_retirada(monkeypatch):
    _, cid, iid = _cotacao_com_cesta(monkeypatch)
    alvo = cesta.consideradas(repo.listar_referencias(iid))[0]
    with pytest.raises(cotacoes.ErroCotacao, match="última retirada"):
        cotacoes.desfazer_retirada(CTX, cid, iid, str(alvo["id"]))
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False)
    outro = cotacoes.Contexto(auth_user_id="u2")
    with pytest.raises(cotacoes.ErroCotacao, match="última retirada"):
        cotacoes.desfazer_retirada(outro, cid, iid, str(alvo["id"]))


def test_remover_duas_vezes_nao_duplica_trilha_ac10(monkeypatch):
    cliente, cid, iid = _cotacao_com_cesta(monkeypatch)
    alvo = cesta.consideradas(repo.listar_referencias(iid))[0]
    for _ in range(2):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                           incluir=False)
    exclusoes = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                 if e["tipo"] == "referencia_excluida"]
    assert len(exclusoes) == 1


def test_conflito_de_versao_nao_deixa_retirada_meio_gravada_ac11(monkeypatch):
    _, cid, iid = _cotacao_com_cesta(monkeypatch)
    alvo = cesta.consideradas(repo.listar_referencias(iid))[0]
    revisao = int(repo.obter_item(iid).get("revisao") or 1)
    with pytest.raises(repo.ConflitoDeVersao):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                           incluir=False,
                                           revisao_esperada=revisao + 7)
    linha = next(l for l in repo.listar_referencias(iid)
                 if l["id"] == alvo["id"])
    assert linha["status"] == alvo["status"]


def test_manter_preco_atipico_tira_a_pendencia_e_fica_na_memoria(monkeypatch):
    _, cid, iid = _cotacao_com_cesta(monkeypatch)
    item = repo.obter_item(iid)
    gravado = item["estatisticas"]
    atipicos = gravado.get("anomalias") or []
    assert atipicos, "o R$ 40 é sinalizado no cálculo"
    assert any("atípico" in p for p in gravado["pendencias"])
    alvo = next(l for l in repo.listar_referencias(iid)
                if l["id_externo"] == atipicos[0]["id_externo"])
    cotacoes.manter_referencia(CTX, cid, iid, str(alvo["id"]))
    depois = repo.obter_item(iid)
    assert not any("atípico" in p for p in
                   depois["estatisticas"]["pendencias"])
    assert "mantido na cesta por decisão do servidor" in \
        depois["justificativa"]
    linha = next(l for l in repo.listar_referencias(iid)
                 if l["id"] == alvo["id"])
    assert linha["status"] == "warning", "continua no cálculo, sinalizado"
    assert estatistica.chave_da_referencia(alvo) in \
        depois["estatisticas"]["decisoes"]["mantidas"]


def test_remover_nao_consulta_fonte_nem_reprocessa(monkeypatch):
    """07_PERFORMANCE: a retirada só toca o item — nenhuma fonte externa."""
    _, cid, iid = _cotacao_com_cesta(monkeypatch)
    from src.precos import busca as busca_mod

    def proibido(*_a, **_k):
        raise AssertionError("remover não pode consultar fonte")

    monkeypatch.setattr(busca_mod, "coletar", proibido)
    alvo = cesta.consideradas(repo.listar_referencias(iid))[0]
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(alvo["id"]),
                                       incluir=False)


def test_integridade_aponta_cesta_acima_do_teto_ac01():
    linhas = [{"id": str(i), "status": "selected", "fonte_id": "compras_gov_precos",
               "valor_unitario_original": "10",
               "valor_unitario_normalizado": "10", "natureza_valor": "homologado"}
              for i in range(17)]
    item = {"estatisticas": {"consideradas": 17}, "preco_estimado": "10",
            "quantidade": "2", "preco_total": "20.00"}
    problemas = cesta.integridade_do_item(item, linhas, teto=15)
    assert any("acima do limite de 15" in p for p in problemas)
    item_inconsistente = {**item, "estatisticas": {"consideradas": 308}}
    assert any("registra 308" in p for p in
               cesta.integridade_do_item(item_inconsistente, linhas))
