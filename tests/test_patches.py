"""
Testes do aplicador determinístico (Etapa 4 da correção automática):
transacionalidade, hash de origem, cláusulas FIXED_LOCKED e
FIXED_PARAMETERIZED, escopo por cláusula no diff, orçamento do ciclo e
inserção ordenada de cláusula ausente.
"""

import pytest

from src import achados, blocos, patches

DOC = """## 1. OBJETO

Aquisição de material escolar.

## 2. VIGÊNCIA

Contrato válido por placeholder meses.

## 3. VALOR

R$ 100,00 conforme planilha.
"""


def _plano(ops, docs, versao=1):
    snap = blocos.snapshot_bundle(docs, versao=versao)
    return {
        "patchPlanId": "plano-teste", "bundleId": "b",
        "sourceBundleVersion": versao, "sourceBundleHash": snap["hash"],
        "operations": ops, "unresolvedFindings": [],
    }


def _finding(fid, permitidos, bloqueados=(), fontes=()):
    return {
        "findingId": fid, "documentId": permitidos[0].split("/")[0],
        "autoCorrectable": True, "allowedPaths": list(permitidos),
        "blockedPaths": list(bloqueados), "sourceIds": list(fontes),
    }


def _hash_de(docs, doc_key, path):
    bs = blocos.dividir_em_blocos(doc_key, docs[doc_key])
    return next(b["hash"] for b in bs if b["path"] == path)


# ---------------------------------------------------------------------------
# caminho feliz (T01) e regressão do finding após o patch
# ---------------------------------------------------------------------------
def test_correcao_aplicada_gera_nova_versao_e_resolve_o_finding():
    docs = {"memo": DOC}
    relatorio = achados.gerar_relatorio(docs)
    f = next(x for x in relatorio["findings"]
             if x["categoria"] == "texto_placeholder")
    path = f["allowedPaths"][0]
    plano = _plano([{
        "findingId": f["findingId"], "documentId": "memo", "op": "replace",
        "path": path, "expectedOldHash": _hash_de(docs, "memo", path),
        "newValue": "Contrato válido por 12 (doze) meses.",
        "sourceIds": [], "reason": "r", "expectedImpact": "i",
    }], docs)

    resultado = patches.aplicar_plano(plano, docs, relatorio)
    assert resultado["versao"] == 2
    assert "12 (doze) meses" in resultado["documentos"]["memo"]
    assert resultado["diff"]["documentos"]["memo"]["alterados"] == [path]
    assert docs["memo"] == DOC  # original intocado

    nova_auditoria = achados.gerar_relatorio(resultado["documentos"])
    assert not [x for x in nova_auditoria["findings"]
                if x["categoria"] == "texto_placeholder"]


def test_hash_de_origem_divergente_rejeita_o_plano():
    docs = {"memo": DOC}
    relatorio = achados.gerar_relatorio(docs)
    f = next(x for x in relatorio["findings"] if x["autoCorrectable"])
    plano = _plano([{
        "findingId": f["findingId"], "documentId": "memo", "op": "replace",
        "path": f["allowedPaths"][0], "newValue": "x",
        "sourceIds": [], "reason": "r",
    }], docs)
    editados = {"memo": DOC.replace("R$ 100,00", "R$ 200,00")}
    with pytest.raises(patches.ErroAplicacao) as erro:
        patches.aplicar_plano(plano, editados, relatorio)
    assert "hash de origem" in str(erro.value)


# ---------------------------------------------------------------------------
# cláusulas fixas de governança (T06)
# ---------------------------------------------------------------------------
DOC_DFD = """## 8. PERÍODO

Vigência de 12 meses a contar da assinatura.

## 9. EQUIPE DE PLANEJAMENTO

Fulano de Tal — matrícula 123.
"""


def test_fixed_locked_nunca_e_alterada_mesmo_com_escopo_autorizado():
    docs = {"dfd": DOC_DFD}
    relatorio = {"bundleId": "b", "bundleVersion": 1,
                 "findings": [_finding("F001", ["dfd/clausula/9/1"])]}
    plano = _plano([{
        "findingId": "F001", "documentId": "dfd", "op": "replace",
        "path": "dfd/clausula/9/1",
        "expectedOldHash": _hash_de(docs, "dfd", "dfd/clausula/9/1"),
        "newValue": "Beltrano — matrícula 999.", "sourceIds": [],
        "reason": "r",
    }], docs)
    with pytest.raises(patches.ErroAplicacao) as erro:
        patches.aplicar_plano(plano, docs, relatorio)
    assert "FIXED_LOCKED" in str(erro.value)
    assert docs["dfd"] == DOC_DFD


def test_fixed_parameterized_aceita_so_troca_de_parametros():
    docs = {"dfd": DOC_DFD}
    relatorio = {"bundleId": "b", "bundleVersion": 1,
                 "findings": [_finding("F001", ["dfd/clausula/8/1"])]}

    def plano_com(novo_texto):
        return _plano([{
            "findingId": "F001", "documentId": "dfd", "op": "replace",
            "path": "dfd/clausula/8/1",
            "expectedOldHash": _hash_de(docs, "dfd", "dfd/clausula/8/1"),
            "newValue": novo_texto, "sourceIds": [], "reason": "r",
        }], docs)

    resultado = patches.aplicar_plano(
        plano_com("Vigência de 24 meses a contar da assinatura."),
        docs, relatorio)
    assert "24 meses" in resultado["documentos"]["dfd"]

    with pytest.raises(patches.ErroAplicacao) as erro:
        patches.aplicar_plano(
            plano_com("Vigência de 24 meses a partir da ordem de serviço."),
            docs, relatorio)
    assert "FIXED_PARAMETERIZED" in str(erro.value)


# ---------------------------------------------------------------------------
# escopo por cláusula no diff (T05/T07) e transacionalidade
# ---------------------------------------------------------------------------
def test_efeito_em_clausula_nao_autorizada_rejeita_tudo():
    """Op autorizada cujo newValue 'vaza' uma cláusula nova não prevista."""
    docs = {"memo": DOC}
    relatorio = {"bundleId": "b", "bundleVersion": 1,
                 "findings": [_finding("F001", ["memo/clausula/2/1"])]}
    plano = _plano([{
        "findingId": "F001", "documentId": "memo", "op": "replace",
        "path": "memo/clausula/2/1",
        "expectedOldHash": _hash_de(docs, "memo", "memo/clausula/2/1"),
        "newValue": "Contrato válido por 12 meses.\n\n"
                    "## 4. CLÁUSULA INTRUSA\n\nTexto não autorizado.",
        "sourceIds": [], "reason": "r",
    }], docs)
    with pytest.raises(patches.ErroAplicacao) as erro:
        patches.aplicar_plano(plano, docs, relatorio)
    assert "fora do escopo" in str(erro.value)
    assert docs["memo"] == DOC  # nada foi aplicado (transacional)


def test_replace_que_vira_dois_paragrafos_na_mesma_clausula_passa():
    docs = {"memo": DOC}
    relatorio = {"bundleId": "b", "bundleVersion": 1,
                 "findings": [_finding("F001", ["memo/clausula/2/1"])]}
    plano = _plano([{
        "findingId": "F001", "documentId": "memo", "op": "replace",
        "path": "memo/clausula/2/1",
        "expectedOldHash": _hash_de(docs, "memo", "memo/clausula/2/1"),
        "newValue": "Contrato válido por 12 meses.\n\n"
                    "A prorrogação observará o art. 107 da Lei 14.133/2021.",
        "sourceIds": [], "reason": "r",
    }], docs)
    resultado = patches.aplicar_plano(plano, docs, relatorio,
                                      max_proporcao_blocos=0.5)
    assert "prorrogação" in resultado["documentos"]["memo"]


def test_orcamento_do_ciclo_rejeita_alteracao_em_massa():
    docs = {"memo": DOC}
    relatorio = {"bundleId": "b", "bundleVersion": 1, "findings": [
        _finding("F001", ["memo/clausula/1/1"]),
        _finding("F002", ["memo/clausula/2/1"]),
    ]}
    ops = [{
        "findingId": fid, "documentId": "memo", "op": "replace",
        "path": path, "expectedOldHash": _hash_de(docs, "memo", path),
        "newValue": f"Texto novo da {path}.", "sourceIds": [], "reason": "r",
    } for fid, path in [("F001", "memo/clausula/1/1"),
                        ("F002", "memo/clausula/2/1")]]
    with pytest.raises(patches.ErroAplicacao) as erro:
        patches.aplicar_plano(_plano(ops, docs), docs, relatorio,
                              max_proporcao_blocos=0.25)
    assert "orçamento" in str(erro.value)  # 2/6 blocos = 33% > 25%
    resultado = patches.aplicar_plano(_plano(ops, docs), docs, relatorio,
                                      max_proporcao_blocos=0.5)
    assert resultado["versao"] == 2


# ---------------------------------------------------------------------------
# inserção de cláusula ausente na posição correta
# ---------------------------------------------------------------------------
def test_add_de_clausula_ausente_insere_entre_as_vizinhas():
    doc = ("## 1. OBJETO\n\nAquisição de canetas.\n\n"
           "## 2. JUSTIFICATIVA\n\nDemanda da rede escolar.\n\n"
           "## 4. VALOR\n\nR$ 100,00.\n")
    docs = {"memo": doc}
    relatorio = {"bundleId": "b", "bundleVersion": 1,
                 "findings": [_finding("F001", ["memo/clausula/3"])]}
    plano = _plano([{
        "findingId": "F001", "documentId": "memo", "op": "add",
        "path": "memo/clausula/3",
        "newValue": "## 3. PERÍODO\n\nVigência de 12 meses.",
        "sourceIds": [], "reason": "r",
    }], docs)
    resultado = patches.aplicar_plano(plano, docs, relatorio,
                                      max_proporcao_blocos=0.5)
    texto = resultado["documentos"]["memo"]
    assert texto.index("## 2.") < texto.index("## 3.") < texto.index("## 4.")
    paths = [b["path"] for b in
             blocos.dividir_em_blocos("memo", texto)]
    assert "memo/clausula/3/0" in paths and "memo/clausula/3/1" in paths
