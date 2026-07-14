"""
Testes da consistência cruzada (Fase 5 do pacote V5): divergências de
valor (KQ-004), erro de cálculo crítico (KQ-016), quantidades, prazos
entre documentos, objeto ausente, flag OFF preservando a auditoria v4
e integração com o corretor (fato como fonte).
"""

import json

from src import achados, consistencia, corretor, fatos, governanca

DADOS = {
    "objeto": "Aquisição de material escolar para a rede municipal",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "prazo": "até março/2027",
    "valor_estimado": 250.0,
    "itens": [{"descricao": "Caneta azul", "quantidade": 100,
               "unidade": "un", "valor_unitario": 2.5}],
}

DOC_OK = """## 1. OBJETO

Aquisição de material escolar para a rede municipal de ensino.

## 5. QUANTIDADES

| Item | Qtd | Unitário |
| --- | --- | --- |
| Caneta azul | 100 | 2,50 |

## 7. ESTIMATIVA DE VALOR

O valor global estimado é de R$ 250,00.

## 8. PERÍODO

Vigência de 12 (doze) meses.
"""


def _fatos(dados=None):
    return fatos.extrair_do_formulario(dados or DADOS, "p1")


def test_bundle_consistente_nao_gera_achados():
    assert consistencia.verificar(_fatos(), {"dfd": DOC_OK}) == []


# ---------------------------------------------------------------------------
# KQ-004: valor divergente entre documento e fato canônico
# ---------------------------------------------------------------------------
def test_valor_divergente_vira_finding_corrigivel_com_fato_como_fonte():
    doc = DOC_OK.replace("R$ 250,00", "R$ 900,00")
    achados_c = consistencia.verificar(_fatos(), {"tr": doc})
    f = next(a for a in achados_c
             if a["categoria"] == "consistencia_valor")
    assert f["documentId"] == "tr" and f["severity"] == "HIGH"
    assert f["autoCorrectable"] is True
    assert f["allowedPaths"] == ["tr/clausula/7/1"]
    assert f["sourceIds"] == ["fato:valor.total"]
    assert "R$ 900,00" in f["descricao"] and "R$ 250,00" in f["descricao"]


# ---------------------------------------------------------------------------
# KQ-016: erro de cálculo é crítico e bloqueia (não corrigível)
# ---------------------------------------------------------------------------
def test_soma_dos_itens_diferente_do_total_e_critico():
    dados = dict(DADOS, valor_estimado=999.0)  # 100 × 2,50 = 250
    achados_c = consistencia.verificar(_fatos(dados), {"dfd": DOC_OK})
    f = next(a for a in achados_c
             if a["categoria"] == "consistencia_calculo")
    assert f["severity"] == "CRITICAL"
    assert f["autoCorrectable"] is False
    assert f["blockingReason"] == "UNRESOLVED_SOURCE_CONFLICT"


def test_quantidade_divergente_na_tabela():
    doc = DOC_OK.replace("| Caneta azul | 100 |", "| Caneta azul | 90 |")
    achados_c = consistencia.verificar(_fatos(), {"dfd": doc})
    f = next(a for a in achados_c
             if a["categoria"] == "consistencia_quantidade")
    assert f["autoCorrectable"] is True
    assert f["allowedPaths"] == ["dfd/clausula/5/1"]
    assert "90" in f["evidencia"][0]


def test_vigencia_divergente_entre_documentos():
    tr = DOC_OK.replace("12 (doze) meses", "24 (vinte e quatro) meses")
    achados_c = consistencia.verificar(_fatos(), {"dfd": DOC_OK, "tr": tr})
    prazos = [a for a in achados_c
              if a["categoria"] == "consistencia_prazo"]
    assert {a["documentId"] for a in prazos} == {"dfd", "tr"}
    assert all("dfd = 12 meses" in a["descricao"]
               and "tr = 24 meses" in a["descricao"] for a in prazos)


def test_objeto_ausente_da_clausula_e_aviso_nao_corrigivel():
    doc = DOC_OK.replace(
        "Aquisição de material escolar para a rede municipal de ensino.",
        "Contratação de serviços diversos.")
    achados_c = consistencia.verificar(_fatos(), {"dfd": doc})
    f = next(a for a in achados_c
             if a["categoria"] == "consistencia_objeto")
    assert f["severity"] == "LOW" and f["autoCorrectable"] is False


# ---------------------------------------------------------------------------
# flag OFF preserva a auditoria v4; flag ON integra no relatório
# ---------------------------------------------------------------------------
def test_flag_desligada_relatorio_v4_identico(monkeypatch):
    monkeypatch.setattr(consistencia.db, "flag_ativa", lambda n: False)
    doc = DOC_OK.replace("R$ 250,00", "R$ 900,00")
    relatorio = achados.gerar_relatorio({"dfd": doc}, "p1")
    assert not [f for f in relatorio["findings"]
                if f["findingId"].startswith("C")]


def test_flag_ligada_integra_findings_no_relatorio(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(consistencia.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_CONSISTENCIA)
    monkeypatch.setattr(consistencia.db, "disponivel", lambda: False)
    st.session_state["dados"] = DADOS
    doc = DOC_OK.replace("R$ 250,00", "R$ 900,00")
    relatorio = achados.gerar_relatorio({"dfd": doc}, "p1")
    consistencias = [f for f in relatorio["findings"]
                     if f["findingId"].startswith("C")]
    assert consistencias and relatorio["status"] != "APPROVED"


# ---------------------------------------------------------------------------
# corretor recebe o valor canônico como fonte
# ---------------------------------------------------------------------------
def test_prompt_do_corretor_inclui_o_fato_referenciado():
    doc = DOC_OK.replace("R$ 250,00", "R$ 900,00")
    finding = next(a for a in consistencia.verificar(_fatos(), {"tr": doc})
                   if a["categoria"] == "consistencia_valor")
    _, user = corretor.montar_prompt([finding], {"tr": doc}, DADOS)
    payload = json.loads(user)
    assert payload["fontes"]["fato:valor.total"] == "250.0"
