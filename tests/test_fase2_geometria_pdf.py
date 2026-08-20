"""
Fase 2 — nenhum texto fora da folha.

Defeito registrado no diagnóstico: spans com borda direita em 598,1 e
602,7 pt numa página A4 de 595,3 pt — texto fora do PAPEL, não apenas da
margem. A causa é a mecânica de cursor do fpdf2: `multi_cell` deixa, por
padrão, o cursor à DIREITA da célula e na mesma linha; dois parágrafos
consecutivos sem linha em branco entre eles faziam o segundo começar na
borda direita e escorrer para fora da página.

O gate mínimo e obrigatório aqui é um só: **nenhum span com x1 além da
largura física da página**. A área útil é medida à parte, e de forma
tolerante, para não reprovar cabeçalho, rodapé e timbrado — que ocupam
legitimamente a faixa de margem.
"""

import json
import shutil
from pathlib import Path

import pytest

from src import export, llm, planilha

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"

# Tolerância de meio ponto: o PDF guarda coordenadas em float e a
# medição de um glifo na borda exata da caixa oscila na última casa.
# Meio ponto é ~0,18 mm — menor que qualquer estouro real e maior que
# qualquer ruído de arredondamento.
TOLERANCIA_PT = 0.5

# Na BORDA DA ÁREA ÚTIL a tolerância precisa ser maior, e por um motivo
# tipográfico, não por conveniência: a caixa do glifo passa da largura de
# avanço em itálico e em linha justificada. Medido neste corpus (DFD, ETP
# e TR do caso de 210 itens): 3,09 a 3,14 pt, sempre em linha justificada
# encostada na margem. 1,5 mm cobre isso com folga e continua duas ordens
# de grandeza abaixo de um estouro real — os spans do defeito original
# ultrapassavam a própria FOLHA em 2,8 a 7,4 pt.
TOLERANCIA_AREA_UTIL_PT = 1.5 / 25.4 * 72

pymupdf = pytest.importorskip("pymupdf",
                              reason="prova de geometria exige PyMuPDF")


@pytest.fixture(scope="module")
def dados():
    caso = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return {
        "orgao": "Prefeitura Municipal de Ensaio",
        "objeto": caso["objeto"],
        "responsavel": "Maria Souza Lima",
        "justificativa": "Reposição do estoque de material de expediente.",
        "alinhamento": "PCA 2026, item 14.",
        "requisitos": "Conformidade com as especificações do anexo.",
        "modelo_execucao": "Sistema de Registro de Preços (SRP)",
        "itens": caso["itens"],
    }


@pytest.fixture(scope="module")
def documentos(dados):
    docs = {k: planilha.injetar_tabela(llm._gerar_demo(k, dados),
                                       dados["itens"])
            for k in ("dfd", "etp", "tr")}
    for k in ("edital", "arp"):
        docs[k] = planilha.injetar_tabela(
            llm.gerar_instrumento_oficial(k, dados), dados["itens"])
    return docs


def _spans_fora_da_folha(pdf_bytes: bytes) -> tuple[int, float, float, list]:
    """(páginas, largura da folha, maior x1, spans fora da folha)."""
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    maior = 0.0
    fora = []
    largura = doc[0].rect.width if doc.page_count else 0.0
    for numero, pagina in enumerate(doc, start=1):
        limite = pagina.rect.width
        for bloco in pagina.get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                for span in linha["spans"]:
                    x1 = span["bbox"][2]
                    maior = max(maior, x1)
                    if x1 > limite + TOLERANCIA_PT:
                        fora.append((numero, round(x1, 1),
                                     span["text"][:60]))
    return doc.page_count, largura, maior, fora


def _sem_libreoffice():
    return export.motor_pdf() != "libreoffice"


sem_lo = pytest.mark.skipif(
    _sem_libreoffice(),
    reason=("motor de PDF efetivo não é o LibreOffice neste ambiente "
            "(a conversão DOCX→PDF não roda); a prova sobre o PDF "
            "institucional real não pode ser executada"))


# ---------------------------------------------------------------------------
# Controle positivo: a prova sabe reprovar
# ---------------------------------------------------------------------------
def test_a_medicao_reprova_um_pdf_deliberadamente_estourado():
    """
    Sem isto, todos os testes abaixo poderiam estar passando por não
    medir nada. Aqui um span é escrito de propósito para fora da folha e
    a medição precisa apontá-lo.
    """
    from fpdf import FPDF

    pdf = FPDF(format="A4", unit="pt")
    pdf.add_page()
    pdf.set_font("Times", "", 12)
    pdf.set_xy(pdf.w - 40, 100)          # começa a 40 pt da borda direita
    pdf.cell(300, 14, "texto que sai da folha", new_x="LMARGIN", new_y="NEXT")
    _, largura, maior, fora = _spans_fora_da_folha(bytes(pdf.output()))
    assert fora, "a medição deveria ter apontado o span fora da folha"
    assert maior > largura


# ---------------------------------------------------------------------------
# O gate: nenhum texto fora da folha
# ---------------------------------------------------------------------------
@sem_lo
def test_documento_individual_nao_tem_texto_fora_da_folha(documentos):
    paginas, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf("Documento de Formalização da Demanda",
                         documentos["dfd"], None))
    assert paginas > 1
    assert fora == [], (f"{len(fora)} span(s) fora da folha de "
                        f"{largura:.1f} pt; maior x1 = {maior:.1f} pt: "
                        f"{fora[:5]}")


@sem_lo
def test_dossie_consolidado_nao_tem_texto_fora_da_folha(documentos, dados):
    paginas, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf_consolidado(documentos, None, dados))
    assert paginas > 10
    assert fora == [], (f"{len(fora)} span(s) fora da folha de "
                        f"{largura:.1f} pt; maior x1 = {maior:.1f} pt: "
                        f"{fora[:5]}")


@sem_lo
def test_timbrado_nao_empurra_texto_para_fora_da_folha(documentos):
    """Cabeçalho, rodapé longo e marca d'água ocupam a margem — não a folha."""
    branding = {
        "orgao": "Prefeitura Municipal de Ensaio",
        "nome": "Secretaria Municipal de Administração e Planejamento",
        "cabecalho": "PREFEITURA MUNICIPAL DE ENSAIO — SECRETARIA DE "
                     "ADMINISTRAÇÃO E PLANEJAMENTO INSTITUCIONAL",
        "rodape": "Rua das Palmeiras, 1000 — Centro — CEP 00000-000 — "
                  "Tel. (00) 0000-0000 — www.exemplo.gov.br",
        "marca_dagua": "MINUTA",
    }
    _, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf("Termo de Referência", documentos["tr"], branding))
    assert fora == [], (f"maior x1 = {maior:.1f} pt em folha de "
                        f"{largura:.1f} pt: {fora[:5]}")


# ---------------------------------------------------------------------------
# O renderizador próprio (fpdf2) — é NELE que o defeito vivia
# ---------------------------------------------------------------------------
def test_renderizador_fpdf2_nao_joga_texto_para_fora_da_folha(
        documentos, monkeypatch):
    """
    Roda SEMPRE, com ou sem LibreOffice: o fpdf2 é o caminho que produz o
    arquivo quando a conversão não está disponível, e era ele quem punha
    span em 598,1 e 602,7 pt. Forçado aqui pela recusa da conversão.
    """
    monkeypatch.setattr(export, "_docx_em_pdf", lambda _b: None)
    _, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf("Documento de Formalização da Demanda",
                         documentos["dfd"], None))
    assert fora == [], (f"{len(fora)} span(s) fora da folha de "
                        f"{largura:.1f} pt; maior x1 = {maior:.1f} pt: "
                        f"{fora[:5]}")


def test_paragrafos_coladas_nao_escorrem_para_a_borda(monkeypatch):
    """
    A forma EXATA do defeito: parágrafos consecutivos sem linha em branco
    entre eles. Sem `new_x='LMARGIN'` o segundo começava na borda direita.
    """
    monkeypatch.setattr(export, "_docx_em_pdf", lambda _b: None)
    texto = "## 1. OBJETO\n" + "".join(
        f"1.{i}. Cláusula de teste com texto suficientemente longo para "
        f"ocupar a linha inteira e forçar a quebra do parágrafo.\n"
        for i in range(1, 25))
    _, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf("Teste", texto, None))
    assert fora == [], f"maior x1 = {maior:.1f} em folha de {largura:.1f}"
    assert maior <= largura, (maior, largura)


# ---------------------------------------------------------------------------
# Área útil — medida à parte, sem reprovar timbrado legítimo
# ---------------------------------------------------------------------------
@sem_lo
def test_corpo_do_texto_respeita_a_margem_institucional(documentos):
    """
    O corpo fica dentro da margem de 2 cm. Cabeçalho e rodapé ocupam a
    faixa de margem por definição e por isso são medidos pela FOLHA, não
    pela área útil — reprová-los seria falso positivo.
    """
    margem_pt = 2.0 / 2.54 * 72          # 2 cm em pontos
    doc = pymupdf.open(
        stream=export.gerar_pdf("Estudo Técnico Preliminar",
                                documentos["etp"], None),
        filetype="pdf")
    excedentes = []
    for numero, pagina in enumerate(doc, start=1):
        altura, limite = pagina.rect.height, pagina.rect.width - margem_pt
        for bloco in pagina.get_text("dict")["blocks"]:
            for linha in bloco.get("lines", []):
                for span in linha["spans"]:
                    y0 = span["bbox"][1]
                    if y0 < margem_pt or y0 > altura - margem_pt:
                        continue          # faixa de cabeçalho/rodapé
                    if span["bbox"][2] > limite + TOLERANCIA_AREA_UTIL_PT:
                        excedentes.append((numero, round(span["bbox"][2], 1),
                                           span["text"][:50]))
    # A tabela da planilha usa a largura útil inteira; o corpo de prosa
    # não pode ultrapassá-la além do transbordo tipográfico do glifo.
    assert excedentes == [], excedentes[:5]


# ---------------------------------------------------------------------------
# H. a tabela continua íntegra e legível depois da correção de geometria
# ---------------------------------------------------------------------------
def test_tabela_permanece_integra_no_documento(documentos, dados):
    texto = documentos["dfd"]
    assert len(planilha.linhas_de_itens_do_texto(texto)) == 210
    assert texto.count("| Código | Descrição") == 1
    assert planilha.conferir_tabela(texto, dados["itens"]) == []
    assert "R$ 8.024.834,67" in texto


@sem_lo
def test_docx_mantem_larguras_proporcionais_e_cabecalho_repetido(documentos):
    """
    A largura proporcional veio da integração do padrão ouro: sem ela a
    Descrição recebia a mesma fatia de 'Unidade' e o texto quebrava a cada
    poucos caracteres. Não pode ter sido sacrificada para corrigir o
    overflow.
    """
    import io

    from docx import Document
    from docx.shared import Cm

    doc = Document(io.BytesIO(
        export.gerar_docx("Documento de Formalização da Demanda",
                          documentos["dfd"], None)))
    tabelas = [t for t in doc.tables if len(t.rows) > 50]
    assert tabelas, "a planilha de 210 itens deveria estar em tabela"
    tabela = tabelas[0]

    larguras = [c.width for c in tabela.rows[0].cells]
    assert all(w for w in larguras), "toda coluna precisa de largura explícita"
    assert len(set(larguras)) > 1, "colunas com largura idêntica: proporção perdida"
    descricao = larguras[1]
    assert descricao == max(larguras), "Descrição deveria ser a coluna mais larga"

    util = Cm(21.0 - 2.0 - 2.0)
    assert sum(larguras) <= util * 1.02, "a tabela excede a largura útil da folha"

    # cabeçalho repetido em cada página da tabela
    from docx.oxml.ns import qn
    tr_pr = tabela.rows[0]._tr.find(qn("w:trPr"))
    assert tr_pr is not None and tr_pr.find(qn("w:tblHeader")) is not None, \
        "a primeira linha deveria repetir como cabeçalho entre páginas"


@sem_lo
def test_nenhuma_celula_da_tabela_sai_da_folha(documentos):
    """No PDF real: as ~150 páginas de tabela também respeitam a folha."""
    _, largura, maior, fora = _spans_fora_da_folha(
        export.gerar_pdf("Documento de Formalização da Demanda",
                         documentos["dfd"], None))
    assert fora == [], fora[:5]
    assert maior <= largura
