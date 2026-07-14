"""
Testes das famílias de modelos (Fase 4 do V6): resolução única (T12),
ambiguidade real vira pergunta objetiva (T13), desempate determinístico
por prioridade, escolha manual, shadow/ativa e o bloco de diretrizes
para a geração.
"""

import streamlit as st

from src import familias, fatos, governanca

DADOS_SERVICO_CONTINUO = {
    "objeto": "Serviços de limpeza predial",
    "modelo_execucao": "Serviço de execução continuada",
    "valor_estimado": 120000.0,
    "itens": [{"descricao": "Posto de limpeza", "quantidade": 4,
               "valor_unitario": 30000.0}],
}


def _familia(chave, nome, criterios, prioridade=100, pergunta="",
             proibidas=None):
    versao = governanca.nova_versao_artefato("familia", chave, {
        "nome": nome,
        "documentos_suportados": ["tr"],
        "criterios": criterios,
        "clausulas_obrigatorias": ["clausula.tr.sla"],
        "clausulas_proibidas": list(proibidas or []),
        "prioridade": prioridade,
        "pergunta_desambiguacao": pergunta,
    }, status="PUBLISHED")
    return {"artefato": {"chave_estavel": chave, "tenant_id": "t1"},
            "versao": versao}


def _fatos():
    return fatos.extrair_do_formulario(DADOS_SERVICO_CONTINUO, "p1")


CRITERIO_CONTINUO = {"field": "procedimento.execucao_continuada",
                     "operator": "EQ", "value": True}
CRITERIO_BENS = {"field": "objeto.natureza", "operator": "EQ",
                 "value": "BENS"}


# ---------------------------------------------------------------------------
# T12: família única resolvida automaticamente
# ---------------------------------------------------------------------------
def test_familia_unica_resolvida_pelo_contexto():
    lista = [
        _familia("familia.tr-continuos", "TR serviços contínuos",
                 CRITERIO_CONTINUO),
        _familia("familia.tr-bens", "TR aquisição de bens", CRITERIO_BENS),
    ]
    resolucao = familias.resolver("tr", _fatos(), lista)
    assert resolucao["situacao"] == "unica"
    assert resolucao["familia"] == "familia.tr-continuos"
    assert resolucao["decisao"]["tipo_decisao"] == "familia_modelo"


def test_sem_familia_elegivel_cai_no_comportamento_atual():
    resolucao = familias.resolver(
        "tr", _fatos(), [_familia("familia.tr-bens", "TR bens",
                                  CRITERIO_BENS)])
    assert resolucao["situacao"] == "nenhuma"
    assert resolucao["familia"] is None


def test_documento_nao_suportado_nao_elege():
    resolucao = familias.resolver(
        "dfd", _fatos(), [_familia("familia.tr-continuos", "TR contínuos",
                                   CRITERIO_CONTINUO)])
    assert resolucao["situacao"] == "nenhuma"


# ---------------------------------------------------------------------------
# T13: ambiguidade real = pergunta objetiva (nunca lista técnica)
# ---------------------------------------------------------------------------
def test_empate_real_vira_pergunta_objetiva():
    lista = [
        _familia("familia.tr-continuos", "TR serviços contínuos",
                 CRITERIO_CONTINUO,
                 pergunta="O serviço terá dedicação exclusiva de mão "
                          "de obra?"),
        _familia("familia.tr-dedicacao", "TR com dedicação exclusiva",
                 CRITERIO_CONTINUO),
    ]
    resolucao = familias.resolver("tr", _fatos(), lista)
    assert resolucao["situacao"] == "ambigua"
    assert resolucao["familia"] is None
    assert "dedicação exclusiva" in resolucao["pergunta"]
    assert [o["rotulo"] for o in resolucao["opcoes"]] == [
        "TR serviços contínuos", "TR com dedicação exclusiva"]


def test_prioridade_desempata_sem_pergunta():
    lista = [
        _familia("familia.tr-continuos", "TR contínuos",
                 CRITERIO_CONTINUO, prioridade=100),
        _familia("familia.tr-dedicacao", "TR dedicação",
                 CRITERIO_CONTINUO, prioridade=200),
    ]
    resolucao = familias.resolver("tr", _fatos(), lista)
    assert resolucao["situacao"] == "unica"
    assert resolucao["familia"] == "familia.tr-dedicacao"


def test_escolha_manual_resolve_a_ambiguidade():
    lista = [
        _familia("familia.tr-continuos", "TR contínuos", CRITERIO_CONTINUO),
        _familia("familia.tr-dedicacao", "TR dedicação", CRITERIO_CONTINUO),
    ]
    resolucao = familias.resolver("tr", _fatos(), lista,
                                  escolha_manual="familia.tr-dedicacao")
    assert resolucao["situacao"] == "unica"
    assert resolucao["familia"] == "familia.tr-dedicacao"
    assert resolucao["decisao"]["ator_tipo"] == "usuario"


def test_resolucao_e_reproduzivel():
    lista = [_familia("familia.tr-continuos", "TR contínuos",
                      CRITERIO_CONTINUO)]
    d1 = familias.resolver("tr", _fatos(), lista)["decisao"]
    d2 = familias.resolver("tr", _fatos(), lista)["decisao"]
    assert d1["input_hash"] == d2["input_hash"]


# ---------------------------------------------------------------------------
# bloco de diretrizes para a geração
# ---------------------------------------------------------------------------
def test_bloco_para_prompt_traz_obrigatorias_e_proibidas():
    item = _familia("familia.tr-continuos", "TR serviços contínuos",
                    CRITERIO_CONTINUO,
                    proibidas=["clausula.tr.entrega-unica"])
    bloco = familias.bloco_para_prompt(item["versao"]["payload"])
    assert "TR serviços contínuos" in bloco
    assert "clausula.tr.sla" in bloco
    assert "PROIBIDAS" in bloco and "entrega-unica" in bloco


# ---------------------------------------------------------------------------
# flags shadow/ativa
# ---------------------------------------------------------------------------
def test_shadow_registra_e_nao_afeta(monkeypatch, caplog):
    registradas = []
    monkeypatch.setattr(familias.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_FAMILIAS_SHADOW)
    monkeypatch.setattr(familias.db, "disponivel", lambda: True)
    monkeypatch.setattr(familias.db, "registrar_decisao",
                        lambda d: registradas.append(d) or d)
    monkeypatch.setattr(familias, "familias_publicadas", lambda: [
        _familia("familia.tr-continuos", "TR contínuos",
                 CRITERIO_CONTINUO)])
    st.session_state.pop("_familia_decisao_tr", None)
    with caplog.at_level("INFO", logger="govdocs.familias"):
        resultado = familias.resolver_para_processo(
            "tr", DADOS_SERVICO_CONTINUO, "p1")
    assert resultado is None            # geração intacta
    assert len(registradas) == 1        # decisão registrada
    # repetição com o mesmo contexto não duplica o registro
    familias.resolver_para_processo("tr", DADOS_SERVICO_CONTINUO, "p1")
    assert len(registradas) == 1


def test_ativa_devolve_a_resolucao(monkeypatch):
    monkeypatch.setattr(familias.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_FAMILIAS_ATIVA)
    monkeypatch.setattr(familias.db, "disponivel", lambda: False)
    monkeypatch.setattr(familias, "familias_publicadas", lambda: [])
    st.session_state.pop("_familia_decisao_tr", None)
    resolucao = familias.resolver_para_processo(
        "tr", DADOS_SERVICO_CONTINUO, "p1")
    assert resolucao is not None
    assert resolucao["situacao"] == "nenhuma"  # sem famílias: fallback


def test_flags_desligadas_nao_fazem_nada(monkeypatch):
    monkeypatch.setattr(familias.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flags OFF não podem resolver")

    monkeypatch.setattr(familias, "resolver", explode)
    assert familias.resolver_para_processo(
        "tr", DADOS_SERVICO_CONTINUO, "p1") is None
