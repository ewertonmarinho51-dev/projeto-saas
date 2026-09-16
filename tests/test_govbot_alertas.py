import pytest
from src import govbot_alertas as alertas, govbot, validacao


def test_dedupe_estado_resolucao_e_reabertura_sem_ia(monkeypatch):
    s = {"dados": {}, "documentos": {}}
    bucket = {}
    lista = alertas.avaliar(s, bucket)
    alvo = next(a for a in lista if a.get("campo") == "objeto")
    alertas.marcar(bucket, alvo["id"], "ADIADO")
    monkeypatch.setattr(validacao, "validar_todos", lambda *a, **k: pytest.fail("Reavaliação sem mudança"))
    assert next(a for a in alertas.avaliar(s, bucket) if a["id"] == alvo["id"])["estado"] == "ADIADO"
    monkeypatch.undo()
    s["dados"]["objeto"] = "Compra de papel"
    assert next(a for a in alertas.avaliar(s, bucket) if a["id"] == alvo["id"])["estado"] == "RESOLVIDO"
    s["dados"]["objeto"] = ""
    assert next(a for a in alertas.avaliar(s, bucket) if a["id"] == alvo["id"])["estado"] == "NOVO"


def test_buckets_isolam_estado_de_alerta_entre_processos():
    sessao = {"usuario": {"id": "u1", "tenant_id": "t1", "secretaria_id": "s1"}}
    a = govbot.obter_bucket(sessao, "processo1")
    b = govbot.obter_bucket(sessao, "processo2")
    primeiro = alertas.avaliar(sessao, a)[0]
    alertas.marcar(a, primeiro["id"], "ADIADO")
    segundo = next(x for x in alertas.avaliar(sessao, b) if x["id"] == primeiro["id"])
    assert segundo["estado"] == "NOVO"


def test_mapa_incompleto_vira_alerta_estruturado_e_obsoleto():
    s = {"dados": {}, "documentos": {"mapa_riscos": "## RISCO 01\nFalha na entrega."}}
    bucket = {}
    antes = [a for a in alertas.avaliar(s,bucket) if a.get("documentId") == "mapa_riscos"]
    assert antes
    s["documentos"] = {}
    depois = alertas.avaliar(s,bucket)
    assert all(a["estado"] == "OBSOLETO" for a in depois if a["id"] in {x["id"] for x in antes})


def test_usuario_nao_pode_marcar_resolvido_sem_corrigir():
    bucket = {}
    item = alertas.avaliar({},bucket)[0]
    with pytest.raises(ValueError):
        alertas.marcar(bucket,item["id"],"RESOLVIDO")


@pytest.mark.parametrize("acao", ["explain", "defer", "resolve"])
def test_eventos_triviais_nao_chamam_modelo_rag_ou_persistencia(monkeypatch, acao):
    from src import db
    from src.ui import govbot_panel
    s = {"dados": {}, "documentos": {}, "etapa": 0}
    bucket = govbot.obter_bucket(s)
    item = alertas.avaliar(s,bucket)[0]
    def proibido(*args, **kwargs):
        pytest.fail("Evento trivial chamou IA/RAG/persistência")
    monkeypatch.setattr(db,"flag_ativa",lambda k:k == "govbot_alertas")
    monkeypatch.setattr(govbot,"processar_mensagem",proibido)
    monkeypatch.setattr(govbot_panel,"_complementar_contexto_rag",proibido)
    monkeypatch.setattr(govbot_panel.state,"autosalvar",proibido)
    evento = {"request_id":"alerta-trivial-001", "event_type":"alert", "text":f"{acao}:{item['id']}",
              "focus":None, "proposal_id":None, "draft":{}}
    assert govbot_panel._processar_evento(s,bucket,evento) is False
    assert s["documentos"] == {} and s["dados"] == {}
    assert bucket["alertas"]["itens"][item["id"]]["estado"] != "RESOLVIDO"


def test_sinal_de_preco_vem_da_pesquisa_sem_inferir_ilegalidade():
    from src.precos.aplicacao import estimativa_estruturada, CHAVE_PROVENIENCIA
    from src.precos.estados import EstadoItem
    pesquisa = estimativa_estruturada({"id":"pesquisa-1"}, [{"id":"item-1", "codigo":"01",
        "estado":EstadoItem.COMPLETO.value, "estatisticas":{"anomalias":[{"criterio":"IQR"}]}}])
    s = {"dados": {CHAVE_PROVENIENCIA:pesquisa}}
    resultado = alertas.avaliar(s,{})
    sinal = next(a for a in resultado if a["categoria"] == "pesquisa_precos")
    assert sinal["evidencias"] == ["IQR"]
    assert sinal["gravidade"] == "ATENCAO"
    assert "não determina ilegalidade nem sobrepreço" in sinal["acao_sugerida"]


def test_resultado_antigo_nao_e_promovido_a_alerta_atual():
    s = {"dados":{}, "documentos":{}, "_score_cache":{"chave":"antiga", "resultado":{"criticos":["Antigo"]}}}
    assert not any(a["descricao"] == "Antigo" for a in alertas.avaliar(s,{}))
