"""
Banco de Preços — núcleo compartilhado (Gates 1 e 2, 15/10/2026).

* `busca.coletar`: um serviço de busca para manual e automática;
* código interno do município não vale como CATMAT na comparabilidade;
* média aritmética simples como método padrão das pesquisas NOVAS, sem
  trocar o método das antigas; método proibido não cai em outro calado;
* `cesta.recalcular`: a revisão humana refaz o preço pela seleção gravada.

Casos do `15_CASOS_TESTE_MAQUINA.yaml` do pacote (dados sintéticos).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest

from src.precos import busca, cesta, estatistica, perfil
from src.precos.compras_gov import ComprasGovAdapter
from src.precos.estados import EstadoItem
from src.precos.estatistica import Cesta, estimar
from src.precos.modelo import Fonte, NaturezaValor, Referencia

OFICIAL = Fonte(id="compras_gov_precos", nome="Compras.gov", tipo="sistema_oficial")


def _ref(valor, ident="x"):
    return Referencia(fonte=OFICIAL, id_externo=str(ident), bruto={},
                      valor_unitario_original=Decimal(valor),
                      valor_unitario_normalizado=Decimal(valor),
                      natureza_valor=NaturezaValor.HOMOLOGADO)


# ---------------------------------------------------------------------------
# método: média aritmética padrão (BAS-05, metodo_calculo, media_tres_validos)
# ---------------------------------------------------------------------------
def test_media_tres_validos():
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("20.00", "22.00", "24.00")]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.metodo == "media" and e.valor_unitario == Decimal("22.00")
    assert e.status == "CONCLUIDO"
    assert e.valor_total(Decimal("10")) == Decimal("220.00")
    # memória em pt-BR desde o G1 de Cotações (dossiê BP, tema 4)
    assert any("soma R$ 66,00 ÷ 3" in m for m in e.memoria)


def test_media_em_decimal_sem_erro_de_float():
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("0.10", "0.20", "0.30")]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.valor_unitario == Decimal("0.20")
    assert isinstance(e.valor_unitario, Decimal)


def test_serie_dispersa_continua_na_media_e_alerta_sem_excluir():
    """Mediana é diagnóstico: dispersão NÃO troca o método (BAS-04)."""
    valores = ("20.00", "21.00", "22.00", "23.00", "200.00")
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in valores]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.metodo == "media"
    assert e.valor_unitario == Decimal("57.20")
    assert len(e.cesta.selecionadas) == 5, "nenhum outlier excluído"
    assert e.anomalias, "o discrepante é sinalizado"


def test_pesquisa_antiga_mantem_a_regra_do_coeficiente_de_variacao():
    """BAS-07: a mudança do padrão não reprocessa pesquisa já feita."""
    valores = ("10.00", "20.00", "90.00", "15.00")
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in valores]),
                regras=estatistica.REGRAS_LEGADAS)
    assert e.metodo == "mediana"


def test_dois_precos_ficam_incompletos():
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("20.00", "22.00")]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.status == "INCOMPLETO"


def test_teto_da_mediana_vale_no_perfil_que_o_exige():
    """BAS-06: IN 65 com estimativa só em sistema oficial."""
    valores = ("20.00", "21.00", "22.00", "23.00", "200.00")
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in valores]),
                perfil=perfil.IN_65_2021, regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.valor_unitario == Decimal("22.00")
    assert any("não supera a mediana" in m for m in e.memoria)


def test_metodo_proibido_nao_cai_em_outro_calado():
    restrito = perfil.PerfilNormativo(id="t", nome="Teste", base_legal="-",
                                      metodos_permitidos=("mediana",))
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("20", "22", "24")]),
                perfil=restrito, regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.valor_unitario is None and e.status == "INCOMPLETO"
    assert any("não é admitido" in m and "mediana" in m for m in e.memoria)


# ---------------------------------------------------------------------------
# busca: serviço único e código interno ≠ CATMAT
# ---------------------------------------------------------------------------
def _compra(preco, ident, descricao="CANETA ESFEROGRÁFICA, COR TINTA: AZUL"):
    return {"idCompraItem": ident, "codigoItemCatalogo": 275111,
            "codigoPdm": 99, "precoUnitario": preco, "descricaoItem": descricao,
            "siglaUnidadeFornecimento": "UN", "dataCompra": "2026-10-01",
            "criterioJulgamento": "Menor Preço"}


def _api(compras):
    def abrir(url):
        if "3_consultarPdmMaterial" in url:
            return json.dumps({"resultado": [
                {"codigoPdm": 99, "nomePdm": "CANETA ESFEROGRÁFICA",
                 "nomeClasse": "ESCRITÓRIO"}], "totalPaginas": 1})
        if "tipo=codigoPdm" in url:
            return json.dumps({"resultado": compras,
                               "totalRegistros": len(compras)})
        return json.dumps({"resultado": [], "totalRegistros": 0})
    return abrir


ITEM_INTERNO = {"id": "i1", "numero": 1, "codigo": "572704",
                "descricao": "CANETA ESFEROGRÁFICA AZUL tinta azul",
                "unidade": "UNIDADE", "quantidade": "10"}


def test_codigo_interno_nao_zera_a_identidade():
    """15/10/2026: 0/10 itens da planilha real concluíam por isto."""
    compras = [_compra(1.0 + i / 10, f"c{i}") for i in range(4)]
    coleta = busca.coletar(ITEM_INTERNO, [ComprasGovAdapter(abrir_url=_api(compras))])
    assert not coleta.codigo_confirmado
    assert all(comp.identidade > 0 for _, comp in coleta.referencias)
    assert coleta.elegiveis(estatistica.PISO_COMPARABILIDADE) >= 3


def test_coleta_distingue_brutas_unicas_e_duplicadas():
    """portal_duplicado: o mesmo registro visto duas vezes conta uma."""
    compras = [_compra(1.0, "c1"), _compra(1.0, "c1"), _compra(2.0, "c2")]
    coleta = busca.coletar(ITEM_INTERNO, [ComprasGovAdapter(abrir_url=_api(compras))])
    assert (coleta.brutas, coleta.unicas, coleta.duplicadas) == (3, 2, 1)


def test_mesmo_valor_em_compras_distintas_nao_deduplica():
    compras = [_compra(19.90, "proc-11"), _compra(19.90, "proc-12")]
    coleta = busca.coletar(ITEM_INTERNO, [ComprasGovAdapter(abrir_url=_api(compras))])
    assert coleta.unicas == 2


def test_falha_de_todas_as_fontes_de_preco_e_erro_tecnico():
    """sem_fonte: falha técnica não é mercado vazio."""
    def cai(_url):
        raise TimeoutError("lento")

    coleta = busca.coletar(ITEM_INTERNO, [ComprasGovAdapter(abrir_url=cai)])
    assert "falha técnica" in coleta.erro


def test_fonte_saudavel_sem_resultado_nao_e_erro():
    """mercado_vazio: 0 preço com API saudável = sem resultado."""
    coleta = busca.coletar(ITEM_INTERNO, [ComprasGovAdapter(abrir_url=_api([]))])
    assert not coleta.erro and coleta.unicas == 0


# ---------------------------------------------------------------------------
# cesta: recálculo pela seleção gravada
# ---------------------------------------------------------------------------
def _linha(valor, status="selected", ident=None):
    return {"id": ident or valor, "status": status, "fonte_id": "compras_gov_precos",
            "fonte_tipo": "sistema_oficial", "id_externo": ident or valor,
            "valor_unitario_original": valor,
            "valor_unitario_normalizado": valor, "natureza_valor": "homologado"}


def test_recalculo_usa_so_as_selecionadas():
    linhas = [_linha("20.00"), _linha("22.00"), _linha("24.00"),
              _linha("99.00", status="rejected")]
    e = cesta.recalcular(linhas, perfil=perfil.LEI_14133,
                         regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.valor_unitario == Decimal("22.00")
    assert cesta.validas_na_cesta(linhas) == 3


def test_selecionada_sem_preco_normalizado_fica_fora_do_calculo():
    linhas = [_linha("20.00"), _linha("22.00"),
              dict(_linha("24.00"), valor_unitario_normalizado=None)]
    e = cesta.recalcular(linhas, perfil=perfil.LEI_14133,
                         regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.status == "INCOMPLETO"
    assert cesta.validas_na_cesta(linhas) == 2


class _RepoFalso:
    def __init__(self, linhas):
        self.linhas = linhas
        self.gravado = None

    def listar_referencias(self, _item_id):
        return self.linhas

    def atualizar_estimativa(self, item, estimativa, *, quantidade=None,
                             decisoes=None, revisao_esperada=None):
        self.gravado = (item["estado"], estimativa, quantidade)
        return {}


def test_excluir_referencia_refaz_o_preco_do_item():
    repo = _RepoFalso([_linha("20.00"), _linha("22.00"), _linha("24.00"),
                       _linha("200.00")])
    pesquisa = {"versao_regras": estatistica.REGRAS_MEDIA_PADRAO}
    item = {"id": "i1", "estado": EstadoItem.EM_REVISAO.value, "quantidade": "10"}
    antes = cesta.recalcular_e_gravar(pesquisa, item, repo, perfil=perfil.LEI_14133)
    repo.linhas[-1]["status"] = "rejected"
    depois = cesta.recalcular_e_gravar(pesquisa, item, repo, perfil=perfil.LEI_14133)
    assert antes.valor_unitario == Decimal("66.50")
    assert depois.valor_unitario == Decimal("22.00")
    assert repo.gravado[2] == Decimal("10")


@pytest.mark.parametrize("plural,singular", [("BALOES", "BALAO"),
                                             ("CLIPES", "CLIPE")])
def test_singular_do_catalogo(plural, singular):
    from src.precos import catalogo

    assert catalogo._singular(plural) == singular


def test_indicador_n_de_3_sai_do_que_o_item_gravou():
    assert cesta.indicador({"estatisticas": {"selecionadas": 4}}) == "4/3 ✓"
    assert cesta.indicador({"estatisticas": {"selecionadas": 2}}) == "2/3"
    assert cesta.indicador({"estado": "pending"}) == "—"
    assert cesta.indicador({"estatisticas": None}) == "—"


# ---------------------------------------------------------------------------
# análise crítica: média de referências APROVADAS (pacote 08, BAS-04)
# ---------------------------------------------------------------------------
def test_erro_grosseiro_da_fonte_torna_a_media_provisoria_mesmo_com_tres():
    """Medido em 15/10/2026: divisória de fichário com média R$ 30.002,33."""
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("14.00", "16.00", "90000.00")]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.concluida and e.provisoria
    assert any("dispersão elevada" in p for p in e.pendencias)
    assert any("PROVISÓRIO" in m for m in e.memoria)
    assert e.para_relatorio()["pendencias"] == e.pendencias


def test_serie_homogenea_nao_tem_pendencia():
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("20.00", "22.00", "24.00")]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert not e.provisoria and e.pendencias == []


def test_discrepante_sinalizado_gera_pendencia_sem_sair_da_cesta():
    valores = ("20.00", "21.00", "22.00", "23.00", "200.00")
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in valores]),
                regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert any("discrepante" in p for p in e.pendencias)
    assert len(e.cesta.selecionadas) == 5


def test_regra_antiga_nao_ganha_pendencia():
    e = estimar(Cesta(selecionadas=[_ref(v, v) for v in ("14.00", "16.00", "90000.00")]),
                regras=estatistica.REGRAS_LEGADAS)
    assert e.metodo == "mediana" and e.pendencias == []


def test_referencia_sinalizada_continua_na_cesta_no_recalculo():
    """Antes, o primeiro clique na revisão tirava o `warning` calado."""
    linhas = [_linha("20.00"), _linha("22.00"), _linha("24.00"),
              _linha("200.00", status="warning")]
    e = cesta.recalcular(linhas, perfil=perfil.LEI_14133,
                         regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert e.valor_unitario == Decimal("66.50")
    assert cesta.validas_na_cesta(linhas) == 4


def test_concluir_com_pendencia_exige_justificativa():
    item = {"estatisticas": {"pendencias": ["1 preço(s) discrepante(s)"]}}
    assert cesta.validar_conclusao(item, "")
    assert cesta.validar_conclusao(item, "ok")
    assert cesta.validar_conclusao(
        item, "Mantido: o preço alto é de compra emergencial documentada") is None
    assert cesta.validar_conclusao({"estatisticas": {}}, "") is None
