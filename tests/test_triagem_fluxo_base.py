"""
Fluxo base da triagem (13/11/2026).

* O corte das buscas correntes é o DIA DA EXECUÇÃO, não a data-base gravada
  na criação da cotação; a janela efetiva vai para a trilha.
* A mesma regra de compatibilidade de OBJETO vale no automático e no "Pôr na
  cesta": analisador de hematologia e locação mensal não compõem a cesta de
  compra de analisador bioquímico.
* Pendência de especificação e de CV aparece em "Para conferência"
  (`manual_review`), com o motivo.

Banco falso e fontes dublês. Nada de rede nem IA.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src import db, governanca
from src.precos import cotacoes, equivalencia
from src.precos import repositorio as repo
from src.precos.modelo import Fonte, NaturezaValor, Referencia
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX
from src.precos.fontes import Capacidade, ResultadoBusca

PNCP = Fonte("pncp", "PNCP — Portal Nacional de Contratações Públicas",
             "sistema_oficial")
ANALISADOR = {"descricao": "Analisador bioquímico", "unidade": "UNIDADE",
              "quantidade": "1"}
EXECUCAO = date(2026, 11, 13)


class _FonteFalsa:
    """Fonte de preço dublê que anota a consulta (o período pedido)."""

    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    def __init__(self, fonte, referencias):
        self.fonte = fonte
        self._referencias = referencias
        self.consultas = []

    def pesquisar(self, consulta):
        self.consultas.append(consulta)
        return ResultadoBusca(fonte=self.fonte, referencias=[
            r for r in self._referencias
            if consulta.data_inicial <= r.data_resultado <= consulta.data_final])


def _ref(ident, descricao, valor, *, data=date(2026, 11, 12), unidade="UNIDADE",
         municipio="Dom Pedro", uf="MA"):
    return Referencia(
        fonte=PNCP, id_externo=ident, bruto={"id": ident, "valor": valor},
        descricao_original=descricao, unidade_original=unidade,
        quantidade_original=Decimal("1"),
        valor_unitario_original=Decimal(valor),
        natureza_valor=NaturezaValor.HOMOLOGADO, orgao="Prefeitura",
        municipio=municipio, uf=uf, data_compra=data, data_resultado=data)


def _cotacao(monkeypatch, *, data_base="2026-11-01", item=ANALISADOR):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_TETO_AUTOMATICO)
    monkeypatch.setattr(cotacoes, "hoje_da_execucao", lambda: EXECUCAO)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Analisadores", "data_base": data_base})
    i = cotacoes.salvar_item(CTX, str(c["id"]), item)
    return str(c["id"]), str(i["id"])


def _por_id(iid):
    return {l["id_externo"]: l for l in repo.listar_referencias(iid)}


# ---------------------------------------------------------------------------
# Regra de objeto, em unidade
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("fonte, unidade, conflito", [
    ("ANALISADOR HEMATOLÓGICO AUTOMÁTICO", "UNIDADE", "especificação diferente"),
    ("Analisador Automático para Hematologia", "UN", "especificação diferente"),
    ("Analisador Automatizado de Bioquímica", "MES", "objeto diferente: locação"),
    ("Locação de analisador bioquímico automático", "UNIDADE", "objeto diferente: locação"),
    ("Manutenção preventiva e corretiva do analisador bioquímico", "SERVIÇO",
     "objeto diferente: serviço"),
    ("ANALISADOR AUTOMÁTICO DE BIOQUÍMICA 620 TESTES/HORA", "UND", ""),
    ("Analisador semiautomático de bioquímica", "UNIDADE", ""),
    ("Analisador de bioquímica e hematologia", "UNIDADE", ""),
    ("Analisador hematológico e bioquímico", "UNIDADE", ""),   # o do item também
    ("Analisador semiautomático", "UNIDADE", ""),        # sem qualificador: revisão
])
def test_conflito_de_objeto_do_analisador(fonte, unidade, conflito):
    motivo = equivalencia.conflito_de_objeto(
        "Analisador bioquímico", fonte, unidade_item="UNIDADE",
        unidade_fonte=unidade)
    assert (conflito in motivo) if conflito else motivo == ""


@pytest.mark.parametrize("item, fonte, conflito", [
    ("Cimento portland composto", "CIMENTO ENDODÔNTICO", True),
    ("Cimento portland composto", "CIMENTO CP-II 32 ACONDICIONADO", False),
    ("Ar condicionado split 12000 btus", "Ar condicionado 12000 BTUs com instalação", False),
    # "manutenção" fora da cabeça da descrição não faz da compra um serviço
    ("Ar condicionado split 12000 btus",
     "Ar condicionado split 12000 BTUs inverter com manutenção na garantia", False),
    ("Eletrocardiógrafo digital", "Eletrocardiógrafo portátil 12 canais", False),
    ("Eletrocardiógrafo digital", "Manutenção de eletrocardiógrafo", True),
])
def test_conflito_de_objeto_fora_do_analisador(item, fonte, conflito):
    assert bool(equivalencia.conflito_de_objeto(item, fonte)) is conflito


def test_equivalencia_marca_incompativel_mesmo_sem_atributo_medido():
    eq = equivalencia.classificar("Analisador bioquímico",
                                  "ANALISADOR HEMATOLÓGICO")
    assert eq is not None and eq.classe == equivalencia.INCOMPATIVEL
    assert "especificação diferente" in eq.explicacao
    # o mesmo código oficial prevalece sobre a redação
    assert equivalencia.classificar("Analisador bioquímico",
                                    "ANALISADOR HEMATOLÓGICO",
                                    mesmo_codigo=True) is None


# ---------------------------------------------------------------------------
# Corte pela data da execução
# ---------------------------------------------------------------------------
def test_homologacao_posterior_a_data_base_chega_a_triagem(monkeypatch):
    """Dom Pedro/MA, R$ 8.600, homologado em 12/11 — depois da data-base
    (01/11) da cotação e antes da execução (13/11)."""
    cid, iid = _cotacao(monkeypatch)
    fonte = _FonteFalsa(PNCP, [_ref("dom-pedro", "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO",
                                    "8600")])
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual", fontes=[fonte])
    consulta = fonte.consultas[-1]
    assert consulta.data_final == EXECUCAO
    assert (consulta.data_final - consulta.data_inicial).days == 365
    assert "dom-pedro" in _por_id(iid)
    [busca] = [e["payload"] for e in repo.listar_eventos(cid)
               if e["tipo"] == "busca_concluida"]
    janela = busca["filtros"]["janela_efetiva"]
    assert janela == {"de": "2025-11-13", "ate": "2026-11-13", "dias": 365,
                      "corte": "data da execução",
                      "data_base_da_cotacao": "2026-11-01"}


def test_fora_do_periodo_a_fonte_nem_e_consultada_para_ele(monkeypatch):
    cid, iid = _cotacao(monkeypatch)
    fonte = _FonteFalsa(PNCP, [])
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            filtros={"janela_dias": 30}, fontes=[fonte])
    consulta = fonte.consultas[-1]
    assert consulta.data_inicial == date(2026, 10, 14)
    assert consulta.data_final == EXECUCAO


# ---------------------------------------------------------------------------
# Mesma compatibilidade no automático e no "Pôr na cesta"
# ---------------------------------------------------------------------------
def _coleta_do_analisador():
    return _FonteFalsa(PNCP, [
        _ref("bio-1", "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO", "8600"),
        _ref("bio-2", "Analisador semiautomático de bioquímica", "7800",
             municipio="Santa Helena de Goiás", uf="GO"),
        _ref("bio-3", "ANALISADOR BIOQUÍMICO", "12300", municipio="Careaçu", uf="MG"),
        _ref("hemato", "ANALISADOR HEMATOLÓGICO AUTOMÁTICO", "98000",
             municipio="Castanhal", uf="PA"),
        _ref("locacao", "Analisador Automatizado de Bioquímica", "12343.36",
             unidade="MES", municipio="Fortaleza", uf="CE"),
    ])


def test_automatico_tira_hematologia_e_locacao_da_serie(monkeypatch):
    cid, iid = _cotacao(monkeypatch)
    r = cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                                fontes=[_coleta_do_analisador()])
    assert r.equivalencias["incompativel"] == 2
    linhas = _por_id(iid)
    # fora da série: nem gravadas como candidatas da cesta
    for ident in ("hemato", "locacao"):
        assert linhas.get(ident, {}).get("status") in (None, "rejected"), ident


def test_cv_acima_do_limite_vai_para_conferencia_com_motivo(monkeypatch):
    """bioquímicos de R$ 8.600 e R$ 12.300: CV 25,04% — a série não fecha
    sozinha; as duas ficam em "Para conferência" (manual_review)."""
    cid, iid = _cotacao(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico",
                            fontes=[_coleta_do_analisador()])
    revisao = [l for l in _por_id(iid).values() if l["status"] == "manual_review"]
    assert {l["id_externo"] for l in revisao} >= {"bio-1", "bio-3"}
    for linha in revisao:
        assert any("coeficiente de variação" in m and "acima de 25%" in m
                   for m in linha["motivos"])
    assert repo.obter_item(iid)["preco_estimado"] is None


@pytest.mark.parametrize("ident", ["hemato", "locacao"])
def test_por_na_cesta_recusa_o_mesmo_que_o_automatico(monkeypatch, ident):
    cid, iid = _cotacao(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            fontes=[_coleta_do_analisador()])
    alvo = _por_id(iid)[ident]
    with pytest.raises(cotacoes.ErroCotacao, match="outro objeto"):
        cotacoes.alterar_status_referencia(
            CTX, cid, iid, str(alvo["id"]), incluir=True,
            motivo="o servidor tentou incluir",
            revisao_esperada=int(repo.obter_item(iid)["revisao"]))
    assert _por_id(iid)[ident]["status"] != "selected"


def test_por_na_cesta_aceita_o_compativel(monkeypatch):
    cid, iid = _cotacao(monkeypatch)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="manual",
                            fontes=[_coleta_do_analisador()])
    alvo = _por_id(iid)["bio-3"]
    cotacoes.alterar_status_referencia(
        CTX, cid, iid, str(alvo["id"]), incluir=True,
        motivo="mesmo produto e unidade",
        revisao_esperada=int(repo.obter_item(iid)["revisao"]))
    assert _por_id(iid)["bio-3"]["status"] == "selected"


def test_por_na_cesta_aceita_homologacao_posterior_a_data_base():
    """O "Pôr na cesta" usa o mesmo corte da busca: o dia da execução."""
    from datetime import timedelta

    from src.precos import decisoes
    from tests.cotacoes_apoio import linha

    hoje = date.today()
    ref = linha(8600, "candidate", descricao="ANALISADOR BIOQUÍMICO",
                data_compra=(hoje - timedelta(days=2)).isoformat())
    item = {"descricao": "Analisador bioquímico", "unidade": "UNIDADE"}
    pesquisa = {"data_base": (hoje - timedelta(days=10)).isoformat()}
    assert "janela" not in decisoes.impedimento(item, ref, pesquisa)
    velha = {**ref, "data_compra": (hoje - timedelta(days=400)).isoformat()}
    assert "janela" in decisoes.impedimento(item, velha, pesquisa)


# ---------------------------------------------------------------------------
# Referência nova no índice do PNCP reabre o pendente afetado
# ---------------------------------------------------------------------------
def _carimbar():
    """O banco real grava `criado_em = now()` no evento; o falso, não."""
    from datetime import datetime, timezone

    for evento in repo._cliente().tabelas["pesquisa_preco_eventos"]:  # noqa: SLF001
        evento.setdefault("criado_em", None)
        if not evento["criado_em"]:
            evento["criado_em"] = datetime.now(timezone.utc).isoformat()


def _pendente_com_indice(monkeypatch):
    from src.precos.pncp_indice import PNCPIndice

    cid, iid = _cotacao(monkeypatch)
    indice = PNCPIndice(lambda termos, **kw: [])
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[indice])
    _carimbar()
    assert repo.obter_item(iid)["preco_estimado"] is None     # ficou pendente
    return cid, iid, indice


def _linha_do_indice(descricao, coletado_em, vigente=True):
    return {"descricao": descricao, "coletado_em": coletado_em, "vigente": vigente}


@pytest.mark.parametrize("linhas, volta", [
    ([_linha_do_indice("ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO", "2099-01-01T00:00:00+00:00")], True),
    ([_linha_do_indice("ANALISADOR BIOQUÍMICO", "2000-01-01T00:00:00+00:00")], False),   # antiga
    ([_linha_do_indice("ANALISADOR HEMATOLÓGICO", "2099-01-01T00:00:00+00:00")], False),  # outro objeto
    ([_linha_do_indice("ANALISADOR BIOQUÍMICO", "2099-01-01T00:00:00+00:00", False)], False),
])
def test_referencia_nova_no_indice_reabre_o_pendente(monkeypatch, linhas, volta):
    cid, iid, indice = _pendente_com_indice(monkeypatch)
    assert cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[indice]) == []
    monkeypatch.setattr(repo, "buscar_indice_pncp", lambda termos, **kw: linhas)
    assert (cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[indice]) == [iid]) is volta


def test_indice_fora_nao_reabre(monkeypatch):
    cid, iid, indice = _pendente_com_indice(monkeypatch)

    def fora(termos, **kw):
        raise RuntimeError("índice fora")

    monkeypatch.setattr(repo, "buscar_indice_pncp", fora)
    assert cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[indice]) == []


def test_reaberto_uma_vez_por_atualizacao(monkeypatch):
    """Depois da nova busca, a mesma referência não reabre o item de novo."""
    from datetime import datetime, timedelta, timezone

    cid, iid, indice = _pendente_com_indice(monkeypatch)
    coletada = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(repo, "buscar_indice_pncp", lambda termos, **kw: [
        _linha_do_indice("ANALISADOR BIOQUÍMICO", coletada)])
    assert cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[indice]) == [iid]
    import time
    time.sleep(1.2)
    cotacoes.pesquisar_item(CTX, cid, iid, modo="automatico", fontes=[indice])
    _carimbar()
    assert cotacoes.recorte_do_lote(cid, modo="automatico", fontes=[indice]) == []
