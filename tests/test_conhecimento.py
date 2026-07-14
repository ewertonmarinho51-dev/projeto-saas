"""
Testes do motor de conhecimento (Fase 3 do pacote V5): avaliador
determinístico, elegibilidade (status/vigência/fonte revogada),
precedência por camada, conflito bloqueante (KQ-015), decisão
reproduzível (KQ-014) e flags shadow/ativo.
"""

from datetime import datetime, timezone

import streamlit as st

from src import conhecimento, db, fatos, governanca

DADOS_SRP_BENS = {
    "orgao": "Secretaria de Educação",
    "objeto": "Aquisição de material escolar",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "valor_estimado": 45000.0,
    "itens": [{"descricao": "Caneta", "quantidade": 10,
               "valor_unitario": 2.0}],
}


def _fatos(dados=None):
    return fatos.extrair_do_formulario(dados or DADOS_SRP_BENS, "p1")


def _regra_me_epp(status="PUBLISHED", camada="municipio", prioridade=100,
                  acao=None, **extras):
    return governanca.nova_regra(
        "regra.me-epp.srp-bens", camada,
        {"op": "ALL", "children": [
            {"field": "procedimento.srp", "operator": "EQ", "value": True},
            {"field": "objeto.natureza", "operator": "EQ", "value": "BENS"},
        ]},
        [acao or {"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}],
        status=status, prioridade=prioridade, **extras)


# ---------------------------------------------------------------------------
# avaliador
# ---------------------------------------------------------------------------
def test_avaliador_operadores_basicos():
    contexto = {"valor.total": 45000.0, "objeto.natureza": "BENS",
                "procedimento.srp": True}
    av = conhecimento.avaliar_condicao(
        {"op": "ALL", "children": [
            {"field": "valor.total", "operator": "GTE", "value": 10000},
            {"field": "objeto.natureza", "operator": "IN",
             "value": ["BENS", "SERVICOS"]},
            {"op": "NOT", "children": [
                {"field": "procedimento.srp", "operator": "EQ",
                 "value": False}]},
            {"field": "objeto.natureza", "operator": "CONTAINS",
             "value": "ben"},
            {"field": "valor.total", "operator": "EXISTS"},
        ]}, contexto)
    assert av["resultado"] is True
    por_operador = {(f["field"], f["operator"]): f for f in av["folhas"]}
    assert por_operador[("valor.total", "GTE")]["satisfeita"] is True
    # a folha dentro do NOT fica insatisfeita — é o NOT que inverte
    assert por_operador[("procedimento.srp", "EQ")]["satisfeita"] is False


def test_dado_ausente_e_conservador_e_registrado():
    av = conhecimento.avaliar_condicao(
        {"field": "duracao.meses", "operator": "GT", "value": 12}, {})
    assert av["resultado"] is False
    assert av["ausentes"] == ["duracao.meses"]


# ---------------------------------------------------------------------------
# KQ-001/KQ-002: regra aplicável inclui; não aplicável não inclui
# ---------------------------------------------------------------------------
def test_regra_aplicavel_inclui_clausula_com_trilha():
    decisao = conhecimento.resolver(_fatos(), [_regra_me_epp()], set(), "p1")
    resultado = decisao["resultado"]
    assert resultado["clausulas_incluir"] == ["clausula.me-epp"]
    assert decisao["regras_versoes"][0]["chave"] == "regra.me-epp.srp-bens"
    trilha = decisao["explicacao"]["regras_avaliadas"][0]
    assert trilha["satisfeita"] is True
    assert any(f["field"] == "procedimento.srp" and f["valor_observado"]
               is True for f in trilha["folhas"])


def test_regra_nao_aplicavel_nao_inclui():
    dados = dict(DADOS_SRP_BENS,
                 modelo_execucao="Entrega única (fornecimento integral)")
    decisao = conhecimento.resolver(_fatos(dados), [_regra_me_epp()],
                                    set(), "p1")
    assert decisao["resultado"]["clausulas_incluir"] == []
    assert decisao["regras_versoes"] == []  # nenhuma satisfeita


# ---------------------------------------------------------------------------
# KQ-003: fonte revogada; vigência
# ---------------------------------------------------------------------------
def test_fonte_revogada_ignora_a_regra_com_anotacao():
    regra = _regra_me_epp(fontes=["in-65-2021"])
    decisao = conhecimento.resolver(_fatos(), [regra], {"in-65-2021"}, "p1")
    assert decisao["resultado"]["clausulas_incluir"] == []
    ignoradas = decisao["resultado"]["regras_ignoradas"]
    assert any("fonte revogada" in i["motivo"] for i in ignoradas)


def test_vigencia_futura_e_expirada_nao_aplicam():
    agora = datetime(2026, 7, 14, tzinfo=timezone.utc)
    futura = _regra_me_epp(vigencia_inicio="2027-01-01T00:00:00+00:00")
    expirada = _regra_me_epp(vigencia_fim="2026-01-01T00:00:00+00:00")
    decisao = conhecimento.resolver(_fatos(), [futura, expirada], set(),
                                    "p1", agora=agora)
    assert decisao["resultado"]["clausulas_incluir"] == []
    assert len(decisao["resultado"]["regras_ignoradas"]) == 2


# ---------------------------------------------------------------------------
# precedência e conflito (KQ-015)
# ---------------------------------------------------------------------------
def test_camada_mais_especifica_vence_sem_conflito():
    inclui_municipio = _regra_me_epp(camada="municipio")
    exclui_secretaria = governanca.nova_regra(
        "regra.excecao.secretaria", "secretaria",
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        [{"type": "EXCLUIR_CLAUSULA", "target": "clausula.me-epp"}],
        status="PUBLISHED", prioridade=1)
    decisao = conhecimento.resolver(
        _fatos(), [inclui_municipio, exclui_secretaria], set(), "p1")
    resultado = decisao["resultado"]
    assert resultado["clausulas_excluir"] == ["clausula.me-epp"]
    assert resultado["conflitos"] == []


def test_conflito_sem_desempate_bloqueia_e_expoe_as_regras():
    inclui = _regra_me_epp()
    exclui = governanca.nova_regra(
        "regra.oposta", "municipio",
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        [{"type": "EXCLUIR_CLAUSULA", "target": "clausula.me-epp"}],
        status="PUBLISHED", prioridade=100)  # mesma camada e prioridade
    decisao = conhecimento.resolver(_fatos(), [inclui, exclui], set(), "p1")
    resultado = decisao["resultado"]
    assert len(resultado["conflitos"]) == 1
    assert set(resultado["conflitos"][0]["regras"]) == {
        "regra.me-epp.srp-bens", "regra.oposta"}
    assert resultado["clausulas_incluir"] == []  # nada em silêncio
    assert any("conflito" in b["motivo"] for b in resultado["bloqueios"])


def test_bloqueio_e_alerta_por_regra():
    bloqueio = _regra_me_epp(acao={
        "type": "BLOQUEAR_EMISSAO", "motivo": "exige parecer prévio"})
    alerta = governanca.nova_regra(
        "regra.alerta", "plataforma",
        {"field": "valor.total", "operator": "GT", "value": 10000},
        [{"type": "ALERTA", "mensagem": "valor acima da faixa de dispensa"}],
        status="PUBLISHED")
    decisao = conhecimento.resolver(_fatos(), [bloqueio, alerta], set(), "p1")
    resultado = decisao["resultado"]
    assert resultado["bloqueios"][0]["motivo"] == "exige parecer prévio"
    assert resultado["alertas"] == ["valor acima da faixa de dispensa"]


# ---------------------------------------------------------------------------
# KQ-014: reprodutibilidade
# ---------------------------------------------------------------------------
def test_decisao_e_reproduzivel_por_hash():
    regras = [_regra_me_epp()]
    d1 = conhecimento.resolver(_fatos(), regras, set(), "p1")
    d2 = conhecimento.resolver(_fatos(), regras, set(), "p1")
    assert d1["input_hash"] == d2["input_hash"]
    assert d1["output_hash"] == d2["output_hash"]


# ---------------------------------------------------------------------------
# flags: shadow registra sem afetar; ativo devolve a decisão
# ---------------------------------------------------------------------------
def test_shadow_registra_decisao_e_nao_afeta_a_tela(monkeypatch, caplog):
    registradas = []
    monkeypatch.setattr(
        conhecimento.db, "flag_ativa",
        lambda n: n == governanca.FLAG_MOTOR_SHADOW)
    monkeypatch.setattr(conhecimento.db, "disponivel", lambda: True)
    monkeypatch.setattr(conhecimento.db, "listar_fatos", lambda p: [])
    monkeypatch.setattr(conhecimento.db, "listar_regras",
                        lambda: [_regra_me_epp()])
    monkeypatch.setattr(conhecimento.db, "registrar_decisao",
                        lambda d: registradas.append(d) or d)
    monkeypatch.setattr(conhecimento, "fontes_revogadas_do_banco",
                        lambda: set())
    st.session_state.pop("_decisao_cache", None)
    with caplog.at_level("INFO", logger="govdocs.conhecimento"):
        resultado = conhecimento.executar_na_tela(DADOS_SRP_BENS, "p1")
    assert resultado is None            # tela intacta
    assert len(registradas) == 1        # decisão persistida
    assert any("shadow" in r.message for r in caplog.records)

    # mesma entrada: cache evita duplicar o registro (idempotência)
    conhecimento.executar_na_tela(DADOS_SRP_BENS, "p1")
    assert len(registradas) == 1


def test_motor_ativo_devolve_decisao(monkeypatch):
    monkeypatch.setattr(
        conhecimento.db, "flag_ativa",
        lambda n: n == governanca.FLAG_MOTOR_ATIVO)
    monkeypatch.setattr(conhecimento.db, "disponivel", lambda: False)
    st.session_state.pop("_decisao_cache", None)
    decisao = conhecimento.executar_na_tela(DADOS_SRP_BENS, "p1")
    assert decisao is not None
    assert decisao["tipo_decisao"] == "resolucao_conhecimento"


def test_flags_desligadas_nao_fazem_nada(monkeypatch):
    monkeypatch.setattr(conhecimento.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flags OFF não podem resolver")

    monkeypatch.setattr(conhecimento, "resolver", explode)
    assert conhecimento.executar_na_tela(DADOS_SRP_BENS, "p1") is None
