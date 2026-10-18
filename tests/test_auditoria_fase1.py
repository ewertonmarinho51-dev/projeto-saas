"""
Auditoria de autenticidade das fontes (18/10/2026) — fase 1.

Cada caso usa o texto REAL do registro de produção que a auditoria
conferiu na fonte (docs/auditoria-fontes-precos/), não exemplo inventado:

* C-1 — preço autêntico de OUTRO produto entrava na cesta (papel A3 e
  colorido na cesta do A4 branco, clipe 0 na do 2/0, grampeador cirúrgico
  e alicate na do grampeador de mesa);
* C-2 — `idCompra` chega como número JSON e perde o zero da UASG; o PDF
  dizia "Não disponível na fonte" e não imprimia o número;
* C-4 — pesquisa com cesta de 317 preços (antes do teto) seguia emitível;
* C-7 — o órgão superior impresso não era a UASG que comprou.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.precos import atributos, busca, cesta, estatistica, links
from src.precos import relatorio_view
from src.precos.fontes import ResultadoBusca
from src.precos.modelo import Fonte, NaturezaValor, Referencia, StatusReferencia
from src.precos.perfil import obter as obter_perfil
from src.precos.saneamento import POLITICA_PADRAO

D = Decimal

# Itens reais da pesquisa "aquisição de materiais de expediente" (17/10)
PAPEL_A4 = ("PAPEL A4 BRANCO. ESPECIFICAÇÃO: Papel sulfite branco, formato A4 "
            "(210 x 297 mm), gramatura 75 g/m², próprio para impressão a laser "
            "e jato de tinta, pacote contendo 500 folhas.")
CLIPE_2_0 = ("CLIPES METÁLICOS Nº 2/0. ESPECIFICAÇÃO: Clipes para papel, "
             "tamanho 2/0, em arame de aço galvanizado, resistentes à oxidação, "
             "acabamento uniforme, caixa contendo 100 unidades.")
GRAMPEADOR = ("GRAMPEADOR DE MESA. ESPECIFICAÇÃO: Grampeador de mesa, estrutura "
              "metálica resistente, capacidade mínima de 25 folhas de papel "
              "75 g/m², compatível com grampos 26/6, base antiderrapante.")
PASTA_AZ = ("PASTA ARQUIVO AZ. ESPECIFICAÇÃO: Pasta registradora tipo AZ, "
            "tamanho ofício, papelão rígido revestido, lombada larga de "
            "aproximadamente 80 mm, mecanismo metálico de fixação e visor de "
            "identificação.")

# Descrições reais da fonte (descricaoDetalhadaItem), idItemCompra entre ()
A3_12728225 = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO SULFITE/APERGAMINHADO/OFÍCIO, "
               "TAMANHO (CX L) 420 X 297 MM, GRAMATURA 75 G/M2, COR BRANCO")
COLORIDO_13021849 = ("Papel Para Impressão Formatado tipo: sulfite/apergaminhado/"
                     "ofício, tamanho (c x l): 297 x 210, gramatura: 75, cor: "
                     "colorido ")
OFFSET_12660435 = ("Papel Para Impressão Formatado Papel Para Impressão "
                   "Formatado, Tipo:Offset, Tamanho (C X L):960 X 660 MM, "
                   "Gramatura:120 G/M2, Cor:Branco, Característica "
                   "Adicional:Fibra Longitudinal ")
TEXTURIZADO_12728156 = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO TEXTURIZADO, "
                        "TAMANHO (C X L) 297 X 210 MM, GRAMATURA 120 G/M2, COR "
                        "COLORIDO, CARACTERÍSTICA ADICIONAL TEXTURA CASCA DEOVO")
A4_BRANCO = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO: SULFITE/APERGAMINHADO/"
             "OFÍCIO , TAMANHO (C X L): 297 X 210 MM, GRAMATURA: 75 G/M2, COR: "
             "BRANCO")
CLIPE0_12977596 = ("Clipe tratamento superficial: galvanizado, tamanho: 0, "
                   "material: aço carbono, formato: paralelo Clips em metal nº "
                   "0/0, tratamento superficial galvanizado, material : aço "
                   "carbono, formato paralelo, caixa com 100 unidades. ")
CLIPE2_12976393 = ("Clipe aplicação: fixar papéis e similares, formato: paralelo, "
                   "material: arame de aço, tamanho: 2/0, tratamento superficial: "
                   "galvanizado ")
CIRURGICO_12848928 = ("Grampeador Cirúrgico aplicação*: p/ tecido normal, "
                      "comprimento: cerca de 75, esterilidade: estéril, "
                      "descartável, formato: linear, modelo: recarregável, "
                      "carregado c/ grampo titânio, tipo: cortante")
ALICATE_12729225 = "GRAMPEADOR, MATERIAL METAL, TIPO ALICATE, TAMANHO GRAMPO 26/6"
MESA_12989072 = ("Grampeador material: metal, tipo: mesa, capacidade: 20, tamanho "
                 "grampo: 26/6, características adicionais: tamanho médio, "
                 "alfinetar 8 folhas Grampeador De Metal - 20Fl")


# ---------------------------------------------------------------------------
# C-1 — barreira por atributo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("item, ref, atributo", [
    (PAPEL_A4, A3_12728225, "formato"),
    (PAPEL_A4, COLORIDO_13021849, "cor"),
    (PAPEL_A4, OFFSET_12660435, "formato"),
    (PAPEL_A4, TEXTURIZADO_12728156, "cor"),
    (CLIPE_2_0, CLIPE0_12977596, "numeração"),
    (GRAMPEADOR, CIRURGICO_12848928, "finalidade"),
    (GRAMPEADOR, ALICATE_12729225, "tipo"),
])
def test_outro_produto_e_contradicao_c1(item, ref, atributo):
    achado = atributos.conflito(item, ref)
    assert achado is not None and achado.tipo == atributos.CONTRADIZ
    assert achado.atributo == atributo
    texto = atributos.motivo(achado)
    assert "produto diferente do item" in texto
    assert "[barreira por atributo]" in texto


CANETA_AZUL = ("CANETA ESFEROGRÁFICA AZUL. ESPECIFICAÇÃO: Caneta esferográfica, "
               "tinta azul, ponta média de 1,0 mm, corpo plástico transparente, "
               "escrita macia e uniforme, tampa ventilada, caixa contendo 50 "
               "unidades.")


@pytest.mark.parametrize("item, ref, atributo", [
    # cestas reais de 17/10 (pesquisa "aquisição"), selected antes da fase 1
    (CANETA_AZUL, "Caneta Esferográfica material: plástico reciclado, material "
     "ponta: esfera de tungstênio, tipo escrita: média, cor tinta: preta, "
     "características adicionais: atóxica, corpo cilíndrico ", "cor da tinta"),
    (CLIPE_2_0, "Clipe tratamento superficial: galvanizado, aplicação: material "
     "de expediente, tamanho: 1/0, material: arame de aço, formato: paralelo "
     "CLIPS 1/0 PARA PAPEL EM ACO", "numeração"),
    (PAPEL_A4, "Papel Para Impressão Formatado tipo: reciclado, tamanho (c x l): "
     "297 x 210, gramatura: 75, cor: branco", "tipo"),
])
def test_casos_das_cestas_de_17_10(item, ref, atributo):
    achado = atributos.conflito(item, ref)
    assert achado.tipo == atributos.CONTRADIZ and achado.atributo == atributo


@pytest.mark.parametrize("item, ref", [
    # sem falso positivo nas mesmas cestas
    (CANETA_AZUL, "Caneta Esferográfica cor tinta: azul, material: plástico, "
     "tipo escrita: média Caneta esferográfica, COR: AZUL/ PRETA/ VERMELHA"),
    (PAPEL_A4, "PAPEL PARA IMPRESSÃO FORMATADO, TIPO SULFITE/APERGAMINHADO/"
     "OFÍCIO, TAMANHO (CX L) 297 X 210 MM, GRAMATURA 90 G/M2, COR BRANCO"),
    (GRAMPEADOR, "Grampeador Grampeador, Tratamento Superficial:Pintura "
     "Eletrostática, Material:Metal, Tipo:Mesa, Capacidade:20 FL, Tamanho "
     "Grampo:24/6 E 26/6"),
    (PASTA_AZ, "Pasta Arquivo material: papelão prensado, tipo: registradora "
     "az, largura: 280, altura: 310, lombada: 80, cor: preta"),
    ("LIVRO ATA", "Livro Ata material: off-set branco, quantidade folhas: 100, "
     "gramatura: 56, comprimento: 310, largura: 220"),
])
def test_sem_falso_positivo_nas_cestas_reais(item, ref):
    assert atributos.conflito(item, ref) is None


def test_tipo_de_papel_diferente_e_contradicao_mesmo_sem_cor():
    ref = ("PAPEL PARA IMPRESSÃO FORMATADO, TIPO: OFFSET , TAMANHO (C X L): "
           "297 X 210 MM, GRAMATURA: 75 G/M2, COR: BRANCO")
    achado = atributos.conflito(PAPEL_A4, ref)
    assert achado.tipo == atributos.CONTRADIZ and achado.atributo == "tipo"


@pytest.mark.parametrize("item, ref", [
    (PAPEL_A4, A4_BRANCO),
    (CLIPE_2_0, CLIPE2_12976393),
    (GRAMPEADOR, MESA_12989072),
])
def test_mesmo_produto_passa(item, ref):
    assert atributos.conflito(item, ref) is None


def test_atributo_essencial_ausente_vai_para_revisao():
    sem_formato = "PAPEL PARA IMPRESSÃO, TIPO: SULFITE, COR: BRANCO"
    achado = atributos.conflito(PAPEL_A4, sem_formato)
    assert achado.tipo == atributos.AUSENTE and achado.atributo == "formato"
    sem_numero = "CLIPE, MATERIAL: AÇO, TRATAMENTO SUPERFICIAL: GALVANIZADO"
    assert atributos.conflito(CLIPE_2_0, sem_numero).tipo == atributos.AUSENTE


def test_formato_no_texto_livre_basta():
    ref = "Papel sulfite A4 branco 75g, resma com 500 folhas, cor branco"
    assert atributos.conflito(PAPEL_A4, ref) is None


def test_so_decide_quando_o_item_diz_o_atributo():
    # item sem formato não rejeita papel por formato
    assert atributos.conflito("PAPEL SULFITE", A3_12728225) is None
    # "papelão" da pasta não é o produto "papel"
    assert atributos.conflito(PASTA_AZ, A3_12728225) is None
    # pesquisar fio cirúrgico continua comparando com cirúrgico
    assert atributos.conflito("FIO DE SUTURA CIRÚRGICO",
                              "FIO DE SUTURA CIRÚRGICO AGULHADO") is None


FONTE = Fonte(id="compras_gov_precos", nome="Compras.gov.br — Preços Praticados",
              tipo="sistema_oficial")


class _Fonte:
    fonte = FONTE

    def __init__(self, descricoes):
        self._descricoes = descricoes

    def pesquisar(self, consulta) -> ResultadoBusca:
        return ResultadoBusca(fonte=FONTE, referencias=[
            Referencia(fonte=FONTE, id_externo=f"R{i}", bruto={"i": i},
                       descricao_original=texto, unidade_original="EMB",
                       quantidade_original=D("10"),
                       valor_unitario_original=D(preco),
                       natureza_valor=NaturezaValor.PRATICADO,
                       orgao=f"ORGAO {i}", ni_fornecedor=f"F{i}", uf="PA",
                       data_compra=date.today() - timedelta(days=10 + i),
                       referencia_externa=f"C{i}")
            for i, (texto, preco) in enumerate(self._descricoes)])


def test_cesta_nao_recebe_outro_produto_e_grava_o_motivo_c1():
    descricoes = [(A4_BRANCO, p) for p in
                  ("24.10", "25.00", "25.46", "26.00", "23.90", "24.80")]
    descricoes += [(A3_12728225, "45.20"), (COLORIDO_13021849, "25.30")]
    item = {"id": "it", "numero": 1, "descricao": PAPEL_A4, "unidade": "PACOTE",
            "quantidade": "10"}
    coleta = busca.coletar(item, [_Fonte(descricoes)], filtros={})
    escolha = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil("in_65_2021"), teto=15,
        saneamento=POLITICA_PADRAO, texto_item=PAPEL_A4)
    na_cesta = {r.descricao_original for r in escolha.selecionadas}
    assert A3_12728225 not in na_cesta and COLORIDO_13021849 not in na_cesta
    barradas = [r for r in escolha.retidas
                if any("[barreira por atributo]" in m for m in r.motivos)]
    assert {r.descricao_original for r in barradas} == {A3_12728225,
                                                       COLORIDO_13021849}
    assert all(r.status == StatusReferencia.REJEITADA for r in barradas)


def test_sem_a_flag_de_saneamento_a_selecao_e_a_de_antes():
    descricoes = [(A4_BRANCO, "25.00"), (A3_12728225, "45.20")]
    item = {"id": "it", "numero": 1, "descricao": PAPEL_A4, "unidade": "PACOTE",
            "quantidade": "10"}
    coleta = busca.coletar(item, [_Fonte(descricoes)], filtros={})
    escolha = estatistica.selecionar_cesta(
        coleta.referencias, obter_perfil("in_65_2021"), saneamento=None,
        texto_item=PAPEL_A4)
    assert not any("[barreira por atributo]" in m
                   for r in escolha.retidas + escolha.selecionadas
                   for m in r.motivos)


def test_relatorio_diz_que_o_sistema_tirou_e_nao_o_servidor():
    linha = {"status": "rejected", "motivos": [atributos.motivo(
        atributos.conflito(PAPEL_A4, A3_12728225))]}
    assert relatorio_view.autoria_da_saida(linha) == \
        "fora da série: produto diferente do item"


# ---------------------------------------------------------------------------
# C-2 / C-7 — identificador da compra e UASG
# ---------------------------------------------------------------------------
STM = {"idCompra": 6000105001912026, "idCompraItem": "0600010500191202600193",
       "codigoUasg": "060001", "nomeUasg": "SUPERIOR TRIBUNAL MILITAR",
       "codigoItemCatalogo": 461797, "numeroItemCompra": 193}


def test_id_compra_recupera_o_zero_pelo_proprio_registro_c2():
    assert links.id_compra_oficial(STM) == "06000105001912026"
    sem_item = {**STM, "idCompraItem": None}
    assert links.id_compra_oficial(sem_item) == "06000105001912026"  # pela UASG
    assert links.id_compra_oficial({"idCompra": 98991505000132026}) == \
        "98991505000132026"


def test_id_compra_nunca_e_completado_por_palpite():
    # 16 dígitos sem campo que prove o zero: não inventa
    assert links.id_compra_oficial({"idCompra": 6000105001912026}) == ""
    # idCompraItem que não é o mesmo número: não usa
    assert links.id_compra_oficial(
        {"idCompra": 6000105001912026,
         "idCompraItem": "0700010500191202600193"}) == ""
    assert links.id_compra_oficial({"idCompra": "abc"}) == ""


def test_resolver_monta_o_link_certo_para_uasg_com_zero_c2():
    r = links.resolver({"fonte_id": "compras_gov_precos", "bruto": STM})
    assert r.contratacao_url.endswith("?compra=06000105001912026")
    assert r.identificacao == "06000105001912026"
    assert r.unidade_compradora == "UASG 060001 — SUPERIOR TRIBUNAL MILITAR"


def test_sem_link_o_numero_continua_impresso_c2():
    from src.precos import documento_cotacao as dc

    sem_prova = {"idCompra": 6000105001912026}
    r = links.resolver({"fonte_id": "compras_gov_precos", "bruto": sem_prova})
    assert r.contratacao_url is None
    assert r.identificacao == "6000105001912026"

    class _Ref:
        contratacao_url = None
        identificacao = "6000105001912026"
        contratacao_rotulo = ""

    textos = [t.texto for t in dc._celula_contratacao(_Ref())]
    assert textos[0] == "6000105001912026"
    assert "Não disponível na fonte" not in " ".join(textos)

    _Ref.identificacao = ""
    assert [t.texto for t in dc._celula_contratacao(_Ref())] == \
        ["Identificador não informado pela fonte"]


def test_uasg_que_comprou_aparece_na_origem_c7():
    from src.precos import documento_cotacao as dc

    linha = {"fonte_id": "compras_gov_precos", "status": "selected",
             "orgao": "PRESIDENCIA DA REPUBLICA",
             "bruto": {"idCompra": 11012005001862026, "codigoUasg": "110120",
                       "nomeUasg": "DEPARTAMENTO DE ADMINISTRACAO DA ABIN/GSI/PR"}}
    ref = relatorio_view._referencia(linha, True)
    assert ref.unidade_compradora.startswith("UASG 110120")
    textos = " ".join(t.texto for t in dc._celula_origem(ref))
    assert "PRESIDENCIA DA REPUBLICA" in textos and "UASG 110120" in textos


# ---------------------------------------------------------------------------
# C-4 — cesta formada antes do teto não vai para documento
# ---------------------------------------------------------------------------
def _linhas(n, *, humanas=0):
    return [{"id": f"L{i}", "id_externo": f"X{i}", "status": "selected",
             "fonte_id": "compras_gov_precos",
             "valor_unitario_original": "10",
             "valor_unitario_normalizado": "10", "natureza_valor": "praticado"}
            for i in range(n)], {f"L{i}" for i in range(humanas)}


def test_cesta_da_maquina_acima_do_teto_trava_c4():
    linhas, _ = _linhas(317)
    acima = cesta.itens_acima_do_teto(
        [{"id": "a", "numero": 2}], {"a": linhas}, 15)
    assert acima == ["item 2: 317 preços na cesta (limite de 15)"]


def test_inclusao_do_servidor_alem_do_teto_nao_trava():
    linhas, humanas = _linhas(17, humanas=2)
    assert cesta.itens_acima_do_teto(
        [{"id": "a", "numero": 1}], {"a": linhas}, 15,
        decididas_por_humano=lambda _id: humanas) == []


def test_sem_teto_ligado_nada_trava():
    linhas, _ = _linhas(317)
    assert cesta.itens_acima_do_teto(
        [{"id": "a", "numero": 1}], {"a": linhas}, None) == []


def test_emissao_para_com_mensagem_clara_c4(monkeypatch):
    from src.precos import cotacoes
    from src.precos.documento_cotacao import ErroDeRenderizacao
    from src.ui import precos_ui

    linhas, _ = _linhas(20)
    monkeypatch.setattr(cotacoes, "politica_automatica",
                        lambda: estatistica.POLITICA_AUTOMATICA)
    monkeypatch.setattr(precos_ui.repo, "referencias_decididas_por_humano",
                        lambda *_a: set())
    with pytest.raises(ErroDeRenderizacao) as erro:
        precos_ui._conteudo_do_relatorio(
            {"id": "p"}, [{"id": "a", "numero": 3}], {"a": linhas},
            formato="pdf", tipo="cotacao")
    assert "item 3: 20 preços na cesta" in str(erro.value)
    assert "Refaça a cotação automática" in str(erro.value)
