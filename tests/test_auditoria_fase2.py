"""
Segunda auditoria das fontes de preços (18/10/2026) — correções N-01/N-04
e N-05 (docs/auditoria-fontes-precos/segunda-auditoria/).

* N-01/N-04 — a barreira por atributo da v1.9.8 só agia na cotação
  automática; as cestas GRAVADAS antes dela seguiam emitíveis com preço
  de outro produto (298 de 983), e o bloqueio de emissão só media o
  tamanho da cesta: "aquisição" passava no teto com 10 contradições;
* N-05 — os 5 PDFs emitidos antes das correções não tinham marca.

Os textos são os registros reais que a auditoria conferiu na fonte.
"""

from __future__ import annotations

import pytest

from src.precos import atributos, cesta, estatistica, relatorio

PAPEL_A4 = ("PAPEL A4 BRANCO. ESPECIFICAÇÃO: Papel sulfite branco, formato A4 "
            "(210 x 297 mm), gramatura 75 g/m², próprio para impressão a laser "
            "e jato de tinta, pacote contendo 500 folhas.")
A4_BRANCO = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE/APERGAMINHADO/"
             "OFÍCIO , TAMANHO (C X L): 297 X 210 MM, GRAMATURA: 75 G/M2, COR: "
             "BRANCO")
A3_12728225 = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO SULFITE/APERGAMINHADO/OFÍCIO, "
               "TAMANHO (CX L) 420 X 297 MM, GRAMATURA 75 G/M2, COR BRANCO")
COLORIDO_13021849 = ("Papel Para Impressão Formatado tipo: sulfite/apergaminhado/"
                     "ofício, tamanho (c x l): 297 x 210, gramatura: 75, cor: "
                     "colorido ")


def _linha(i, descricao, *, status="selected", fonte="compras_gov_precos"):
    return {"id": f"L{i}", "id_externo": f"X{i}", "status": status,
            "fonte_id": fonte, "descricao_original": descricao,
            "valor_unitario_original": "25", "valor_unitario_normalizado": "25",
            "natureza_valor": "praticado"}


def _cesta_do_papel(*extras):
    linhas = [_linha(i, A4_BRANCO) for i in range(3)]
    return [{"id": "a", "numero": 1, "descricao": PAPEL_A4}], {"a": linhas + list(extras)}


# ---------------------------------------------------------------------------
# N-01 — a cesta gravada é conferida pela barreira na emissão
# ---------------------------------------------------------------------------
def test_cesta_gravada_com_outro_produto_e_apontada_n01():
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225),
                                  _linha(4, COLORIDO_13021849))
    achados = cesta.contradicoes_na_cesta(itens, refs)
    assert len(achados) == 1
    assert achados[0].startswith("item 1: 2 preços de outro produto na cesta (")
    # o motivo diz o atributo e os dois valores — o servidor sabe o que olhar
    for ref in (A3_12728225, COLORIDO_13021849):
        assert atributos.conflito(PAPEL_A4, ref).motivo in achados[0]


def test_um_preco_no_singular():
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225))
    assert cesta.contradicoes_na_cesta(itens, refs)[0].startswith(
        "item 1: 1 preço de outro produto na cesta (")


def test_cesta_do_mesmo_produto_nao_e_apontada():
    itens, refs = _cesta_do_papel()

    def nao_chame(_item_id):
        raise AssertionError("a trilha só é consultada quando há contradição")

    assert cesta.contradicoes_na_cesta(itens, refs,
                                       decididas_por_humano=nao_chame) == []


def test_preco_decidido_por_pessoa_nao_trava():
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225),
                                  _linha(4, COLORIDO_13021849))
    assert cesta.contradicoes_na_cesta(
        itens, refs, decididas_por_humano=lambda _id: {"L3", "X4"}) == []
    # só uma das duas decidida: a outra continua travando
    so_uma = cesta.contradicoes_na_cesta(
        itens, refs, decididas_por_humano=lambda _id: {"L3"})
    assert so_uma and so_uma[0].startswith("item 1: 1 preço")


def test_cotacao_direta_e_decisao_do_servidor():
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225, fonte="cotacao_direta"))
    assert cesta.contradicoes_na_cesta(itens, refs) == []


@pytest.mark.parametrize("status", ["candidate", "manual_review", "rejected"])
def test_preco_fora_da_cesta_nao_conta(status):
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225, status=status))
    assert cesta.contradicoes_na_cesta(itens, refs) == []


def test_sinalizada_esta_na_cesta_e_conta():
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225, status="warning"))
    assert cesta.contradicoes_na_cesta(itens, refs)


def test_atributo_ausente_e_conferencia_nao_trava():
    sem_formato = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO SULFITE, GRAMATURA "
                   "75 G/M2, COR BRANCO")
    assert atributos.conflito(PAPEL_A4, sem_formato).tipo == atributos.AUSENTE
    itens, refs = _cesta_do_papel(_linha(3, sem_formato))
    assert cesta.contradicoes_na_cesta(itens, refs) == []


def test_item_sem_descricao_nao_decide_nada():
    _, refs = _cesta_do_papel(_linha(3, A3_12728225))
    assert cesta.contradicoes_na_cesta([{"id": "a", "numero": 1}], refs) == []


# ---------------------------------------------------------------------------
# N-04 — a emissão para mesmo com a cesta dentro do teto
# ---------------------------------------------------------------------------
@pytest.fixture
def emissao(monkeypatch):
    from src.precos import cotacoes, saneamento
    from src.ui import precos_ui

    monkeypatch.setattr(cotacoes, "politica_automatica",
                        lambda: estatistica.POLITICA_AUTOMATICA)
    monkeypatch.setattr(cotacoes, "politica_saneamento",
                        lambda: saneamento.POLITICA_PADRAO)
    monkeypatch.setattr(precos_ui.repo, "referencias_decididas_por_humano",
                        lambda *_a: set())
    return precos_ui


def test_cesta_dentro_do_teto_com_outro_produto_nao_emite_n04(emissao):
    from src.precos.documento_cotacao import ErroDeRenderizacao

    itens, refs = _cesta_do_papel(_linha(3, A3_12728225))
    assert len(cesta.consideradas(refs["a"])) <= estatistica.POLITICA_AUTOMATICA.teto
    with pytest.raises(ErroDeRenderizacao) as erro:
        emissao._conteudo_do_relatorio({"id": "p"}, itens, refs,
                                       formato="pdf", tipo="cotacao")
    texto = str(erro.value)
    assert "preço de produto diferente do pedido" in texto
    assert "item 1: 1 preço de outro produto na cesta" in texto
    assert "Refaça a cotação automática" in texto and "exclua-os da cesta" in texto


def test_teto_continua_sendo_conferido_primeiro(emissao):
    from src.precos.documento_cotacao import ErroDeRenderizacao

    linhas = [_linha(i, A4_BRANCO) for i in range(20)] + [_linha(20, A3_12728225)]
    with pytest.raises(ErroDeRenderizacao) as erro:
        emissao._conferir_cestas(
            {"id": "p"}, [{"id": "a", "numero": 2, "descricao": PAPEL_A4}],
            {"a": linhas})
    assert "item 2: 21 preços na cesta (limite de 15)" in str(erro.value)


def test_cesta_limpa_emite(emissao):
    itens, refs = _cesta_do_papel()
    emissao._conferir_cestas({"id": "p"}, itens, refs)  # não levanta


def test_sem_a_flag_da_barreira_a_emissao_e_a_de_antes(emissao, monkeypatch):
    from src.precos import cotacoes

    monkeypatch.setattr(cotacoes, "politica_saneamento", lambda: None)
    itens, refs = _cesta_do_papel(_linha(3, A3_12728225))
    emissao._conferir_cestas({"id": "p"}, itens, refs)  # não levanta


# ---------------------------------------------------------------------------
# N-05 — emissões anteriores às correções ficam marcadas
# ---------------------------------------------------------------------------
# os 5 registros de produção (pesquisa_preco_emissoes, consulta de 18/10)
EMITIDAS_ANTES = ["2026-10-16T19:03:46.399991+00:00",
                  "2026-10-16T23:31:14.794031+00:00",
                  "2026-10-17T18:58:59.817933+00:00",
                  "2026-10-17T19:05:35.435735+00:00",
                  "2026-10-18T04:19:42.984928+00:00"]


def test_as_cinco_emissoes_de_producao_sao_superadas_n05():
    emissoes = [{"criado_em": c} for c in EMITIDAS_ANTES]
    assert relatorio.emissoes_superadas(emissoes) == emissoes


def test_emissao_depois_do_corte_nao_e_marcada():
    depois = {"criado_em": "2026-10-18T05:53:00+00:00"}
    no_corte = {"criado_em": "2026-10-18T05:52:00+00:00"}
    assert relatorio.emissoes_superadas([depois, no_corte]) == []


def test_emissao_sem_data_nao_e_afirmada():
    assert relatorio.emissoes_superadas(
        [{"criado_em": None}, {"criado_em": "ontem"}, {}]) == []


def test_data_sem_fuso_e_lida_como_utc():
    assert relatorio.emissoes_superadas(
        [{"criado_em": "2026-10-18T05:51:00"}]) == [{"criado_em": "2026-10-18T05:51:00"}]


def test_aviso_diz_o_que_pode_estar_errado_e_o_que_fazer():
    from src.ui import precos_ui

    varios = precos_ui._aviso_de_emissoes_superadas(5)
    assert varios.startswith("Há 5 relatórios emitidos desta pesquisa antes das "
                             "correções de 18/10/2026")
    assert "preço de produto diferente do item" in varios
    assert "sem o número da compra" in varios
    assert "gere o relatório de novo e substitua o documento no processo" in varios
    um = precos_ui._aviso_de_emissoes_superadas(1)
    assert um.startswith("Há 1 relatório emitido desta pesquisa")
    assert "Ele pode" in um and "use esse arquivo" in um
