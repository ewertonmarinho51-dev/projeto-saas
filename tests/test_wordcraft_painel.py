from types import SimpleNamespace

from src.ui.wordcraft_painel import modelo


def test_modelo_reune_seis_capacidades_sem_callbacks_de_mutacao():
    audit = {"diff": [{"path": "tr/p/1"}],
             "reports": [{"findings": [{"findingId": "F1"}]}, {"findings": []}],
             "plan": {"unresolvedFindings": [{"findingId": "P1"}]}}
    preparation = SimpleNamespace(operation_id="op", plan_hash="plan",
        source_bundle_hash="before", target_bundle_hash="after",
        resultados=(SimpleNamespace(fonte=SimpleNamespace(doc_key="tr")),),
        auditoria=lambda: audit)
    panel = modelo(preparacao=preparation,
        atendimentos_parecer={"reports": [{"operationId": "legal-op"}]},
        evidencias=({"estado": "VERIFICADA"},),
        template={"hash": "template"}, institucional={"hash": "identity"},
        montagem={"hash": "assembly"},
        historico=({"revision": 1},))
    assert panel["capacidades"] == ["govbot", "auditoria", "parecer", "template",
                                      "evidencias", "montagem"]
    assert panel["preparacao"]["documentos"] == ["tr"]
    assert panel["preparacao"]["auditoria"] is audit
    assert panel["evidencias"][0]["estado"] == "VERIFICADA"
    assert panel["institucional"]["hash"] == "identity"
    assert panel["atendimentos_parecer"]["reports"][0]["operationId"] == "legal-op"
    assert "confirmar" not in panel and "salvar" not in panel


def test_modelo_vazio_e_estavel():
    first = modelo()
    second = modelo()
    assert first == second
    assert first["preparacao"] is None
    assert first["historico"] == []
