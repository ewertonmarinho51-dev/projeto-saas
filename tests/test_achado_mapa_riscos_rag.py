"""
ACHADO DA AUDITORIA PRÉ-OPERACIONAL: o Mapa de Riscos não gerava.

O DEFEITO, como foi encontrado

Na bateria do §8, com a pilha de homologação de pé e a IA simulada
respondendo, os quatro documentos do fluxo foram gerados em sequência.
Dois responderam; `mapa_riscos` morreu com `KeyError: 'mapa_riscos'` em
`rag.montar_consulta` — e `dfd` morreu com `KeyError: 'dfd'` em
`prompts.montar_prompt`, este último só porque o teste passou um
contexto anterior que o app nunca passa ao primeiro documento.

O do Mapa de Riscos é real e chega ao usuário:

    config.SEQUENCIA_COM_MAPA = [dfd, etp, mapa_riscos, tr, edital]
    state.configurar_fluxo() liga o fluxo quando `flag_mapa_riscos` = 1
    produção tem `flag_mapa_riscos` = 1 (medido em 22/09/2026)

    steps._gerar → llm.gerar_documento("mapa_riscos", …)
                 → rag.montar_contexto → recuperar → montar_consulta
                 → nomes["mapa_riscos"] → KeyError

`recuperar` só devolve cedo quando `db.disponivel()` é falso. Em
produção o banco existe, então o caminho chega inteiro ao dicionário
incompleto. `steps._gerar` captura `Exception` e mostra "Não foi
possível concluir o documento" — o servidor vê uma falha genérica,
recorrente, sem causa, e o log guarda só `tipo=KeyError`.

Como a etapa precisa ser APROVADA para o fluxo avançar, o efeito não é
um documento a menos: é o processo inteiro travado no meio, sem chegar
ao TR nem ao Edital.

POR QUE A SUÍTE NÃO PEGOU

`rag.montar_consulta` tem teste; o Mapa de Riscos tem teste; a geração
tem teste. Nenhum cruzava os dois: os testes de geração dublam o RAG
(`montar_bloco_referencias`/`montar_contexto`), e os testes de RAG usam
os quatro documentos que existiam antes de o Mapa de Riscos entrar no
fluxo.

Por isso a prova que fecha este achado NÃO é "mapa_riscos funciona".
É a estrutural: TODO documento do fluxo tem de ser conhecido por
`rag.montar_consulta`. O próximo tipo de documento que alguém
acrescentar falha aqui, e não em produção.
"""

from __future__ import annotations

import pytest

from src import config, rag


DADOS = {
    "objeto": "Aquisição de materiais de expediente",
    "justificativa": "Reposição do estoque anual das unidades",
    "modelo_execucao": "Entrega parcelada",
}


# ---------------------------------------------------------------------------
# 1) A prova ESTRUTURAL — a que impede a repetição
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("doc_key", config.SEQUENCIA_COM_MAPA)
def test_todo_documento_do_fluxo_tem_consulta_de_rag(doc_key):
    """
    Um documento no fluxo que o RAG não conhece derruba a geração dele.

    Parametrizado pela SEQUÊNCIA, e não por uma lista escrita à mão:
    quem acrescentar um documento ao fluxo ganha o caso de teste de
    graça, que é o único jeito de esta prova continuar valendo.
    """
    consulta = rag.montar_consulta(DADOS, doc_key)
    assert consulta, f"{doc_key}: consulta vazia"
    assert DADOS["objeto"] in consulta


def test_a_consulta_do_mapa_de_riscos_fala_de_risco():
    """
    Não basta não quebrar. Se a consulta do Mapa de Riscos fosse só o
    objeto, o RAG traria material de qualquer documento e o mapa nasceria
    sem lastro — defeito silencioso no lugar de um ruidoso.
    """
    consulta = rag.montar_consulta(DADOS, "mapa_riscos").lower()
    assert "risco" in consulta


# ---------------------------------------------------------------------------
# 2) O CONTRATO de `montar_contexto`: "nunca levanta"
# ---------------------------------------------------------------------------
def test_montar_contexto_nao_levanta_nem_com_documento_desconhecido(
        monkeypatch):
    """
    A docstring de `recuperar` promete "nunca levanta" e a de
    `montar_contexto` diz "RAG é enriquecimento". A promessa valia só
    para `ErroRAG`: qualquer outra exceção subia e derrubava a geração.

    É a diferença entre "o Mapa de Riscos sai sem referências" e "o
    Mapa de Riscos não sai" — e foi a segunda que aconteceu.
    """
    monkeypatch.setattr(rag.db, "disponivel", lambda: True)
    monkeypatch.setattr(rag, "recuperar",
                        lambda *_a, **_k: (_ for _ in ()).throw(
                            KeyError("documento que ninguém cadastrou")))

    contexto = rag.montar_contexto(DADOS, "documento_do_futuro")

    assert contexto["bloco"] == ""
    assert contexto["trace"]["erro"], (
        "a falha precisa ficar no rastro — engolir sem registrar troca um "
        "defeito visível por um invisível")
