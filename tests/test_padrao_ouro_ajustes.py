"""
Ajustes finais do padrão ouro (14/08), pedidos após a auditoria
independente.

Cobre: CNPJ rotulado quebrado entre linhas, resumo semântico da planilha
(o modelo entende o objeto sem poder reproduzir a lista), rótulos da UI
coerentes com o que o botão faz e com o que o pacote contém.
"""

import io
import json
import re
from pathlib import Path

import pytest

from src import export, planilha, prompts, validacao
from src.ui import steps

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"


@pytest.fixture(scope="module")
def itens():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))["itens"]


# ---------------------------------------------------------------------------
# 1. CNPJ rotulado quebrado entre linhas
# ---------------------------------------------------------------------------
def test_cnpj_com_quebra_de_linha_entre_rotulo_e_numero_bloqueia():
    """Forma exata em que o par sai da extração de PDF."""
    texto = "CNPJ\nsob o nº 541984981984984"
    bloqueios = [a["mensagem"] for a in validacao.bloqueios(
        validacao.validar_documento("arp", texto))]
    assert any("CNPJ com 15 dígitos" in m for m in bloqueios), bloqueios


def test_cnpj_com_espacos_e_multiplas_quebras():
    for separador in ("CNPJ sob o nº ", "CNPJ\nsob o nº ", "CNPJ  :  ",
                      "CNPJ\n  n°\n"):
        texto = f"{separador}541984981984984"
        bloqueios = [a["mensagem"] for a in validacao.bloqueios(
            validacao.validar_documento("arp", texto))]
        assert any("CNPJ com 15" in m for m in bloqueios), separador


def test_cnpj_detectado_no_texto_extraido_de_um_PDF_real():
    """
    Fim a fim: gera o PDF, extrai o texto e confere que o validador
    reprova — é assim que o defeito chegou ao dossiê auditado.
    """
    pymupdf = pytest.importorskip("pymupdf")
    doc = ("## 1. PARTES\n\n1.1. Prefeitura Municipal, inscrita no CNPJ "
           "sob o nº 541984981984984, doravante Administração.\n")
    pdf = export.gerar_pdf_consolidado({"arp": doc}, None)
    extraido = "\n".join(p.get_text()
                         for p in pymupdf.open(stream=pdf, filetype="pdf"))
    assert "541984981984984" in extraido
    bloqueios = [a["mensagem"] for a in validacao.bloqueios(
        validacao.validar_documento("arp", extraido))]
    assert any("CNPJ com 15 dígitos" in m for m in bloqueios), bloqueios


def test_cnpj_valido_continua_passando_mesmo_quebrado():
    texto = "CNPJ\nsob o nº 05.514.464/0001-30"
    assert not [a for a in validacao.validar_documento("arp", texto)
                if "CNPJ" in a["mensagem"]]


# ---------------------------------------------------------------------------
# 2. Nenhuma linha real da planilha entra no prompt
# ---------------------------------------------------------------------------
def _bloco_do_prompt(itens):
    return prompts.formatar_dados_formulario(
        {"orgao": "Prefeitura", "objeto": "materiais de expediente",
         "itens": itens})


def test_nenhuma_linha_real_da_planilha_entra_no_prompt(itens):
    bloco = _bloco_do_prompt(itens)
    # nenhum código, nenhuma linha de tabela
    assert "|" not in bloco
    for item in itens[:40]:
        assert str(item["codigo"]) not in bloco, item["codigo"]
    # nenhuma descrição literal (compara pelos 30 primeiros caracteres)
    for item in itens[:40]:
        trecho = (item.get("descricao") or "")[:30].strip()
        if len(trecho) >= 15:
            assert trecho not in bloco, trecho


def test_resumo_semantico_nao_tem_codigo_preco_nem_url(itens):
    resumo = planilha.resumo_semantico(itens)
    assert resumo
    assert "R$" not in resumo
    assert "http" not in resumo and "www." not in resumo
    assert "|" not in resumo
    assert not re.search(r"\b\d{3,}\b", resumo)   # nenhum código/quantidade
    for item in itens[:40]:
        assert str(item["codigo"]) not in resumo


def test_valor_global_e_o_unico_valor_monetario_do_prompt(itens):
    """
    A modalidade e a estimativa dependem do total; o item, não.

    Os extremos de preço unitário saíram por decisão de auditoria: não
    são necessários a DFD, ETP ou TR e estimulam inferência econômica que
    o processo não sustenta. Qualquer outro valor monetário no bloco da
    planilha precisa de origem independente e justificativa explícita —
    e então este teste é o lugar de registrá-la.
    """
    bloco = _bloco_do_prompt(itens)
    assert "R$ 8.024.834,67" in bloco
    precos = [p.rstrip(".,") for p in re.findall(r"R\$\s*[\d.,]+", bloco)]
    assert precos == ["R$ 8.024.834,67"], precos


def test_extremos_de_preco_unitario_nao_vao_para_a_ia(itens):
    """Menor e maior preço unitário do caso real não podem aparecer."""
    resumo = planilha.resumo_para_prompt(*planilha.calcular(itens))
    unitarios = [i["valor_unitario"] for i in planilha.calcular(itens)[0]]
    for extremo in (min(unitarios), max(unitarios)):
        assert planilha.formatar_moeda(extremo) not in resumo
    assert "Preços unitários entre" not in resumo


# ---------------------------------------------------------------------------
# 3. DFD, ETP e TR recebem a composição funcional
# ---------------------------------------------------------------------------
def test_composicao_por_familia_agrupa_o_objeto_real(itens):
    composicao = planilha.composicao_por_familia(itens)
    assert composicao
    assert sum(n for _, n, _ in composicao) == 210
    assert abs(sum(p for _, _, p in composicao) - 100.0) < 0.5
    familias = {f for f, _, _ in composicao}
    assert "Papelaria e expediente" in familias
    assert "Arquivo e organização de documentos" in familias
    # a família majoritária de um processo de expediente é papelaria
    assert composicao[0][0] == "Papelaria e expediente"


@pytest.mark.parametrize("doc_key", ["dfd", "etp", "tr"])
def test_documentos_de_prosa_recebem_as_categorias_funcionais(doc_key, itens):
    """
    O ETP precisa das famílias para justificar solução e parcelamento; o
    TR, para fixar requisitos e recebimento. Sem isso o texto sai
    genérico — foi por isso que o resumo semântico voltou ao prompt.
    """
    system, user = prompts.montar_prompt(
        doc_key,
        {"orgao": "Prefeitura", "objeto": "materiais de expediente",
         "itens": itens},
        contexto_anterior=None)
    assert "COMPOSIÇÃO FUNCIONAL DO OBJETO" in user
    assert "Papelaria e expediente" in user
    # …e continua sem nada copiável
    assert "|" not in user.split("COMPOSIÇÃO FUNCIONAL")[1]


def test_sem_planilha_nao_ha_resumo_semantico():
    assert planilha.resumo_semantico([]) == ""
    assert planilha.composicao_por_familia([]) == []


# ---------------------------------------------------------------------------
# 4. Rótulos da interface
# ---------------------------------------------------------------------------
def test_botao_de_edital_e_arp_nao_diz_com_ia():
    for doc_key, sigla in (("edital", "Edital"), ("arp", "ARP")):
        rotulo = steps._rotulo_do_botao(doc_key, {"sigla": sigla})
        assert "com IA" not in rotulo, rotulo
        assert "minuta" in rotulo.lower() and sigla in rotulo


def test_botao_dos_documentos_de_prosa_continua_dizendo_com_ia():
    for doc_key, sigla in (("dfd", "DFD"), ("etp", "ETP"), ("tr", "TR")):
        assert steps._rotulo_do_botao(doc_key, {"sigla": sigla}) == \
            f"Gerar {sigla} com IA"


def test_zip_empacota_quatro_sem_arp_e_cinco_com_arp():
    base = {k: f"## 1. OBJETO\n\nTexto do {k}.\n"
            for k in ("dfd", "etp", "tr", "edital")}
    import zipfile

    nomes = zipfile.ZipFile(
        io.BytesIO(export.gerar_zip(base, "pdf"))).namelist()
    assert len(nomes) == 4

    com_arp = {**base, "arp": "## 1. OBJETO\n\nAta.\n"}
    nomes = zipfile.ZipFile(
        io.BytesIO(export.gerar_zip(com_arp, "pdf"))).namelist()
    assert len(nomes) == 5
    assert any("ARP" in n for n in nomes), nomes
