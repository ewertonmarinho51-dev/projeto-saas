"""
G2 — telas de Cotações no AppTest (app inteiro, banco falso, fontes dublês).

* flag DESLIGADA: o menu continua "Pesquisa de Preços" e a tela antiga
  roda — rollback é desligar a flag;
* flag LIGADA: "Cotações" substitui a entrada (uma porta só), Minhas
  Cotações → Nova cotação → Elaborar Cotação; no MESMO item, busca manual
  e Cotação automática gravam a mesma cesta; o cabeçalho mostra N/3;
* conflito de versão vindo de "outra aba" aparece como aviso, sem
  sobrescrever.
"""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from src import db, governanca
from src.precos import cotacoes
from src.precos import repositorio as repo
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte

APP = str(Path(__file__).resolve().parents[1] / "app.py")
USUARIO = {"auth_user_id": "u1", "login": "servidor.teste",
           "nome": "Servidor Teste", "papel": "servidor", "secretaria_id": None}


def _app(monkeypatch, *, unificada: bool, pagina: str):
    from src.ui import cotacoes_ui, precos_ui

    ligadas = {repo.FLAG} | ({governanca.FLAG_COTACOES_UNIFICADAS}
                             if unificada else set())
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)
    cliente = ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_fonte()])
    monkeypatch.setattr(cotacoes_ui, "_fontes", lambda: [_fonte()])
    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = pagina
    at.session_state["usuario"] = USUARIO
    return at, cliente


def _botao(at, rotulo):
    return next(b for b in at.button if b.label == rotulo)


def test_flag_desligada_mantem_a_pesquisa_de_precos(monkeypatch):
    at, _ = _app(monkeypatch, unificada=False, pagina="Pesquisa de Preços")
    at.run()
    assert not at.exception
    opcoes = at.radio(key="pagina").options
    assert "Pesquisa de Preços" in opcoes and "Cotações" not in opcoes


def test_flag_ligada_uma_entrada_so_e_criacao_da_cotacao(monkeypatch):
    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    at.run()
    assert not at.exception
    opcoes = at.radio(key="pagina").options
    assert "Cotações" in opcoes and "Pesquisa de Preços" not in opcoes
    assert any(m.label == "Em elaboração" for m in at.metric)

    _botao(at, "Nova cotação").click().run()
    at.text_input[0].input("Expediente 2026")
    _botao(at, "Criar cotação").click().run()
    assert not at.exception
    assert len(cliente.tabelas["pesquisas_preco"]) == 1
    assert any(b.label == "Cotação automática" for b in at.button)
    textos = " ".join(str(m.value) for m in at.markdown)
    assert "Expediente 2026" in textos


def test_mesmo_item_manual_e_automatico_e_cesta_ao_lado(monkeypatch):
    from src.ui import cotacoes_ui

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "Papel"})
    item = cotacoes.salvar_item(CTX, str(cotacao["id"]), ITEM)
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(cotacao["id"])
    at.run()
    assert not at.exception

    _botao(at, "Pesquisar preços").click().run()
    assert not at.exception
    assert {r["status"] for r in repo.listar_referencias(str(item["id"]))} == \
        {"candidate"}
    metricas = {m.label: m.value for m in at.metric}
    assert metricas["Encontradas"] == "5" and metricas["Consideradas"] == "0"

    _botao(at, "Cotação automática deste item").click().run()
    assert not at.exception
    assert len(cliente.tabelas["pesquisas_preco"]) == 1
    assert len(cliente.tabelas["pesquisa_preco_itens"]) == 1
    linha = repo.obter_item(str(item["id"]))
    assert linha["estado"] == "review"
    preco = " ".join(str(m.value) for m in at.markdown)
    assert "R$ 24,00" in preco
    assert any("5/3 considerados" in str(m.value) for m in at.markdown)


def test_lote_automatico_percorre_os_itens_e_termina(monkeypatch):
    from src.ui import cotacoes_ui

    at, _ = _app(monkeypatch, unificada=True, pagina="Cotações")
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "Lote"})
    for n in range(3):
        cotacoes.salvar_item(CTX, str(cotacao["id"]),
                             {**ITEM, "descricao": f"PAPEL SULFITE A4 75G {n}"})
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(cotacao["id"])
    at.run()
    _botao(at, "Cotação automática").click().run()
    _botao(at, "Iniciar").click().run()
    for _ in range(6):
        if cotacoes_ui.LOTE not in at.session_state:
            break
        at.run()
    assert not at.exception
    estados = {i["estado"] for i in repo.listar_itens(str(cotacao["id"]))}
    assert "pending" not in estados


def test_conflito_de_outra_aba_vira_aviso_sem_sobrescrever(monkeypatch):
    from src.ui import cotacoes_ui

    at, _ = _app(monkeypatch, unificada=True, pagina="Cotações")
    cotacao = cotacoes.criar_cotacao(CTX, {"nome": "Conflito"})
    item = cotacoes.salvar_item(CTX, str(cotacao["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(cotacao["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(cotacao["id"])
    at.run()
    # "outra aba" muda o item depois que esta tela o leu
    repo.atualizar_item(str(item["id"]), {"quantidade": "12"},
                        revisao_esperada=int(repo.obter_item(str(item["id"]))
                                             ["revisao"]))
    antes = {r["id"]: r["status"] for r in
             repo.listar_referencias(str(item["id"]))}
    # primeiro formulário de referência da tela (a considerada vem antes)
    motivo = next(t for t in at.text_input
                  if (t.placeholder or "").startswith("mesmo produto"))
    motivo.input("fora da curva")
    _botao(at, "Confirmar").click().run()
    assert any("outra aba" in str(w.value) for w in at.warning)
    depois = {r["id"]: r["status"] for r in
              repo.listar_referencias(str(item["id"]))}
    assert depois == antes

    # atualizar e reaplicar: a tela já mostra a versão nova
    motivo = next(t for t in at.text_input
                  if (t.placeholder or "").startswith("mesmo produto"))
    motivo.input("fora da curva")
    _botao(at, "Confirmar").click().run()
    assert not any("outra aba" in str(w.value) for w in at.warning)
    final = [r["status"] for r in repo.listar_referencias(str(item["id"]))]
    assert final.count("rejected") == 1
