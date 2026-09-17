"""
Ingestão: o que foi lido, o que não foi, e a diferença entre as duas.

A prova central aqui é `test_pdf_de_imagem_nao_vira_secretaria_sem_pedido`.
Dos doze arquivos reais, dois (SECULT e SEMEL) são digitalizações sem
camada de texto. Se eles entrassem como extração vazia, a tabela
consolidada diria que aquelas secretarias não pediram nada — uma
afirmação falsa, e pior do que um erro visível, porque ninguém revisa
uma linha que parece decidida.
"""

from __future__ import annotations

import io

import pytest

from src.demanda import ingestao
from src.demanda.consolidacao import ILEGIVEL, IMAGEM, LIDO


def _pdf(texto: str = "", paginas: int = 1) -> bytes:
    """PDF de verdade, gerado na hora — não um arquivo fixo no disco."""
    import pymupdf

    doc = pymupdf.open()
    for _ in range(paginas):
        pagina = doc.new_page()
        if texto:
            pagina.insert_textbox(pymupdf.Rect(40, 40, 560, 780), texto,
                                  fontsize=9)
    dados = doc.tobytes()
    doc.close()
    return dados


QUADRO = (
    "DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº 20260101001\n"
    "ÓRGÃO :\n"
    "05  Secretaria de Teste\n"
    "Código Quant Unidade Descrição\n"
    "370614 ENVELOPE AMARELO 260MMX360MM 50,0000 UNIDADE\n"
    "133975 PAPEL VERGE CORES VARIADAS 30,0000 PACOTE\n"
)


def test_le_um_pdf_com_quadro():
    origem = ingestao.ler("dfd.pdf", _pdf(QUADRO))

    assert origem.status == LIDO
    assert len(origem.dfds) == 1
    assert len(origem.dfds[0].itens) == 2


def test_a_secretaria_sai_do_orgao_declarado_no_documento():
    """§6: nunca do nome do arquivo."""
    origem = ingestao.ler("qualquer_nome_sem_sigla.pdf", _pdf(QUADRO))

    assert "Secretaria de Teste" in origem.secretaria


def test_o_rotulo_informado_pelo_servidor_prevalece():
    """
    Quem confere pode corrigir o rótulo. A correção vale mais que o que
    está escrito no documento — é ela que o §13 chama de intervenção
    humana auditável.
    """
    origem = ingestao.ler("dfd.pdf", _pdf(QUADRO), secretaria="SEMEC")

    assert origem.secretaria == "SEMEC"


def test_pdf_de_imagem_nao_vira_secretaria_sem_pedido():
    """
    O caso de SECULT e SEMEL. Status próprio, não extração vazia: a
    diferença entre "ninguém leu" e "não pediram nada".
    """
    origem = ingestao.ler("digitalizado.pdf", _pdf(paginas=3))

    assert origem.status == IMAGEM
    assert origem.dfds == ()


def test_pdf_de_imagem_ainda_assim_tem_impressao_digital():
    """
    Sem hash, o mesmo arquivo ilegível reenviado dez vezes viraria dez
    avisos iguais na tela.
    """
    origem = ingestao.ler("digitalizado.pdf", _pdf(paginas=3))

    assert len(origem.hash_arquivo) == 64


def test_o_mesmo_arquivo_tem_sempre_a_mesma_impressao():
    dados = _pdf(QUADRO)

    assert ingestao.impressao_digital(dados) == ingestao.impressao_digital(dados)
    assert ingestao.impressao_digital(dados) != ingestao.impressao_digital(b"outro")


def test_arquivo_vazio_nao_explode():
    origem = ingestao.ler("vazio.pdf", b"")

    assert origem.status == ILEGIVEL


def test_formato_nao_suportado_diz_qual_e():
    with pytest.raises(ingestao.ErroIngestao) as erro:
        ingestao.ler("planilha.xlsx", b"conteudo")

    assert "xlsx" in str(erro.value)


def test_pdf_corrompido_vira_erro_explicado_e_nao_traceback():
    with pytest.raises(ingestao.ErroIngestao) as erro:
        ingestao.ler("quebrado.pdf", b"isto nao e um pdf")

    assert "corrompido" in str(erro.value).lower()


def test_pdf_legivel_sem_quadro_nenhum_nao_e_dado_como_lido():
    """
    Texto existe, mas não há DFD. Marcar como lido faria a secretaria
    entrar na consolidação com zero itens e ninguém investigaria.
    """
    origem = ingestao.ler("oficio.pdf", _pdf("Ofício sem quadro de itens. " * 40))

    assert origem.status == ILEGIVEL
    assert origem.dfds == ()


def test_sem_orgao_no_documento_a_tela_precisa_perguntar():
    origem = ingestao.ler("sem_orgao.pdf", _pdf(
        "DOCUMENTO DE FORMALIZAÇÃO DE DEMANDA Nº 20260101001\n"
        "370614 ENVELOPE AMARELO 50,0000 UNIDADE\n"))

    assert ingestao.precisa_de_confirmacao(origem)


def test_com_orgao_a_tela_nao_precisa_perguntar():
    origem = ingestao.ler("dfd.pdf", _pdf(QUADRO))

    assert not ingestao.precisa_de_confirmacao(origem)


def test_arquivo_de_imagem_nao_pede_confirmacao_de_secretaria():
    """
    Pedir para confirmar a secretaria de um arquivo que ninguém leu
    seria pedir uma decisão sobre nada.
    """
    origem = ingestao.ler("digitalizado.pdf", _pdf(paginas=3))

    assert not ingestao.precisa_de_confirmacao(origem)
