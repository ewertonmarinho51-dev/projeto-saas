"""
Remoção sem justificativa obrigatória (pacote Jev de 17/10/2026,
objetivo B; plano de testes R01–R09).

Retirar uma cotação da cesta ou um item da cotação não pede texto: a
trilha é automática (ator, hora, operação, de/para, revisão,
`user_reason` nulo). Incluir continua pedindo motivo — e a exceção à
regra dos três continua com todas as suas exigências.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.precos import cesta, cotacoes
from src.precos import repositorio as repo
from src.precos.perfil import obter as obter_perfil
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte

D = Decimal
RAIZ = Path(__file__).resolve().parents[1]


def _pesquisada(monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Remoção"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    return cliente, str(c["id"]), str(item["id"])


def _eventos(cliente, tipo):
    return [e for e in cliente.tabelas["pesquisa_preco_eventos"]
            if e["tipo"] == tipo]


@pytest.mark.parametrize("motivo", ["ausente", None, ""],
                         ids=["R01_ausente", "R02_nulo", "R03_vazio"])
def test_r01_r03_retirar_cotacao_sem_motivo(monkeypatch, motivo):
    cliente, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    antes = D(str(repo.obter_item(iid)["preco_estimado"]))
    opcoes = {} if motivo == "ausente" else {"motivo": motivo}
    estimativa = cotacoes.alterar_status_referencia(
        CTX, cid, iid, str(r1["id"]), incluir=False, **opcoes)
    linha = next(r for r in repo.listar_referencias(iid) if r["id"] == r1["id"])
    assert linha["status"] == "rejected"
    # R09: preço refeito sem a retirada (20 sai de 20..28 → média 25)
    assert estimativa.valor_unitario == D("25.00") != antes
    assert D(str(repo.obter_item(iid)["preco_estimado"])) == D("25.00")
    [evento] = _eventos(cliente, "referencia_excluida")
    p = evento["payload"]
    assert p["operacao"] == "manual_removed" and p["origem"] == "user"
    assert p["user_reason"] is None
    assert p["de"] == "selected" and p["para"] == "rejected"
    assert p["revisao_anterior"] is not None
    assert evento["ator"] == "u1"
    assert evento["descricao"] == cotacoes.MOTIVO_RETIRADA_AUTOMATICO


def test_motivo_voluntario_e_preservado(monkeypatch):
    cliente, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False, motivo="fora da curva")
    [evento] = _eventos(cliente, "referencia_excluida")
    assert evento["payload"]["user_reason"] == "fora da curva"
    linha = next(r for r in repo.listar_referencias(iid) if r["id"] == r1["id"])
    assert "fora da curva" in linha["motivos"]


def test_duplo_clique_na_retirada_nao_duplica_trilha(monkeypatch):
    cliente, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    for _ in range(2):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                           incluir=False)
    assert len(_eventos(cliente, "referencia_excluida")) == 1


def test_incluir_continua_exigindo_motivo(monkeypatch):
    _, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False)
    with pytest.raises(cotacoes.ErroCotacao, match="motivo da inclusão"):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                           incluir=True, motivo="  ")


@pytest.mark.parametrize("motivo", [None, ""], ids=["nulo", "vazio"])
def test_r04_retirar_item_inteiro_sem_motivo(monkeypatch, motivo):
    cliente, cid, iid = _pesquisada(monkeypatch)
    cotacoes.remover_item(CTX, cid, iid, motivo)
    assert repo.obter_item(iid)["removido_em"]
    [evento] = _eventos(cliente, "item_removido")
    p = evento["payload"]
    assert p["operacao"] == "basket_item_removed" and p["user_reason"] is None
    assert p["estado_anterior"] and evento["ator"] == "u1"
    # repetir não duplica
    cotacoes.remover_item(CTX, cid, iid)
    assert len(_eventos(cliente, "item_removido")) == 1


def test_r04_item_de_outra_cotacao_e_recusado(monkeypatch):
    _, cid, iid = _pesquisada(monkeypatch)
    outra = cotacoes.criar_cotacao(CTX, {"nome": "Outra"})
    with pytest.raises(cotacoes.ErroCotacao, match="não encontrado"):
        cotacoes.remover_item(CTX, str(outra["id"]), iid)


def test_r05_cotacao_nao_editavel_continua_recusando(monkeypatch):
    _, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    monkeypatch.setattr(cotacoes, "_exigir_editavel",
                        lambda c: (_ for _ in ()).throw(
                            cotacoes.CotacaoImutavel("cotação concluída")))
    with pytest.raises(cotacoes.CotacaoImutavel):
        cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                           incluir=False)
    with pytest.raises(cotacoes.CotacaoImutavel):
        cotacoes.remover_item(CTX, cid, iid)


def test_r06_retirada_nao_apaga_fonte_preco_nem_evidencia(monkeypatch):
    cliente, cid, iid = _pesquisada(monkeypatch)
    antes = {r["id"]: dict(r) for r in repo.listar_referencias(iid)}
    [r1, *_] = antes.values()
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False)
    depois = {r["id"]: r for r in repo.listar_referencias(iid)}
    assert set(depois) == set(antes), "nenhuma linha apagada"
    for chave in ("fonte_id", "id_externo", "raw_hash", "bruto",
                  "valor_unitario_original", "descricao_original"):
        assert depois[r1["id"]][chave] == r1[chave]


def test_r08_motivos_antigos_continuam_legiveis(monkeypatch):
    _, cid, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False, motivo="motivo antigo")
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=True, motivo="volta")
    cotacoes.alterar_status_referencia(CTX, cid, iid, str(r1["id"]),
                                       incluir=False)
    linha = next(r for r in repo.listar_referencias(iid) if r["id"] == r1["id"])
    assert "motivo antigo" in linha["motivos"] and "volta" in linha["motivos"]


def test_repositorio_aceita_retirada_sem_texto_e_recusa_inclusao_sem_texto(
        monkeypatch):
    _, _, iid = _pesquisada(monkeypatch)
    [r1, *_] = repo.listar_referencias(iid)
    repo.reclassificar_referencia(str(r1["id"]), "rejected", None)
    with pytest.raises(ValueError, match="incluir"):
        repo.reclassificar_referencia(str(r1["id"]), "selected", "")


def test_excluir_discrepantes_sem_motivo_registra_o_criterio(monkeypatch):
    cliente, cid, iid = _pesquisada(monkeypatch)
    pesquisa = repo.obter_pesquisa(cid)
    item = repo.obter_item(iid)
    alvo = repo.listar_referencias(iid)[0]
    monkeypatch.setattr(cesta, "discrepantes",
                        lambda linhas, **k: [(alvo, "IQR+MAD")])
    cesta.excluir_discrepantes(pesquisa, item, repo,
                               perfil=obter_perfil(None), ator="u1")
    linha = next(r for r in repo.listar_referencias(iid) if r["id"] == alvo["id"])
    assert linha["status"] == "rejected"
    assert any("critério IQR+MAD" in m for m in linha["motivos"])
    [evento] = _eventos(cliente, "referencia_excluida")
    assert evento["payload"]["user_reason"] is None


def test_excecao_a_regra_dos_tres_continua_exigindo_justificativa(monkeypatch):
    """O que NÃO muda: ato administrativo diverso da retirada operacional."""
    _, cid, iid = _pesquisada(monkeypatch)
    pesquisa = repo.obter_pesquisa(cid)
    item = repo.obter_item(iid)
    with pytest.raises(cesta.ExcecaoInvalida):
        cesta.registrar_excecao(pesquisa, item, repo,
                                perfil=obter_perfil("lei_14133"), texto="",
                                fundamento="mercado_restrito", aprovador="",
                                aprovacao_declarada=False, ator="u1")


def test_r07_telas_nao_pedem_motivo_obrigatorio_para_retirar():
    """Nenhum campo "obrigatório" de motivo de RETIRADA nas duas telas."""
    cotacoes_ui = (RAIZ / "src" / "ui" / "cotacoes_ui.py").read_text(
        encoding="utf-8")
    precos_ui = (RAIZ / "src" / "ui" / "precos_ui.py").read_text(
        encoding="utf-8")
    assert "Motivo para retirar da cotação" not in cotacoes_ui
    assert '"Motivo (obrigatório)"' not in cotacoes_ui
    assert '"Motivo (obrigatório)"' not in precos_ui
    assert "Motivo da exclusão (obrigatório)" not in precos_ui


def test_r07_tela_retira_referencia_sem_texto(monkeypatch):
    """E2E na tela de Cotações: abre o item, retira sem escrever nada."""
    from src.ui import cotacoes_ui
    from tests.test_cotacoes_g2_ui import _app

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    c = cotacoes.criar_cotacao(CTX, {"nome": "Tela"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state[cotacoes_ui.ITEM] = str(item["id"])
    at.run()
    assert not at.exception
    # Revisão 02 (03_CESTA): um botão, sem formulário nem campo de texto
    retirar = [b for b in at.button if b.label == "Remover da cesta"]
    assert retirar, "o botão de remover existe"
    retirar[0].click().run()
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    [evento] = _eventos(cliente, "referencia_excluida")
    assert evento["payload"]["user_reason"] is None
