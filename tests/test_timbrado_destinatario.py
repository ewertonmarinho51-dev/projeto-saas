"""
O timbrado do Relatório de Cotação segue o DESTINATÁRIO da pesquisa (0041).

A regra, nas palavras do dono (09/11/2026): "só sairão no timbrado de
paragominas se for direcionado para prefeitura municipal de paragominas ou a
alguma secretaria pertencente a prefeitura municipal de paragominas; se for
direcionado a outra prefeitura que não tenha ainda um timbrado salvo deverá
sair sem timbrado".

O defeito que estas provas guardam: o timbrado vinha do VÍNCULO de quem emite,
e todo usuário de produção é de Paragominas — então tudo saía com o timbrado
dela. Pesquisa sem destinatário (anterior à 0041) segue o vínculo, por decisão
do dono.

Cada prova olha o ARQUIVO (a imagem dentro do DOCX, o que vai para o PDF), não
só o dicionário escolhido: a escolha certa que não chega ao documento é o
mesmo defeito.
"""

from __future__ import annotations

import base64
import io
import zipfile

import pytest

from src import db
from src.precos import documento_cotacao as dc
from src.precos import emissao
from tests.relatorio_cotacao_apoio import cenario


def _png(cor: tuple[int, int, int]) -> str:
    from PIL import Image

    saida = io.BytesIO()
    Image.new("RGB", (800, 120), cor).save(saida, format="PNG")
    return base64.b64encode(saida.getvalue()).decode()


TIMBRADO_PGM = _png((20, 60, 120))
TIMBRADO_SEMAD = _png((120, 20, 20))

PREFEITURA = {"id": "11111111-0000-4000-8000-000000000001",
              "nome": "Prefeitura Municipal de Paragominas", "padrao": True,
              "ativo": True, "cabecalho_img": TIMBRADO_PGM}
SEMAD = {"id": "11111111-0000-4000-8000-000000000002",
         "nome": "Secretaria Municipal de Administração e Finanças",
         "padrao": False, "ativo": True, "cabecalho_img": TIMBRADO_SEMAD}
# Secretaria de Paragominas SEM timbrado próprio: herda o do município.
SEMED = {"id": "11111111-0000-4000-8000-000000000003",
         "nome": "Secretaria Municipal de Educação", "padrao": False,
         "ativo": True}
SECRETARIAS = [PREFEITURA, SEMAD, SEMED]
# De OUTRO município: nunca aparece na lista do tenant (RLS + filtro).
DE_OUTRA_PREFEITURA = "22222222-0000-4000-8000-000000000009"

PELO_VINCULO = {"nome": "VÍNCULO DE QUEM EMITE", "cabecalho_img": TIMBRADO_PGM}


@pytest.fixture
def banco(monkeypatch):
    """Secretarias do município; o vínculo de quem emite é Paragominas."""
    chamadas: list[str] = []

    def listar(incluir_inativas: bool = False):
        chamadas.append("secretarias")
        return list(SECRETARIAS)

    def vinculo():
        chamadas.append("vinculo")
        return PELO_VINCULO

    monkeypatch.setattr(db, "listar_secretarias", listar)
    monkeypatch.setattr(emissao, "marca_resolvida", vinculo)
    return chamadas


def _pesquisa(**destino) -> dict:
    p, itens, refs = cenario("minima")
    p.update(destino)
    return p, itens, refs


def _imagens(docx: bytes) -> list[bytes]:
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        return [z.read(n) for n in z.namelist() if n.startswith("word/media/")]


def _cabecalhos(docx: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        return " ".join(z.read(n).decode("utf-8") for n in z.namelist()
                        if n.startswith("word/header"))


def _docx(pesquisa, itens, refs) -> bytes:
    marca = emissao.marca_do_relatorio(pesquisa)
    conteudo, nome, _ = emissao.renderizar(
        pesquisa, itens, refs, formato="docx", tipo="cotacao",
        ciencia_doc=None, marca=marca)
    assert nome.endswith(".docx")
    return conteudo


def _bytes(b64: str) -> bytes:
    return base64.b64decode(b64)


# ---------------------------------------------------------------------------
# Os quatro destinos da regra, no DOCX
# ---------------------------------------------------------------------------
def test_prefeitura_de_paragominas_sai_com_o_timbrado_dela(banco):
    docx = _docx(*_pesquisa(destinatario_secretaria_id=PREFEITURA["id"]))
    assert _imagens(docx) == [_bytes(TIMBRADO_PGM)]
    assert "vinculo" not in banco


def test_secretaria_de_paragominas_com_timbrado_proprio_usa_o_dela(banco):
    docx = _docx(*_pesquisa(destinatario_secretaria_id=SEMAD["id"]))
    assert _imagens(docx) == [_bytes(TIMBRADO_SEMAD)]


def test_secretaria_de_paragominas_sem_timbrado_herda_o_do_municipio(banco):
    docx = _docx(*_pesquisa(destinatario_secretaria_id=SEMED["id"]))
    assert _imagens(docx) == [_bytes(TIMBRADO_PGM)]


def test_outra_prefeitura_sem_timbrado_salvo_sai_sem_timbrado(banco):
    docx = _docx(*_pesquisa(
        destinatario_externo="Prefeitura Municipal de Ulianópolis"))
    assert _imagens(docx) == []
    assert "PARAGOMINAS" not in _cabecalhos(docx).upper()
    # Nem pergunta ao vínculo: era por ele que o de Paragominas entrava.
    assert banco == []


def test_outra_prefeitura_e_dita_no_relatorio_como_o_orgao(banco):
    from tests.test_relatorio_cotacao import _texto_docx

    docx = _docx(*_pesquisa(
        destinatario_externo="  Prefeitura Municipal   de Ulianópolis "))
    assert "Prefeitura Municipal de Ulianópolis" in _texto_docx(docx)


def test_secretaria_de_outro_municipio_nao_cai_no_timbrado_de_paragominas(banco):
    # O gatilho da 0041 recusa gravar isto; se uma linha assim existir (dado
    # antigo, outro caminho de escrita), a falta de cadastro é "sem
    # timbrado", nunca o padrão do município.
    docx = _docx(*_pesquisa(destinatario_secretaria_id=DE_OUTRA_PREFEITURA))
    assert _imagens(docx) == []
    assert "vinculo" not in banco


def test_pesquisa_sem_destinatario_segue_o_vinculo(banco):
    docx = _docx(*_pesquisa())
    assert _imagens(docx) == [_bytes(TIMBRADO_PGM)]
    assert banco == ["vinculo"]


def test_secretaria_ilegivel_sai_sem_timbrado(monkeypatch, banco):
    def fora(incluir_inativas: bool = False):
        raise db.ErroBanco("banco fora")

    monkeypatch.setattr(db, "listar_secretarias", fora)
    assert emissao.marca_do_relatorio(
        {"destinatario_secretaria_id": SEMAD["id"]}) is None
    assert "vinculo" not in banco


# ---------------------------------------------------------------------------
# PDF: o mesmo timbrado vai para a conversão e para a marca d'água
# ---------------------------------------------------------------------------
@pytest.fixture
def conversor(monkeypatch):
    """O LibreOffice não roda aqui; o que importa é O QUE chega até ele."""
    recebido: dict = {}

    def em_pdf(docx, branding=None, **_):
        recebido.update(docx=docx, branding=branding)
        return b"%PDF-1.7 sintetico"

    monkeypatch.setattr(dc, "em_pdf", em_pdf)
    return recebido


@pytest.mark.parametrize("destino, imagens, com_marca", [
    ({"destinatario_secretaria_id": PREFEITURA["id"]}, [TIMBRADO_PGM], True),
    ({"destinatario_secretaria_id": SEMAD["id"]}, [TIMBRADO_SEMAD], True),
    ({"destinatario_externo": "Prefeitura Municipal de Ulianópolis"}, [], False),
])
def test_pdf_recebe_o_timbrado_do_destinatario(banco, conversor, destino,
                                               imagens, com_marca):
    pesquisa, itens, refs = _pesquisa(**destino)
    conteudo, nome, mime = emissao.renderizar(
        pesquisa, itens, refs, formato="pdf", tipo="cotacao", ciencia_doc=None,
        marca=emissao.marca_do_relatorio(pesquisa))
    assert (nome.endswith(".pdf"), mime) == (True, "application/pdf")
    assert _imagens(conversor["docx"]) == [_bytes(i) for i in imagens]
    assert (conversor["branding"] is not None) is com_marca


# ---------------------------------------------------------------------------
# Leitura do destinatário e validação do que se grava
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("linha, esperado", [
    ({}, ("legado", "")),
    ({"destinatario_secretaria_id": None, "destinatario_externo": ""},
     ("legado", "")),
    ({"destinatario_externo": "   "}, ("legado", "")),
    ({"destinatario_secretaria_id": SEMAD["id"]}, ("secretaria", SEMAD["id"])),
    ({"destinatario_externo": " Prefeitura  X "}, ("externo", "Prefeitura X")),
])
def test_destinatario_da_linha(linha, esperado):
    assert emissao.destinatario(linha) == esperado


def test_validacao_recusa_os_dois_ao_mesmo_tempo():
    from src.precos import cotacoes

    with pytest.raises(cotacoes.ErroCotacao, match="não os dois"):
        cotacoes.destinatario_validado(
            {"destinatario_secretaria_id": SEMAD["id"],
             "destinatario_externo": "Prefeitura X"}, SECRETARIAS)


def test_validacao_recusa_secretaria_de_outro_municipio():
    from src.precos import cotacoes

    with pytest.raises(cotacoes.ErroCotacao, match="não é deste município"):
        cotacoes.destinatario_validado(
            {"destinatario_secretaria_id": DE_OUTRA_PREFEITURA}, SECRETARIAS)


def test_validacao_aceita_e_normaliza():
    from src.precos import cotacoes

    assert cotacoes.destinatario_validado(
        {"destinatario_secretaria_id": SEMED["id"]}, SECRETARIAS) == (
            SEMED["id"], "")
    assert cotacoes.destinatario_validado(
        {"destinatario_externo": "  Prefeitura   X "}, SECRETARIAS) == (
            None, "Prefeitura X")
    assert cotacoes.destinatario_validado({}, SECRETARIAS) == (None, "")


def test_validacao_recusa_nome_longo_demais():
    from src.precos import cotacoes

    with pytest.raises(cotacoes.ErroCotacao, match="limite"):
        cotacoes.destinatario_validado(
            {"destinatario_externo": "x" * 201}, SECRETARIAS)


# ---------------------------------------------------------------------------
# Streamlit: a tela usa o mesmo resolvedor, com a pesquisa
# ---------------------------------------------------------------------------
def test_streamlit_tira_o_timbrado_do_destinatario(monkeypatch, banco):
    from src.ui import precos_ui

    monkeypatch.setattr(db, "disponivel", lambda: True)
    assert precos_ui._branding_da_emissao(
        {"destinatario_externo": "Prefeitura de Ulianópolis"}) is None
    assert precos_ui._branding_da_emissao(
        {"destinatario_secretaria_id": SEMAD["id"]}) is SEMAD
    assert banco == ["secretarias"]
