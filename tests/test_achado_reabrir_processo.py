"""
ACHADO P1 DA AUDITORIA (§5): reabrir um processo salvo derrubava a tela.

O DEFEITO, como foi encontrado

Na navegação do §5, depois de criar um processo com os cinco documentos
aprovados, recarregar a página e entrar de novo, a lista de Processos
mostrava tudo certo — "Concluído", "5 de 5 documentos concluídos",
"Etapa atual: Todos os documentos aprovados". Clicar em **Continuar de
onde parei** devolvia isto, na tela do servidor:

    streamlit.errors.StreamlitWidgetAlreadyInstantiatedError:
    st.session_state.pagina cannot be modified after the widget with key
    pagina is instantiated.

CAUSA

`pagina` é a CHAVE do `st.radio` da navegação lateral, criado em
`components.render_sidebar()` — cedo, antes de qualquer roteamento.
`processos_ui._abrir` rodava depois e atribuía a essa mesma chave, o que
o Streamlit proíbe.

CONSEQUÊNCIA

Total, e no caminho mais comum que existe: reabrir um processo salvo é o
que o servidor faz em todo dia seguinte de trabalho. O processo não
abria, e o que aparecia era um traceback de Python.

O `app.py` tinha o mesmo defeito em três lugares — as quedas para "Novo
processo" quando Parecer Jurídico, Consolidar Demandas ou Pesquisa de
Preços estão indisponíveis. Mais raras, idênticas.

POR QUE A SUÍTE NÃO PEGOU

Porque a exceção só existe quando a BARRA LATERAL foi desenhada antes.
Os testes de `processos_ui` chamam a tela isolada, sem sidebar, e nessa
condição a atribuição é legítima. É um defeito que só aparece no app
inteiro — e por isso a prova estrutural abaixo olha o app inteiro.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent

# `components.py` é a exceção legítima e a única: é lá que o radio
# nasce, e as atribuições dele acontecem ANTES da instanciação.
ARQUIVO_DO_RADIO = RAIZ / "src" / "ui" / "components.py"


def _fontes_que_rodam_depois_da_sidebar() -> list[pathlib.Path]:
    arquivos = [RAIZ / "app.py"]
    arquivos += [p for p in (RAIZ / "src" / "ui").glob("*.py")
                 if p != ARQUIVO_DO_RADIO]
    return arquivos


def _atribuicoes_a_pagina(fonte: str) -> list[int]:
    """Linhas que escrevem em `st.session_state.pagina` ou `['pagina']`."""
    arvore = ast.parse(fonte)
    linhas: list[int] = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        alvos = no.targets if isinstance(no, ast.Assign) else [no.target]
        for alvo in alvos:
            if isinstance(alvo, ast.Attribute) and alvo.attr == "pagina":
                linhas.append(no.lineno)
            elif (isinstance(alvo, ast.Subscript)
                    and isinstance(alvo.slice, ast.Constant)
                    and alvo.slice.value == "pagina"):
                linhas.append(no.lineno)
    return linhas


@pytest.mark.parametrize(
    "caminho", _fontes_que_rodam_depois_da_sidebar(),
    ids=lambda p: p.name)
def test_ninguem_escreve_na_chave_do_radio_depois_da_sidebar(caminho):
    """
    A prova que impede a repetição.

    Quem precisar trocar de página depois da barra lateral usa
    `components.ir_para_pagina`, que guarda o pedido para a execução
    seguinte — a única janela em que `pagina` ainda pode ser escrita.
    """
    linhas = _atribuicoes_a_pagina(caminho.read_text(encoding="utf-8"))
    assert not linhas, (
        f"{caminho.name}: atribuição a `pagina` nas linhas {linhas}. "
        "Depois de `render_sidebar()` isso levanta "
        "StreamlitWidgetAlreadyInstantiatedError na tela do servidor — "
        "use `components.ir_para_pagina(...)`.")


def test_o_pedido_de_troca_e_atendido_antes_de_o_radio_existir():
    """
    O pedido só funciona se for consumido ANTES do `st.radio`. Trocada a
    ordem, ele seria escrito na chave de um widget já instanciado — o
    mesmo erro, agora dentro da função que existe para evitá-lo.
    """
    fonte = ARQUIVO_DO_RADIO.read_text(encoding="utf-8")
    consumo = fonte.index("CHAVE_PAGINA_PENDENTE, \"\"")
    radio = fonte.index('st.radio("Navegação"')
    assert consumo < radio, (
        "o pedido de troca de página é consumido DEPOIS de o radio "
        "existir — a proteção deixou de proteger")


def test_ir_para_pagina_nao_toca_na_chave_do_widget(monkeypatch):
    from src.ui import components

    estado: dict = {}
    monkeypatch.setattr(components, "st",
                        type("_St", (), {"session_state": estado})())
    components.ir_para_pagina("Processos")

    assert estado == {components.CHAVE_PAGINA_PENDENTE: "Processos"}
    assert "pagina" not in estado, (
        "escrever direto em `pagina` é exatamente o que derrubava a tela")
