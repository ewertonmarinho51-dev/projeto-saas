"""
Busca automática que recupera EQUIVALENTES (cotação multiportal, PR 2,
10/11/2026).

O que estas provas guardam:

* recuperar não é aceitar: "papel para impressão A4 75 g, resma 500 folhas"
  é EQUIVALENTE ao "papel sulfite A4 75 g/m², 500 folhas" e entra na cesta;
  papel 90 g/m² é INCOMPATÍVEL; caixa sem quantidade comprovada não entra
  sozinha; produto diferente com a mesma medida não vira equivalente;
* a estratégia de expansão é UMA, no item avulso e no lote: descrição e
  termo do servidor primeiro (o termo manual sempre na frente), variantes
  locais só com amostra curta, IA só depois e com cache;
* funciona sem IA (variantes locais determinísticas);
* o índice do PNCP consulta POR VARIANTE: a lista achatada de 12 palavras
  não suprime mais o sinônimo;
* a trilha registra termos por origem, fases, elegíveis por fase e
  candidatos por classe — ganho de cobertura separado de mais candidatos.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.precos import busca, cotacoes, equivalencia, estatistica, expansao, matching
from src.precos import pncp_indice as indice
from src.precos import repositorio as repo
from src.precos.fontes import Consulta, ResultadoBusca
from src.precos.modelo import Fonte, NaturezaValor, Referencia, StatusReferencia
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX

ITEM_PAPEL = "papel sulfite A4 75 g/m², 500 folhas"
FONTE = Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial")


def _ref(descricao, unidade="RESMA", valor="25.00", ident="r1", fonte=FONTE):
    return Referencia(
        fonte=fonte, id_externo=ident, bruto={"id": ident},
        descricao_original=descricao, unidade_original=unidade,
        quantidade_original=Decimal("10"), valor_unitario_original=Decimal(valor),
        natureza_valor=NaturezaValor.HOMOLOGADO, uf="PA",
        data_resultado=date(2026, 9, 1))


def _ranquear(item, refs):
    coleta = busca.Coleta()
    return busca._ranquear(refs, item, {"data_base": "2026-10-01", "uf": "PA"},  # noqa: SLF001
                           coleta, set())


ITEM = {"descricao": ITEM_PAPEL, "unidade": "RESMA", "quantidade": "10"}


# ---------------------------------------------------------------------------
# Classes de equivalência
# ---------------------------------------------------------------------------
def test_papel_para_impressao_75g_resma_e_equivalente_e_entra_na_cesta():
    [(ref, comp)] = _ranquear(ITEM, [_ref("papel para impressão A4 75 g, resma 500 folhas")])
    assert comp.classe_equivalencia == equivalencia.EQUIVALENTE
    assert comp.identidade >= equivalencia.IDENTIDADE_EQUIVALENTE
    assert comp.score >= estatistica.PISO_COMPARABILIDADE
    fator = next(f for f in comp.fatores if f.nome == "equivalencia")
    assert fator.explicacao.startswith("equivalente comprovado")
    assert "gramatura 75 g/m²" in fator.explicacao and "formato A4" in fator.explicacao
    cesta = estatistica.selecionar_cesta([(ref, comp)])
    assert cesta.selecionadas == [ref]


def test_papel_90g_e_incompativel_e_sai_da_serie_com_autoria_do_sistema():
    [(ref, comp)] = _ranquear(ITEM, [_ref("PAPEL SULFITE A4 90 G/M2 500 FOLHAS")])
    assert comp.classe_equivalencia == equivalencia.INCOMPATIVEL
    assert comp.identidade == 0
    cesta = estatistica.selecionar_cesta([(ref, comp)])
    assert not cesta.selecionadas and ref.status is StatusReferencia.REJEITADA
    assert any(m.startswith("[barreira por atributo] incompatível") and "90 g/m²" in m
               for m in ref.motivos)
    from src.precos.relatorio_view import autoria_da_saida
    assert autoria_da_saida({"status": "rejected", "motivos": ref.motivos}) == \
        "fora da série: produto diferente do item"


def test_caixa_sem_quantidade_comprovada_fica_fora_da_selecao_automatica():
    [(ref, comp)] = _ranquear(ITEM, [_ref("PAPEL A4 75G CAIXA", unidade="CAIXA")])
    assert ref.valor_unitario_normalizado is None
    cesta = estatistica.selecionar_cesta([(ref, comp)])
    assert not cesta.selecionadas


def test_similar_sem_prova_do_atributo_fica_com_o_servidor():
    # mesma unidade, mas a fonte não diz a gramatura
    [(ref, comp)] = _ranquear(ITEM, [_ref("PAPEL SULFITE A4 BRANCO 500 FOLHAS")])
    assert comp.classe_equivalencia == equivalencia.SIMILAR
    cesta = estatistica.selecionar_cesta([(ref, comp)])
    assert not cesta.selecionadas and ref.status is StatusReferencia.REVISAO_MANUAL
    assert any("a fonte não comprova: gramatura 75 g/m²" in m for m in ref.motivos)
    assert busca.Coleta(referencias=[(ref, comp)]).pre_selecao(
        estatistica.PISO_COMPARABILIDADE) == set()


def test_volume_divergente_e_incompativel_e_igual_por_conversao_confere():
    agua = {"descricao": "ÁGUA MINERAL SEM GÁS GARRAFÃO 20 L", "unidade": "UNIDADE",
            "quantidade": "100"}
    [(_, dez)] = _ranquear(agua, [_ref("AGUA MINERAL GALAO 10 LITROS", "UNIDADE")])
    assert dez.classe_equivalencia == equivalencia.INCOMPATIVEL
    [(_, vinte)] = _ranquear(agua, [_ref("AGUA MINERAL NATURAL GALAO 20000 ML", "UNIDADE")])
    assert vinte.classe_equivalencia in (equivalencia.EQUIVALENTE, equivalencia.MESMO_ITEM)


def test_contagem_e_embalagem_provada_pela_conversao_nao_divergencia():
    # resma de 500 contra o item em pacote de 500: a conversão confere
    c = equivalencia.classificar(ITEM_PAPEL, "PAPEL A4 GRAMATURA 75 G/M2",
                                 unidade_fonte="EMB", convertida=True)
    assert c.classe == equivalencia.EQUIVALENTE
    assert any("pela conversão de embalagem" in x for x in c.conferidos)
    assert equivalencia.classificar(ITEM_PAPEL, "PAPEL A4 GRAMATURA 75 G/M2",
                                    unidade_fonte="EMB").classe == equivalencia.SIMILAR


def test_produto_diferente_com_a_mesma_medida_nao_vira_equivalente():
    item = "BLOCO AUTOADESIVO 76X76 100 FOLHAS"
    assert equivalencia.classificar(item, "PRODUTO DIFERENTE GENERICO 0 ZZZ",
                                    convertida=True) is None
    # só a contagem pela conversão não basta para "equivalente comprovado"
    c = equivalencia.classificar(item, "BLOCO DE RECADOS", convertida=True)
    assert c.classe == equivalencia.SIMILAR


def test_item_sem_atributo_quantificavel_nao_e_classificado():
    [(_, comp)] = _ranquear({"descricao": "GASOLINA COMUM", "unidade": "LITRO"},
                            [_ref("GASOLINA COMUM", "LITRO")])
    assert comp.equivalencia is None
    assert all(f.nome != "equivalencia" for f in comp.fatores)


def test_mesmo_codigo_oficial_e_mesmo_item():
    c = equivalencia.classificar(ITEM_PAPEL, "outra redação qualquer", mesmo_codigo=True)
    assert c.classe == equivalencia.MESMO_ITEM


# ---------------------------------------------------------------------------
# Estratégia de expansão
# ---------------------------------------------------------------------------
def test_variantes_locais_de_sinonimo_e_unidade():
    variantes = expansao.variantes_locais(ITEM_PAPEL)
    assert "PAPEL PARA IMPRESSAO A4 75 G/M2 500 FOLHAS" in variantes
    assert "PAPEL SULFITE A4 75 G 500 FOLHAS" in variantes
    assert len(variantes) <= expansao.MAX_VARIANTES_LOCAIS
    assert expansao.descricao_curta(
        "BLOCO AUTOADESIVO 76X76 ESPECIFICAÇÃO: Bloco de notas reposicionáveis") == \
        "BLOCO AUTOADESIVO 76X76"


def test_termo_manual_vai_na_frente_e_literal_para_na_primeira_fase():
    plano = expansao.Plano(ITEM, termo="papel offset", literal=True)
    assert plano.fase_inicial() == ("papel offset",)
    assert plano.proxima_fase() is None
    plano = expansao.Plano(ITEM, termo="papel offset")
    plano.fase_inicial()
    proximos = plano.proxima_fase()
    assert proximos[0] == "papel offset"            # preservado na frente
    assert "PAPEL PARA IMPRESSAO A4 75 G/M2 500 FOLHAS" in proximos
    # termo igual à descrição não é termo novo
    assert expansao.Plano(ITEM, termo=ITEM_PAPEL.upper()).fase_inicial() == ()


def test_ia_so_depois_das_locais_um_pedido_por_item_e_cache(monkeypatch):
    from src.precos import semantica

    pedidos = []
    monkeypatch.setattr(semantica, "sugerir_termos",
                        lambda motor, item, limite=8: pedidos.append(1) or ["RESMA A4"])
    cache = expansao.CacheDeTermos()
    plano = expansao.Plano(ITEM, motor=object(), cache=cache)
    plano.fase_inicial()
    assert "RESMA A4" not in plano.proxima_fase()        # fase local primeiro
    assert plano.proxima_fase()[-1] == "RESMA A4"        # depois a IA
    assert plano.proxima_fase() is None                  # orçamento de fases
    # outro plano, mesma descrição e política: do cache, sem novo pedido
    outro = expansao.Plano(ITEM, motor=object(), cache=cache)
    outro.fase_inicial(); outro.proxima_fase(); outro.proxima_fase()
    assert pedidos == [1] and outro.ia_do_cache
    # o lote recarrega o cache pela trilha
    trilha = expansao.CacheDeTermos()
    trilha.carregar_da_trilha([{"expansao": outro.para_registro()}])
    assert trilha.obter(expansao.chave_de_cache(ITEM)) == ("RESMA A4",)


def test_chave_de_cache_muda_com_a_descricao():
    assert expansao.chave_de_cache(ITEM) != expansao.chave_de_cache(
        {**ITEM, "descricao": "papel sulfite A4 90 g/m²"})


# ---------------------------------------------------------------------------
# Pelo caminho real: cotacoes.pesquisar_item
# ---------------------------------------------------------------------------
class _FonteDeSinonimo:
    """Só conhece o produto pelo nome de catálogo: responde à VARIANTE."""

    fonte = FONTE

    def __init__(self):
        self.consultas: list[Consulta] = []

    def pesquisar(self, consulta):
        self.consultas.append(consulta)
        if not any("IMPRESSAO" in t for t in consulta.termos_alternativos):
            return ResultadoBusca(fonte=self.fonte)
        return ResultadoBusca(fonte=self.fonte, referencias=[
            _ref("PAPEL PARA IMPRESSÃO A4 75 G, RESMA 500 FOLHAS", valor=v, ident=f"s{i}")
            for i, v in enumerate(("24.90", "25.40", "26.10"))])


def _cotacao_papel(monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Papel", "data_base": "2026-10-01"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), ITEM)
    return cliente, str(c["id"]), str(item["id"])


@pytest.mark.parametrize("modo", ["manual", "automatico"])
def test_item_recuperado_por_variante_sem_ia(monkeypatch, modo):
    cliente, cid, iid = _cotacao_papel(monkeypatch)
    fonte = _FonteDeSinonimo()
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo=modo, fontes=[fonte])
    assert len(fonte.consultas) == 2                   # inicial vazia + variantes
    assert r.elegiveis == 3 and r.unicas == 3
    assert r.equivalencias == {equivalencia.EQUIVALENTE: 3}
    fases = r.expansao["fases"]
    assert [f["fase"] for f in fases] == ["descricao", "variantes_locais"]
    assert (fases[0]["elegiveis"], fases[1]["elegiveis"]) == (0, 3)
    assert not r.expansao["ia"]
    evento = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
              if e["tipo"] == "busca_concluida"][-1]["payload"]
    assert evento["expansao"]["fases"][1]["elegiveis"] == 3
    assert evento["equivalencias"] == {equivalencia.EQUIVALENTE: 3}
    if modo == "automatico":
        selecionadas = [l for l in repo.listar_referencias(iid) if l["status"] == "selected"]
        assert len(selecionadas) == 3
        assert repo.obter_item(iid)["preco_estimado"] is not None


def test_amostra_suficiente_na_primeira_fase_nao_amplia(monkeypatch):
    _, cid, iid = _cotacao_papel(monkeypatch)

    class Farta(_FonteDeSinonimo):
        def pesquisar(self, consulta):
            self.consultas.append(consulta)
            return ResultadoBusca(fonte=self.fonte, referencias=[
                _ref("PAPEL SULFITE A4 75 G/M2 500 FOLHAS", valor=v, ident=f"f{i}")
                for i, v in enumerate(("24.90", "25.40", "26.10"))])

    fonte = Farta()
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[fonte])
    assert len(fonte.consultas) == 1 and r.termos == []


def test_lote_usa_a_mesma_estrategia(monkeypatch):
    _, cid, iid = _cotacao_papel(monkeypatch)
    fonte = _FonteDeSinonimo()
    resultados, restantes = cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico",
                                                       tamanho=5, fontes=[fonte])
    assert restantes == 0 and resultados[0].elegiveis == 3
    assert [f["fase"] for f in resultados[0].expansao["fases"]] == \
        ["descricao", "variantes_locais"]


# ---------------------------------------------------------------------------
# Índice do PNCP: uma consulta por variante
# ---------------------------------------------------------------------------
def test_pncp_consulta_por_variante_e_nao_suprime_o_sinonimo():
    descricao = ("AGUA MINERAL NATURAL SEM GAS ACONDICIONADA GARRAFAO RETORNAVEL "
                 "CAPACIDADE VINTE LITROS LACRE SEGURANCA ROTULAGEM VALIDADE FABRICANTE")
    consulta = Consulta(descricao=descricao, termos_alternativos=("galao 20 litros",))
    # a lista achatada: as 12 vagas ficam com a descrição longa
    assert "galao" not in indice.termos_da_consulta(consulta)
    grupos = indice.grupos_da_consulta(consulta)
    assert len(grupos) == 2 and grupos[1] == ["litros", "galao"]
    chamadas = []

    def buscar(termos, **_):
        chamadas.append(list(termos))
        return []

    fonte = indice.PNCPIndice(buscar)
    resultado = fonte.pesquisar(consulta)
    assert chamadas == grupos and resultado.chamadas == 2


def test_pncp_linha_que_so_casa_com_a_variante_entra():
    from tests.test_pncp_indice import _indexar

    armazem = _indexar().armazem
    alvo = next(iter(armazem.resultados.values()))
    texto = alvo["descricao"]
    fonte = indice.PNCPIndice(armazem.buscar)
    sem = fonte.pesquisar(Consulta(descricao="ITEM SEM RELACAO NENHUMA XQZ"))
    com = fonte.pesquisar(Consulta(descricao="ITEM SEM RELACAO NENHUMA XQZ",
                                   termos_alternativos=(texto,)))
    assert alvo["id_externo"] not in {r.id_externo for r in sem.referencias}
    assert alvo["id_externo"] in {r.id_externo for r in com.referencias}
