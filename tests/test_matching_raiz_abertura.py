"""
Régua de descrição: raiz das palavras de área e nome do item na abertura
da fonte (13/11/2026).

Medido em produção: "Analisador hematológico" não achava nenhuma das três
compras de analisador hematológico do índice (0,24 / 0,24 / 0,48 contra o
piso de 0,5). Os pares abaixo são descrições REAIS do índice do PNCP.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.precos import matching
from src.precos.modelo import Fonte, NaturezaValor, Referencia

PISO = Decimal("0.5")


def _score(item: str, fonte: str, unidade: str = "UNIDADE") -> Decimal:
    ref = Referencia(
        fonte=Fonte("pncp", "PNCP", "oficial"), id_externo="x", bruto={},
        descricao_original=fonte, unidade_original=unidade,
        quantidade_original=Decimal(1), valor_unitario_original=Decimal(10),
        natureza_valor=NaturezaValor.HOMOLOGADO, data_resultado=date(2026, 10, 1),
        data_compra=date(2026, 10, 1), unidade_normalizada="UNIDADE",
        valor_unitario_normalizado=Decimal(10))
    return matching.comparar(ref, descricao=item, quantidade=Decimal(4),
                             data_base=date(2026, 11, 13), unidade="UNIDADE").score


@pytest.mark.parametrize(("palavra", "raiz"), [
    ("HEMATOLOGICO", "HEMATOLOG"), ("HEMATOLOGIA", "HEMATOLOG"),
    ("HEMATOLOGICA", "HEMATOLOG"), ("BIOQUIMICO", "BIOQUIM"),
    ("BIOQUIMICA", "BIOQUIM"), ("PLASTICOS", "PLAST"),
    # curtas, com número ou sem a terminação: ficam como estão
    ("DIARIA", "DIARIA"), ("MEDICO", "MEDICO"), ("ANALISADOR", "ANALISADOR"),
    ("50MM", "50MM"), ("SANITARIO", "SANITARIO"),
])
def test_raiz_tira_so_a_terminacao_de_area_das_palavras_longas(palavra, raiz):
    assert matching._raiz(palavra) == raiz


@pytest.mark.parametrize("fonte", [
    "Analisador Autómatico para Hematologia: Equipamento automático para rotinas "
    "hematológicas, na analise morfológica e contagem de células de sangue",
    "ANALISADOR DE HEMATOLOGIA 5 PARTES – Equipamento novo, totalmente "
    "automatizado, sem reticulócitos. Diferencial 5 partes. 27 parâmetros.",
    "ANALISADOR HEMATOLÓGICO AUTOMATIZADO 50 PARÂMETROS – Equipamento novo, "
    "totalmente automatizado, com diferencial leucocitário em 5 partes.",
])
def test_analisador_hematologico_acha_as_compras_reais_do_indice(fonte):
    assert _score("Analisador hematológico.", fonte) >= PISO


def test_bioquimico_com_adjetivo_no_meio_tambem_chega():
    fonte = ("Analisador automático bioquímico, com velocidade de pipetagem de no "
             "mínimo 180 testes fotométricos por hora ou mais")
    assert _score("Analisador bioquímico", fonte) >= PISO


@pytest.mark.parametrize(("item", "fonte"), [
    ("Analisador bioquímico", "ANALISADOR HEMATOLÓGICO AUTOMATIZADO 50 PARÂMETROS"),
    ("Analisador hematológico.", "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO"),
])
def test_hematologico_e_bioquimico_continuam_separados(item, fonte):
    assert _score(item, fonte) < PISO


@pytest.mark.parametrize(("item", "fonte", "unidade"), [
    # a palavra do item aparece, mas o produto é outro
    ("AREIA GROSSA", "Caneleira Tipo: Peso De Areia, Características Adicionais: "
     "Revestido Em Náilon Com Velcro, Peso: 2 KG", "Par"),
    ("CAIXA D'AGUA EM POLIETILENO 500 LITROS, COM TAMPA",
     "LÁPIS PRETO HB, CAIXA COM 144 UNIDADES", "CX"),
    ("JOELHO PVC ROSCAVEL, 45 GRAUS, 1\", COR BRANCA, PARA ÁGUA FRIA PREDIAL",
     "FRATURAS E/OU LUXAÇÕES AO NÍVEL DO JOELHO - TRATAMENTO CIRÚRGICO", "Unidade"),
    ("LUVA DE CORRER, PVC, DN 50MM, PARA ESGOTO PREDIAL",
     "LUVA DE PROCEDIMENTO NÃO CIRURGICO COM PÓ TAMANHO M C/100", "Caixa"),
    ("QUADRO DE DISTRIBUIÇÃO COM BARRAMENTO TRIFÁSICO, DE EMBUTIR, EM CHAPA DE ACO "
     "GALVANIZADO, PARA 18 DISJUNTORES DIN, 100 A",
     "QUADRO DE AVISO, Especificação: TIPO: NÃO MAGNÉTICO, CORTIÇA MOLDURA ALUMÍNIO",
     "UNIDADE"),
    ("TUBO PVC, SOLDÁVEL, DE 25MM, ÁGUA FRIA (NBR-5648)",
     "Tubo endotraqueal com cuff nº 7.5", "Unidade"),
])
def test_armadilhas_reais_continuam_abaixo_do_piso(item, fonte, unidade):
    assert _score(item, fonte, unidade) < PISO


def test_nome_na_abertura_exige_todas_as_palavras_do_item_no_comeco():
    assert matching._nome_na_abertura(
        "Analisador hematológico", "ANALISADOR DE HEMATOLOGIA 5 PARTES – equipamento")
    # a segunda palavra só aparece no fim: não é a abertura
    assert not matching._nome_na_abertura(
        "Analisador hematológico",
        "Analisador automatizado de bancada com tela sensível ao toque, impressora "
        "térmica e interface para rotinas hematológicas")


def test_item_de_uma_palavra_nao_usa_a_abertura():
    # genérico demais: "PAPEL" na abertura não prova papel A4
    assert not matching._nome_na_abertura("REFLETOR", "REFLETOR LED SMD 50W")
    fator = matching._fator_descricao(
        "REFLETOR", Referencia(fonte=Fonte("pncp", "PNCP", "oficial"), id_externo="x",
                               bruto={}, descricao_original="REFLETOR LED SMD 50W ATA R.P"))
    assert "começa pelo nome" not in fator.explicacao


def test_abertura_nao_chega_a_mesmo_item():
    # o atributo (medida, gramatura) continua decidindo equivalência
    from src.precos import equivalencia
    assert matching.PISO_DO_NOME_NA_ABERTURA < equivalencia.SEMELHANCA_MESMO_ITEM
    fator = matching._fator_descricao(
        "Analisador hematológico", Referencia(
            fonte=Fonte("pncp", "PNCP", "oficial"), id_externo="x", bruto={},
            descricao_original="ANALISADOR HEMATOLÓGICO AUTOMATIZADO 50 PARÂMETROS – "
                               "Equipamento novo, totalmente automatizado"))
    assert fator.score == matching.PISO_DO_NOME_NA_ABERTURA
    assert "começa pelo nome do item" in fator.explicacao
