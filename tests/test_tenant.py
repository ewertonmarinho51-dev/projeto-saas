"""Fase 1 multi-tenant: tenant padrão e persistência do registro de geração."""

import time

from src import db, llm


def test_tenant_padrao_sem_contexto():
    assert db.tenant_atual() == db.TENANT_PADRAO


def test_registro_persiste_best_effort_sem_banco(monkeypatch):
    """Sem Supabase (ou sem a migração 0006) o registro não pode quebrar."""
    monkeypatch.setattr(db, "disponivel", lambda: False)
    registro = llm.registrar_geracao("dfd", "openai", time.time(), "ok")
    assert registro["status"] == "ok" and registro["documento"] == "dfd"


def test_registro_envia_tenant_e_campos(monkeypatch):
    capturado = {}

    class _Tabela:
        def insert(self, dados):
            capturado.update(dados)
            return self

        def execute(self):
            return None

    class _Cliente:
        def table(self, nome):
            capturado["_tabela"] = nome
            return _Tabela()

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: _Cliente())
    db.registrar_geracao_bd({
        "processo": "(novo)", "documento": "etp", "motor": "openai",
        "modelo": "gpt-5-mini", "duracao_s": 12.3, "tokens_entrada": 100,
        "tokens_saida": 2000, "request_id": "req_x", "status": "ok",
        "erro": "", "fallback": False,
    })
    assert capturado["_tabela"] == "geracoes"
    assert capturado["tenant_id"] == db.TENANT_PADRAO
    assert capturado["processo_id"] is None            # "(novo)" não é uuid
    assert capturado["documento"] == "etp"
    assert capturado["tokens_saida"] == 2000


def test_registro_engole_erro_de_tabela_ausente(monkeypatch):
    """Migração 0006 ainda não aplicada → insert falha → segue em frente."""
    class _Explode:
        def table(self, nome):
            raise RuntimeError("relation geracoes does not exist")

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "_cliente", lambda: _Explode())
    db.registrar_geracao_bd({"documento": "tr", "motor": "openai",
                             "status": "ok"})  # não levanta
