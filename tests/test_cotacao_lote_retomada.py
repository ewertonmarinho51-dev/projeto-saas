"""
Lote da cotação automática: desfecho por item, falha na trilha e
"Reprocessar pendentes" (cotação multiportal, PR 3, 10/11/2026).

O que estas provas guardam:

* cada item termina com UM desfecho acionável (pronto para revisão,
  revisar similaridade, revisar CV, amostra insuficiente, sem referência
  compatível, falha técnica), mais os motivos adicionais (consulta parcial);
  indisponibilidade de fonte não se confunde com pesquisa sem preço;
* a exceção de um item não fica só no retorno do lote: vai para a trilha;
* "Reprocessar pendentes" pega o item sem preço proposto, com falha ou com
  CV reprovado — nunca o concluído — e preserva a decisão de pessoa;
* reprocessar duas vezes não duplica referência (idempotência).
"""

from __future__ import annotations

from decimal import Decimal

from src.precos import cotacoes, estados, execucao
from src.precos import repositorio as repo
from src.precos.fontes import Desfecho, ResultadoBusca
from src.precos.modelo import Fonte
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacao_equivalencia import _ref
from tests.test_cotacoes_g2_servico import CTX

FONTE = Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial")
FONTE_B = Fonte("pncp", "PNCP", "contratacao_similar")


def _r(**kw):
    base = dict(item_id="i", modo="automatico", diagnostico="ok")
    return cotacoes.ResultadoPesquisa(**{**base, **kw})


# ---------------------------------------------------------------------------
# Desfecho por item
# ---------------------------------------------------------------------------
def test_desfechos_distinguiveis():
    assert _r().desfecho == "pronto_para_revisao"
    assert _r(diagnostico="fonte_indisponivel").desfecho == "falha_tecnica"
    assert _r(diagnostico="zero_resultados").desfecho == "sem_referencia_compativel"
    assert _r(diagnostico="sem_comparaveis").desfecho == "sem_referencia_compativel"
    assert _r(diagnostico="amostra_insuficiente").desfecho == "amostra_insuficiente"
    assert _r(barreira_cv={"aprovada": False}).desfecho == "revisar_cv"
    # há candidato similar à espera do servidor: a ação é revisar similaridade
    assert _r(diagnostico="sem_comparaveis",
              equivalencias={"similar": 2}).desfecho == "revisar_similaridade"
    assert _r(diagnostico="amostra_insuficiente",
              equivalencias={"similar": 1}).desfecho == "revisar_similaridade"


def test_motivos_adicionais_sem_contar_o_item_duas_vezes():
    r = _r(desfechos={"compras_gov_precos": Desfecho.COM_PRECOS.value,
                      "pncp": Desfecho.FALHA.value},
           equivalencias={"similar": 1, "equivalente": 3})
    assert r.desfecho == "pronto_para_revisao"
    assert r.motivos_extras == ["consulta_parcial", "revisar_similaridade"]
    assert set(cotacoes.PENDENTES) == set(cotacoes.DESFECHOS) - {"pronto_para_revisao"}


# ---------------------------------------------------------------------------
# Quem o "Reprocessar pendentes" pega
# ---------------------------------------------------------------------------
def test_precisa_de_reprocesso():
    r = execucao.precisa_de_reprocesso
    assert r({"estado": "pending"}) and r({"estado": "error"})
    assert r({"estado": "incomplete", "preco_estimado": None})
    assert r({"estado": "review", "preco_estimado": None})
    assert r({"estado": "review", "preco_estimado": "10",
              "estatisticas": {"barreira_cv": {"aprovada": False}}})
    assert not r({"estado": "review", "preco_estimado": "10",
                  "estatisticas": {"barreira_cv": {"aprovada": True}}})
    assert not r({"estado": "complete", "preco_estimado": None})   # aceito


# ---------------------------------------------------------------------------
# Pelo domínio
# ---------------------------------------------------------------------------
class _Fonte:
    fonte = FONTE

    def __init__(self, valores=("24.90", "25.40", "26.10"), fonte=FONTE):
        self.valores = list(valores)
        self.fonte = fonte
        self.chamadas = 0

    def pesquisar(self, consulta):
        self.chamadas += 1
        return ResultadoBusca(fonte=self.fonte, referencias=[
            _ref("PAPEL SULFITE A4 75 G/M2 500 FOLHAS", valor=v, ident=f"{self.fonte.id}{i}",
                 fonte=self.fonte)
            for i, v in enumerate(self.valores)])


ITEM = {"descricao": "papel sulfite A4 75 g/m², 500 folhas", "unidade": "RESMA",
        "quantidade": "10"}


def _cotacao(monkeypatch, n=2):
    cliente = ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Lote", "data_base": "2026-10-01"})
    itens = [cotacoes.salvar_item(CTX, str(c["id"]), {**ITEM, "descricao": f"{ITEM['descricao']}"})
             for _ in range(n)]
    return cliente, str(c["id"]), [str(i["id"]) for i in itens]


def test_falha_de_um_item_vai_para_a_trilha(monkeypatch):
    cliente, cid, (i1, i2) = _cotacao(monkeypatch)
    verdadeira = cotacoes.pesquisar_item

    def quebra_no_primeiro(ctx, cotacao_id, item_id, **kw):
        if item_id == i1:
            raise estados.TransicaoInvalida("rodada anterior interrompida")
        return verdadeira(ctx, cotacao_id, item_id, **kw)

    monkeypatch.setattr(cotacoes, "pesquisar_item", quebra_no_primeiro)
    resultados, restantes = cotacoes.pesquisar_em_lote(
        CTX, cid, modo="automatico", tamanho=5, fontes=[_Fonte()])
    assert restantes == 0
    assert {r.item_id: r.desfecho for r in resultados}[i1] == "falha_tecnica"
    falhas = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
              if e["tipo"] == "busca_falhou" and e["item_id"] == i1]
    assert falhas and falhas[0]["payload"]["desfecho"] == "falha_tecnica"
    assert "TransicaoInvalida" in falhas[0]["payload"]["erro"]
    # o outro item foi pesquisado e o desfecho também está na trilha
    feito = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
             if e["tipo"] == "busca_concluida" and e["item_id"] == i2][-1]
    assert feito["payload"]["desfecho"] == "pronto_para_revisao"


def test_reprocessar_pendentes_preserva_aceito_e_decisao_de_pessoa(monkeypatch):
    cliente, cid, (i1, i2) = _cotacao(monkeypatch)
    # primeira rodada: amostra curta (2 preços) → os dois sem preço proposto
    cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=5,
                               fontes=[_Fonte(("24.90", "25.40"))])
    assert all(execucao.precisa_de_reprocesso(repo.obter_item(i)) for i in (i1, i2))
    # o servidor concluiu i1 (aceite humano, p. ex. com cotação direta)
    next(i for i in cliente.tabelas["pesquisa_preco_itens"]
         if str(i["id"]) == i1)["estado"] = "complete"
    # e retira uma referência de i2 à mão
    ref_i2 = repo.listar_referencias(i2)[0]
    cotacoes.alterar_status_referencia(CTX, cid, i2, str(ref_i2["id"]), incluir=False,
                                       motivo="marca fora da especificação")
    # chegou fonte nova: reprocessar pendentes
    nova = _Fonte(("25.00", "25.80"), fonte=FONTE_B)
    resultados, _ = cotacoes.pesquisar_em_lote(
        CTX, cid, modo="automatico", tamanho=5, reprocessar=True,
        fontes=[_Fonte(("24.90", "25.40")), nova])
    assert [r.item_id for r in resultados] == [i2]          # i1 aceito não entra
    assert repo.obter_item(i1)["estado"] == "complete"
    retirada = next(l for l in repo.listar_referencias(i2) if l["id"] == ref_i2["id"])
    assert retirada["status"] == "rejected"                 # decisão de pessoa
    assert resultados[0].desfecho == "pronto_para_revisao"


def test_reprocessar_duas_vezes_nao_duplica_referencia(monkeypatch):
    cliente, cid, _ = _cotacao(monkeypatch, n=1)
    fonte = _Fonte(("24.90", "25.40"))
    cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=5, fontes=[fonte])
    antes = len(cliente.tabelas["pesquisa_preco_referencias"])
    for _ in range(2):
        cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=5,
                                   reprocessar=True, fontes=[fonte])
    assert len(cliente.tabelas["pesquisa_preco_referencias"]) == antes


def test_somas_do_lote_fecham(monkeypatch):
    _, cid, ids = _cotacao(monkeypatch, n=3)
    resultados, _ = cotacoes.pesquisar_em_lote(CTX, cid, modo="automatico", tamanho=10,
                                               fontes=[_Fonte()])
    desfechos = [r.desfecho for r in resultados]
    assert len(desfechos) == len(ids) == len(set(r.item_id for r in resultados))
    assert sum(1 for d in desfechos if d in cotacoes.PENDENTES) + \
        desfechos.count("pronto_para_revisao") == len(ids)
    assert all(Decimal(str(repo.obter_item(i)["preco_estimado"])) > 0 for i in ids)
