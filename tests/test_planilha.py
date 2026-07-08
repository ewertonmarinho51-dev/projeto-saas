"""Testes da planilha orçamentária (cálculo de totais e valor global)."""

import pytest

from src import planilha, prompts


def test_calcula_total_por_item_e_valor_global():
    itens = [
        {"codigo": "1", "descricao": "Notebook", "unidade": "un",
         "quantidade": 10, "valor_unitario": 4500.0},
        {"codigo": "2", "descricao": "Monitor", "unidade": "un",
         "quantidade": 10, "valor_unitario": 900.0},
    ]
    calculados, global_ = planilha.calcular(itens)
    assert calculados[0]["valor_total"] == 45000.0
    assert calculados[1]["valor_total"] == 9000.0
    assert global_ == 54000.0


def test_ignora_linhas_vazias_ou_incompletas():
    itens = [
        {"descricao": "", "quantidade": 0, "valor_unitario": 0},          # vazia
        {"descricao": "Serviço", "quantidade": 0, "valor_unitario": 0},   # sem valor
        {"descricao": "Cadeira", "quantidade": 5, "valor_unitario": 200},  # válida
    ]
    calculados, global_ = planilha.calcular(itens)
    assert len(calculados) == 1
    assert global_ == 1000.0


def test_valores_invalidos_nao_quebram():
    itens = [{"descricao": "X", "quantidade": "abc", "valor_unitario": None}]
    calculados, global_ = planilha.calcular(itens)
    assert calculados == [] and global_ == 0.0


def test_formatar_moeda_padrao_brasileiro():
    assert planilha.formatar_moeda(1234567.89) == "R$ 1.234.567,89"
    assert planilha.formatar_moeda(0) == "R$ 0,00"


def test_markdown_tem_cabecalho_itens_e_valor_global():
    itens, global_ = planilha.calcular(
        [{"descricao": "Notebook", "quantidade": 2, "valor_unitario": 5000}]
    )
    md = planilha.para_markdown(itens, global_)
    assert "| Código | Descrição |" in md
    assert "Notebook" in md
    assert "VALOR GLOBAL" in md and "R$ 10.000,00" in md


def test_prompt_inclui_a_planilha():
    dados = {
        "orgao": "Prefeitura X", "objeto": "Aquisição",
        "itens": [{"descricao": "Notebook", "quantidade": 2, "valor_unitario": 5000}],
    }
    bloco = prompts.formatar_dados_formulario(dados)
    assert "VALOR GLOBAL" in bloco and "Notebook" in bloco
    assert "R$ 10.000,00" in bloco


# ---------------------------------------------------------------------------
# Importação de XLSX
# ---------------------------------------------------------------------------
def _xlsx(linhas: list[list]) -> bytes:
    import io
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for linha in linhas:
        ws.append(linha)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_importa_xlsx_com_cabecalho_acentuado_e_moeda_br():
    dados = _xlsx([
        ["Código", "Descrição", "Unid.", "Qtd", "Valor Unitário"],
        ["001", "Notebook i5", "un", 100, "4.500,00"],
        ["002", "Monitor 24", "un", 100, 900],
        ["", "", "", "", ""],
    ])
    itens = planilha.importar_de_xlsx(dados)
    assert len(itens) == 2
    assert itens[0]["descricao"] == "Notebook i5"
    assert itens[0]["quantidade"] == 100.0 and itens[0]["valor_unitario"] == 4500.0
    _, global_ = planilha.calcular(itens)
    assert global_ == 540000.0


def test_importa_xlsx_sem_cabecalho_posicional():
    dados = _xlsx([["10", "Cadeira", "un", 5, 350.0]])
    itens = planilha.importar_de_xlsx(dados)
    assert itens[0]["descricao"] == "Cadeira" and itens[0]["quantidade"] == 5.0


def test_importa_xlsx_ordem_de_colunas_diferente():
    dados = _xlsx([
        ["Descrição", "Quantidade", "Valor unitário"],
        ["Serviço de limpeza", 12, 2500.0],
    ])
    itens = planilha.importar_de_xlsx(dados)
    assert itens[0]["descricao"] == "Serviço de limpeza"
    assert itens[0]["quantidade"] == 12.0 and itens[0]["valor_unitario"] == 2500.0


def test_importa_xlsx_invalido_da_erro():
    with pytest.raises(planilha.ErroPlanilha):
        planilha.importar_de_xlsx(b"isto nao e um xlsx")


# ---------------------------------------------------------------------------
# Colunas extras (fonte/link) e compactação de links
# ---------------------------------------------------------------------------
def test_eh_url_e_link_markdown():
    assert planilha.eh_url("https://x.com/a")
    assert planilha.eh_url("www.x.com")
    assert not planilha.eh_url("Dell")
    assert planilha.para_link_markdown("www.x.com") == "[link](https://www.x.com)"
    assert planilha.para_link_markdown("Dell") == "Dell"


def test_calcular_preserva_fonte_e_extras():
    itens = [{"descricao": "Notebook", "quantidade": 2, "valor_unitario": 5000,
              "fonte": "https://x.com/nb", "Marca": "Dell"}]
    calc, _ = planilha.calcular(itens)
    assert calc[0]["fonte"] == "https://x.com/nb"
    assert calc[0]["Marca"] == "Dell"
    assert planilha.colunas_extra(calc) == ["fonte", "Marca"]


def test_markdown_inclui_link_compacto_e_coluna_extra():
    itens = [{"descricao": "Notebook", "quantidade": 1, "valor_unitario": 5000,
              "fonte": "https://loja.com/nb", "Marca": "Dell"}]
    calc, glob = planilha.calcular(itens)
    md = planilha.para_markdown(calc, glob)
    assert "Fonte / Link" in md and "Marca" in md
    assert "[link](https://loja.com/nb)" in md
    assert "Dell" in md


def test_importa_xlsx_preserva_coluna_extra():
    dados = _xlsx([
        ["Descrição", "Quantidade", "Valor unitário", "Fonte", "Marca"],
        ["Notebook", 2, 4500, "https://loja.com/nb", "Dell"],
    ])
    itens = planilha.importar_de_xlsx(dados)
    assert itens[0]["fonte"] == "https://loja.com/nb"
    assert itens[0]["Marca"] == "Dell"


def test_export_docx_link_compacto_clicavel():
    import io
    import zipfile

    from src import export

    itens = [{"descricao": "Notebook", "quantidade": 1, "valor_unitario": 5000,
              "fonte": "https://loja.com/nb"}]
    calc, glob = planilha.calcular(itens)
    md = "## Estimativa\n\n" + planilha.para_markdown(calc, glob)
    docx_bytes = export.gerar_docx_consolidado({"etp": md})
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        doc = zf.read("word/document.xml").decode()
        rels = "".join(zf.read(n).decode() for n in zf.namelist()
                       if "document.xml.rels" in n)
    assert "w:hyperlink" in doc          # hyperlink real
    assert ">link<" in doc               # texto compacto
    assert "loja.com/nb" in rels         # URL só no destino
    assert "loja.com/nb" not in doc      # não expande a URL no texto


def test_export_pdf_link_clicavel():
    from src import export

    itens = [{"descricao": "Notebook", "quantidade": 1, "valor_unitario": 5000,
              "fonte": "https://loja.com/nb"}]
    calc, glob = planilha.calcular(itens)
    md = "## Estimativa\n\n" + planilha.para_markdown(calc, glob)
    pdf = export.gerar_pdf_consolidado({"etp": md})
    assert pdf.startswith(b"%PDF")
    assert b"URI" in pdf and (b"/Link" in pdf or b"/Annot" in pdf)
