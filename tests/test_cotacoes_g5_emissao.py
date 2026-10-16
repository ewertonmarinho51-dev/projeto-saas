"""
G5 — formalização: registro de emissão (hash decisório + hash do
arquivo + pendências impressas), conferência de identificador, prévia
na tela, fornecedores sugeridos das referências reais e aplicação ao
processo amarrada à versão (pacote: U08; dossiê: F132, F140, F151, F162).
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from pathlib import Path

from streamlit.testing.v1 import AppTest

from src.precos import cotacao, cotacoes, relatorio
from src.precos import repositorio as repo
from tests.cotacoes_apoio import ligar_banco_falso, linha
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte
from tests.test_cotacoes_g2_ui import _app, _botao

APP = str(Path(__file__).resolve().parents[1] / "app.py")


def _cotacao_pesquisada(monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Emissão"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    outro = cotacoes.salvar_item(CTX, str(c["id"]),
                                 {**ITEM, "descricao": "ITEM SEM PRECO"})
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    return cliente, repo.obter_pesquisa(str(c["id"])), item, outro


def _tudo(pid):
    itens = cotacoes.ativos(repo.listar_itens(pid))
    return itens, {str(i["id"]): repo.listar_referencias(str(i["id"]))
                   for i in itens}


def test_dados_da_emissao_trazem_os_dois_hashes_e_as_pendencias(monkeypatch):
    _, pesquisa, item, outro = _cotacao_pesquisada(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    conteudo = b"%PDF-fake"
    dados = relatorio.dados_da_emissao(pesquisa, itens, refs, tipo="completo",
                                       formato="pdf", conteudo=conteudo,
                                       nome_arquivo="x.pdf")
    assert dados["hash_arquivo"] == hashlib.sha256(conteudo).hexdigest()
    assert dados["hash_decisorio"] == relatorio.identificador_da_versao(
        pesquisa, itens, refs)
    itens_pendentes = {p["item"] for p in dados["pendencias"]}
    assert itens_pendentes == {1, 2}, "item em revisão e item sem preço"
    assert not {"ip", "endereco_ip", "ip_origem"} & set(dados), "sem IP (LGPD)"


def test_mesmo_resultado_mesmo_hash_decisorio_em_emissoes_diferentes(monkeypatch):
    _, pesquisa, *_ = _cotacao_pesquisada(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    a = relatorio.dados_da_emissao(pesquisa, itens, refs, tipo="completo",
                                   formato="pdf", conteudo=b"1", nome_arquivo="a")
    b = relatorio.dados_da_emissao(pesquisa, itens, refs, tipo="completo",
                                   formato="pdf", conteudo=b"2", nome_arquivo="a")
    assert a["hash_decisorio"] == b["hash_decisorio"]
    assert a["hash_arquivo"] != b["hash_arquivo"]


def test_registro_e_listagem_e_falha_sem_0029_nao_derruba(monkeypatch):
    cliente, pesquisa, *_ = _cotacao_pesquisada(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    dados = relatorio.dados_da_emissao(pesquisa, itens, refs, tipo="resumido",
                                       formato="pdf", conteudo=b"x",
                                       nome_arquivo="r.pdf")
    assert repo.registrar_emissao(str(pesquisa["id"]), dados) is not None
    [registro] = repo.listar_emissoes(str(pesquisa["id"]))
    assert registro["hash_arquivo"] == dados["hash_arquivo"]

    from src import db

    incidentes = []
    monkeypatch.setattr(db, "registrar_incidente",
                        lambda exc, contexto="": incidentes.append(contexto))

    class _SemTabela:
        def table(self, nome):
            raise RuntimeError('relation "pesquisa_preco_emissoes" does not exist')

    monkeypatch.setattr(db, "cliente_do_usuario", lambda: _SemTabela())
    assert repo.registrar_emissao(str(pesquisa["id"]), dados) is None
    assert incidentes == ["registro de emissão de preços"]


def test_conferencia_de_identificador(monkeypatch):
    _, pesquisa, item, _ = _cotacao_pesquisada(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    impresso = relatorio.identificador_da_versao(pesquisa, itens, refs)
    assert relatorio.conferir_identificador(
        pesquisa, itens, refs, impresso[:16]).startswith("confere")
    [r1, *_] = repo.listar_referencias(str(item["id"]))
    cotacoes.alterar_status_referencia(CTX, str(pesquisa["id"]), str(item["id"]),
                                       str(r1["id"]), incluir=False,
                                       motivo="depois da emissão")
    itens, refs = _tudo(str(pesquisa["id"]))
    assert relatorio.conferir_identificador(
        pesquisa, itens, refs, impresso).startswith("NÃO confere")
    v1 = relatorio.identificador_da_versao_v1(pesquisa, itens, refs)
    assert "formato 1" in relatorio.conferir_identificador(pesquisa, itens, refs, v1)


def test_fornecedores_sugeridos_vem_das_referencias_e_nao_do_preco():
    linhas = [linha("10.00", ni_fornecedor="11.222.333/0001-81",
                    fornecedor="Alfa"),
              linha("9.00", "candidate", ident="b", ni_fornecedor="",
                    fornecedor="Beta"),
              linha("12.00", ident="c", ni_fornecedor="11222333000181",
                    fornecedor="Alfa")]
    sugeridos = cotacao.fornecedores_sugeridos(linhas)
    assert [s["fornecedor"] for s in sugeridos] == ["Alfa", "Beta"]
    assert sugeridos[0]["na_cesta"] == 2 and sugeridos[0]["aparicoes"] == 2


def test_gerar_relatorio_na_tela_registra_a_emissao(monkeypatch):
    from src.ui import cotacoes_ui, precos_ui

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    c = cotacoes.criar_cotacao(CTX, {"nome": "Tela"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    cotacoes.concluir_item(CTX, str(c["id"]), str(item["id"]),
                           justificativa="conferido na fonte oficial")
    monkeypatch.setattr(precos_ui, "_conteudo_do_relatorio",
                        lambda *a, **k: (b"%PDF-teste", "rel.pdf",
                                         "application/pdf"))
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state["cot_painel_relatorio"] = True
    at.run()
    assert not at.exception
    assert any("Prévia do quadro resumido" in str(e.label) for e in at.expander)
    _botao(at, "Quadro resumido (PDF)").click().run()
    assert not at.exception
    [registro] = cliente.tabelas["pesquisa_preco_emissoes"]
    assert registro["hash_arquivo"] == hashlib.sha256(b"%PDF-teste").hexdigest()
    tipos = [e["tipo"] for e in cliente.tabelas["pesquisa_preco_eventos"]]
    assert "relatorio_emitido" in tipos


def test_aviso_nominal_bloqueia_emissao_ate_a_ciencia(monkeypatch):
    from src.ui import cotacoes_ui

    at, _ = _app(monkeypatch, unificada=True, pagina="Cotações")
    c = cotacoes.criar_cotacao(CTX, {"nome": "Pendente"})
    cotacoes.salvar_item(CTX, str(c["id"]), {**ITEM, "descricao": "SEM PRECO X"})
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state["cot_painel_relatorio"] = True
    at.run()
    assert not at.exception
    avisos = " ".join(str(w.value) for w in at.warning)
    assert "SEM PRECO X" in avisos and "ainda não pesquisado" in avisos
    assert not any(b.label == "Quadro resumido (PDF)" for b in at.button)
    next(c for c in at.checkbox if "Estou ciente" in c.label).check().run()
    assert any(b.label == "Quadro resumido (PDF)" for b in at.button)


def test_sem_a_versao_de_cotacoes_nao_tenta_gravar_emissao(monkeypatch):
    """Produção sem a 0029: nenhuma escrita na tabela inexistente."""
    from src import db
    from src.ui import precos_ui

    cliente, pesquisa, *_ = _cotacao_pesquisada(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)
    chamadas = []
    monkeypatch.setattr(repo, "registrar_emissao",
                        lambda *a, **k: chamadas.append(a))
    itens, refs = _tudo(str(pesquisa["id"]))
    precos_ui._registrar_emissao(pesquisa, itens, refs, tipo="resumido",
                                 formato="pdf", conteudo=b"x", nome="r.pdf")
    assert chamadas == []
    assert not [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == "relatorio_emitido"]
