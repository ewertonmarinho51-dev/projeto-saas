from decimal import Decimal

import pytest

from src import parecer_correcao
from src.wordcraft_capacidades import (
    ABAS, Capacidade, CorrecaoContextual, ErroCapacidade,
    compilar_correcao, montar_itens, painel_unico, parecer_para_correcao,
    propositor, propositor_govbot_selecao, propositor_selecao,
    snapshot_template, verificar_evidencia,
)


def _estado(source_ids=()):
    path = "tr/clausula/4/11111111-1111-1111-1111-111111111111"
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


def test_propositor_de_selecao_resolve_um_unico_bloco_e_finding_backend():
    report, snapshot, path = _estado()
    fn = propositor_selecao(doc_key="tr", texto_selecionado="antes",
                            novo_texto="depois", motivo="melhorar clareza")
    operation = fn(relatorio=report, snapshot=snapshot, contexto={})["operations"][0]
    assert operation["path"] == path and operation["expectedOldHash"] == "a" * 64
    assert operation["newValue"] == "depois" and operation["findingId"] == "F1"


@pytest.mark.parametrize("case", ["partial", "duplicate", "source", "blocked"])
def test_propositor_de_selecao_recusa_hint_ambiguo_ou_sem_autorizacao(case):
    report, snapshot, path = _estado()
    selected = "ant" if case == "partial" else "antes"
    if case == "duplicate":
        snapshot["documentos"]["tr"]["blocos"].append(
            {"path": "tr/body/paragraph/5", "hash": "b" * 64, "conteudo": "antes"})
    if case == "source": report["findings"][0]["sourceIds"] = ["fato:1"]
    if case == "blocked": report["findings"][0]["blockedPaths"] = [path]
    fn = propositor_selecao(doc_key="tr", texto_selecionado=selected,
                            novo_texto="depois", motivo="ajuste")
    with pytest.raises(ErroCapacidade):
        fn(relatorio=report, snapshot=snapshot, contexto={})


def test_propositor_govbot_reusa_gateway_e_recompila_resposta_declarativa():
    report, snapshot, path = _estado()
    calls = []
    def model(system, user, **kwargs):
        calls.append((system, user, kwargs))
        import json
        return json.dumps({"intent": "suggest_section_patch", "response": "Sugestão pronta",
            "target": path, "payload": {"new_value": "texto sugerido", "reason": "clareza"},
            "sources": []})
    fn = propositor_govbot_selecao(doc_key="tr", texto_selecionado="antes",
                                   pedido="Melhore a clareza", chamar=model)
    result = fn(relatorio=report, snapshot=snapshot,
                contexto={"processo": {"id": "p", "dados": {}}, "fatos": []})
    assert result["operations"][0]["newValue"] == "texto sugerido"
    assert calls[0][2]["finalidade"] == "govbot"


def test_propositor_govbot_recusa_resposta_que_nao_e_patch():
    report, snapshot, _ = _estado()
    fn = propositor_govbot_selecao(doc_key="tr", texto_selecionado="antes", pedido="Explique",
        chamar=lambda *a, **k: '{"intent":"explain_current","response":"x","target":null,"payload":{},"sources":[]}')
    with pytest.raises(ErroCapacidade):
        fn(relatorio=report, snapshot=snapshot,
           contexto={"processo": {"id": "p", "dados": {}}, "fatos": []})


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
