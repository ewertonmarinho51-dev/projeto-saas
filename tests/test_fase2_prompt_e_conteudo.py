"""
Fase 2 — prompt e conteúdo são coisas diferentes.

Defeito que sobreviveu à integração do padrão ouro: `_gerar_demo`
reutilizava `prompts.formatar_dados_formulario`, que é material
ENDEREÇADO AO MODELO. O DFD do Modo Demonstração saía com "PROIBIDO
escrever a lista de itens", "…EXATAMENTE UMA VEZ, SOZINHA em uma linha
própria…" e "COMPOSIÇÃO FUNCIONAL DO OBJETO (para você compreender o que
se contrata; NÃO reproduza esta análise como lista)" dentro do corpo —
um ato administrativo dando ordens a quem o redige.

Aqui se prova a correção na causa (duas representações do mesmo
formulário) e a segunda barreira (`validacao._BLOQUEANTES`), com
negativos explícitos para que a barreira não reprove prosa legítima.
"""

import json
import re
from pathlib import Path

import pytest

from src import llm, planilha, prompts, validacao

FIXTURE = Path(__file__).parent / "fixtures" / "caso_210_itens.json"

# Frases que só existem porque alguém está falando COM O MODELO.
LINGUAGEM_DE_PROMPT = (
    "PROIBIDO escrever",
    "EXATAMENTE UMA VEZ",
    "COMPOSIÇÃO FUNCIONAL DO OBJETO",
    "para você compreender",
    "NÃO reproduza",
    "não reproduza",
    "Escreva o texto da cláusula",
    "AUTOMATICAMENTE",
    "no lugar da marca",
    "ignore-a",
    planilha.MARCADOR_TABELA,
)


@pytest.fixture(scope="module")
def caso():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dados(caso):
    return {
        "orgao": "Prefeitura Municipal de Ensaio",
        "objeto": caso["objeto"],
        "responsavel": "Maria Souza Lima",
        "justificativa": "Reposição do estoque de material de expediente.",
        "alinhamento": "PCA 2026, item 14.",
        "requisitos": "Conformidade com as especificações do anexo.",
        "modelo_execucao": "Registro de preços",
        "itens": caso["itens"],
    }


@pytest.fixture(scope="module")
def dfd_demo(dados):
    """O DFD do Modo Demonstração, já com a tabela injetada."""
    return planilha.injetar_tabela(llm._gerar_demo("dfd", dados),
                                   dados["itens"])


# ---------------------------------------------------------------------------
# B. as duas representações do mesmo formulário
# ---------------------------------------------------------------------------
def test_bloco_para_o_modelo_continua_instruindo_o_modelo(dados):
    """A correção não pode desarmar o prompt real."""
    bloco = prompts.formatar_dados_formulario(dados)
    assert "PROIBIDO escrever a lista de itens" in bloco
    assert planilha.MARCADOR_TABELA in bloco
    assert "COMPOSIÇÃO FUNCIONAL DO OBJETO" in bloco


def test_bloco_para_o_documento_nao_fala_com_o_modelo(dados):
    bloco = prompts.dados_objetivos_do_formulario(dados)
    for frase in LINGUAGEM_DE_PROMPT:
        if frase == planilha.MARCADOR_TABELA:
            continue        # o marcador é o ponto de injeção; some depois
        assert frase not in bloco, frase


def test_as_duas_representacoes_descrevem_os_mesmos_fatos(dados):
    """
    Separação de DESTINO, não de dados: um percurso de campos, um cálculo
    de planilha. Os fatos objetivos têm de bater nas duas.
    """
    para_ia = prompts.formatar_dados_formulario(dados)
    para_doc = prompts.dados_objetivos_do_formulario(dados)
    for fato in ("Prefeitura Municipal de Ensaio", "Maria Souza Lima",
                 "PCA 2026, item 14.", "R$ 8.024.834,67", "210"):
        assert fato in para_ia, fato
        assert fato in para_doc, fato


def test_o_marcador_da_tabela_e_o_mesmo_ponto_de_injecao(dados):
    """Um pipeline só: a tabela entra pelo mesmo lugar nas duas versões."""
    assert planilha.MARCADOR_TABELA in \
        prompts.dados_objetivos_do_formulario(dados)
    assert planilha.MARCADOR_TABELA in prompts.formatar_dados_formulario(dados)


def test_resumo_objetivo_nao_repete_a_planilha(dados):
    itens, glob = planilha.calcular(dados["itens"])
    resumo = planilha.resumo_objetivo(itens, glob)
    assert "210" in resumo and "R$ 8.024.834,67" in resumo
    assert "|" not in resumo                     # nenhuma linha de tabela
    for item in itens[:40]:
        assert str(item["codigo"]) not in resumo, item["codigo"]


def test_preferencia_de_modelagem_do_etp_e_fala_para_o_modelo(dados):
    """
    O enquadramento "a ser CONFIRMADA OU AFASTADA pelo estudo" orienta o
    modelo; no documento entra só o dado informado.
    """
    assert "PREFERÊNCIA DE MODELAGEM" in \
        prompts.formatar_dados_formulario(dados, "etp")
    para_doc = prompts.dados_objetivos_do_formulario(dados)
    assert "PREFERÊNCIA DE MODELAGEM" not in para_doc
    assert "Registro de preços" in para_doc


# ---------------------------------------------------------------------------
# C + E. o DFD do Modo Demonstração
# ---------------------------------------------------------------------------
def test_dfd_demo_nao_contem_uma_linha_endereçada_ao_modelo(dfd_demo):
    for frase in LINGUAGEM_DE_PROMPT:
        assert frase not in dfd_demo, frase


def test_dfd_demo_continua_identificado_como_demonstracao(dfd_demo):
    assert "Modo Demonstração" in dfd_demo
    assert "Minuta-esqueleto" in dfd_demo


def test_dfd_demo_traz_os_dados_objetivos_do_formulario(dfd_demo):
    for fato in ("Prefeitura Municipal de Ensaio", "Maria Souza Lima",
                 "Reposição do estoque", "PCA 2026, item 14.",
                 "Quantidade de itens: 210.", "R$ 8.024.834,67"):
        assert fato in dfd_demo, fato


def test_dfd_demo_mantem_a_planilha_integra(dfd_demo, dados):
    assert len(planilha.linhas_de_itens_do_texto(dfd_demo)) == 210
    assert dfd_demo.count("| Código | Descrição") == 1
    assert planilha.conferir_tabela(dfd_demo, dados["itens"]) == []


def test_dfd_demo_nao_repete_codigos_fora_da_tabela(dfd_demo, dados):
    """
    O contexto não pode reintroduzir a lista: cada código aparece uma vez
    e apenas dentro da tabela oficial.
    """
    linhas_da_tabela = set(planilha.linhas_de_itens_do_texto(dfd_demo))
    fora = [ln for ln in dfd_demo.splitlines()
            if ln not in linhas_da_tabela and not ln.lstrip().startswith("|")]
    corpo_fora = "\n".join(fora)
    for item in dados["itens"][:60]:
        assert str(item["codigo"]) not in corpo_fora, item["codigo"]


def test_dfd_demo_nao_tem_bloqueio_de_vazamento_de_prompt(dfd_demo, dados):
    """
    Avisos de profundidade do Modo Demonstração são esperados — ele é uma
    minuta-esqueleto. O que não pode existir é bloqueio de MECÂNICA
    INTERNA.
    """
    achados = validacao.validar_documento("dfd", dfd_demo, None, dados)
    vazamentos = [a["mensagem"] for a in validacao.bloqueios(achados)
                  if "prompt" in a["mensagem"]
                  or "marcador interno" in a["mensagem"]
                  or "mecânica interna" in a["mensagem"]]
    assert vazamentos == [], vazamentos


@pytest.mark.parametrize("doc_key", ["dfd", "etp", "tr", "edital"])
def test_nenhum_documento_demo_vaza_linguagem_de_prompt(doc_key, dados):
    texto = planilha.injetar_tabela(llm._gerar_demo(doc_key, dados),
                                    dados["itens"])
    for frase in LINGUAGEM_DE_PROMPT:
        assert frase not in texto, (doc_key, frase)


# ---------------------------------------------------------------------------
# D. a segunda barreira — positivos
# ---------------------------------------------------------------------------
VAZAMENTOS = [
    "5.1. " + planilha.MARCADOR_TABELA,
    "PROIBIDO escrever a lista de itens, ainda que parcialmente.",
    "coloque a marca EXATAMENTE UMA VEZ, SOZINHA em uma linha própria.",
    "NÃO reproduza esta análise como lista.",
    "Amostra apenas ilustrativa dos primeiros itens.",
    "COMPOSIÇÃO FUNCIONAL DO OBJETO (para você compreender o que se "
    "contrata): papelaria.",
    "para você compreender o que se contrata, veja abaixo.",
    "A tabela completa é inserida automaticamente no lugar da marca.",
]


@pytest.mark.parametrize("trecho", VAZAMENTOS)
def test_linguagem_interna_injetada_bloqueia_a_emissao(trecho):
    texto = f"## 1. OBJETO\n\nAquisição de canetas.\n\n## 5. VALOR\n\n{trecho}\n"
    bloqueios = [a["mensagem"] for a in
                 validacao.bloqueios(validacao.validar_documento("dfd", texto))]
    assert any("prompt" in m or "marcador interno" in m or "mecânica" in m
               or "ponto de injeção" in m or "contexto do prompt" in m
               for m in bloqueios), (trecho, bloqueios)


# ---------------------------------------------------------------------------
# D. a segunda barreira — negativos (nada de falso positivo)
# ---------------------------------------------------------------------------
LEGITIMOS = [
    "A análise de riscos consta do item 7 deste documento.",
    "Os valores serão reajustados automaticamente na forma do art. 92, §3º.",
    "O pagamento será processado automaticamente após o atesto da nota.",
    "A amostra do produto poderá ser exigida para fins de aceitação.",
    "O licitante deverá apresentar amostra no prazo de 5 (cinco) dias úteis.",
    "Não reproduza o logotipo do órgão sem autorização prévia.",
    "A tabela de preços de referência integra o Anexo I deste Termo.",
    "A planilha orçamentária será inserida no processo pela unidade "
    "requisitante.",
    "A composição funcional do objeto abrange materiais de expediente.",
    "A contratada deverá escrever o relatório mensal de execução.",
    "Cada item deverá ser entregue exatamente uma vez por competência.",
    "O sistema atualiza o saldo automaticamente a cada empenho.",
]


@pytest.mark.parametrize("frase", LEGITIMOS)
def test_prosa_administrativa_legitima_nao_e_bloqueada(frase):
    texto = f"## 1. OBJETO\n\nAquisição de canetas.\n\n## 5. VALOR\n\n{frase}\n"
    bloqueios = [a["mensagem"] for a in
                 validacao.bloqueios(validacao.validar_documento("dfd", texto))]
    assert not any("prompt" in m or "mecânica" in m or "ponto de injeção" in m
                   or "contexto do prompt" in m
                   for m in bloqueios), (frase, bloqueios)


def test_os_documentos_do_catalogo_oficial_passam_pela_barreira(dados):
    """Edital e ARP são determinísticos: não podem tropeçar nas regras novas."""
    for doc_key in ("edital", "arp"):
        texto = llm.gerar_instrumento_oficial(doc_key, dados)
        bloqueios = [a["mensagem"] for a in validacao.bloqueios(
            validacao.validar_documento(doc_key, texto, None, dados))]
        assert not any("prompt" in m or "mecânica" in m
                       for m in bloqueios), (doc_key, bloqueios)


def test_o_proprio_prompt_real_seria_reprovado_como_documento(dados):
    """
    Prova de que a barreira mira o material certo: o bloco destinado ao
    modelo, se algum dia voltar a virar corpo de documento, é reprovado.
    """
    bloco = prompts.formatar_dados_formulario(dados)
    bloqueios = [a["mensagem"] for a in
                 validacao.bloqueios(validacao.validar_documento("dfd", bloco))]
    assert any("prompt" in m or "marcador interno" in m
               for m in bloqueios), bloqueios
