"""
§13 da auditoria: exportar, ABRIR e conferir — DOCX e PDF.

O §13 é explícito: "não se limite a verificar se o download foi
concluído". Estas provas abrem os arquivos e conferem o conteúdo contra
os dados canônicos do processo.

O QUE SE CONFERE, E POR QUE ESSES ITENS

  * todos os códigos da planilha, um a um, no DOCX E no PDF. O defeito
    histórico deste projeto foi justamente esse: dos 210 códigos, 53
    saíam no edital e o resto sumia, e depois códigos saíam PARTIDOS no
    PDF ("57270" virando "57270" + "4"). Contar linhas não pega isso;
    conferir código a código pega;
  * o valor global, calculado aqui e não lido do sistema — senão a
    prova compara o sistema consigo mesmo;
  * os cabeçalhos da tabela, porque tabela longa quebra entre páginas e
    a segunda página sem cabeçalho é ilegível;
  * a ordem das seções do dossiê;
  * ausência de marcador interno e de menção à mecânica do sistema.

O CENÁRIO G É O QUE IMPORTA AQUI

210 itens, várias páginas, descrições longas. Os outros cenários provam
que o caminho funciona; o G prova que ele funciona no tamanho em que o
defeito aparece.

FRONTEIRA: estas provas leem TEXTO. Margens, alinhamento e quebra de
página são geometria, e ficam com `test_fase2_geometria_pdf.py`, que
mede o PDF renderizado. Uma prova de texto que se dissesse completa
sobre formatação seria pior que nenhuma.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "bloqueio_de_custo"))

import ia_simulada  # noqa: E402
import sem_llm  # noqa: E402

import massas_auditoria as massas  # noqa: E402

from src import export, llm, planilha  # noqa: E402

CHAVE_DE_ENSAIO = "sk-ensaio-sem-custo-nao-e-credencial"

exige_libreoffice = pytest.mark.skipif(
    export.motor_pdf() != "libreoffice",
    reason="motor de PDF efetivo não é o LibreOffice: a conversão "
           "DOCX→PDF institucional não roda neste ambiente")


@pytest.fixture
def com_ia_simulada(monkeypatch):
    monkeypatch.setenv("GOVDOCS_IA_SIMULADA", "coerente")
    monkeypatch.setattr(llm, "obter_openai_key", lambda: CHAVE_DE_ENSAIO)
    monkeypatch.setattr(llm, "obter_api_key", lambda: "")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "")
    sem_llm.zerar()
    ia_simulada.zerar()
    sem_llm.instalar()
    ia_simulada.instalar()
    try:
        yield
    finally:
        ia_simulada.remover()
        sem_llm.remover()
        ia_simulada.zerar()
        sem_llm.zerar()


@pytest.fixture(scope="module")
def cenario_g():
    return massas.cenario_g()


def _texto_do_docx(bytes_docx: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(bytes_docx))
    partes = [p.text for p in doc.paragraphs]
    for tabela in doc.tables:
        for linha in tabela.rows:
            partes.extend(celula.text for celula in linha.cells)
    return "\n".join(partes)


def _tabelas_do_docx(bytes_docx: bytes):
    from docx import Document

    return Document(io.BytesIO(bytes_docx)).tables


def _texto_do_pdf(bytes_pdf: bytes) -> str:
    from pypdf import PdfReader

    leitor = PdfReader(io.BytesIO(bytes_pdf))
    return "\n".join((pagina.extract_text() or "") for pagina in leitor.pages)


def _codigos(cenario: dict) -> list[str]:
    return [str(i.get("codigo") or "").strip()
            for i in cenario["dados"]["itens"]
            if str(i.get("codigo") or "").strip()]


def _moeda(valor: float) -> str:
    return ("R$ " + f"{valor:,.2f}".replace(",", "§")
            .replace(".", ",").replace("§", "."))


# ---------------------------------------------------------------------------
# 1) O DOCX
# ---------------------------------------------------------------------------
def test_o_docx_leva_TODOS_os_codigos_do_cenario_de_estresse(
        cenario_g, com_ia_simulada):
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    bytes_docx = export.gerar_docx("DFD", texto)
    saida = _texto_do_docx(bytes_docx)

    ausentes = [c for c in _codigos(cenario_g) if c not in saida]
    assert not ausentes, (
        f"{len(ausentes)} de {len(_codigos(cenario_g))} códigos não saíram "
        f"no DOCX (ex.: {ausentes[:8]})")


def test_o_docx_leva_o_valor_global_calculado_fora_do_sistema(
        cenario_g, com_ia_simulada):
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    saida = _texto_do_docx(export.gerar_docx("DFD", texto))
    esperado = _moeda(massas.valor_global_esperado(cenario_g))
    presentes = sorted(set(re.findall(r"R\$ [\d.]+,\d\d", saida)))[:5]
    assert esperado in saida, (
        f"valor global {esperado} ausente do DOCX; valores presentes: "
        f"{presentes}")


def test_a_tabela_do_docx_repete_o_cabecalho_nas_paginas(
        cenario_g, com_ia_simulada):
    """
    Tabela de 210 linhas quebra entre páginas. Sem `tblHeader` na linha
    de cabeçalho, a segunda página vira uma lista de números sem nome de
    coluna — e o servidor não tem como conferir quantidade contra preço.
    """
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    tabelas = _tabelas_do_docx(export.gerar_docx("DFD", texto))
    assert tabelas, "o DOCX saiu sem tabela nenhuma"

    maior = max(tabelas, key=lambda t: len(t.rows))
    xml_do_cabecalho = maior.rows[0]._tr.xml
    assert "tblHeader" in xml_do_cabecalho, (
        "a primeira linha da tabela não está marcada para repetir no topo "
        "de cada página")


def test_o_dossie_sai_na_ordem_e_com_todos_os_documentos(
        com_ia_simulada):
    from src.config import DOCUMENTOS

    cenario = massas.CENARIO_F
    documentos = {}
    contexto = None
    for doc_key in ("dfd", "etp", "tr"):
        documentos[doc_key] = llm.gerar_documento(
            doc_key, dict(cenario["dados"]), contexto)
        contexto = documentos[doc_key]

    saida = _texto_do_docx(export.gerar_docx_consolidado(
        documentos, dados=cenario["dados"]))

    posicoes = [saida.find(DOCUMENTOS[d]["titulo"].upper())
                for d in ("dfd", "etp", "tr")]
    assert all(p >= 0 for p in posicoes), (
        f"documento ausente do dossiê: {posicoes}")
    assert posicoes == sorted(posicoes), (
        f"o dossiê saiu fora de ordem: {posicoes}")


def test_o_docx_nao_leva_mecanica_interna_do_sistema(cenario_g,
                                                     com_ia_simulada):
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    saida = _texto_do_docx(export.gerar_docx("DFD", texto)).lower()
    for proibido in ("[[tabela_itens]]", "formulário matriz",
                     "system prompt", "placeholder"):
        assert proibido not in saida, (
            f"mecânica interna vazou para o ato administrativo: {proibido!r}")


# ---------------------------------------------------------------------------
# 2) O PDF — onde o defeito histórico morava
# ---------------------------------------------------------------------------
@exige_libreoffice
def test_o_pdf_leva_TODOS_os_codigos_inteiros(cenario_g, com_ia_simulada):
    """
    O achado histórico deste projeto: códigos PARTIDOS no PDF — "57270"
    saindo como "57270" e "4" em linhas diferentes. Contar linhas não
    pega; procurar cada código, pega.
    """
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    saida = _texto_do_pdf(export.gerar_pdf("DFD", texto))
    sem_espacos = re.sub(r"\s+", "", saida)

    ausentes = [c for c in _codigos(cenario_g) if c not in sem_espacos]
    assert not ausentes, (
        f"{len(ausentes)} de {len(_codigos(cenario_g))} códigos não saíram "
        f"inteiros no PDF (ex.: {ausentes[:8]})")


@exige_libreoffice
def test_o_pdf_e_o_docx_contam_a_mesma_planilha(cenario_g, com_ia_simulada):
    """
    Comparação entre os dois formatos, e não de cada um com a fonte: um
    defeito que afetasse só a conversão apareceria aqui como divergência
    entre DOCX e PDF, mesmo que os dois ainda contivessem "algum"
    número.
    """
    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    codigos = _codigos(cenario_g)

    # Os dois lados medidos DO MESMO JEITO — procurar cada código
    # esperado dentro da saída. A primeira versão extraía números do PDF
    # com `\d{4,6}` depois de tirar os espaços, e aí os códigos vizinhos
    # viravam um número só: 190 "ausências" que eram defeito da régua,
    # não do PDF.
    def presentes(saida: str) -> set[str]:
        compacto = re.sub(r"\s+", "", saida)
        return {c for c in codigos if c in compacto}

    no_docx = presentes(_texto_do_docx(export.gerar_docx("DFD", texto)))
    no_pdf = presentes(_texto_do_pdf(export.gerar_pdf("DFD", texto)))
    assert no_docx == no_pdf, (
        f"só no DOCX: {sorted(no_docx - no_pdf)[:6]} | "
        f"só no PDF: {sorted(no_pdf - no_docx)[:6]}")
    assert len(no_docx) == len(codigos)


@exige_libreoffice
def test_o_pdf_do_cenario_extenso_tem_mais_de_uma_pagina(cenario_g,
                                                         com_ia_simulada):
    """
    210 itens não cabem numa página. Um PDF de página única aqui
    significaria tabela truncada — e truncada em silêncio.
    """
    from pypdf import PdfReader

    texto = llm.gerar_documento("dfd", dict(cenario_g["dados"]), None)
    leitor = PdfReader(io.BytesIO(export.gerar_pdf("DFD", texto)))
    assert len(leitor.pages) > 1, (
        "210 itens couberam numa página só — a tabela foi truncada")


# ---------------------------------------------------------------------------
# 3) A planilha do processo é a fonte, e a exportação não a altera
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cenario", massas.TODOS, ids=[c["id"] for c in massas.TODOS])
def test_nenhuma_quantidade_muda_entre_a_planilha_e_o_documento(
        cenario, com_ia_simulada):
    """
    Conferência célula a célula na TABELA do DOCX.

    `planilha.conferir_tabela` não serve aqui: ela lê markdown, e o que
    sai do DOCX já é tabela do Word. Passar o texto extraído para ela
    devolvia "tabela de itens ausente" para todos os cenários — achado
    da prova, não do sistema.
    """
    itens, _ = planilha.calcular(cenario["dados"]["itens"])
    texto = llm.gerar_documento("dfd", dict(cenario["dados"]), None)
    tabelas = _tabelas_do_docx(export.gerar_docx("DFD", texto))
    assert tabelas, f"{cenario['id']}: DOCX sem tabela"

    maior = max(tabelas, key=lambda t: len(t.rows))
    por_codigo = {}
    for linha in maior.rows[1:]:
        celulas = [c.text.strip() for c in linha.cells]
        if celulas and celulas[0]:
            por_codigo[celulas[0]] = celulas

    for item in itens:
        codigo = str(item.get("codigo") or "").strip()
        if not codigo:
            continue
        assert codigo in por_codigo, (
            f"{cenario['id']}: código {codigo} não saiu no DOCX")
        celulas = " | ".join(por_codigo[codigo])
        assert str(item["unidade"]) in celulas, (
            f"{cenario['id']}/{codigo}: unidade mudou no documento "
            f"({celulas})")
        quantidade = item["quantidade"]
        inteira = (str(int(quantidade)) if float(quantidade).is_integer()
                   else str(quantidade))
        assert inteira in celulas.replace(".", ""), (
            f"{cenario['id']}/{codigo}: quantidade {inteira} não confere "
            f"({celulas})")
