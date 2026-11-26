"""
Cotação automática pronta para revisão (26/11/2026) — as causas medidas na
cotação real de 383 itens de materiais de construção (produção):

* o passo do lote, com o recorte JÁ fixado pelo worker, não refaz a
  pergunta "o índice do PNCP ganhou dado novo?" para cada pendente — ela
  custava ~1,4 s por item consultado e somava ~2 min a cada item processado;
* ao fixar o recorte, essa pergunta corre em paralelo, no contexto (JWT)
  da requisição;
* a equivalência separa classe e tamanho que SÃO especificação: argamassa
  AC-I/II/III, bucha S4…S10, bitola em polegadas, seção do cabo em mm². A
  série deixa de misturar produtos diferentes, e o CV deixa de reprovar
  por causa disso.

Banco falso e fontes dublês. Nada de rede nem IA.
"""

from __future__ import annotations

import contextvars
from decimal import Decimal

import pytest

from src.precos import cotacoes, equivalencia, estatistica
from src.precos import repositorio as repo
from src.precos.fontes import ResultadoBusca
from src.precos.modelo import Fonte
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacao_equivalencia import _ref
from tests.test_cotacoes_g2_servico import CTX

FONTE = Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial")


class _Fonte:
    def __init__(self, ofertas, unidade="RESMA"):
        self.fonte = FONTE
        self.ofertas = list(ofertas)       # (descrição, valor)
        self.unidade = unidade
        self.chamadas = 0

    def pesquisar(self, consulta):
        self.chamadas += 1
        return ResultadoBusca(fonte=self.fonte, referencias=[
            _ref(d, unidade=self.unidade, valor=v, ident=f"r{i}", fonte=self.fonte)
            for i, (d, v) in enumerate(self.ofertas)])


def _cotacao(monkeypatch, itens):
    ligar_banco_falso(monkeypatch)
    # a política de produção: teto 5 e barreira do CV ligados
    monkeypatch.setattr(cotacoes, "politica_automatica",
                        lambda: estatistica.POLITICA_AUTOMATICA)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Lote", "data_base": "2026-11-01"})
    ids = [str(cotacoes.salvar_item(CTX, str(c["id"]), item)["id"]) for item in itens]
    return str(c["id"]), ids


PAPEL = {"descricao": "papel sulfite A4 75 g/m², 500 folhas", "unidade": "RESMA",
         "quantidade": "10"}
OFERTAS_PAPEL = [("PAPEL SULFITE A4 75 G/M2 500 FOLHAS", v) for v in ("24.90", "25.40", "26.10")]
DISPERSAS = [("PAPEL SULFITE A4 75 G/M2 500 FOLHAS", v) for v in ("10", "25", "60")]


# ---------------------------------------------------------------------------
# Passo do lote com recorte fixo: sem consulta ao índice por pendente
# ---------------------------------------------------------------------------
def test_passo_com_recorte_fixo_nao_consulta_o_indice_dos_pendentes(monkeypatch):
    cid, ids = _cotacao(monkeypatch, [PAPEL] * 4)
    dispersa = _Fonte(DISPERSAS)
    # 1ª rodada: os quatro ficam pendentes (CV reprovado)
    cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=4, fontes=[dispersa])
    consultas = []
    monkeypatch.setattr(cotacoes, "novidade_no_indice",
                        lambda item, ultima, fontes: consultas.append(item["id"]) or False)
    # o worker fixou um recorte de dois itens; cada passo processa UM
    tentados: set[str] = set()
    for _ in range(3):
        cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=1,
                                   item_ids=ids[:2], ja_tentados=tentados,
                                   fontes=[dispersa])
    assert consultas == []                  # nenhuma pergunta ao índice
    assert tentados == set(ids[:2])         # e os dois do recorte rodaram


def test_passo_com_recorte_fixo_pula_o_item_que_o_servidor_concluiu(monkeypatch):
    cid, ids = _cotacao(monkeypatch, [PAPEL] * 2)
    from tests.cotacoes_apoio import ClientePrecosFalso  # noqa: F401 — o banco já está ligado
    linhas = repo.listar_itens(cid)
    concluido = next(l for l in linhas if str(l["id"]) == ids[0])
    concluido["estado"] = "complete"
    monkeypatch.setattr(repo, "listar_itens", lambda _cid: linhas)
    fonte = _Fonte(OFERTAS_PAPEL)
    resultados, restantes = cotacoes.pesquisar_em_lote(
        CTX, cid, modo="automatico", tamanho=5, item_ids=ids, fontes=[fonte])
    assert [r.item_id for r in resultados] == [ids[1]] and restantes == 0


def test_recorte_da_largada_pergunta_ao_indice_em_paralelo_com_o_jwt(monkeypatch):
    cid, ids = _cotacao(monkeypatch, [PAPEL] * 3)
    cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=3,
                               fontes=[_Fonte(DISPERSAS)])
    marca = contextvars.ContextVar("marca", default="sem contexto")
    marca.set("jwt do usuário")
    vistos = []

    def novidade(item, ultima, fontes):
        vistos.append(marca.get())
        return str(item["id"]) == ids[1]

    monkeypatch.setattr(cotacoes, "novidade_no_indice", novidade)
    recorte = cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[_Fonte(DISPERSAS)])
    assert recorte == [ids[1]]
    assert vistos == ["jwt do usuário"] * 3      # o contexto chegou às threads


# ---------------------------------------------------------------------------
# Equivalência: classe e tamanho que são especificação
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("item,fonte,classe", [
    ("ARGAMASSA COLANTE AC 2, SACO DE 20KG", "ARGAMASSA COLANTE AC-II, SACO COM 20KG.", "equivalente"),
    ("ARGAMASSA COLANTE AC 2, SACO DE 20KG", "ARGAMASSA DE CIMENTO COLANTE ACII SACO COM 20KG", "equivalente"),
    ("ARGAMASSA COLANTE AC 2, SACO DE 20KG", "ARGAMASSA COLANTE AC-I, SACO COM 20KG", "incompativel"),
    ("ARGAMASSA COLANTE AC 2, SACO DE 20KG", "ARGAMASSA COLANTE (TIPO: AC-III|USO EXTERNO) 20KG", "incompativel"),
    # sem a classe no texto da fonte: não comprova — fica com o servidor
    ("ARGAMASSA COLANTE AC 2, SACO DE 20KG",
     "Argamassa composição: cimento, agregados minerais e aditivos, aplicação: assentamento", "similar"),
    ("BUCHA DE NYLON SEM ABA S6", "BUCHA DE NYLON SEM ABA, TAMANHO S6", "equivalente"),
    ("BUCHA DE NYLON SEM ABA S6", "BUCHA DE NYLON SEM ABA S8", "incompativel"),
    ("BUCHA DE NYLON SEM ABA S6", "BUCHA DE NYLON SEM ABA S10", "incompativel"),
    ("ALICATE DE CORTE DIAGONAL 6” COM ISOLAMENTO", 'ALICATE CORTE DIAGONAL 6" ISOLADO', "equivalente"),
    ("ALICATE DE CORTE DIAGONAL 6” COM ISOLAMENTO", "ALICATE CORTE DIAGONAL 8 POL", "incompativel"),
    ("JOELHO PVC SOLDAVEL 90 GRAUS 3/4\"", "JOELHO PVC 90 1.1/2\"", "incompativel"),
    ("CABO FLEXIVEL 2,5MM² 750V", "CABO FLEXIVEL 4 MM2 750V", "incompativel"),
    ("CABO FLEXIVEL 2,5MM² 750V", "CABO FLEX 2,5 MM2 450/750V", "equivalente"),
])
def test_classe_tamanho_bitola_e_secao(item, fonte, classe):
    r = equivalencia.classificar(item, fonte, semelhanca=Decimal("0.5"))
    assert r is not None and r.classe == classe, r and r.explicacao


def test_tamanho_s_so_vale_em_bucha_e_ac_nao_confunde_220v():
    assert "tamanho" not in equivalencia.atributos("CAMISETA TAMANHO S6 ALGODAO")
    assert "classe" not in equivalencia.atributos("TOMADA AC 220V 10A")
    assert equivalencia.atributos("BUCHA S 8")["tamanho"] == {"S8"}
    assert equivalencia.atributos('TUBO 1.1/2"')["polegadas"] == {Decimal("1.5")}


def test_motivo_da_exclusao_aponta_o_atributo_do_registro():
    r = equivalencia.classificar("BUCHA DE NYLON SEM ABA S6", "BUCHA DE NYLON SEM ABA S8",
                                 semelhanca=Decimal("0.5"))
    assert r.divergem == ("tamanho S8 na fonte, S6 no item",)
    assert equivalencia.VERSAO == "2026-11-26.equivalencia.3"


def test_serie_de_tamanhos_misturados_vira_cesta_so_do_tamanho_pedido(monkeypatch):
    """O caso real: S6 recebia S4–S10 (CV 39%). Com a régua nova, só os S6
    entram, e o item chega pronto para revisão."""
    bucha = {"descricao": "BUCHA DE NYLON SEM ABA S6", "unidade": "UNIDADE", "quantidade": "100"}
    cid, (iid,) = _cotacao(monkeypatch, [bucha])
    ofertas = [("BUCHA DE NYLON SEM ABA S6", "0.10"), ("BUCHA DE NYLON SEM ABA S6", "0.11"),
               ("BUCHA NYLON SEM ABA S6 UNIDADE", "0.12"), ("BUCHA DE NYLON SEM ABA S8", "0.18"),
               ("BUCHA DE NYLON SEM ABA S10", "0.26"), ("BUCHA DE NYLON SEM ABA S4", "0.02")]
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[_Fonte(ofertas, unidade="UN")])
    assert r.desfecho == "pronto_para_revisao", r.mensagem
    na_cesta = sorted(l["descricao_original"] for l in repo.listar_referencias(iid)
                      if l["status"] == "selected")
    assert na_cesta and all("S6" in d for d in na_cesta)
    item = repo.obter_item(iid)
    assert cotacoes.proposta_apta(item)


# ---------------------------------------------------------------------------
# Rodada 2 sobre o lote A com fontes reais (26/11/2026)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("item,fonte,classe", [
    # água: o qualificador é o produto
    ("ÁGUA SANITÁRIA 1 LITRO", "Água Coco material: água côco verde, 1 litro", "incompativel"),
    ("ÁGUA SANITÁRIA 1 LITRO", "ÁGUA SANITÁRIA, HIPOCLORITO DE SÓDIO, 1 LITRO", "equivalente"),
    # recarga × vasilhame (o exemplo do pedido)
    ("ÁGUA MINERAL GARRAFÃO 20 LITROS (RECARGA)",
     "ÁGUA MINERAL NATURAL, GALÃO DE 20 LITROS RETORNÁVEL (RECARGA)", "equivalente"),
    ("ÁGUA MINERAL GARRAFÃO 20 LITROS (RECARGA)", "AGUA MINERAL NATURAL GARRAFAO 20L", "similar"),
    ("ÁGUA MINERAL GARRAFÃO 20 LITROS (RECARGA)", "ÁGUA MINERAL 20 L COM VASILHAME", "incompativel"),
    # bucha em conjunto com parafuso não é a bucha
    ("BUCHA DE NYLON SEM ABA S6", "BUCHA DE NYLON TIPO S6 COM PARAFUSO PHILIPS", "incompativel"),
    # cimento: tipo, adição e classe
    ("CIMENTO PORTLAND COMPOSTO CPIIE32 - SACO C/50KG",
     "CIMENTO BRANCO, TIPO CIMENTO PORTLAND, COR BRANCA 50KG", "incompativel"),
    ("CIMENTO PORTLAND COMPOSTO CPIIE32 - SACO C/50KG", "CIMENTO PORTLAND CP II-E-32 SACO 50 KG", "equivalente"),
    ("CIMENTO PORTLAND COMPOSTO CPIIE32 - SACO C/50KG", "CIMENTO CP II F 32 50KG", "incompativel"),
    ("CIMENTO PORTLAND COMPOSTO CPIIE32 - SACO C/50KG", "CIMENTO PORTLAND 50KG", "similar"),
    # fita: medida nominal com folga, largura diferente sai
    ("FITA CREPE ROLO DE 25 MM X 50 M", "FITA CREPE 24 X 50", "equivalente"),
    ("FITA CREPE ROLO DE 25 MM X 50 M", "FITA CREPE - 48 X 50", "incompativel"),
    # cor: só a divergência declarada pesa
    ("SACO PARA LIXO 100 LITROS PRETO", "Saco Plástico Lixo capacidade: 100 L, cor: branca", "incompativel"),
    ("SACO PARA LIXO 100 LITROS PRETO", "SACO DE LIXO 100LTS PRETO PC C/100 UNID", "equivalente"),
    ("CANETA ESFEROGRÁFICA AZUL", "Caneta Esferográfica cor tinta: preta", "incompativel"),
    ("CANETA ESFEROGRÁFICA AZUL", "Caneta Esferográfica cor tinta: azul, material: plástico", "equivalente"),
    ("CANETA ESFEROGRÁFICA AZUL", "Caneta Esferográfica personalizada conforme modelo, cor tinta: azul",
     "incompativel"),
    ("CANETA ESFEROGRÁFICA AZUL", "Caneta Esferográfica retrátil, 1.0 mm, personalizada, cor tinta: azul",
     "incompativel"),
    # o lacre personalizado do garrafão não é produto personalizado
    ("ÁGUA MINERAL GARRAFÃO 20 LITROS (RECARGA)",
     "ÁGUA MINERAL NATURAL – ACONDICIONADA EM EMBALAGEM RETORNÁVEL (GARRAFÃO) DE 20 LITROS, "
     "COM LACRE DE SEGURANÇA PERSONALIZADO PELO FABRICANTE", "equivalente"),
    # caneta indicador laser não é caneta esferográfica
    ("CANETA ESFEROGRÁFICA AZUL", "Caneta - Indicador material: alumínio, tipo indicador: laser",
     "incompativel"),
])
def test_rodada_2_especificacoes_do_lote_real(item, fonte, classe):
    r = equivalencia.classificar(item, fonte, semelhanca=Decimal("0.5"))
    assert r is not None and r.classe == classe, r and r.explicacao


def test_cor_calada_na_fonte_nao_tira_a_elegibilidade():
    # o catálogo omite a cor em muita descrição: sem divergência, nada muda
    assert equivalencia.classificar("CANETA ESFEROGRÁFICA AZUL",
                                    "Caneta Esferográfica material: plástico, 1 carga",
                                    semelhanca=Decimal("0.5")) is None


def test_desfecho_do_lote_e_honesto(monkeypatch):
    """Preço atípico à espera de decisão não conta como pronto, e série
    abaixo do mínimo é amostra curta, não dispersão."""
    from types import SimpleNamespace
    base = dict(item_id="i", modo="automatico", diagnostico="ok")
    atipico = cotacoes.ResultadoPesquisa(**base, estimativa=SimpleNamespace(
        pendencias=["1 preço(s) atípico(s) aguardam decisão"]))
    assert atipico.desfecho == "revisar_atipico" and "revisar_atipico" in cotacoes.PENDENTES
    curta = cotacoes.ResultadoPesquisa(**base, barreira_cv={
        "aprovada": False, "motivo": estatistica.CV_INDISPONIVEL, "quantidade": 1})
    assert curta.desfecho == "amostra_insuficiente"
