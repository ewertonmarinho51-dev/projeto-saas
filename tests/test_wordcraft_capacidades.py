from decimal import Decimal

import pytest

from src import parecer_correcao
from src.wordcraft_capacidades import (
    ABAS, Capacidade, CorrecaoContextual, ErroCapacidade,
    compilar_correcao, montar_itens, painel_unico, parecer_para_correcao,
    propositor, snapshot_template, verificar_evidencia,
)


def _estado(source_ids=()):
    path = "tr/body/paragraph/4"
    report = {"findings": [{"findingId": "F1", "documentId": "tr",
        "autoCorrectable": True, "allowedPaths": [path], "blockedPaths": [],
        "sourceIds": list(source_ids)}]}
    snapshot = {"documentos": {"tr": {"blocos": [
        {"path": path, "hash": "a" * 64, "conteudo": "antes"}]}}}
    return report, snapshot, path


def test_painel_unico_expoe_seis_capacidades_e_cinco_abas():
    painel = painel_unico()
    assert painel["abas"] == list(ABAS)
    assert painel["capacidades"] == [item.value for item in Capacidade]
    assert set(painel["mutacoes"]) == {"govbot", "auditoria", "parecer"}


@pytest.mark.parametrize("capacidade", [Capacidade.GOVBOT, Capacidade.AUDITORIA,
                                         Capacidade.PARECER])
def test_toda_mutacao_compila_para_o_mesmo_contrato_g4(capacidade):
    report, snapshot, path = _estado(("fato:itens[0].quantidade",))
    proposta = compilar_correcao(CorrecaoContextual(capacidade, "F1", "depois",
        "ajuste", ("fato:itens[0].quantidade",)), relatorio=report, snapshot=snapshot)
    assert proposta == {"operations": [{"findingId": "F1", "documentId": "tr",
        "op": "replace", "path": path, "expectedOldHash": "a" * 64,
        "newValue": "depois", "sourceIds": ["fato:itens[0].quantidade"],
        "reason": "ajuste"}], "unresolvedFindings": []}


def test_propositor_tem_assinatura_do_documento_service():
    report, snapshot, _ = _estado()
    fn = propositor(CorrecaoContextual(Capacidade.GOVBOT, "F1", "novo", "seleção"))
    assert fn(relatorio=report, snapshot=snapshot, contexto={"segredo": "ignorado"})["operations"]


@pytest.mark.parametrize("mudanca", ["finding", "path", "source"])
def test_rejeita_finding_caminho_ou_fonte_nao_autorizados(mudanca):
    report, snapshot, path = _estado(("fato:valor",))
    correcao = CorrecaoContextual(Capacidade.GOVBOT,
        "OUTRO" if mudanca == "finding" else "F1", "novo", "r",
        ("fonte:falsa",) if mudanca == "source" else ("fato:valor",))
    with pytest.raises(ErroCapacidade):
        compilar_correcao(correcao, relatorio=report, snapshot=snapshot,
                          caminho="tr/outro/1" if mudanca == "path" else path)


def test_parecer_ambiguo_fica_pendente_e_objetivo_pode_compilar():
    ambiguo = parecer_correcao.Apontamento("P1", "p", "r", "f", "tr", "c",
        "alta", 1.0, parecer_correcao.AMBIGUO, "duas interpretações")
    assert parecer_para_correcao(ambiguo, novo_texto="x")["requiresHumanInput"] is True
    objetivo = parecer_correcao.Apontamento("F1", "p", "corrigir", "f", "tr", "c",
        "alta", 1.0, parecer_correcao.CORRECAO_AUTOMATICA)
    assert parecer_para_correcao(objetivo, novo_texto="x").capacidade == Capacidade.PARECER


def test_estados_de_evidencia_nao_confundem_ausencia_com_prova():
    assert verificar_evidencia({"id": "L1", "vigente": True})["estado"] == "VERIFICADA"
    assert verificar_evidencia({"id": "L2", "vigente": False})["estado"] == "INDISPONIVEL"
    assert verificar_evidencia(None)["estado"] == "NAO_VERIFICADA"
    fonte = {"id": "L3", "ativo": True, "citacoes": ["art. 1"]}
    assert verificar_evidencia(fonte, citacao="art. 99")["estado"] == "PENDENTE"
    assert verificar_evidencia({"id": "L4"}, citacao="art. inventado")["estado"] == "PENDENTE"


def test_snapshot_institucional_nao_muda_quando_a_origem_muda_depois():
    template = {"id": "T1", "versao": 3, "hash": "publicado"}
    identidade = {"secretaria": "Saúde", "logo": "logo-a", "assinantes": [{"nome": "Ana"}]}
    snap = snapshot_template(template, identidade, {"texto": "ato", "pendencias": []})
    identidade["logo"] = "logo-b"
    identidade["assinantes"][0]["nome"] = "Outra pessoa"
    assert snap["institucional"]["logo"] == "logo-a"
    assert snap["institucional"]["assinantes"][0]["nome"] == "Ana"
    assert snapshot_template(template, {"secretaria": "Saúde", "logo": "logo-a", "assinantes": [{"nome": "Ana"}]},
                             {"texto": "ato", "pendencias": []})["hash"] == snap["hash"]


def test_montagem_de_210_itens_preserva_decimal_numeracao_e_total():
    itens = [{"codigo": f"I{i:03}", "descricao": f"Item {i}",
              "quantidade": Decimal("0.1"), "valor_unitario": Decimal("0.2")}
             for i in range(1, 211)]
    montagem = montar_itens(itens)
    assert montagem["quantidade_itens"] == 210
    assert montagem["itens"][-1]["numero"] == 210
    assert Decimal(montagem["valor_total"]) == Decimal("4.20")
    assert montar_itens(itens)["hash"] == montagem["hash"]
