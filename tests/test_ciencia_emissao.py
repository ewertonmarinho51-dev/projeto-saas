"""
Relatório nunca travado por preço atípico — ciência na emissão (pacote
Jev de 17/10/2026, objetivo C; plano de testes E01–E14).

Serviço (`precos.ciencia`) no banco falso e a tela de Cotações pelo
AppTest: aviso, "Voltar e revisar", "Estou ciente, emitir relatório",
ciência vinculada à versão da cesta e ao usuário, conferida no servidor
antes de gerar qualquer arquivo. Nenhuma rede, nenhuma IA.
"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal

import pytest

from src import db, governanca
from src.precos import ciencia, cotacoes, relatorio, relatorio_view, saneamento
from src.precos import documento_cotacao as dc
from src.precos import repositorio as repo
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX, ITEM, _fonte

D = Decimal
COM_ATIPICO = ("20.00", "22.00", "24.00", "26.00", "28.00", "200.00")


def _cotacao(monkeypatch, valores=COM_ATIPICO, *, concluir=True):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Emissão com alerta"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    # sem a triagem pré-cesta: o atípico entra, como numa cesta antiga
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte(valores)])
    if concluir:
        cotacoes.concluir_item(CTX, str(c["id"]), str(item["id"]),
                               justificativa="conferido nas fontes oficiais")
    return cliente, repo.obter_pesquisa(str(c["id"])), str(item["id"])


def _tudo(pid):
    itens = cotacoes.ativos(repo.listar_itens(pid))
    return itens, {str(i["id"]): repo.listar_referencias(str(i["id"]))
                   for i in itens}


def _registrar(pesquisa, preparo, ator="u1"):
    return ciencia.registrar(pesquisa, preparo, ator=ator, repositorio=repo,
                             recarregar=lambda: _tudo(str(pesquisa["id"])))


def test_e01_sem_alertas_emite_direto(monkeypatch):
    _, pesquisa, _ = _cotacao(monkeypatch, ("20.00", "22.00", "24.00",
                                            "26.00", "28.00"))
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    assert preparo.alertas == [] and not preparo.requer_ciencia
    assert ciencia.exigir(pesquisa, itens, refs, ator="u1",
                          repositorio=repo) is None


def test_e02_alerta_traz_item_cotacao_valor_e_mediana(monkeypatch):
    _, pesquisa, iid = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    assert preparo.requer_ciencia
    [alerta] = preparo.alertas
    assert alerta.item_id == iid and alerta.numero == 1
    assert D(alerta.valor) == D("200") and D(alerta.mediana) == D("25")
    assert saneamento.VARIACAO_RELEVANTE in alerta.codigos
    texto = alerta.mensagem.lower()
    assert "inexequ" not in texto and "sobrepreço" not in texto
    with pytest.raises(ciencia.CienciaNecessaria) as pedido:
        ciencia.exigir(pesquisa, itens, refs, ator="u1", repositorio=repo)
    assert pedido.value.preparo.assinatura == preparo.assinatura


def test_e04_e05_ciencia_libera_e_mantem_o_preco_atipico(monkeypatch):
    cliente, pesquisa, iid = _cotacao(monkeypatch)
    preco = repo.obter_item(iid)["preco_estimado"]
    itens, refs = _tudo(str(pesquisa["id"]))
    evento = _registrar(pesquisa, ciencia.preparar(pesquisa, itens, refs))
    assert evento["tipo"] == ciencia.TIPO_EVENTO
    assert evento["payload"]["ato"] == ciencia.ATO
    assert evento["ator"] == "u1"
    liberado = ciencia.exigir(pesquisa, itens, refs, ator="u1",
                              repositorio=repo)
    assert liberado["payload"]["assinatura"] == evento["payload"]["assinatura"]
    # nada mudou na cesta: o atípico continua considerado e o preço igual
    assert repo.obter_item(iid)["preco_estimado"] == preco
    assert any(D(str(l["valor_unitario_normalizado"])) == D("200")
               and l["status"] in ("selected", "warning")
               for l in repo.listar_referencias(iid))


def test_e06_mudar_a_cesta_invalida_a_ciencia(monkeypatch):
    _, pesquisa, iid = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    _registrar(pesquisa, ciencia.preparar(pesquisa, itens, refs))
    cotacoes.reabrir_item(CTX, str(pesquisa["id"]), iid, "rever a cesta")
    [r20] = [l for l in repo.listar_referencias(iid)
             if D(str(l["valor_unitario_normalizado"])) == D("20")]
    cotacoes.alterar_status_referencia(CTX, str(pesquisa["id"]), iid,
                                       str(r20["id"]), incluir=False)
    itens, refs = _tudo(str(pesquisa["id"]))
    with pytest.raises(ciencia.CienciaNecessaria):
        ciencia.exigir(pesquisa, itens, refs, ator="u1", repositorio=repo)


def test_e06_confirmar_aviso_desatualizado_nao_grava(monkeypatch):
    cliente, pesquisa, iid = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    # outra aba muda a cesta entre o aviso e o clique
    cotacoes.reabrir_item(CTX, str(pesquisa["id"]), iid, "outra aba")
    with pytest.raises(ciencia.CienciaDesatualizada) as novo:
        _registrar(pesquisa, preparo)
    assert novo.value.preparo.assinatura != preparo.assinatura
    assert not [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == ciencia.TIPO_EVENTO]


def test_e07_ciencia_de_outro_usuario_ou_pesquisa_nao_vale(monkeypatch):
    _, pesquisa, _ = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    _registrar(pesquisa, preparo, ator="outro-usuario")
    with pytest.raises(ciencia.CienciaNecessaria):
        ciencia.exigir(pesquisa, itens, refs, ator="u1", repositorio=repo)
    # a assinatura amarra a pesquisa: a mesma cesta em outra pesquisa difere
    outra = {**pesquisa, "id": "outra-pesquisa"}
    assert ciencia.preparar(outra, itens, refs).assinatura != preparo.assinatura
    # e `acknowledged=true` solto não existe: só o evento desta assinatura
    assert ciencia.localizar(str(pesquisa["id"]), "qualquer", "u1",
                             repo) is None


def test_e08_duplo_clique_grava_uma_ciencia(monkeypatch):
    cliente, pesquisa, _ = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    a = _registrar(pesquisa, preparo)
    b = _registrar(pesquisa, preparo)
    assert a["id"] == b["id"]
    assert len([e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == ciencia.TIPO_EVENTO]) == 1


def test_falha_tecnica_ao_gravar_e_erro_legitimo_nao_bloqueio(monkeypatch):
    _, pesquisa, _ = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    monkeypatch.setattr(repo, "registrar_evento", lambda *a, **k: None)
    with pytest.raises(ciencia.ErroDeCiencia):
        _registrar(pesquisa, ciencia.preparar(pesquisa, itens, refs))


def test_e09_documento_imprime_a_ciencia_com_linguagem_neutra(monkeypatch):
    _, pesquisa, _ = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    evento = _registrar(pesquisa, ciencia.preparar(pesquisa, itens, refs))
    doc = ciencia.para_documento(evento, "Servidor Teste")
    completo = relatorio.completo(pesquisa, itens, refs, ciencia=doc)
    resumido = relatorio.resumido(pesquisa, itens, refs, ciencia=doc)
    for texto in (completo, resumido):
        assert "Ciência dos alertas na emissão" in texto
        assert "Servidor Teste" in texto and "itens 01" in texto
        assert "não constitui aprovação administrativa" in texto
    neutro = " ".join(relatorio.texto_da_ciencia(doc)).lower()
    assert "inexequ" not in neutro and "sobrepreço" not in neutro
    # a ciência não muda o resultado: identificador igual com ou sem ela
    vista = relatorio_view.projetar(pesquisa, itens, refs, ciencia=doc)
    assert vista.hash_decisorio == relatorio.identificador_da_versao(
        pesquisa, itens, refs)
    docx = dc.relatorio_de_cotacao_docx(vista)
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        corpo = zf.read("word/document.xml").decode("utf-8")
    assert "Ciência na emissão" in corpo and "Servidor Teste" in corpo


def test_e10_desconsiderada_antes_da_cesta_nao_entra_no_calculo(monkeypatch):
    ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "E10"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    from tests import saneamento_apoio as apoio
    fixture = next(i for i in apoio.itens() if i["item_id"] == "ITEM_09")
    item = cotacoes.salvar_item(CTX, str(c["id"]), {
        "descricao": fixture["description"], "unidade": "UN",
        "quantidade": "10"})
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico",
                            fontes=[apoio.FonteDaFixture(fixture)],
                            triagem=saneamento.POLITICA_PADRAO)
    assert D(str(repo.obter_item(str(item["id"]))["preco_estimado"])) == D("180")


def test_e11_retirada_manual_nao_volta_numa_nova_busca(monkeypatch):
    _, pesquisa, iid = _cotacao(monkeypatch, concluir=False)
    [r1, *_] = repo.listar_referencias(iid)
    cotacoes.alterar_status_referencia(CTX, str(pesquisa["id"]), iid,
                                       str(r1["id"]), incluir=False)
    cotacoes.pesquisar_item(CTX, str(pesquisa["id"]), iid, modo="automatico",
                            fontes=[_fonte(COM_ATIPICO)])
    linha = next(l for l in repo.listar_referencias(iid) if l["id"] == r1["id"])
    assert linha["status"] == "rejected"


def test_e12_emissao_registrada_nao_muda_quando_a_cesta_muda(monkeypatch):
    cliente, pesquisa, iid = _cotacao(monkeypatch)
    itens, refs = _tudo(str(pesquisa["id"]))
    dados = relatorio.dados_da_emissao(pesquisa, itens, refs, tipo="completo",
                                       formato="pdf", conteudo=b"%PDF-1",
                                       nome_arquivo="r.pdf")
    repo.registrar_emissao(str(pesquisa["id"]), dados)
    cotacoes.reabrir_item(CTX, str(pesquisa["id"]), iid, "rever depois")
    [registro] = cliente.tabelas["pesquisa_preco_emissoes"]
    assert registro["hash_decisorio"] == dados["hash_decisorio"]
    itens, refs = _tudo(str(pesquisa["id"]))
    assert relatorio.identificador_da_versao(pesquisa, itens, refs) != \
        registro["hash_decisorio"]


def test_e14_cesta_com_menos_de_tres_emite_com_ressalvas_apos_ciencia(
        monkeypatch):
    _, pesquisa, _ = _cotacao(monkeypatch, ("20.00", "22.00"), concluir=False)
    itens, refs = _tudo(str(pesquisa["id"]))
    preparo = ciencia.preparar(pesquisa, itens, refs)
    assert preparo.pendencias and preparo.requer_ciencia
    evento = _registrar(pesquisa, preparo)
    doc = ciencia.para_documento(evento, "Servidor Teste")
    texto = relatorio.completo(pesquisa, itens, refs, ciencia=doc)
    assert "2/3 preços considerados" in texto
    assert "pendência" in texto


# ---------------------------------------------------------------------------
# A verificação do SERVIDOR mora no gerador: sem bypass pela tela
# ---------------------------------------------------------------------------
def _flags(monkeypatch, *extras):
    ligadas = {repo.FLAG, governanca.FLAG_COTACOES_UNIFICADAS, *extras}
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in ligadas)


def test_gerador_recusa_sem_ciencia_e_gera_com_ela(monkeypatch):
    from src import export
    from src.ui import precos_ui

    _, pesquisa, _ = _cotacao(monkeypatch)
    _flags(monkeypatch, governanca.FLAG_CIENCIA_EMISSAO)
    monkeypatch.setattr(precos_ui, "_identidade", lambda: ("u1", None))
    monkeypatch.setattr(export, "gerar_pdf",
                        lambda titulo, md, branding=None: md.encode("utf-8"))
    itens, refs = _tudo(str(pesquisa["id"]))
    with pytest.raises(ciencia.CienciaNecessaria):
        precos_ui._conteudo_do_relatorio(pesquisa, itens, refs,
                                         formato="pdf", tipo="resumido")
    with pytest.raises(ciencia.CienciaNecessaria):
        precos_ui.montar_pacote(pesquisa, itens, refs)
    _registrar(pesquisa, ciencia.preparar(pesquisa, itens, refs))
    conteudo, nome, _ = precos_ui._conteudo_do_relatorio(
        pesquisa, itens, refs, formato="pdf", tipo="resumido")
    assert "Ciência dos alertas na emissão".encode() in conteudo
    # o atípico continua no cálculo: média de 20..28 e 200 = 53,33
    assert "53,33".encode() in conteudo, "a cesta confirmada é a do documento"


def test_flag_desligada_mantem_o_gerador_de_antes(monkeypatch):
    from src import export
    from src.ui import precos_ui

    _, pesquisa, _ = _cotacao(monkeypatch)
    _flags(monkeypatch)
    monkeypatch.setattr(export, "gerar_pdf",
                        lambda titulo, md, branding=None: md.encode("utf-8"))
    itens, refs = _tudo(str(pesquisa["id"]))
    conteudo, _, _ = precos_ui._conteudo_do_relatorio(
        pesquisa, itens, refs, formato="pdf", tipo="resumido")
    assert "Ciência".encode() not in conteudo


# ---------------------------------------------------------------------------
# Tela (AppTest): aviso, voltar, confirmar, gerar
# ---------------------------------------------------------------------------
def _tela(monkeypatch):
    from src import export
    from src.ui import cotacoes_ui
    from tests.test_cotacoes_g2_ui import _app

    at, cliente = _app(monkeypatch, unificada=True, pagina="Cotações")
    _flags(monkeypatch, governanca.FLAG_CIENCIA_EMISSAO)
    monkeypatch.setattr(export, "gerar_pdf",
                        lambda titulo, md, branding=None: md.encode("utf-8"))
    c = cotacoes.criar_cotacao(CTX, {"nome": "Tela com alerta"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                            modo="automatico", fontes=[_fonte(COM_ATIPICO)])
    cotacoes.concluir_item(CTX, str(c["id"]), str(item["id"]),
                           justificativa="conferido nas fontes oficiais")
    at.session_state[cotacoes_ui.TELA] = cotacoes_ui.ELABORAR
    at.session_state[cotacoes_ui.COTACAO] = str(c["id"])
    at.session_state["cot_painel_relatorio"] = True
    return at, cliente


def _botao(at, rotulo):
    return next(b for b in at.button if b.label == rotulo)


def _emissoes(cliente):
    return cliente.tabelas["pesquisa_preco_emissoes"]


def test_tela_aviso_nao_trava_e_voltar_nao_gera(monkeypatch):
    at, cliente = _tela(monkeypatch)
    at.run()
    assert not at.exception
    avisos = " ".join(str(w.value) for w in at.warning)
    assert "variação relevante" in avisos and "não impede a emissão" in avisos
    # nenhuma caixa de "Estou ciente" travando os botões: eles existem
    assert not any("Estou ciente" in c.label for c in at.checkbox)
    _botao(at, "Quadro resumido (PDF)").click().run()
    assert not at.exception
    assert any(b.label == "Estou ciente, emitir relatório" for b in at.button)
    assert _emissoes(cliente) == [], "E03: o aviso não gera arquivo"
    _botao(at, "Voltar e revisar").click().run()
    assert not at.exception
    assert _emissoes(cliente) == []
    assert not [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == ciencia.TIPO_EVENTO]


def test_tela_estou_ciente_registra_e_gera(monkeypatch):
    at, cliente = _tela(monkeypatch)
    at.run()
    _botao(at, "Quadro resumido (PDF)").click().run()
    _botao(at, "Estou ciente, emitir relatório").click().run()
    assert not at.exception
    [ciente] = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == ciencia.TIPO_EVENTO]
    assert ciente["ator"] == "u1"
    [emissao] = _emissoes(cliente)
    [emitido] = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
                 if e["tipo"] == "relatorio_emitido"]
    assert emitido["payload"]["ciencia"]["assinatura"] == \
        ciente["payload"]["assinatura"]
    assert emissao["hash_decisorio"] == ciente["payload"]["revisao"]
    # segunda emissão da MESMA versão: sem novo aviso, sem nova ciência
    _botao(at, "Quadro resumido (PDF)").click().run()
    assert not any(b.label == "Estou ciente, emitir relatório"
                   for b in at.button)
    assert len([e for e in cliente.tabelas["pesquisa_preco_eventos"]
                if e["tipo"] == ciencia.TIPO_EVENTO]) == 1
