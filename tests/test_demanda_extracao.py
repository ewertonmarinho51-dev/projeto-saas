"""
Extração dos Documentos de Formalização de Demanda.

As fixtures são trechos VERBATIM dos arquivos reais de doze secretarias
de Paragominas. Não foram estilizadas: os erros de digitação
("Planemjamento", "Adminstração") estão lá porque estão no original, e
um parser que só funcione com texto limpo não serve para o que chega.

Três fatos dos arquivos reais moldaram tudo o que está aqui:

1. O documento NÃO se chama "Solicitação de Despesa". Internamente é
   `DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº`, com órgão codificado no
   cabeçalho. O nome do arquivo é rótulo externo, e o §6 proíbe deduzir
   secretaria a partir dele.

2. Um arquivo pode conter VÁRIOS DFDs. SEMEC traz dois; SEMS, quatro.
   Não são reimpressões: para o mesmo código as quantidades divergem
   (2.000 contra 10.000). Tratar arquivo como unidade de ingestão
   perderia metade da demanda do SEMEC.

3. Existem dois layouts de quadro, e dois arquivos são imagem pura.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from src.demanda import extracao

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "demanda"


def _texto(nome: str) -> str:
    return (FIXTURES / nome).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Cabeçalho: quem está pedindo
# ---------------------------------------------------------------------------
def test_le_o_numero_do_dfd_e_o_orgao():
    dfds = extracao.extrair_do_texto(_texto("layout_a_seplan.txt"))

    assert len(dfds) == 1
    dfd = dfds[0]
    assert dfd.numero == "20260511004"
    assert dfd.orgao_codigo == "05"
    assert "Planejamento" in dfd.orgao_nome


def test_o_orgao_sai_do_conteudo_e_nao_do_nome_do_arquivo():
    """
    §6: não inferir secretaria pelo nome do arquivo. A prova é que o
    texto sozinho — sem nome de arquivo nenhum — já identifica o órgão.
    """
    dfds = extracao.extrair_do_texto(_texto("layout_b_semafi.txt"))

    assert dfds[0].orgao_codigo == "06"
    assert dfds[0].orgao_nome


# ---------------------------------------------------------------------------
# Os dois layouts
# ---------------------------------------------------------------------------
def test_layout_a_quantidade_e_unidade_na_mesma_linha():
    """SEPLAN: tem coluna `Vl. Estimado` e junta quantidade com unidade."""
    dfd = extracao.extrair_do_texto(_texto("layout_a_seplan.txt"))[0]

    primeiro = dfd.itens[0]
    assert primeiro.codigo == "370614"
    assert primeiro.descricao == "ENVELOPE AMARELO 260MMX360MM"
    assert primeiro.quantidade == Decimal("50")
    assert primeiro.unidade == "UNIDADE"


def test_layout_b_quantidade_e_unidade_em_linhas_separadas():
    """SEMAFI e outros oito: sem coluna de valor, campos em linhas próprias."""
    dfd = extracao.extrair_do_texto(_texto("layout_b_semafi.txt"))[0]

    assert dfd.itens, "nenhum item extraído do layout B"
    assert all(i.unidade for i in dfd.itens)
    assert all(i.quantidade > 0 for i in dfd.itens)
    # Nenhuma unidade pode ter vindo grudada com número: seria o layout A
    # lido errado, e a unidade viraria "50,0000 UNIDADE".
    assert not any("," in i.unidade for i in dfd.itens)


def test_a_descricao_de_varias_linhas_vira_uma_so():
    """
    "MARCA TEXTO ... A BASE DE AGUA SECAGEM" + "RAPIDA" são duas linhas
    no PDF e um item só. Quebrar ali criaria um item fantasma sem código.
    """
    dfd = extracao.extrair_do_texto(_texto("layout_a_seplan.txt"))[0]

    marca = next(i for i in dfd.itens if i.codigo == "249002")
    assert "SECAGEM RAPIDA" in marca.descricao


def test_a_especificacao_e_capturada_quando_existe():
    dfd = extracao.extrair_do_texto(_texto("layout_a_seplan.txt"))[0]

    fita = next(i for i in dfd.itens if i.codigo == "372860")
    assert fita.especificacao
    assert "celulose" in fita.especificacao

    envelope = next(i for i in dfd.itens if i.codigo == "370614")
    assert envelope.especificacao is None


# ---------------------------------------------------------------------------
# Vários DFDs no mesmo arquivo
# ---------------------------------------------------------------------------
def test_um_arquivo_pode_conter_varios_dfds():
    """
    O caso do SEMS. Se isto voltar a devolver 1, metade da demanda some
    sem ninguém ver — e a soma final fica menor que a real.
    """
    dfds = extracao.extrair_do_texto(_texto("multi_dfd_sems.txt"))

    assert len(dfds) == 2
    assert dfds[0].numero != dfds[1].numero


def test_cada_item_sabe_de_qual_dfd_veio():
    """Rastreabilidade do §12 começa aqui: item sem origem não se audita."""
    dfds = extracao.extrair_do_texto(_texto("multi_dfd_sems.txt"))

    for dfd in dfds:
        assert all(i.dfd == dfd.numero for i in dfd.itens)


def test_codigo_repetido_entre_dfds_nao_e_duplicata():
    """
    O mesmo código aparece nos dois DFDs com quantidades DIFERENTES.
    São demandas distintas da mesma secretaria; descartar a segunda como
    duplicata apagaria demanda real.
    """
    dfds = extracao.extrair_do_texto(_texto("multi_dfd_sems.txt"))
    a = {i.codigo: i.quantidade for i in dfds[0].itens}
    b = {i.codigo: i.quantidade for i in dfds[1].itens}

    comuns = set(a) & set(b)
    assert comuns, "as fixtures deveriam compartilhar códigos"
    assert any(a[c] != b[c] for c in comuns)


# ---------------------------------------------------------------------------
# Números
# ---------------------------------------------------------------------------
def test_quantidade_e_decimal_e_nao_float():
    """
    Quantidade entra em soma que precisa fechar exatamente. `float`
    transforma 0,1 + 0,2 em 0,30000000000000004, e o §12 exige que o
    total feche — não que fique perto.
    """
    dfd = extracao.extrair_do_texto(_texto("layout_a_seplan.txt"))[0]

    assert all(isinstance(i.quantidade, Decimal) for i in dfd.itens)


def test_o_decimal_brasileiro_e_lido_certo():
    """`1.500,0000` é mil e quinhentos, não um e meio."""
    assert extracao.numero("1.500,0000") == Decimal("1500")
    assert extracao.numero("50,0000") == Decimal("50")
    assert extracao.numero("0,5000") == Decimal("0.5")


@pytest.mark.parametrize("entrada", ["", "   ", None, "abc", "—"])
def test_numero_invalido_nao_vira_zero_silencioso(entrada):
    """
    Zero é uma quantidade legítima. Converter lixo em zero faria um item
    ilegível virar "pediram nenhum" — e ninguém revisaria.
    """
    with pytest.raises(extracao.ErroExtracao):
        extracao.numero(entrada)


# ---------------------------------------------------------------------------
# O que o parser NÃO pode fazer
# ---------------------------------------------------------------------------
def test_nao_inventa_item_em_texto_sem_quadro():
    """Ofício sem tabela não produz item nenhum — produz zero."""
    dfds = extracao.extrair_do_texto(
        "Estado do Pará\n"
        "DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº 20260101001\n"
        "ÓRGÃO :\n01  Secretaria de Teste\n"
        "Submetemos à apreciação de Vossa Senhoria a relação do(s) item(ns).\n"
    )

    assert len(dfds) == 1
    assert dfds[0].itens == ()


def test_texto_vazio_nao_produz_dfd():
    assert extracao.extrair_do_texto("") == ()


def test_item_sem_quantidade_nao_entra_pela_metade():
    """
    Código e descrição sem quantidade não viram item com quantidade
    presumida. O item é descartado da extração e some da contagem — o
    que a conferência humana enxerga, porque o total não fecha.
    """
    dfds = extracao.extrair_do_texto(
        "DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº 20260101001\n"
        "ÓRGÃO :\n01  Secretaria de Teste\n"
        "Código\nQuant Unidade\nDescrição\n"
        "123456\nITEM SEM QUANTIDADE NENHUMA\n"
    )

    assert dfds[0].itens == ()
