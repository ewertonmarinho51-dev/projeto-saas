"""
Pesquisa de preços — Fase 2: matching, estatística, anomalias e cesta.

Nenhum teste desta suíte usa rede ou IA: tudo aqui é determinístico e
precisa continuar reproduzível ao centavo daqui a dois anos.

As quatro fronteiras que estas provas defendem:

1. **a cesta não é dos três mais baratos** — é dos mais comparáveis, na
   prioridade normativa das fontes;
2. **outlier estatístico não é preço inexequível** — o sistema sinaliza e
   explica a distância; a classificação jurídica é humana;
3. **a regra dos três não se cumpre fabricando referência** — falta
   referência, a pesquisa fica INCOMPLETA;
4. **exclusão não apaga** — o descartado continua na série, com motivo.
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src.precos import (IN_65_2021, LEI_14133, Cesta, Fonte, Referencia,
                        StatusReferencia, calcular, comparar,
                        detectar_anomalias, estimar, mediana, normalizar,
                        ordenar_por_comparabilidade, selecionar_cesta)
from src.precos.estatistica import PISO_COMPARABILIDADE, METODO_AUTOMATICO
from src.precos.matching import FATORES_DE_IDENTIDADE, PESOS, tokens

OFICIAL = Fonte("compras_gov_precos", "Compras.gov — Preços", "sistema_oficial")
SIMILAR = Fonte("compras_gov_itens", "Compras.gov — Contratações",
                "contratacao_similar")
HOJE = date(2026, 9, 4)


def ref(preco, *, descricao="PASTA CATALOGO 100 ENVELOPES PLASTICOS",
        unidade="UN", fonte=OFICIAL, dias=30, quantidade="1000",
        uf="PA", codigo=None, classe=None, criterio="V", ident=None,
        capacidade=None) -> Referencia:
    """Referência já normalizada, para não repetir a montagem em cada prova."""
    r = Referencia(
        fonte=fonte, id_externo=ident or f"id-{preco}-{descricao[:6]}",
        bruto={"preco": str(preco)},
        descricao_original=descricao,
        unidade_original=unidade,
        quantidade_original=Decimal(quantidade),
        valor_unitario_original=Decimal(str(preco)),
        capacidade_embalagem=None if capacidade is None
        else Decimal(str(capacidade)),
        codigo_catalogo=codigo, codigo_classe=classe, uf=uf,
        criterio_julgamento=criterio,
        data_resultado=HOJE - timedelta(days=dias))
    return normalizar(r, "UNIDADE")


CRITERIOS = {"descricao": "PASTA CATALOGO 100 ENVELOPES PLASTICOS",
             "quantidade": Decimal("1000"), "uf": "PA", "data_base": HOJE}


# ---------------------------------------------------------------------------
# 1. Matching — pares positivos e negativos (§49)
# ---------------------------------------------------------------------------
def test_descricao_equivalente_pontua_alto():
    c = comparar(ref(30, descricao="PASTA CATALOGO COM 100 ENVELOPES "
                                   "PLASTICOS, CAPA DURA"), **CRITERIOS)
    assert c.score > Decimal("0.7"), c.linhas()
    assert any("fortemente semelhante" in l for l in c.linhas())


@pytest.mark.parametrize("descricao_negativa", [
    "PASTA SUSPENSA KRAFT COM GRAMPO PLASTIFICADO",   # pasta comum
    "ENVELOPE PLASTICO OFICIO PACOTE COM 100",         # pacote de envelopes
    "PASTA CATALOGO 50 ENVELOPES PLASTICOS",           # capacidade diferente
])
def test_itens_diferentes_pontuam_menos_que_o_equivalente(descricao_negativa):
    """
    O score precisa refletir diferença REAL — os três negativos do §49
    são justamente os que um casamento ingênuo confundiria.
    """
    positivo = comparar(
        ref(30, descricao="PASTA CATALOGO COM 100 ENVELOPES PLASTICOS"),
        **CRITERIOS)
    negativo = comparar(ref(30, descricao=descricao_negativa), **CRITERIOS)
    assert negativo.score < positivo.score, (
        descricao_negativa, negativo.score, positivo.score)


def test_numero_da_descricao_separa_produtos():
    """'100 envelopes' e '50 envelopes' não são o mesmo produto."""
    assert "100" in tokens("PASTA CATALOGO 100 ENVELOPES")
    cem = comparar(ref(30, descricao="PASTA CATALOGO 100 ENVELOPES"),
                   **CRITERIOS)
    cinquenta = comparar(ref(30, descricao="PASTA CATALOGO 50 ENVELOPES"),
                         **CRITERIOS)
    assert cem.score > cinquenta.score


def test_mesmo_codigo_de_catalogo_e_evidencia_forte():
    com = comparar(ref(30, codigo="572775"),
                   codigo_catalogo="572775", **CRITERIOS)
    sem = comparar(ref(30, codigo="999999"),
                   codigo_catalogo="572775", **CRITERIOS)
    assert com.score > sem.score
    assert any("mesmo código" in l for l in com.linhas())
    assert any("!" in l and "diferente" in l for l in sem.linhas())


def test_ausencia_de_catmat_nao_penaliza():
    """
    O módulo aceita CATMAT sem exigir — punir quem não informa
    contradiria a decisão de produto.
    """
    sem_codigo = comparar(ref(30), **CRITERIOS)
    fator = next(f for f in sem_codigo.fatores if f.nome == "catalogo")
    assert fator.score == Decimal("0.5") and fator.conforme
    assert any("sem código de catálogo" in l for l in sem_codigo.linhas())


def test_unidade_nao_convertida_zera_o_fator_de_unidade():
    """Caixa sem fator de embalagem não é comparável — e o score diz."""
    caixa = ref(30, unidade="CX")           # sem capacidade informada
    c = comparar(caixa, **CRITERIOS)
    fator = next(f for f in c.fatores if f.nome == "unidade")
    assert fator.score == Decimal("0") and not fator.conforme


def test_contratacao_antiga_pontua_menos_que_recente():
    recente = comparar(ref(30, dias=30), **CRITERIOS)
    antiga = comparar(ref(30, dias=1500), **CRITERIOS)
    assert recente.score > antiga.score
    assert any("recente" in l for l in recente.linhas())
    assert any("antiga" in l for l in antiga.linhas())


def test_quantidade_de_ordem_muito_diferente_penaliza():
    proxima = comparar(ref(30, quantidade="1200"), **CRITERIOS)
    distante = comparar(ref(30, quantidade="3"), **CRITERIOS)
    assert proxima.score > distante.score


def test_outro_estado_sinaliza_sem_reprovar():
    c = comparar(ref(30, uf="SP"), **CRITERIOS)
    fator = next(f for f in c.fatores if f.nome == "geografia")
    assert not fator.conforme and fator.score > 0, "outro estado é legítimo"


def test_explicacao_lista_todos_os_fatores_e_e_conferivel():
    c = comparar(ref(30), **CRITERIOS)
    total = len(PESOS) + len(FATORES_DE_IDENTIDADE)
    assert len(c.fatores) == total and len(c.linhas()) == total
    # score = identidade × circunstâncias, e as circunstâncias são a
    # média ponderada — o auditor refaz as duas contas à mão
    circunstanciais = [f for f in c.fatores if f.peso > 0]
    esperado = (sum((f.contribuicao for f in circunstanciais), Decimal("0"))
                / sum((f.peso for f in circunstanciais), Decimal("0")))
    assert c.circunstancias == esperado
    assert c.score == c.identidade * c.circunstancias
    assert 0 <= c.percentual <= 100


def test_identidade_multiplica_e_nao_disputa_peso():
    """
    O defeito que os testes pegaram: circunstância impecável não pode
    transformar um produto em outro.
    """
    outro_produto = comparar(
        ref(30, descricao="GRAMPEADOR METALICO 26/6"), **CRITERIOS)
    assert outro_produto.circunstancias > Decimal("0.8"), "tudo mais bate"
    assert outro_produto.identidade < Decimal("0.2"), "mas é outro produto"
    assert outro_produto.score < Decimal("0.2")


def test_mesmo_codigo_vence_a_diferenca_de_redacao():
    """Prova documental de identidade prevalece sobre a escolha de palavras."""
    c = comparar(ref(30, descricao="PST CAT 100 ENV", codigo="572775"),
                 codigo_catalogo="572775", **CRITERIOS)
    assert c.identidade == Decimal("1")


def test_ranqueia_por_comparabilidade_e_nao_por_preco():
    """O barato incomparável não pode liderar o ranking."""
    caro_comparavel = ref(90, descricao="PASTA CATALOGO 100 ENVELOPES "
                                        "PLASTICOS", ident="caro")
    barato_diferente = ref(5, descricao="GRAMPEADOR METALICO 26/6",
                           ident="barato")
    ordenadas = ordenar_por_comparabilidade(
        [barato_diferente, caro_comparavel], **CRITERIOS)
    assert ordenadas[0][0].id_externo == "caro"


# ---------------------------------------------------------------------------
# 2. Estatística determinística (§50)
# ---------------------------------------------------------------------------
def _d(*valores):
    return [Decimal(str(v)) for v in valores]


def test_estatisticas_basicas():
    e = calcular(_d("10.00", "20.00", "30.00", "40.00"))
    assert e.quantidade == 4
    assert e.menor == Decimal("10.00") and e.maior == Decimal("40.00")
    assert e.media == Decimal("25.00")
    assert e.mediana == Decimal("25.00")
    assert e.amplitude == Decimal("30.00")


def test_mediana_com_numero_impar_e_par():
    assert mediana(_d(1, 2, 3)) == Decimal("2")
    assert mediana(_d(1, 2, 3, 4)) == Decimal("2.5")


def test_quartis_conferem_com_a_interpolacao_de_planilha():
    e = calcular(_d(1, 2, 3, 4, 5))
    assert e.q1 == Decimal("2") and e.q3 == Decimal("4")
    assert e.iqr == Decimal("2")


def test_serie_vazia_devolve_none_e_nao_zero():
    """Zero afirmaria que a média é zero — falso."""
    assert calcular([]) is None


def test_serie_de_um_elemento_nao_quebra():
    e = calcular(_d("18.21"))
    assert e.quantidade == 1 and e.desvio_padrao == Decimal("0")
    assert e.media == e.mediana == Decimal("18.21")


def test_precisao_decimal_nao_herda_erro_de_float():
    e = calcular(_d("0.1", "0.2"))
    assert e.media == Decimal("0.15")
    assert sum(_d("0.1", "0.2")) == Decimal("0.3")


def test_valor_total_arredonda_para_centavo():
    cesta = Cesta(selecionadas=[ref("18.215")])
    estimativa = estimar(cesta, justificativa="amostra única de ensaio")
    total = estimativa.valor_total(Decimal("3"))
    assert total == (estimativa.valor_unitario * 3).quantize(Decimal("0.01"))
    assert total.as_tuple().exponent == -2


def test_quantidade_fracionaria_e_grande():
    cesta = Cesta(selecionadas=[ref("2.50")])
    e = estimar(cesta, justificativa="ensaio")
    assert e.valor_total(Decimal("0.5")) == Decimal("1.25")
    assert e.valor_total(Decimal("1000000")) == Decimal("2500000.00")


# ---------------------------------------------------------------------------
# 3. Anomalias — sinaliza, explica, e NÃO julga juridicamente (§10, §23)
# ---------------------------------------------------------------------------
def test_discrepante_e_sinalizado_com_a_distancia_da_mediana():
    refs = [ref(v, ident=f"r{v}") for v in
            ("18.20", "19.10", "19.50", "20.00", "83.90")]
    e = calcular([r.valor_unitario_normalizado for r in refs])
    anomalias = detectar_anomalias(refs, e)
    assert len(anomalias) == 1
    a = anomalias[0]
    assert a.valor == Decimal("83.90")
    assert a.distancia_da_mediana_pct > 300
    assert "acima da mediana" in a.motivo and "revisão" in a.motivo


def test_anomalia_nunca_afirma_inexequibilidade():
    """
    A fronteira do §10: estatística não classifica juridicamente. Nenhum
    texto gerado aqui pode dizer 'inexequível' ou 'ilegal'.
    """
    refs = [ref(v) for v in ("18.20", "19.10", "19.50", "20.00", "0.01")]
    e = calcular([r.valor_unitario_normalizado for r in refs])
    for a in detectar_anomalias(refs, e):
        texto = a.motivo.lower()
        assert "inexequ" not in texto and "ilegal" not in texto
        assert "irregular" not in texto and "sobrepre" not in texto


def test_discrepante_nao_e_removido_da_serie():
    """Exclusão silenciosa de preço coletado é o oposto de auditável."""
    refs = [ref(v) for v in ("18.20", "19.10", "19.50", "20.00", "83.90")]
    e = calcular([r.valor_unitario_normalizado for r in refs])
    detectar_anomalias(refs, e)
    marcados = [r for r in refs if r.status is StatusReferencia.ALERTA]
    assert len(marcados) == 1
    assert len(refs) == 5, "nenhuma referência pode sumir da série"
    assert any("discrepante" in m for m in marcados[0].motivos)


def test_serie_pequena_nao_gera_alarme_falso():
    """Com 3 pontos qualquer um parece distante — sinalizar seria ruído."""
    refs = [ref(v) for v in ("10.00", "20.00", "90.00")]
    e = calcular([r.valor_unitario_normalizado for r in refs])
    assert detectar_anomalias(refs, e) == []


def test_serie_homogenea_nao_tem_anomalia():
    refs = [ref(v) for v in ("19.00", "19.10", "19.20", "19.30", "19.40")]
    e = calcular([r.valor_unitario_normalizado for r in refs])
    assert detectar_anomalias(refs, e) == []


# ---------------------------------------------------------------------------
# 4. Cesta — comparabilidade e prioridade, nunca preço (§12)
# ---------------------------------------------------------------------------
def test_cesta_nao_e_a_dos_tres_mais_baratos():
    baratos = [ref(v, descricao="GRAMPEADOR METALICO 26/6",
                   ident=f"barato{v}") for v in ("1.00", "2.00", "3.00")]
    caros = [ref(v, ident=f"caro{v}") for v in ("30.00", "31.00", "32.00")]
    cesta = selecionar_cesta(
        ordenar_por_comparabilidade(baratos + caros, **CRITERIOS))
    selecionados = {r.id_externo for r in cesta.selecionadas}
    assert selecionados == {"caro30.00", "caro31.00", "caro32.00"}
    assert all(r.id_externo.startswith("barato")
               for r in cesta.descartadas)


def test_sistema_oficial_vem_antes_de_contratacao_similar():
    similar = ref("30.00", fonte=SIMILAR, ident="similar")
    oficial = ref("31.00", fonte=OFICIAL, ident="oficial")
    cesta = selecionar_cesta(
        ordenar_por_comparabilidade([similar, oficial], **CRITERIOS))
    assert cesta.selecionadas[0].id_externo == "oficial"


def test_referencia_sem_unidade_comparavel_e_rejeitada():
    caixa = ref("30.00", unidade="CX", ident="caixa")   # sem fator
    unidade = ref("31.00", ident="unidade")
    cesta = selecionar_cesta(
        ordenar_por_comparabilidade([caixa, unidade], **CRITERIOS))
    assert [r.id_externo for r in cesta.selecionadas] == ["unidade"]
    assert caixa.status is StatusReferencia.REJEITADA


def test_abaixo_do_piso_fica_para_revisao_manual_e_nao_some():
    ruim = ref("30.00", descricao="CIMENTO PORTLAND SACO 50KG", ident="ruim")
    cesta = selecionar_cesta(
        ordenar_por_comparabilidade([ruim], **CRITERIOS))
    assert cesta.selecionadas == []
    assert ruim in cesta.descartadas
    assert ruim.status is StatusReferencia.REVISAO_MANUAL
    assert any("inclusão manual" in m for m in ruim.motivos)


def test_piso_de_comparabilidade_e_explicito():
    assert Decimal("0") < PISO_COMPARABILIDADE < Decimal("1")


# ---------------------------------------------------------------------------
# 5. Regra dos três — sem fabricar referência (§11, §53)
# ---------------------------------------------------------------------------
def test_duas_referencias_resultam_em_incompleto():
    cesta = Cesta(selecionadas=[ref("30.00", ident="a"),
                                ref("31.00", ident="b")])
    e = estimar(cesta)
    assert e.status == "INCOMPLETO" and not e.concluida
    assert any("apenas 2 referência" in m for m in e.memoria)
    assert any("nenhum preço é fabricado" in m for m in e.memoria)


def test_tres_referencias_concluem():
    cesta = Cesta(selecionadas=[ref(v, ident=v) for v in
                                ("30.00", "31.00", "32.00")])
    assert estimar(cesta).status == "CONCLUIDO"


def test_menos_de_tres_com_justificativa_conclui_e_registra():
    cesta = Cesta(selecionadas=[ref("30.00", ident="a")])
    e = estimar(cesta, justificativa="item exclusivo, fornecedor único")
    assert e.status == "CONCLUIDO"
    assert any("fornecedor único" in m for m in e.memoria)


def test_cesta_vazia_nao_inventa_preco():
    e = estimar(Cesta())
    assert e.valor_unitario is None and e.status == "INCOMPLETO"
    assert e.estatisticas is None


# ---------------------------------------------------------------------------
# 6. Método e perfil normativo (§22, §3)
# ---------------------------------------------------------------------------
def test_automatico_usa_mediana_em_serie_dispersa():
    cesta = Cesta(selecionadas=[ref(v, ident=v) for v in
                                ("10.00", "20.00", "90.00", "15.00")])
    e = estimar(cesta, metodo=METODO_AUTOMATICO)
    assert e.metodo == "mediana"
    assert any("série dispersa" in m for m in e.memoria)


def test_automatico_usa_media_em_serie_homogenea():
    cesta = Cesta(selecionadas=[ref(v, ident=v) for v in
                                ("19.00", "19.10", "19.20", "19.30")])
    e = estimar(cesta, metodo=METODO_AUTOMATICO)
    assert e.metodo == "media"
    assert any("homogênea" in m for m in e.memoria)


@pytest.mark.parametrize("metodo,esperado", [
    ("media", Decimal("30.00")), ("mediana", Decimal("30.00")),
    ("menor", Decimal("20.00")),
])
def test_metodo_explicito_e_respeitado(metodo, esperado):
    cesta = Cesta(selecionadas=[ref(v, ident=v) for v in
                                ("20.00", "30.00", "40.00")])
    e = estimar(cesta, metodo=metodo)
    assert e.metodo == metodo and e.valor_unitario == esperado


def test_in65_limita_a_estimativa_a_mediana_em_sistema_oficial():
    """
    Art. 6º da IN 65: com estimativa apoiada SÓ em sistema oficial, o
    valor não supera a mediana. Aqui a média (33,33) excede a mediana
    (30,00) e precisa ser ajustada.
    """
    cesta = Cesta(selecionadas=[ref(v, fonte=OFICIAL, ident=v) for v in
                                ("20.00", "30.00", "50.00")])
    e = estimar(cesta, perfil=IN_65_2021, metodo="media")
    assert e.valor_unitario == Decimal("30.00")
    assert any("não supera a mediana" in m for m in e.memoria)


def test_teto_nao_se_aplica_com_fonte_de_outro_tipo():
    """A restrição vale para estimativa EXCLUSIVAMENTE de sistema oficial."""
    cesta = Cesta(selecionadas=[
        ref("20.00", fonte=OFICIAL, ident="a"),
        ref("30.00", fonte=OFICIAL, ident="b"),
        ref("50.00", fonte=SIMILAR, ident="c")])
    e = estimar(cesta, perfil=IN_65_2021, metodo="media")
    assert e.valor_unitario == Decimal("33.33")


def test_perfil_base_nao_aplica_teto_da_mediana():
    cesta = Cesta(selecionadas=[ref(v, fonte=OFICIAL, ident=v) for v in
                                ("20.00", "30.00", "50.00")])
    e = estimar(cesta, perfil=LEI_14133, metodo="media")
    assert e.valor_unitario == Decimal("33.33")
    assert e.perfil_id == "lei_14133"


def test_perfis_declaram_base_legal_e_minimo():
    for perfil in (LEI_14133, IN_65_2021):
        assert perfil.base_legal and perfil.minimo_referencias == 3
    assert IN_65_2021.teto_da_mediana_em_sistema_oficial
    assert not LEI_14133.teto_da_mediana_em_sistema_oficial


# ---------------------------------------------------------------------------
# 7. Memória de cálculo — o relatório precisa reproduzir a conta
# ---------------------------------------------------------------------------
def test_memoria_registra_metodo_e_quantidade():
    cesta = Cesta(selecionadas=[ref(v, ident=v) for v in
                                ("30.00", "31.00", "32.00")])
    e = estimar(cesta)
    assert any("3 referência" in m for m in e.memoria)
    projecao = e.para_relatorio()
    assert projecao["status"] == "CONCLUIDO"
    assert projecao["selecionadas"] == 3
    assert isinstance(projecao["valor_unitario"], str)
    assert projecao["estatisticas"]["quantidade"] == 3


def test_relatorio_da_comparabilidade_e_serializavel():
    projecao = comparar(ref(30), **CRITERIOS).para_relatorio()
    assert isinstance(projecao["score"], str)
    # as duas parcelas viajam separadas: o relatório precisa distinguir
    # "outro produto" de "produto certo, contratação distante"
    assert isinstance(projecao["identidade"], str)
    assert isinstance(projecao["circunstancias"], str)
    assert len(projecao["fatores"]) == len(PESOS) + len(FATORES_DE_IDENTIDADE)
    assert all(isinstance(f["peso"], str) for f in projecao["fatores"])
