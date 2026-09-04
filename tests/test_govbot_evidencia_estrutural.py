"""Numeração/diagnóstico estrutural não autoriza valores materiais na prosa."""

import copy

import pytest

from src import achados, blocos, corretor, db, govbot


def _estado(texto):
    return {"dados": {"objeto": "Cadeiras"}, "documentos": {"dfd": texto},
            "aprovados": set(), "edicoes_pendentes": {}, "etapa": 1,
            "processo_id": None, "_save_status": "local"}


def _plano(relatorio, documentos, finding, novo, op):
    snapshot = blocos.snapshot_bundle(documentos)
    path = finding["allowedPaths"][0]
    bloco = next((b for b in snapshot["documentos"]["dfd"]["blocos"]
                  if b["path"] == path), None)
    return {
        "patchPlanId": "plano-material", "bundleId": relatorio["bundleId"],
        "sourceBundleVersion": 1, "sourceBundleHash": snapshot["hash"],
        "operations": [{
            "operationId": "OP001", "findingId": finding["findingId"],
            "documentId": "dfd", "op": op, "path": path,
            "expectedOldHash": bloco["hash"] if bloco else None,
            "newValue": novo, "sourceIds": finding["sourceIds"], "reason": "Correção",
            "expectedImpact": "Texto consistente",
        }], "unresolvedFindings": [], "createdAt": "2026-09-04T00:00:00Z",
    }


@pytest.mark.parametrize("novo,permitido", [
    ("# 3. ANÁLISE\n\nAnálise completa.", True),
    ("# 3. ANÁLISE\n\nSerão analisadas 3 alternativas.", False),
    ("# 3. ANÁLISE\n\nSerão analisadas três alternativas.", False),
    ("# 3. ANÁLISE DE 3 ALTERNATIVAS\n\nAnálise completa.", False),
    ("# 999. ANÁLISE\n\nAnálise completa.", False),
    ("# 3. ANÁLISE\n\n# 4. OUTRA CLÁUSULA\n\nTexto.", False),
])
def test_achado_real_de_clausula_ausente_nao_e_fonte_material(
    monkeypatch, novo, permitido,
):
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    estado = _estado("# 1. CONTEXTO\n\nAnálise pendente.")
    # O relatório e a classificação são reais; somente a saída de IA é dupla.
    relatorio = achados.gerar_relatorio(estado["documentos"], dados=estado["dados"])
    finding = next(f for f in relatorio["findings"]
                   if f["allowedPaths"] == ["dfd/clausula/3"])
    assert finding["autoCorrectable"]
    assert "3." in finding["descricao"]
    monkeypatch.setattr(corretor, "gerar_plano", lambda r, docs, *_a, **_k:
                        _plano(r, docs, finding, novo, "add"))
    bucket = govbot.obter_bucket(estado)
    antes = copy.deepcopy(estado)
    if permitido:
        resposta = govbot.corrigir_achado(
            estado, bucket, finding["findingId"], "material-add-001",
            max_proporcao_blocos=1.0)
        assert resposta.applied
        assert novo in estado["documentos"]["dfd"]
    else:
        with pytest.raises((govbot.ErroValorMaterial, govbot.ErroAlvo)):
            govbot.corrigir_achado(
                estado, bucket, finding["findingId"], "material-add-001",
                max_proporcao_blocos=1.0)
        assert estado == antes


@pytest.mark.parametrize("numero", ["3", "três"])
@pytest.mark.parametrize("origem", ["path", "descricao", "resultadoEsperado", "evidencia"])
def test_correcao_nao_reaproveita_numero_estrutural(
    monkeypatch, numero, origem,
):
    estado = _estado("# 3. ANÁLISE\n\nAnálise pendente.")
    path = blocos.dividir_em_blocos("dfd", estado["documentos"]["dfd"])[1]["path"]
    finding = {
        "findingId": "F001", "documentId": "dfd", "categoria": "clareza",
        "descricao": "Análise incompleta", "resultadoEsperado": "Clareza",
        "regraViolada": "clareza", "evidencia": [], "autoCorrectable": True,
        "allowedPaths": [path], "blockedPaths": [], "sourceIds": [],
        "blockingReason": None,
    }
    if origem in ("descricao", "resultadoEsperado"):
        finding[origem] = "Revisar a cláusula 3."
    elif origem == "evidencia":
        finding[origem] = ["# 3. ANÁLISE\n\nAnálise pendente."]
    relatorio = {
        "auditId": "audit-material", "bundleId": "bundle-material",
        "bundleVersion": 1, "bundleHash": blocos.hash_bundle(estado["documentos"]),
        "status": "CORRECTIONS_REQUIRED", "findings": [finding],
    }
    novo = f"Serão analisadas {numero} alternativas."
    monkeypatch.setattr(achados, "gerar_relatorio", lambda *_a, **_k: relatorio)
    monkeypatch.setattr(corretor, "gerar_plano", lambda r, docs, *_a, **_k:
                        _plano(r, docs, finding, novo, "replace"))
    bucket = govbot.obter_bucket(estado)
    antes = copy.deepcopy(estado)
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.corrigir_achado(estado, bucket, "F001", "material-replace-001")
    assert estado == antes


def test_correcao_legal_real_preserva_dispositivo_do_mapa_canonico(monkeypatch):
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    estado = _estado("# 3. PAGAMENTO\n\nO pagamento obedece ao art. 98 da Lei nº 14.133/2021.")
    relatorio = achados.gerar_relatorio(estado["documentos"], dados=estado["dados"])
    finding = next(f for f in relatorio["findings"]
                   if f["categoria"] == "fundamento_legal" and f["autoCorrectable"])
    novo = "O pagamento obedece ao art. 141 da Lei nº 14.133/2021."
    monkeypatch.setattr(corretor, "gerar_plano", lambda r, docs, *_a, **_k:
                        _plano(r, docs, finding, novo, "replace"))
    resultado = govbot.corrigir_achado(
        estado, govbot.obter_bucket(estado), finding["findingId"],
        "material-legal-001", max_proporcao_blocos=1.0)
    assert resultado.applied
    assert novo in estado["documentos"]["dfd"]


@pytest.mark.parametrize("numero", ["3", "três"])
def test_recorte_real_achatado_nao_transforma_titulo_em_quantidade(monkeypatch, numero):
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    estado = _estado(
        "Introdução preliminar.\n\n# 3. ANÁLISE\n\n"
        "Texto placeholder precisa ser revisado.")
    relatorio = achados.gerar_relatorio(estado["documentos"], dados=estado["dados"])
    finding = next(f for f in relatorio["findings"]
                   if f["categoria"] == "texto_placeholder" and f["autoCorrectable"])
    assert any("# 3." in trecho and "\n" not in trecho for trecho in finding["evidencia"])
    novo = f"Serão analisadas {numero} alternativas."
    monkeypatch.setattr(corretor, "gerar_plano", lambda r, docs, *_a, **_k:
                        _plano(r, docs, finding, novo, "replace"))
    bucket = govbot.obter_bucket(estado)
    antes = copy.deepcopy(estado)
    with pytest.raises(govbot.ErroValorMaterial):
        govbot.corrigir_achado(
            estado, bucket, finding["findingId"], "material-recorte-001",
            max_proporcao_blocos=1.0)
    assert estado == antes
