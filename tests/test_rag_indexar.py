"""
`rag.indexar` (M6): a indexação que o Streamlit e a API usam.

O que ela promete além de `indexar_arquivo`: o documento nasce no TENANT
DA SESSÃO (é o que o RLS da 0020 confere no INSERT — o default fixo da
coluna só servia ao tenant original), categoria fora do catálogo é
recusada antes de extrair ou vetorizar, e a resposta diz se o material
ficou pendente de vetor.
"""

from __future__ import annotations

import pytest

from src import rag


@pytest.fixture
def banco(monkeypatch):
    gravados: dict[str, list[dict]] = {}

    class _Tabela:
        def __init__(self, nome):
            self.nome = nome

        def insert(self, dados):
            gravados.setdefault(self.nome, []).extend(dados if isinstance(dados, list) else [dados])
            return self

        def execute(self):
            return type("R", (), {"data": [{"id": "doc-1"}]})()

    class _Cliente:
        def table(self, nome):
            return _Tabela(nome)

    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "_cliente", _Cliente)
    monkeypatch.setattr(rag.db, "tenant_atual", lambda: "tenant-da-sessao")
    monkeypatch.setattr(rag.st, "warning", lambda *a, **k: None)
    return gravados


def test_documento_nasce_no_tenant_da_sessao(banco, monkeypatch):
    monkeypatch.setattr(rag, "_gerar_embeddings", lambda textos, para_consulta: [[0.1] * 768 for _ in textos])
    feito = rag.indexar("norma.txt", "Norma", "lei", b"x" * 200)
    assert banco["documentos_referencia"][0]["tenant_id"] == "tenant-da-sessao"
    assert feito == rag.Indexada(documento_id="doc-1", trechos=len(banco["chunks_referencia"]),
                                 pendente_de_vetor=False)
    assert all(c["documento_id"] == "doc-1" for c in banco["chunks_referencia"])


def test_sem_vetor_a_resposta_diz_pendente(banco, monkeypatch):
    monkeypatch.setattr(rag, "_gerar_embeddings", lambda textos, para_consulta: None)
    feito = rag.indexar("norma.txt", "", "lei", b"x" * 200)
    assert feito.pendente_de_vetor is True
    assert banco["documentos_referencia"][0]["titulo"] == "norma.txt"
    assert rag.indexar_arquivo("norma.txt", "", "lei", b"x" * 200) == feito.trechos


def test_categoria_fora_do_catalogo_e_recusada_antes_de_qualquer_trabalho(banco, monkeypatch):
    def nao_pode(*_a, **_k):
        raise AssertionError("extraiu ou vetorizou com categoria inválida")

    monkeypatch.setattr(rag, "extrair_texto", nao_pode)
    monkeypatch.setattr(rag, "_gerar_embeddings", nao_pode)
    with pytest.raises(rag.ErroRAG, match="Categoria inexistente"):
        rag.indexar("norma.txt", "", "inventada", b"x" * 200)
    assert not banco


def test_falha_nos_trechos_desfaz_o_documento(monkeypatch):
    """Sem compensação, o documento ficava "indexado" sem trecho nenhum."""
    apagados = []

    class _Tabela:
        def __init__(self, nome):
            self.nome, self.op = nome, None

        def insert(self, dados):
            self.op = "insert"
            return self

        def delete(self):
            self.op = "delete"
            return self

        def eq(self, coluna, valor):
            apagados.append((self.nome, coluna, valor))
            return self

        def execute(self):
            if self.nome == "chunks_referencia" and self.op == "insert":
                raise RuntimeError("new row violates row-level security policy")
            return type("R", (), {"data": [{"id": "doc-1"}]})()

    class _Cliente:
        def table(self, nome):
            return _Tabela(nome)

    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag.db, "_cliente", _Cliente)
    monkeypatch.setattr(rag.db, "tenant_atual", lambda: "t")
    monkeypatch.setattr(rag, "_gerar_embeddings", lambda textos, para_consulta: None)
    monkeypatch.setattr(rag.st, "warning", lambda *a, **k: None)
    with pytest.raises(rag.ErroRAG):
        rag.indexar("norma.txt", "", "lei", b"x" * 200)
    assert apagados == [("documentos_referencia", "id", "doc-1")]
