"""
Testes do modelo canônico de blocos (Etapa 1 da correção automática):
caminhos estáveis, hashes, agrupamento de tabelas, round-trip e
localização de blocos por trecho.
"""

from src import blocos

DOC = """DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA

## 1. INFORMAÇÕES GERAIS

Setor requisitante: Secretaria Municipal de Educação.

## 2. JUSTIFICATIVA

A contratação visa suprir a demanda de material escolar.

| Item | Qtd |
| --- | --- |
| Caneta | 10 |

## 3. PERÍODO

Vigência de 12 meses a contar da assinatura.
"""


def _paths(bs):
    return [b["path"] for b in bs]


def test_divisao_em_blocos_com_caminhos_estaveis():
    bs = blocos.dividir_em_blocos("dfd", DOC)
    assert _paths(bs) == [
        "dfd/preambulo/0",
        "dfd/clausula/1/0", "dfd/clausula/1/1",
        "dfd/clausula/2/0", "dfd/clausula/2/1", "dfd/clausula/2/2",
        "dfd/clausula/3/0", "dfd/clausula/3/1",
    ]
    tipos = {b["path"]: b["tipo"] for b in bs}
    assert tipos["dfd/clausula/1/0"] == "titulo"
    assert tipos["dfd/clausula/2/1"] == "paragrafo"
    assert tipos["dfd/clausula/2/2"] == "tabela"


def test_tabela_agrupada_em_um_unico_bloco():
    bs = blocos.dividir_em_blocos("dfd", DOC)
    tabela = next(b for b in bs if b["tipo"] == "tabela")
    assert tabela["conteudo"].count("|") >= 9  # 3 linhas inteiras
    assert "Caneta" in tabela["conteudo"]


def test_editar_um_bloco_nao_desloca_caminhos_dos_demais():
    editado = DOC.replace("suprir a demanda", "atender à necessidade")
    assert _paths(blocos.dividir_em_blocos("dfd", DOC)) == \
        _paths(blocos.dividir_em_blocos("dfd", editado))


def test_hash_muda_somente_quando_o_conteudo_muda():
    bs1 = blocos.dividir_em_blocos("dfd", DOC)
    bs2 = blocos.dividir_em_blocos(
        "dfd", DOC.replace("12 meses", "24 meses"))
    h1 = {b["path"]: b["hash"] for b in bs1}
    h2 = {b["path"]: b["hash"] for b in bs2}
    assert h1["dfd/clausula/3/1"] != h2["dfd/clausula/3/1"]
    diferentes = [p for p in h1 if h1[p] != h2[p]]
    assert diferentes == ["dfd/clausula/3/1"]


def test_round_trip_reconstruir_e_idempotente():
    bs = blocos.dividir_em_blocos("dfd", DOC)
    texto_normalizado = blocos.reconstruir(bs)
    bs2 = blocos.dividir_em_blocos("dfd", texto_normalizado)
    assert [(b["path"], b["conteudo"]) for b in bs] == \
        [(b["path"], b["conteudo"]) for b in bs2]


def test_clausulas_com_numero_repetido_nao_colidem():
    doc = "## 2. PRIMEIRA\n\ntexto a\n\n## 2. SEGUNDA\n\ntexto b\n"
    paths = _paths(blocos.dividir_em_blocos("tr", doc))
    assert "tr/clausula/2/0" in paths
    assert "tr/clausula/2.2/0" in paths
    assert len(paths) == len(set(paths))


def test_localizar_bloco_por_trecho():
    bs = blocos.dividir_em_blocos("dfd", DOC)
    bloco = blocos.localizar_bloco(bs, "suprir a demanda de material")
    assert bloco is not None
    assert bloco["path"] == "dfd/clausula/2/1"
    assert blocos.localizar_bloco(bs, "texto que não existe") is None
    assert blocos.localizar_bloco(bs, "") is None


def test_caminhos_de_titulos_e_da_clausula():
    bs = blocos.dividir_em_blocos("dfd", DOC)
    assert blocos.caminhos_de_titulos(bs) == [
        "dfd/clausula/1/0", "dfd/clausula/2/0", "dfd/clausula/3/0"]
    assert blocos.caminhos_da_clausula(bs, 2) == [
        "dfd/clausula/2/0", "dfd/clausula/2/1", "dfd/clausula/2/2"]


def test_hash_bundle_estavel_e_independente_de_ordem():
    docs_a = {"dfd": "abc", "etp": "def"}
    docs_b = {"etp": "def", "dfd": "abc"}
    assert blocos.hash_bundle(docs_a) == blocos.hash_bundle(docs_b)
    assert blocos.hash_bundle(docs_a) != blocos.hash_bundle(
        {"dfd": "abc", "etp": "XXX"})


def test_snapshot_bundle_traz_versao_hash_e_blocos():
    snap = blocos.snapshot_bundle({"dfd": DOC}, versao=3)
    assert snap["versao"] == 3
    assert snap["hash"] == blocos.hash_bundle({"dfd": DOC})
    assert snap["documentos"]["dfd"]["hash"] == blocos.hash_texto(DOC)
    assert snap["documentos"]["dfd"]["blocos"][0]["path"] == "dfd/preambulo/0"
