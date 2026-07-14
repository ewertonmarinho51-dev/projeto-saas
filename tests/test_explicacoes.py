"""
Testes da explicabilidade (Fase 4 do pacote V5): explicação aponta
regra e evidência REAIS do registro (KQ-008), nunca inventa quando não
há registro, é determinística, e os níveis admin/auditor expõem trilha
e hashes de reprodução.
"""

from src import conhecimento, explicacoes, fatos, governanca

DADOS = {
    "objeto": "Aquisição de material escolar",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "valor_estimado": 45000.0,
    "itens": [{"descricao": "Caneta", "quantidade": 10,
               "valor_unitario": 2.0}],
}


def _decisao():
    regra = governanca.nova_regra(
        "regra.me-epp.srp-bens", "municipio",
        {"op": "ALL", "children": [
            {"field": "procedimento.srp", "operator": "EQ", "value": True},
            {"field": "objeto.natureza", "operator": "EQ", "value": "BENS"},
        ]},
        [{"type": "INCLUIR_CLAUSULA", "target": "clausula.me-epp"}],
        status="PUBLISHED", fontes=["lc-123-2006"],
        justificativa="Tratamento favorecido para ME/EPP no SRP de bens.")
    lista = fatos.extrair_do_formulario(DADOS, "p1")
    return conhecimento.resolver(lista, [regra], set(), "p1")


# ---------------------------------------------------------------------------
# KQ-008: regra e evidências reais; sem registro, sem explicação
# ---------------------------------------------------------------------------
def test_explicacao_aponta_regra_condicoes_e_fontes_reais():
    decisao = _decisao()
    explicacao = explicacoes.explicar_clausula(decisao, "clausula.me-epp")
    assert explicacao is not None
    assert explicacao["regras"][0]["chave"] == "regra.me-epp.srp-bens"
    condicoes = {c["fato"]: c for c in explicacao["condicoes"]}
    assert condicoes["procedimento.srp"]["observado"] is True
    assert condicoes["objeto.natureza"]["observado"] == "BENS"
    assert explicacao["fontes"] == ["lc-123-2006"]


def test_sem_registro_nao_ha_explicacao():
    decisao = _decisao()
    assert explicacoes.explicar_clausula(
        decisao, "clausula.inexistente") is None


def test_texto_usuario_traz_valores_observados_e_regra():
    decisao = _decisao()
    texto = explicacoes.texto_usuario(
        explicacoes.explicar_clausula(decisao, "clausula.me-epp"))
    assert "clausula.me-epp" in texto
    assert "Sistema de Registro de Preços" in texto  # rótulo amigável
    assert "informado no processo: sim" in texto     # valor observado real
    assert "regra.me-epp.srp-bens v1 (municipio)" in texto
    assert "lc-123-2006" in texto


def test_explicacao_e_deterministica():
    decisao = _decisao()
    a = explicacoes.texto_usuario(
        explicacoes.explicar_clausula(decisao, "clausula.me-epp"))
    b = explicacoes.texto_usuario(
        explicacoes.explicar_clausula(decisao, "clausula.me-epp"))
    assert a == b


# ---------------------------------------------------------------------------
# níveis admin e auditor
# ---------------------------------------------------------------------------
def test_nivel_admin_lista_todas_as_regras_avaliadas():
    decisao = _decisao()
    linhas = explicacoes.texto_admin(decisao)
    assert any("SATISFEITA" in linha for linha in linhas)
    assert any("municipio/p100" in linha for linha in linhas)


def test_nivel_admin_inclui_regras_ignoradas():
    regra = governanca.nova_regra(
        "regra.revogada", "municipio",
        {"field": "procedimento.srp", "operator": "EQ", "value": True},
        [{"type": "ALERTA", "mensagem": "x"}],
        status="PUBLISHED", fontes=["in-antiga"])
    lista = fatos.extrair_do_formulario(DADOS, "p1")
    decisao = conhecimento.resolver(lista, [regra], {"in-antiga"}, "p1")
    linhas = explicacoes.texto_admin(decisao)
    assert any("ignorada: fonte revogada" in linha for linha in linhas)


def test_nivel_auditor_permite_reproducao():
    decisao = _decisao()
    registro = explicacoes.registro_auditor(decisao)
    assert registro["input_hash"] == decisao["input_hash"]
    assert registro["output_hash"] == decisao["output_hash"]
    assert registro["regras_versoes"][0]["versao"] == 1
    assert registro["fatos_versoes"]  # aponta as versões dos fatos usadas
