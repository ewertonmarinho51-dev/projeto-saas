"""
Testes do corretor por patches (Etapa 3 da correção automática):
validação determinística do plano, tentativas técnicas, montagem do
prompt restrita ao escopo e shadow mode (flag OFF = nenhuma chamada).
"""

import json

import pytest

from src import achados, blocos, corretor

DOC = """## 1. OBJETO

Aquisição de material escolar.

## 2. VIGÊNCIA

Contrato válido por placeholder meses.

## 3. VALOR

R$ 100,00 conforme planilha.
"""

DOCS = {"memo": DOC}
DADOS = {"orgao": "Prefeitura", "prazo": "12 meses",
         "itens": [{"descricao": "Caneta", "quantidade": 10}]}


def _relatorio():
    return achados.gerar_relatorio(DOCS, "proc-1")


def _finding_corrigivel(relatorio):
    return next(f for f in relatorio["findings"] if f["autoCorrectable"])


def _resposta_valida(relatorio):
    f = _finding_corrigivel(relatorio)
    path = f["allowedPaths"][0]
    bs = blocos.dividir_em_blocos("memo", DOC)
    hash_atual = next(b["hash"] for b in bs if b["path"] == path)
    return json.dumps({
        "operations": [{
            "findingId": f["findingId"],
            "documentId": "memo",
            "op": "replace",
            "path": path,
            "expectedOldHash": hash_atual,
            "newValue": "Contrato válido por 12 (doze) meses.",
            "sourceIds": ["formulario:prazo"],
            "reason": "remove texto provisório",
            "expectedImpact": "cláusula de vigência definitiva",
        }],
        "unresolvedFindings": [],
    })


# ---------------------------------------------------------------------------
# geração do plano
# ---------------------------------------------------------------------------
def test_plano_valido_ganha_envelope_com_hash_da_versao():
    relatorio = _relatorio()
    chamadas = []

    def fake(system, user, finalidade):
        chamadas.append(finalidade)
        return _resposta_valida(relatorio)

    plano = corretor.gerar_plano(relatorio, DOCS, DADOS, chamar=fake)
    assert chamadas == ["corretor"]
    assert plano["sourceBundleHash"] == blocos.hash_bundle(DOCS)
    assert plano["sourceBundleVersion"] == 1
    assert plano["operations"][0]["operationId"] == "OP001"
    assert corretor.validar_plano(plano, relatorio, blocos.snapshot_bundle(DOCS)) == []


def test_sem_findings_corrigiveis_nao_chama_a_ia():
    doc_limpo = {"memo": "## 1. OBJETO\n\nAquisição de canetas.\n"}
    relatorio = achados.gerar_relatorio(doc_limpo)

    def fake(*_a, **_k):
        raise AssertionError("não deveria chamar a IA")

    plano = corretor.gerar_plano(relatorio, doc_limpo, DADOS, chamar=fake)
    assert plano["operations"] == []


def test_findings_manuais_entram_como_nao_resolvidos():
    docs = {"memo": DOC + "\nPrazo: [PREENCHER: prazo de vigência]\n"}
    relatorio = achados.gerar_relatorio(docs)

    def fake(system, user, finalidade):
        f = next(x for x in relatorio["findings"] if x["autoCorrectable"])
        bs = blocos.dividir_em_blocos("memo", docs["memo"])
        h = next(b["hash"] for b in bs if b["path"] == f["allowedPaths"][0])
        return json.dumps({"operations": [{
            "findingId": f["findingId"], "documentId": "memo",
            "op": "replace", "path": f["allowedPaths"][0],
            "expectedOldHash": h, "newValue": "Texto corrigido.",
            "sourceIds": f["sourceIds"] or ["formulario:prazo"],
            "reason": "corrige", "expectedImpact": "ok",
        }], "unresolvedFindings": []})

    plano = corretor.gerar_plano(relatorio, docs, DADOS, chamar=fake)
    pendente = next(u for u in plano["unresolvedFindings"]
                    if u["requiresHumanInput"])
    assert pendente["requiredFields"] == ["prazo de vigência"]


def test_retry_tecnico_apos_json_invalido():
    relatorio = _relatorio()
    respostas = ["isto não é JSON", _resposta_valida(relatorio)]
    recebidos = []

    def fake(system, user, finalidade):
        recebidos.append(user)
        return respostas[len(recebidos) - 1]

    plano = corretor.gerar_plano(relatorio, DOCS, DADOS, chamar=fake)
    assert len(recebidos) == 2
    assert "rejeitada" in recebidos[1]  # feedback da 1ª falha na 2ª chamada
    assert plano["operations"]


def test_escopo_violado_duas_vezes_gera_erro_explicito():
    relatorio = _relatorio()
    f = _finding_corrigivel(relatorio)
    fora_do_escopo = json.dumps({"operations": [{
        "findingId": f["findingId"], "documentId": "memo",
        "op": "replace", "path": "memo/clausula/3/1",
        "newValue": "R$ 999.999,99", "sourceIds": ["formulario:prazo"],
        "reason": "x", "expectedImpact": "x",
    }], "unresolvedFindings": []})

    with pytest.raises(corretor.ErroCorrecao) as erro:
        corretor.gerar_plano(relatorio, DOCS, DADOS,
                             chamar=lambda *a, **k: fora_do_escopo)
    assert "fora do escopo" in str(erro.value)


# ---------------------------------------------------------------------------
# validação determinística do plano
# ---------------------------------------------------------------------------
def _plano_base(relatorio, **op_extra):
    f = _finding_corrigivel(relatorio)
    op = {
        "findingId": f["findingId"], "documentId": "memo",
        "op": "replace", "path": f["allowedPaths"][0],
        "newValue": "novo", "sourceIds": list(f["sourceIds"]),
        "reason": "r", "expectedImpact": "i",
    } | op_extra
    return {"operations": [op], "unresolvedFindings": []}


def test_validar_plano_rejeita_finding_nao_autorizado():
    relatorio = _relatorio()
    plano = _plano_base(relatorio, findingId="F999")
    violacoes = corretor.validar_plano(
        plano, relatorio, blocos.snapshot_bundle(DOCS))
    assert any("não autorizado" in v for v in violacoes)


def test_validar_plano_rejeita_operacao_desconhecida():
    relatorio = _relatorio()
    plano = _plano_base(relatorio, op="rewrite_all")
    violacoes = corretor.validar_plano(
        plano, relatorio, blocos.snapshot_bundle(DOCS))
    assert any("tipo inválido" in v for v in violacoes)


def test_validar_plano_rejeita_hash_de_origem_divergente():
    relatorio = _relatorio()
    plano = _plano_base(relatorio, expectedOldHash="hash-errado")
    violacoes = corretor.validar_plano(
        plano, relatorio, blocos.snapshot_bundle(DOCS))
    assert any("hash de origem divergente" in v for v in violacoes)


def test_validar_plano_rejeita_excesso_de_operacoes():
    relatorio = _relatorio()
    op = _plano_base(relatorio)["operations"][0]
    plano = {"operations": [dict(op) for _ in range(31)],
             "unresolvedFindings": []}
    violacoes = corretor.validar_plano(
        plano, relatorio, blocos.snapshot_bundle(DOCS))
    assert any("máximo de 30" in v for v in violacoes)


def test_extrair_json_tolerante_a_cerca_de_codigo():
    assert corretor.extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(corretor.ErroCorrecao):
        corretor.extrair_json("sem json aqui")


# ---------------------------------------------------------------------------
# prompt restrito ao escopo
# ---------------------------------------------------------------------------
def test_prompt_do_corretor_so_leva_blocos_do_escopo():
    relatorio = _relatorio()
    corrigiveis = [f for f in relatorio["findings"] if f["autoCorrectable"]]
    _, user = corretor.montar_prompt(corrigiveis, DOCS, DADOS)
    payload = json.loads(user)
    paths_enviados = {b["path"] for b in payload["blocosAtuais"]}
    autorizados = {p for f in corrigiveis for p in f["allowedPaths"]}
    assert paths_enviados == autorizados
    assert "formulario:prazo" in payload["fontes"]
    assert "formulario:itens" in payload["fontes"]


# ---------------------------------------------------------------------------
# shadow mode
# ---------------------------------------------------------------------------
def test_shadow_desligado_nao_chama_nada(monkeypatch):
    monkeypatch.setattr(corretor.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("flag OFF não pode gerar plano")

    monkeypatch.setattr(corretor, "gerar_plano", explode)
    assert corretor.plano_em_shadow(DOCS, DADOS, "proc-1") is None


def test_shadow_ligado_roda_uma_vez_por_versao(monkeypatch, caplog):
    import streamlit as st

    monkeypatch.setattr(corretor.db, "flag_ativa",
                        lambda n: n == corretor.FLAG_CORRETOR)
    monkeypatch.setattr(corretor.db, "disponivel", lambda: False)
    st.session_state.pop("_shadow_plano_hash", None)
    chamadas = []

    def fake_gerar(relatorio, documentos, dados):
        chamadas.append(1)
        return {"patchPlanId": "p1", "operations": [],
                "unresolvedFindings": []}

    monkeypatch.setattr(corretor, "gerar_plano", fake_gerar)
    with caplog.at_level("INFO", logger="govdocs.corretor"):
        corretor.plano_em_shadow(DOCS, DADOS, "proc-1")
        corretor.plano_em_shadow(DOCS, DADOS, "proc-1")  # mesma versão
    assert len(chamadas) == 1
    assert any("shadow" in r.message for r in caplog.records)


def test_shadow_falha_de_ia_nao_derruba_a_tela(monkeypatch):
    import streamlit as st

    monkeypatch.setattr(corretor.db, "flag_ativa",
                        lambda n: n == corretor.FLAG_CORRETOR)
    monkeypatch.setattr(corretor.db, "disponivel", lambda: False)
    st.session_state.pop("_shadow_plano_hash", None)

    def explode(*_a, **_k):
        raise corretor.ErroCorrecao("IA fora do ar")

    monkeypatch.setattr(corretor, "gerar_plano", explode)
    corretor.plano_em_shadow(DOCS, DADOS, "proc-1")  # não pode levantar
