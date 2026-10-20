"""
G0 — reprodução dos achados P1 da engenharia reversa contra o HEAD.

Cada prova abaixo descreve um comportamento EXIGIDO pelo pacote de
implementação (docs `02_ESCOPO_PRIORIDADES.md`, `06_REGRAS_...`) e
reproduz um defeito que o dossiê comparativo apontou no código, com
`arquivo:linha` no docstring. Escritas ANTES da correção: as marcadas
`xfail(strict=True)` precisam falhar no HEAD de origem (0de2939) e passar
depois do G1 — o `strict` faz a suíte acusar se uma delas passar antes
da hora ou continuar falhando depois.

Os casos aritméticos (29,00 → 25,85 → 20,45 → 25,85) vêm das contas
conferidas em `05_OBSERVACOES_POR_JORNADA.md` (J09/J10) e já passam: são
regressão, não defeito.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.precos import cesta, estatistica, orientacao, perfil, relatorio
from src.precos import repositorio as repo
from src.precos import unidades
from src.precos.estados import EstadoItem
from tests.cotacoes_apoio import (cotacao_com_item, ligar_banco_falso, linha,
                                  referencia)

def PENDENTE_G1(funcao):
    """Era xfail(strict) no G0; corrigido no G1 — agora prova comum."""
    return funcao


def _estimar(valores, regras=estatistica.REGRAS_MEDIA_PADRAO):
    refs = [referencia(v, f"r{i}") for i, v in enumerate(valores)]
    for r in refs:
        r.valor_unitario_normalizado = r.valor_unitario_original
    return estatistica.estimar(estatistica.Cesta(selecionadas=refs),
                               regras=regras)


# ---------------------------------------------------------------------------
# Aritmética do dossiê (J09/J10) — regressão
# ---------------------------------------------------------------------------
def test_um_preco_e_provisorio_e_nao_conclui():
    est = _estimar(["29.00"])
    assert est.valor_unitario == Decimal("29.00")
    assert est.status == "INCOMPLETO"
    assert len(est.cesta.selecionadas) == 1


def test_dois_precos_media_25_85_e_dois_de_tres():
    est = _estimar(["29.00", "22.70"])
    assert est.valor_unitario == Decimal("25.85")
    assert est.status == "INCOMPLETO"


def test_tres_precos_media_20_45_desvio_amostral_e_cv():
    est = _estimar(["29.00", "22.70", "9.66"])
    assert est.valor_unitario == Decimal("20.45")
    assert est.status == "CONCLUIDO"
    e = est.estatisticas
    assert e.desvio_padrao.quantize(Decimal("0.01")) == Decimal("9.86")
    assert (e.coeficiente_variacao * 100).quantize(Decimal("0.01")) == Decimal("48.23")


def test_desconsiderar_9_66_volta_a_25_85_com_dois_de_tres(monkeypatch):
    """O BP mostrou 3/3 ✓ com só 2 no cálculo (J10). Aqui conta o considerado."""
    linhas = [linha("29.00"), linha("22.70"), linha("9.66", "rejected",
                                                    motivos=["inexequível"])]
    est = cesta.recalcular(linhas, perfil=perfil.LEI_14133,
                           regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert est.valor_unitario == Decimal("25.85")
    assert est.status == "INCOMPLETO"
    assert cesta.validas_na_cesta(linhas) == 2


def test_sem_referencia_e_sem_preco_nunca_zero():
    est = cesta.recalcular([], perfil=perfil.LEI_14133,
                           regras=estatistica.REGRAS_MEDIA_PADRAO)
    assert est.valor_unitario is None
    assert est.valor_total(Decimal("10")) is None


# ---------------------------------------------------------------------------
# Tema 1 — `warning` está na cesta e precisa contar em toda superfície
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_relatorio_completo_conta_sinalizada_como_considerada():
    """relatorio.py:452-453 — a sinalizada saía em 'desconsideradas'."""
    linhas = [linha("10.00"), linha("11.00"), linha("12.00"),
              linha("30.00", "warning")]
    item = {"id": "item-1", "numero": 1, "descricao": "PAPEL",
            "estado": "review", "estatisticas": {}}
    texto = relatorio.completo({"id": "p", "nome": "t"}, [item],
                               {"item-1": linhas})
    assert "consideradas no cálculo (4)" in texto


@PENDENTE_G1
def test_resumido_destaca_a_sinalizada_entre_os_precos():
    """relatorio.py:720 — os 'Preço 1–3' omitiam a sinalizada."""
    linhas = [linha("10.00"), linha("11.00"), linha("30.00", "warning")]
    item = {"id": "item-1", "numero": 1, "descricao": "PAPEL",
            "estado": "review", "estatisticas": {}}
    texto = relatorio.resumido({"id": "p", "nome": "t"}, [item],
                               {"item-1": linhas})
    assert "30,00" in texto


@PENDENTE_G1
def test_govbot_nao_diz_abaixo_do_minimo_com_sinalizada_na_cesta():
    """orientacao.py:114 — contava só `selected`."""
    linhas = [linha("10.00"), linha("11.00"), linha("30.00", "warning")]
    item = {"numero": 1, "estado": "review", "estatisticas": {}}
    avisos = orientacao.do_item(item, linhas, perfil.LEI_14133)
    assert not any("abaixo do mínimo" in a.texto for a in avisos)


# ---------------------------------------------------------------------------
# Tema 6 — menos de três com justificativa; memória preservada
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_confirmar_item_acrescenta_justificativa_sem_apagar_memoria(monkeypatch):
    """repositorio.py:607-608 — a justificativa SUBSTITUÍA a memória."""
    ligar_banco_falso(monkeypatch)
    pesquisa, item = cotacao_com_item()
    repo.mover_item(str(item["id"]), EstadoItem.BUSCANDO, EstadoItem.PENDENTE)
    repo.mover_item(str(item["id"]), EstadoItem.CLASSIFICANDO,
                    EstadoItem.BUSCANDO)
    repo.mover_item(str(item["id"]), EstadoItem.EM_REVISAO,
                    EstadoItem.CLASSIFICANDO,
                    justificativa="média de 3 referência(s) = 20,45")
    linha_item = repo.confirmar_item(str(item["id"]),
                                     justificativa="mantido o discrepante")
    assert "média de 3 referência(s)" in linha_item["justificativa"]
    assert "mantido o discrepante" in linha_item["justificativa"]


@PENDENTE_G1
def test_existe_caminho_para_concluir_com_menos_de_tres(monkeypatch):
    """cesta.py:119-122 + estados.py:136 — item <3 ficava PARCIAL para sempre."""
    ligar_banco_falso(monkeypatch)
    pesquisa, item = cotacao_com_item()
    repo.registrar_referencias(str(item["id"]), [
        referencia("29.00", "a", normalizada=True),
        referencia("22.70", "b", normalizada=True)])
    for r in repo.listar_referencias(str(item["id"])):
        repo.reclassificar_referencia(str(r["id"]), "selected", "escolhida")
    repo.mover_item(str(item["id"]), EstadoItem.BUSCANDO, EstadoItem.PENDENTE)
    repo.mover_item(str(item["id"]), EstadoItem.INCOMPLETO, EstadoItem.BUSCANDO)
    [item] = repo.listar_itens(str(pesquisa["id"]))
    estimativa = cesta.registrar_excecao(
        pesquisa, item, repo, perfil=perfil.LEI_14133,
        texto="Produto muito específico; só duas contratações no período.",
        fundamento="especificacao_singular", aprovador="Secretário de Administração",
        ator="u1")
    assert estimativa.concluida
    [item] = repo.listar_itens(str(pesquisa["id"]))
    assert item["estado"] == EstadoItem.EM_REVISAO.value
    assert "Secretário de Administração" in item["justificativa"]


# ---------------------------------------------------------------------------
# Tema 5c — metodologia descreve o método realmente aplicado
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_metodologia_do_relatorio_e_a_da_media_nas_pesquisas_novas():
    """relatorio.py:310-313 — descrevia 'mediana quando CV > 0,25'."""
    pesquisa = {"id": "p", "versao_regras": estatistica.REGRAS_MEDIA_PADRAO}
    texto = relatorio.completo(pesquisa, [], {})
    assert "mediana quando a série é dispersa" not in texto
    assert "média aritmética" in texto.lower()


# ---------------------------------------------------------------------------
# Tema 10a/11a — unidade inválida não desliga a normalização em silêncio
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_item_sem_unidade_valida_nao_mistura_caixa_e_unidade():
    """unidades.py:180-189 — item sem unidade mantinha o preço da fonte."""
    caixa = referencia("282.28", "cx", unidade="CAIXA")
    for unidade_do_item in ("", "Caixotes", "UNDADE"):
        ref = unidades.normalizar(referencia("282.28", "cx", unidade="CAIXA"),
                                  unidade_do_item)
        assert ref.valor_unitario_normalizado is None, unidade_do_item
    assert caixa.valor_unitario_normalizado is None


# ---------------------------------------------------------------------------
# Tema 12b — o identificador cobre o conteúdo decisório inteiro
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_identificador_muda_com_quantidade_total_ou_justificativa():
    """relatorio.py:153-164 — quantidade/justificativa fora do hash."""
    base = {"id": "i", "numero": 1, "descricao": "PAPEL", "estado": "complete",
            "metodo": "media", "preco_estimado": "20.45", "quantidade": "10",
            "preco_total": "204.50", "unidade": "RESMA", "justificativa": "x"}
    pesquisa = {"id": "p"}
    original = relatorio.identificador_da_versao(pesquisa, [base], {})
    for campo, valor in (("quantidade", "20"), ("preco_total", "409.00"),
                         ("justificativa", "y"), ("unidade", "CAIXA")):
        alterado = relatorio.identificador_da_versao(
            pesquisa, [{**base, campo: valor}], {})
        assert alterado != original, campo


# ---------------------------------------------------------------------------
# Tema 2/3 — percentual gravado e critério percentual configurável
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_distancia_da_mediana_e_gravada_na_memoria():
    """estatistica.py:341-345 — o percentual não era gravado."""
    est = _estimar(["10", "10.5", "11", "10.2", "50"])
    [anomalia] = est.para_relatorio()["anomalias"]
    assert anomalia["distancia_da_mediana_pct"] is not None


@PENDENTE_G1
def test_criterio_percentual_reproduz_42_56_com_tres_precos():
    """IQR/MAD não analisa n=3 (estatistica.py:162). O critério percentual
    configurável, separado do detector, sinaliza 9,66 = 42,56% da média
    dos outros sem os elevados — sem excluir nada."""
    marcas = estatistica.analise_percentual(
        [Decimal("29.00"), Decimal("9.66"), Decimal("22.70")],
        elevado_pct=Decimal("30"), inexequivel_pct=Decimal("70"))
    por_valor = {m.valor: m for m in marcas}
    assert por_valor[Decimal("9.66")].marca == "inexequivel_sinalizado"
    assert por_valor[Decimal("9.66")].percentual == Decimal("42.56")
    assert por_valor[Decimal("29.00")].marca == "elevado_sinalizado"
    assert por_valor[Decimal("22.70")].marca == "valido"


# ---------------------------------------------------------------------------
# Tema 7 — trilha de fontes e enquadramento por referência no relatório
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_relatorio_traz_trilha_de_coleta_e_enquadramento():
    """relatorio.py:405-419 — só nome, tipo bruto e contagem."""
    linhas = [linha("10.00", coletado_em="2026-10-16T13:45:00+00:00")]
    item = {"id": "item-1", "numero": 1, "descricao": "PAPEL",
            "estado": "review", "estatisticas": {},
            "desfechos": {"compras_gov_precos": "success_with_prices",
                          "pncp": "failure"}}
    texto = relatorio.completo({"id": "p"}, [item], {"item-1": linhas})
    assert "16/10/2026 13:45" in texto
    assert "INDISPONÍVEL" in texto
    assert "inciso I" in texto


# ---------------------------------------------------------------------------
# Tema 11 — importação lista TODOS os erros e não cria unidade/UF inválida
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_importacao_lista_todos_os_erros_com_linha_e_motivo():
    from io import BytesIO

    from openpyxl import Workbook

    from src.precos import importacao

    wb = Workbook()
    ws = wb.active
    ws.append(["Código", "Descrição", "Quantidade", "Unidade", "UF"])
    ws.append(["A1", "Caneta azul", "3", "UNIDADE", "PA"])
    ws.append(["A2", "", "abc", "Caixotes", "ZZ"])
    buffer = BytesIO()
    wb.save(buffer)
    diagnostico = importacao.diagnosticar(buffer.getvalue())
    motivos = " ".join(e.motivo for e in diagnostico.erros)
    assert {e.linha for e in diagnostico.erros} == {3}
    assert "descrição" in motivos and "quantidade" in motivos
    assert "Caixotes" in motivos and "ZZ" in motivos
    assert len(diagnostico.validos) == 1


# ---------------------------------------------------------------------------
# F100 — fórmula por referência sobre propostas REAIS (J08)
# ---------------------------------------------------------------------------
@PENDENTE_G1
def test_formulas_da_referencia_conferem_com_j08():
    from src.precos import formulas

    finais = [Decimal(v) for v in ("29.00", "29.99", "30.00", "30.00",
                                   "33.00", "33.02", "33.02", "33.02",
                                   "33.02")]
    assert formulas.calcular("mediana_3_melhores", finais) == Decimal("29.99")
    assert formulas.calcular("media", finais) == Decimal("31.56")
    assert formulas.calcular("menor", finais) == Decimal("29.00")
