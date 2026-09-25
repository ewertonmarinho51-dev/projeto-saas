"""
Formulário em linguagem simples — e a garantia de que o motor não mudou.

A prova mais importante deste arquivo é
`test_o_prompt_do_modelo_nao_mudou`. A instrução era explícita: não
alterar o comportamento da geração de documentos. Só que `prompts.py`
monta o prompt com `meta['rotulo']` — o MESMO campo que a interface
exibia. Reescrever rótulos teria mudado o prompt sem ninguém notar.

Por isso entrou `rotulo_tela`: a tela passou a ler dele, e `rotulo`
continua sendo o canônico que vai ao modelo.
"""

from __future__ import annotations

import pytest

from src.config import CAMPOS_FORMULARIO

# Rótulos canônicos como estavam ANTES desta rodada. Fixados aqui de
# propósito: se alguém editar `rotulo` achando que mexe só na tela, esta
# lista reprova — e a mensagem explica o que ele acabou de mudar.
ROTULOS_CANONICOS = {
    "memorando": "Documento inicial da demanda (memorando / ofício)",
    "orgao": "Órgão / Entidade Requisitante",
    "responsavel": "Responsável pela Demanda (nome e cargo)",
    "objeto": "Objeto Detalhado da Contratação",
    "justificativa": "Justificativa e Problema a Ser Resolvido",
    "alinhamento": "Alinhamento Estratégico (PCA / Planejamento)",
    "requisitos": "Requisitos Técnicos e Normativos",
    "itens": "Planilha Orçamentária (itens da contratação)",
    "modelo_execucao": "Modelo de Execução / Fornecimento",
    "prazo": "Prazo / Data Pretendida para a Contratação",
    "riscos": "Riscos Identificados",
}


def test_o_prompt_do_modelo_nao_mudou():
    """
    `prompts.py` monta o prompt com `meta['rotulo']`. Mudar esses textos
    mudaria o que o modelo recebe — exatamente o que a instrução proibia.

    Se esta prova falhar, a pergunta não é "como faço passar": é se a
    mudança no prompt foi intencional e medida contra o padrão-ouro.
    """
    atuais = {chave: meta["rotulo"] for chave, meta in CAMPOS_FORMULARIO.items()}
    assert atuais == ROTULOS_CANONICOS


def test_prompts_continua_lendo_o_rotulo_canonico():
    """
    A separação só vale enquanto `prompts.py` usar `rotulo`. Se um dia
    ele passar a ler `rotulo_tela`, o prompt volta a depender da
    linguagem da interface — e a garantia acima vira letra morta.
    """
    from pathlib import Path

    fonte = Path("src/prompts.py").read_text(encoding="utf-8")
    assert "meta['rotulo']" in fonte or 'meta["rotulo"]' in fonte
    assert "rotulo_tela" not in fonte


# ---------------------------------------------------------------------------
# Linguagem da tela
# ---------------------------------------------------------------------------
def test_todo_campo_tem_rotulo_de_tela():
    faltando = [c for c, m in CAMPOS_FORMULARIO.items()
                if not (m.get("rotulo_tela") or "").strip()]
    assert not faltando, faltando


def test_os_rotulos_de_tela_sao_curtos():
    """
    Rótulo longo vira parágrafo e deixa de ser rótulo. O canônico
    "Justificativa e Problema a Ser Resolvido" tem 39 caracteres; o de
    tela cabe em bem menos.
    """
    longos = {c: m["rotulo_tela"] for c, m in CAMPOS_FORMULARIO.items()
              if len(m["rotulo_tela"]) > 45}
    assert not longos, longos


def test_a_ajuda_da_tela_nao_cita_artigo_de_lei():
    """
    O público-alvo é servidor sem formação jurídica. "art. 18, §1º, III"
    não ajuda quem não sabe o que é o artigo 18 — e ocupava o lugar da
    frase que ajudaria.

    O texto legal não se perde: `help` continua intacto, e é ele que
    alimenta o prompt.
    """
    com_jargao = {
        chave: meta["ajuda_simples"]
        for chave, meta in CAMPOS_FORMULARIO.items()
        if "art." in meta.get("ajuda_simples", "")
        or "§" in meta.get("ajuda_simples", "")
    }
    assert not com_jargao, com_jargao


def test_a_ajuda_original_continua_intacta():
    """Ela some da tela, não do arquivo: é insumo do prompt."""
    assert all(meta.get("help") for meta in CAMPOS_FORMULARIO.values())


def test_a_ajuda_da_tela_e_mais_curta_que_a_original():
    piores = {
        chave: (len(meta["ajuda_simples"]), len(meta["help"]))
        for chave, meta in CAMPOS_FORMULARIO.items()
        if len(meta["ajuda_simples"]) > len(meta["help"])
    }
    assert not piores, piores


# ---------------------------------------------------------------------------
# Exemplos
# ---------------------------------------------------------------------------
def test_todo_campo_tem_exemplo():
    """
    Inclusive os dois que não tinham nem placeholder — `itens` e
    `modelo_execucao` — e que eram justamente os mais difíceis de
    preencher no escuro.
    """
    faltando = [c for c, m in CAMPOS_FORMULARIO.items()
                if not (m.get("exemplo") or "").strip()]
    assert not faltando, faltando


def test_os_exemplos_sao_de_prefeitura_e_nao_genericos():
    """
    "Ex.: texto aqui" não ensina nada. O exemplo precisa ser uma frase
    que o servidor poderia copiar e adaptar.
    """
    vagos = {
        chave: meta["exemplo"]
        for chave, meta in CAMPOS_FORMULARIO.items()
        if len(meta["exemplo"]) < 25
        or meta["exemplo"].lower().startswith(("ex.:", "exemplo"))
    }
    assert not vagos, vagos


@pytest.mark.parametrize("chave", sorted(CAMPOS_FORMULARIO))
def test_o_exemplo_nao_repete_o_rotulo(chave):
    """Exemplo que só repete o nome do campo ocupa espaço sem ensinar."""
    meta = CAMPOS_FORMULARIO[chave]
    assert meta["exemplo"].strip().lower() != meta["rotulo_tela"].strip().lower()


def test_os_exemplos_falam_de_uma_compra_plausivel():
    """
    Coerência entre campos: os exemplos contam UMA história (material de
    expediente para escolas municipais). Exemplos desconexos entre si
    fazem o servidor achar que cada campo é de um processo diferente.
    """
    texto = " ".join(m["exemplo"] for m in CAMPOS_FORMULARIO.values()).lower()
    assert "escola" in texto
    assert "expediente" in texto or "papel" in texto


# ---------------------------------------------------------------------------
# A TELA usa mesmo o rótulo simples?
#
# As provas acima garantem que os dois textos existem e são diferentes —
# mas nenhuma delas olhava para o que o servidor vê. Reverter `_campo`
# para `meta["rotulo"]` passava por toda a suíte. Esta prova nasceu de uma
# mutação que escapou.
# ---------------------------------------------------------------------------
def _formulario_do_servidor(monkeypatch):
    """
    Abre "Novo processo" como servidor comum, sem banco real.

    Vale a pena estar num lugar só: são cinco provas olhando a MESMA
    tela, e cada cópia do preâmbulo seria mais uma chance de uma delas
    passar a testar uma tela diferente das outras sem ninguém notar.
    """
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    from src import auth, db

    monkeypatch.setattr(auth, "precisa_configurar", lambda: False)
    monkeypatch.setattr(auth, "modo_aberto", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(auth, "eh_admin", lambda: False)
    monkeypatch.setattr(
        auth, "usuario_logado",
        lambda: {"id": "u1", "nome": "S", "login": "s", "papel": "usuario"})
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: False)

    at = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "app.py"), default_timeout=60)
    at.session_state["pagina"] = "Novo processo"
    at.run()
    assert not at.exception
    return at


def test_a_tela_mostra_o_rotulo_simples_e_nao_o_canonico(monkeypatch):
    at = _formulario_do_servidor(monkeypatch)

    rotulos = [w.label for w in list(at.text_input) + list(at.text_area)
               + list(at.selectbox)]
    texto = " ".join(rotulos)

    # O simples aparece…
    assert "Quem está pedindo" in texto
    assert "O que vai ser comprado ou contratado" in texto
    # …e o canônico, cheio de jargão, não.
    assert "Órgão / Entidade Requisitante" not in texto
    assert "Objeto Detalhado da Contratação" not in texto


def test_o_exemplo_aparece_abaixo_do_campo(monkeypatch):
    """
    O exemplo no placeholder sumia ao digitar a primeira letra. Abaixo do
    campo ele fica — e é isso que esta prova fixa.
    """
    at = _formulario_do_servidor(monkeypatch)

    legendas = " ".join(c.value for c in at.caption)
    assert "Exemplo:" in legendas
    assert "Secretaria de Educação" in legendas


def test_o_formulario_diz_quanto_falta_antes_de_submeter(monkeypatch):
    """
    Antes, o aviso de campos obrigatórios só vinha no clique de avançar —
    depois de rolar a página inteira.
    """
    at = _formulario_do_servidor(monkeypatch)

    legendas = " ".join(c.value for c in at.caption)
    assert "campos obrigatórios" in legendas
    assert "Ainda falta" in legendas


# ---------------------------------------------------------------------------
# A planilha é um campo como os outros
#
# `itens` não passa por `_campo`: tem editor próprio, `_render_planilha`,
# que escrevia o rótulo e a ajuda à mão. Ficou de fora da simplificação —
# e um campo em jargão no meio de dez em linguagem simples é pior do que
# dez em jargão, porque parece erro de tela.
# ---------------------------------------------------------------------------
def test_a_planilha_tambem_fala_a_lingua_simples(monkeypatch):
    at = _formulario_do_servidor(monkeypatch)

    texto = " ".join(
        [m.value for m in at.markdown] + [c.value for c in at.caption])

    assert "Lista de itens e preços" in texto
    assert "Planilha Orçamentária (itens da contratação)" not in texto
    # A ajuda canônica da planilha cita o artigo; a de tela, não.
    assert "Um item por linha" in texto


# ---------------------------------------------------------------------------
# O assistente também é tela
#
# O GovBot respondia "o que preencher aqui?" devolvendo `help` — o texto
# canônico, com artigo de lei. Simplificar o formulário e deixar o
# assistente falando em jargão devolveria o servidor ao ponto de partida
# justamente na hora em que ele pediu ajuda.
#
# Nada disso toca o prompt de geração: `prompts.py` monta o prompt com
# `rotulo`, nunca com `help`.
# ---------------------------------------------------------------------------
def test_a_orientacao_do_assistente_usa_a_ajuda_simples():
    from src import govbot

    contexto = govbot.GovBotContext(
        processo_id="p1", etapa=1, campo_em_foco="orgao")
    intent = govbot.orientacao_local(contexto, "o que preencher")

    assert intent is not None
    assert CAMPOS_FORMULARIO["orgao"]["ajuda_simples"] in intent.response
    assert "art." not in intent.response


def test_a_orientacao_do_assistente_mostra_o_exemplo():
    """
    Quem pergunta "o que preencher aqui?" quer ver uma frase pronta mais
    do que uma definição. O exemplo já existe no catálogo de campos;
    escondê-lo do assistente seria tê-lo escrito duas vezes e usado uma.
    """
    from src import govbot

    contexto = govbot.GovBotContext(
        processo_id="p1", etapa=1, campo_em_foco="orgao")
    intent = govbot.orientacao_local(contexto, "o que preencher")

    assert CAMPOS_FORMULARIO["orgao"]["exemplo"] in intent.response


def test_o_painel_do_assistente_entrega_a_ajuda_simples():
    from src import govbot

    contexto = govbot.GovBotContext(
        processo_id="p1", etapa=1, campo_em_foco="justificativa")
    view = govbot.montar_view_model({}, contexto)

    orientacao = view["guidance"]["justificativa"]
    assert orientacao == CAMPOS_FORMULARIO["justificativa"]["ajuda_simples"]


def test_o_assistente_nao_fica_mudo_num_campo_sem_ajuda_simples(monkeypatch):
    """
    A queda para `help` não é detalhe: um campo novo, cadastrado sem
    `ajuda_simples`, faria o assistente responder com string vazia — e
    "não sei" silencioso é pior do que jargão.
    """
    from src import govbot

    campos = {
        chave: (dict(meta, ajuda_simples="", exemplo="") if chave == "orgao"
                else meta)
        for chave, meta in CAMPOS_FORMULARIO.items()
    }
    monkeypatch.setattr(govbot, "CAMPOS_FORMULARIO", campos)

    contexto = govbot.GovBotContext(
        processo_id="p1", etapa=1, campo_em_foco="orgao")
    intent = govbot.orientacao_local(contexto, "o que preencher")

    assert intent.response == CAMPOS_FORMULARIO["orgao"]["help"]


# ---------------------------------------------------------------------------
# O contador de obrigatórios depois de salvar — achado da navegação (§5/§16)
#
# MEDIDO NO NAVEGADOR, não deduzido: com o formulário inteiro preenchido
# e o rascunho salvo, a tela dizia
#
#   "1 de 5 campos obrigatórios preenchidos. Ainda falta: Quem está
#    pedindo, O que vai ser comprado ou contratado, Por que isso é
#    necessário, Como a entrega vai acontecer."
#
# listando exatamente os quatro campos que o servidor acabara de
# preencher — e logo abaixo, "Rascunho salvo.".
#
# CAUSA: o contador é desenhado ANTES do `st.form`, lendo
# `st.session_state.dados`; e widget dentro de um `st.form` só chega ao
# estado no submit. O caminho "Iniciar elaboração" já fazia `st.rerun()`
# e por isso nunca mostrou o defeito; o de "Salvar rascunho" não fazia.
#
# CONSEQUÊNCIA para quem usa (§16): confusão e retrabalho. O servidor é
# informado de que os campos obrigatórios estão vazios no instante
# seguinte a preenchê-los e salvá-los, e a saída natural é digitar tudo
# de novo.
# ---------------------------------------------------------------------------
def _formulario_preenchido():
    from tests.test_app import _app_modo_aberto  # noqa: PLC0415

    at = _app_modo_aberto()
    at.run()
    assert not at.exception
    return at


def test_contador_de_obrigatorios_acompanha_o_rascunho_salvo():
    at = _formulario_preenchido()

    valores = {
        "Quem está pedindo": "Prefeitura de Ensaio — Secretaria de Compras",
        "O que vai ser comprado": "Aquisição de material de expediente.",
        "Por que isso é necessário": "Reposição do estoque do almoxarifado.",
    }
    for trecho, valor in valores.items():
        alvos = [e for e in list(at.text_input) + list(at.text_area)
                 if trecho.lower() in (e.label or "").lower()]
        assert alvos, f"campo {trecho!r} não encontrado"
        alvos[0].set_value(valor)

    at.session_state["dados"] = dict(at.session_state.get("dados") or {})
    salvar = [b for b in at.button if "rascunho" in (b.label or "").lower()]
    assert salvar, [b.label for b in at.button]
    salvar[0].click().run()
    assert not at.exception

    legendas = " ".join(c.value for c in at.caption)
    assert "Ainda falta: Quem está pedindo" not in legendas, (
        "depois de salvar, a tela ainda pede os campos que acabaram de ser "
        f"preenchidos. Legendas: {legendas[:300]}")


def test_o_aviso_de_rascunho_salvo_sobrevive_ao_rerun():
    """
    O rerun que conserta o contador não pode engolir a confirmação: sem
    ela, o servidor clica em salvar e nada acontece na tela.
    """
    at = _formulario_preenchido()
    salvar = [b for b in at.button if "rascunho" in (b.label or "").lower()]
    salvar[0].click().run()
    assert not at.exception
    sucessos = " ".join(s.value for s in at.success)
    assert "ascunho" in sucessos, (
        f"nenhuma confirmação de salvamento na tela: {sucessos[:200]}")
