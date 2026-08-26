"""
Fases 2 e 3 do padrão ouro — integridade da tabela de itens e das
identificações.

Caso de regressão: processo real de 210 itens, R$ 8.024.834,67
(docs/diagnostico-padrao-ouro.md). Os defeitos reproduzidos aqui são os
encontrados no bundle aprovado em produção: DFD com a planilha
duplicada, edital com 53 dos 210 códigos em 3 fragmentos, matrícula
999999, "Representante da área: 15".

Os 210 itens vivem no FIXTURE — nunca na lógica de produção.
"""

import json
from pathlib import Path

import pytest

from src import planilha, validacao

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"


@pytest.fixture(scope="module")
def caso():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def itens(caso):
    return caso["itens"]


# ---------------------------------------------------------------------------
# O fixture é o caso real
# ---------------------------------------------------------------------------
def test_fixture_tem_exatamente_210_itens_e_o_total_do_processo(caso, itens):
    assert len(itens) == 210
    assert len({str(i["codigo"]) for i in itens}) == 210
    _, total = planilha.calcular(itens)
    assert f"{total:.2f}" == "8024834.67"
    assert caso["valor_estimado"] == 8024834.67


# ---------------------------------------------------------------------------
# Injeção determinística
# ---------------------------------------------------------------------------
def test_injecao_reproduz_a_planilha_integralmente(itens):
    texto = planilha.injetar_tabela(
        "## 5. ESTIMATIVA\n\nSegue a planilha.\n\n[[TABELA_ITENS]]\n", itens)
    assert planilha.conferir_tabela(texto, itens) == []
    assert "R$ 8.024.834,67" in texto
    assert len(planilha.linhas_de_itens_do_texto(texto)) == 210


def test_marcador_repetido_nao_duplica_a_planilha(itens):
    texto = planilha.injetar_tabela(
        "A\n\n[[TABELA_ITENS]]\n\nB\n\n[[TABELA_ITENS]]\n", itens)
    assert texto.count("| Código | Descrição") == 1
    assert planilha.conferir_tabela(texto, itens) == []


def test_tabela_escrita_pela_ia_e_removida_antes_da_injecao(itens):
    """Defeito real do DFD: cópia da IA + tabela oficial no mesmo doc."""
    copia_da_ia = planilha.para_markdown(itens[:53], 0, incluir_global=False)
    texto = (f"## 1. IDENTIFICAÇÃO\n\n{copia_da_ia}\n\n"
             "## 5. ESTIMATIVA\n\n[[TABELA_ITENS]]\n")
    saida = planilha.injetar_tabela(texto, itens)
    assert saida.count("| Código | Descrição") == 1
    assert planilha.conferir_tabela(saida, itens) == []
    assert "## 1. IDENTIFICAÇÃO" in saida   # a prosa permanece


def test_tabela_de_riscos_nao_e_confundida_com_a_planilha(itens):
    """Tabelas legítimas de prosa (sem códigos) são preservadas."""
    riscos = ("| Risco | Probabilidade |\n|---|---|\n"
              "| Atraso na entrega | Média |\n")
    saida = planilha.injetar_tabela(
        f"## 7. RISCOS\n\n{riscos}\n## 5. ESTIMATIVA\n\n[[TABELA_ITENS]]\n",
        itens)
    assert "| Atraso na entrega | Média |" in saida
    assert planilha.conferir_tabela(saida, itens) == []


# ---------------------------------------------------------------------------
# Conferência contra a fonte
# ---------------------------------------------------------------------------
def test_tabela_parcial_e_reprovada(itens):
    """Edital real: 53 de 210 códigos."""
    parcial = planilha.para_markdown(itens[:53], 8024834.67)
    problemas = planilha.conferir_tabela(parcial, itens)
    assert any("157 item(ns) da planilha não constam" in p for p in problemas)


def test_tabela_ausente_e_reprovada(itens):
    problemas = planilha.conferir_tabela("## 5. ESTIMATIVA\n\nR$ 1,00\n",
                                         itens)
    assert problemas == ["tabela de itens ausente do documento "
                         "(210 item(ns) na planilha do processo)"]


def test_tabela_duplicada_e_reprovada(itens):
    completa = planilha.para_markdown(itens, 8024834.67)
    problemas = planilha.conferir_tabela(completa + "\n\n" + completa, itens)
    assert any("aparece 2 vezes" in p for p in problemas)


def test_valor_unitario_adulterado_e_reprovado(itens):
    completa = planilha.para_markdown(itens, 8024834.67)
    codigo = str(itens[0]["codigo"])
    original = planilha.formatar_moeda(itens[0]["valor_unitario"])
    adulterada = completa.replace(f"| {original} |", "| R$ 99,99 |", 1)
    problemas = planilha.conferir_tabela(adulterada, itens)
    assert any("valor divergente" in p and codigo in p for p in problemas)


def test_item_estranho_e_reprovado(itens):
    completa = planilha.para_markdown(itens, 8024834.67)
    intruso = "| 999999 | Item inventado | UN | 1 | R$ 1,00 | R$ 1,00 | - |"
    problemas = planilha.conferir_tabela(completa + "\n" + intruso, itens)
    assert any("não existem na planilha" in p for p in problemas)


def test_total_da_linha_adulterado_e_reprovado(itens):
    """
    Quantidade e unitário conferem, mas o produto escrito na linha não.
    Sem esta conferência a aritmética errada atravessa a validação linha
    a linha, e o documento afirma um total que a planilha não sustenta.
    """
    completa = planilha.para_markdown(itens, 8024834.67)
    codigo = str(itens[0]["codigo"])
    total = planilha.formatar_moeda(
        itens[0]["quantidade"] * itens[0]["valor_unitario"])
    adulterada = completa.replace(f"| {total} |", "| R$ 0,01 |", 1)
    assert adulterada != completa
    problemas = planilha.conferir_tabela(adulterada, itens)
    assert any("valor divergente" in p and codigo in p
               for p in problemas), problemas


def test_codigos_conferidos_por_valor_e_nao_por_quantidade_de_digitos(itens):
    """
    O caso real mistura códigos de 3 a 6 dígitos. Uma conferência que
    exigisse comprimento fixo daria por perdidos os itens curtos — foi
    exatamente esse o erro de medição do diagnóstico anterior.
    """
    comprimentos = {len(str(i["codigo"])) for i in itens}
    assert len(comprimentos) > 1, comprimentos
    completa = planilha.para_markdown(itens, 8024834.67)
    lidos = {planilha._celulas(ln)[0]
             for ln in planilha.linhas_de_itens_do_texto(completa)}
    assert lidos == {str(i["codigo"]) for i in itens}
    assert planilha.conferir_tabela(completa, itens) == []


def test_valor_global_ausente_e_reprovado(itens):
    sem_global = planilha.para_markdown(itens, 8024834.67,
                                        incluir_global=False)
    problemas = planilha.conferir_tabela(sem_global, itens)
    assert any("valor global" in p for p in problemas)


def test_sem_planilha_na_sessao_a_checagem_nao_opina():
    assert planilha.conferir_tabela("qualquer texto", None) == []
    assert planilha.conferir_tabela("qualquer texto", []) == []


# ---------------------------------------------------------------------------
# O validador bloqueia a emissão
# ---------------------------------------------------------------------------
def test_validador_bloqueia_documento_com_tabela_divergente(caso, itens):
    parcial = planilha.para_markdown(itens[:53], 8024834.67)
    achados = validacao.validar_documento(
        "edital", f"## 5. ESTIMATIVA\n\n{parcial}\n", None, caso)
    bloqueios = [a["mensagem"] for a in validacao.bloqueios(achados)]
    assert any("tabela de itens divergente da planilha" in m
               for m in bloqueios), bloqueios


def test_validador_aprova_documento_com_a_tabela_integra(caso, itens):
    texto = planilha.injetar_tabela(
        "## 5. ESTIMATIVA\n\nValor estimado conforme pesquisa.\n\n"
        "[[TABELA_ITENS]]\n", itens)
    achados = validacao.validar_documento("etp", texto, None, caso)
    assert not [a for a in validacao.bloqueios(achados)
                if "tabela de itens" in a["mensagem"]]


# ---------------------------------------------------------------------------
# Identificações sem vínculo
# ---------------------------------------------------------------------------
def test_nome_designado_fora_do_processo_bloqueia():
    dados = {"orgao": "Prefeitura Municipal de Paragominas",
             "responsavel": "Maria Souza Lima"}
    texto = "5.1. Gestor do contrato: Carlos Eduardo Ferreira Nunes.\n"
    achados = validacao.validar_documento("tr", texto, None, dados)
    bloqueios = [a["mensagem"] for a in validacao.bloqueios(achados)]
    assert any("agente público designado sem vínculo" in m
               for m in bloqueios), bloqueios


def test_nome_do_responsavel_do_processo_e_aceito():
    dados = {"orgao": "Prefeitura", "responsavel": "Maria Souza Lima"}
    texto = "5.1. Gestor do contrato: Maria Souza Lima.\n"
    achados = validacao.validar_documento("tr", texto, None, dados)
    assert not [a for a in achados if "sem vínculo" in a["mensagem"]]


def test_sem_formulario_a_checagem_de_nomes_nao_opina():
    texto = "5.1. Gestor do contrato: Carlos Eduardo Ferreira Nunes.\n"
    assert not [a for a in validacao.validar_documento("tr", texto)
                if "sem vínculo" in a["mensagem"]]


def test_numero_funcional_improvisado_sem_o_rotulo_matricula():
    texto = "Servidor designado, nº funcional 999999, responderá pela gestão.\n"
    achados = validacao.validar_documento("tr", texto)
    assert any("número funcional com aparência de improviso" in a["mensagem"]
               for a in achados)


def test_numero_funcional_real_passa():
    texto = "Servidor designado, nº funcional 48291, responderá pela gestão.\n"
    achados = validacao.validar_documento("tr", texto)
    assert not [a for a in achados if "número funcional" in a["mensagem"]]


def test_designar_unidade_administrativa_e_legitimo():
    """
    "Gestora: Secretaria Municipal de Saúde" designa uma UNIDADE, não uma
    pessoa — não é identificação inventada. Falso positivo encontrado no
    edital real ao rodar esta regra pela primeira vez.
    """
    dados = {"orgao": "Prefeitura", "responsavel": "Maria Souza Lima"}
    for unidade in ("Secretaria Municipal de Saúde",
                    "Departamento de Compras",
                    "Comissão de Contratação"):
        texto = f"5.1. Gestora: {unidade}.\n"
        achados = validacao.validar_documento("tr", texto, None, dados)
        assert not [a for a in achados if "sem vínculo" in a["mensagem"]], unidade
