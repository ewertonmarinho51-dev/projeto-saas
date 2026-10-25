"""
`src/formulario_matriz.py`: as regras do Formulário Matriz sem tela, que a
API (apps/api) usa. Devem bater com o wizard (`ui/steps.render_formulario`).
"""

import pytest

from src import formulario_matriz as fm
from src.config import CAMPOS_FORMULARIO

COMPLETO = {
    "orgao": "Secretaria de Saúde", "objeto": "Aquisição de luvas",
    "justificativa": "Reposição do estoque.", "modelo_execucao": "Entrega parcelada",
    "itens": [{"codigo": "1", "descricao": "Luva", "unidade": "CX", "quantidade": "10", "valor_unitario": "25,50"}],
}


def _processo(**extra):
    return {"dados": {}, "documentos": {}, "aprovados": [], "etapa": 0, **extra}


def test_campos_sao_os_do_wizard_com_rotulo_de_tela():
    campos = fm.campos()
    assert [c["chave"] for c in campos] == list(CAMPOS_FORMULARIO)
    orgao = next(c for c in campos if c["chave"] == "orgao")
    assert orgao["rotulo"] == (CAMPOS_FORMULARIO["orgao"].get("rotulo_tela") or CAMPOS_FORMULARIO["orgao"]["rotulo"])


def test_planilha_e_calculada_como_no_wizard():
    dados = fm.normalizar(COMPLETO)
    assert dados["itens"][0]["valor_total"] == 255.0
    assert dados["valor_estimado"] == 255.0
    assert dados["orgao"] == "Secretaria de Saúde"


def test_faltantes_contam_a_planilha_pelo_item_valido():
    falta = fm.faltantes({**COMPLETO, "itens": [{"codigo": "", "descricao": ""}]})
    assert falta == [CAMPOS_FORMULARIO["itens"].get("rotulo_tela") or CAMPOS_FORMULARIO["itens"]["rotulo"]]
    assert fm.faltantes(fm.normalizar(COMPLETO)) == []


def test_iniciar_sem_obrigatorio_recusa():
    with pytest.raises(fm.ErroDoFormulario, match="Preencha os campos obrigatórios"):
        fm.gravar(_processo(), {"orgao": "x"}, iniciar=True)


def test_iniciar_completo_vai_para_a_etapa_1_e_rascunho_nao():
    assert fm.gravar(_processo(), COMPLETO, iniciar=True).etapa == 1
    assert fm.gravar(_processo(), COMPLETO, iniciar=False).etapa == 0
    assert fm.gravar(_processo(etapa=3), COMPLETO, iniciar=True).etapa == 3


def test_dado_alterado_descarta_a_cadeia_e_a_ata_sai_com_o_edital():
    proc = _processo(dados=fm.normalizar(COMPLETO), documentos={"dfd": "D", "edital": "E", "arp": "A"},
                     aprovados=["dfd", "edital"], etapa=4)
    g = fm.gravar(proc, {**COMPLETO, "objeto": "Luvas nitrílicas"}, iniciar=False)
    assert g.mudou and g.documentos == {} and g.aprovados == []
    assert {"dfd", "edital", "arp"} <= set(g.descartados)


def test_salvar_igual_nao_descarta_mesmo_com_dado_legado():
    legado = {**COMPLETO, "itens": [{"codigo": "1", "descricao": "Luva", "unidade": "CX",
                                     "quantidade": "10", "valor_unitario": "25,50"}]}
    proc = _processo(dados=legado, documentos={"dfd": "D"}, aprovados=["dfd"], etapa=2)
    g = fm.gravar(proc, COMPLETO, iniciar=False)
    assert not g.mudou and g.documentos == {"dfd": "D"} and g.descartados == []


def test_chaves_fora_do_formulario_sao_mantidas():
    proc = _processo(dados={**COMPLETO, "_fluxo_mapa_riscos": True, "estimativa_pesquisa": {"a": 1}})
    g = fm.gravar(proc, COMPLETO, iniciar=False)
    assert g.dados["_fluxo_mapa_riscos"] is True and g.dados["estimativa_pesquisa"] == {"a": 1}


@pytest.mark.parametrize("valores", [
    {"tenant_id": "x"},
    {"modelo_execucao": "Inventado"},
    {"orgao": "x" * (fm.LIMITE_TEXTO + 1)},
    {"objeto": 12},
    {"itens": "lista"},
    {"itens": [{"descricao": {"aninhado": True}}]},
])
def test_entrada_invalida_e_recusada(valores):
    with pytest.raises(fm.ErroDoFormulario):
        fm.normalizar(valores)


def test_o_modulo_nao_puxa_o_streamlit():
    import subprocess
    import sys

    codigo = "import sys, src.formulario_matriz; print('streamlit' in sys.modules)"
    saida = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, check=True)
    assert saida.stdout.strip() == "False"
