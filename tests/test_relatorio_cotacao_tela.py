"""
G4 — a tela de relatórios com a flag `precos_relatorio_visual`.

* DESLIGADA (padrão): os mesmos botões de antes — rollback é desligar;
* LIGADA: Relatório de Cotação (PDF/DOCX), memória analítica (XLSX) e
  Relatório Analítico Integral sob demanda, nos MESMOS lugares; a emissão
  é registrada com o tipo que a tabela da 0029 aceita;
* o pacote do padrão novo não gera o PDF integral sem pedido.
"""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from src import db, governanca
from src.precos import cotacoes
from src.precos import repositorio as repo
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte
from tests.test_cotacoes_g2_ui import _app, _botao


def _tela(monkeypatch, *, visual: bool):
    from src.ui import cotacoes_ui

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    ligadas = {repo.FLAG, governanca.FLAG_COTACOES_UNIFICADAS}
    if visual:
        ligadas.add(governanca.FLAG_RELATORIO_VISUAL)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Relatório visual"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte()])
    cotacoes.concluir_item(CTX, str(c["id"]), str(item["id"]),
                           justificativa="conferido na fonte oficial")
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state["cot_painel_relatorio"] = True
    return at, cliente, c


def test_flag_desligada_mantem_os_botoes_anteriores(monkeypatch):
    at, _, _ = _tela(monkeypatch, visual=False)
    at.run()
    assert not at.exception
    rotulos = {b.label for b in at.button}
    assert {"Relatório completo (PDF)", "Quadro resumido (PDF)"} <= rotulos
    assert "Relatório de Cotação (PDF)" not in rotulos


def test_flag_ligada_troca_os_botoes_no_mesmo_lugar(monkeypatch):
    at, _, _ = _tela(monkeypatch, visual=True)
    at.run()
    assert not at.exception
    rotulos = {b.label for b in at.button}
    assert {"Relatório de Cotação (PDF)", "Relatório de Cotação (DOCX)",
            "Memória analítica (XLSX)",
            "Relatório Analítico Integral (PDF)",
            "Pacote completo (ZIP)"} <= rotulos
    assert "Relatório completo (PDF)" not in rotulos
    assert any("Relatório Analítico Integral" in str(c.value)
               for c in at.caption)


def test_docx_gerado_na_tela_registra_emissao_como_completo(monkeypatch):
    at, cliente, _ = _tela(monkeypatch, visual=True)
    at.run()
    _botao(at, "Relatório de Cotação (DOCX)").click().run()
    assert not at.exception
    [registro] = cliente.tabelas["pesquisa_preco_emissoes"]
    assert registro["tipo"] == "completo" and registro["formato"] == "docx"
    assert registro["nome_arquivo"].endswith("relatorio-cotacao.docx")
    baixar = [b for b in at.get("download_button")]
    assert baixar, "o download aparece depois da geração"
    assert any("Arquivo SHA-256" in str(c.value) for c in at.caption)


def test_falha_de_conversao_vira_mensagem_e_nao_registra(monkeypatch):
    from src.precos import documento_cotacao as dc

    at, cliente, _ = _tela(monkeypatch, visual=True)

    def sem_conversor(*_a, **_k):
        raise dc.ErroDeRenderizacao("conversão indisponível (teste)")

    monkeypatch.setattr(dc, "em_pdf", sem_conversor)
    at.run()
    _botao(at, "Relatório de Cotação (PDF)").click().run()
    assert not at.exception
    assert any("conversão indisponível" in str(e.value) for e in at.error)
    assert not cliente.tabelas.get("pesquisa_preco_emissoes")


def test_volume_acima_do_limite_nao_oferece_o_integral(monkeypatch):
    from src.ui import precos_ui

    at, _, _ = _tela(monkeypatch, visual=True)
    monkeypatch.setattr(precos_ui, "LIMITE_DO_ANALITICO", 1)
    at.run()
    assert not at.exception
    assert not any(b.label == "Relatório Analítico Integral (PDF)"
                   for b in at.button)
    assert any("não é gerado" in str(w.value) for w in at.warning)


def test_pacote_visual_sem_integral_por_padrao(monkeypatch, motor_institucional):
    from src.ui import precos_ui

    _, cliente, c = _tela(monkeypatch, visual=True)
    pesquisa = repo.obter_pesquisa(str(c["id"]))
    itens = cotacoes.ativos(repo.listar_itens(str(c["id"])))
    refs = {str(i["id"]): repo.listar_referencias(str(i["id"])) for i in itens}
    pacote = precos_ui.montar_pacote(pesquisa, itens, refs, visual=True)
    with zipfile.ZipFile(io.BytesIO(pacote)) as z:
        nomes = z.namelist()
    assert any(n.endswith("relatorio-cotacao.pdf") for n in nomes)
    assert any(n.endswith(".xlsx") for n in nomes)
    assert not any("analitico-integral" in n for n in nomes)
    assert hashlib.sha256(pacote).hexdigest()


@pytest.mark.parametrize("orgaos, esperado", [
    ([], None),
    ([{"orgao": "PREFEITURA PADRÃO"}, {"orgao": "OUTRA"}],
     "PREFEITURA PADRÃO"),
])
def test_timbrado_vem_do_resolvedor_das_exportacoes(monkeypatch, orgaos,
                                                    esperado):
    from src import contexto
    from src.ui import precos_ui

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(contexto, "identidade_para_exportacao", lambda: None)
    monkeypatch.setattr(db, "listar_orgaos", lambda: orgaos)
    marca = precos_ui._branding_da_emissao()
    assert (marca or {}).get("orgao") == esperado


def test_timbrado_do_vinculo_tem_precedencia(monkeypatch):
    from src import contexto
    from src.ui import precos_ui

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(contexto, "identidade_para_exportacao",
                        lambda: ({"orgao": "SECRETARIA X"}, "secretaria"))
    monkeypatch.setattr(db, "listar_orgaos",
                        lambda: pytest.fail("não deveria listar órgãos"))
    assert precos_ui._branding_da_emissao() == {"orgao": "SECRETARIA X"}
