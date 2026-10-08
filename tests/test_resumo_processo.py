"""
Contexto canônico: a economia não pode custar uma decisão.

O QUE ESTAS PROVAS GUARDAM

Recortar o contexto é a maior economia disponível (71% dos tokens de
entrada de um processo de 210 itens, medido em `docs/custo/antes.json`).
É também a mudança com o pior modo de falha do trabalho inteiro: um TR
que não souber qual solução o ETP escolheu vai escolher outra, e a
cadeia passa a mentir — sem erro na tela, sem achado, sem aviso.

Por isso as provas aqui não conferem "ficou menor". Conferem que cada
decisão que o próximo documento HERDA continua atravessando, e que
quando o módulo não tem certeza ele manda o documento inteiro em vez de
adivinhar.
"""

from __future__ import annotations

import pytest

from src import perfis, resumo_processo


def _documento(doc_key: str, *, com_tabela: bool = False,
               marca_por_clausula: str = "conteudo") -> str:
    """
    Um documento com a estrutura REAL dos perfis — a mesma que o prompt
    exige e a validação confere. Cada cláusula carrega uma marca única,
    para a prova poder dizer QUAL cláusula atravessou.
    """
    partes = []
    for c in perfis.PERFIS[doc_key]["clausulas"]:
        partes.append(f"## {c['n']}. {c['titulo']}")
        partes.append(f"{c['n']}.1. {marca_por_clausula}-{doc_key}-{c['n']} "
                      + "texto desenvolvido da cláusula. " * 8)
        if com_tabela and c["tabela"]:
            # Linhas CONSECUTIVAS, como o injetor de tabela escreve —
            # uma tabela Markdown não tem linha em branco no meio.
            linhas = ["| Item | Código | Descrição | Valor |",
                      "|---|---|---|---|"]
            linhas += [f"| {i} | {i:05d} | Material {i} | R$ 1,00 |"
                       for i in range(1, 40)]
            partes.append("\n".join(linhas))
    return "\n\n".join(partes)


DFD = _documento("dfd", com_tabela=True)
ETP = _documento("etp", com_tabela=True)


# ---------------------------------------------------------------------------
# A decisão atravessa
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("clausula", resumo_processo.PRECISA_DE["tr"]["etp"])
def test_cada_clausula_declarada_do_etp_chega_ao_tr(clausula):
    """
    O mapa `PRECISA_DE` é a promessa. Esta prova é a cobrança dela,
    cláusula por cláusula — e falha nomeando a que sumiu.
    """
    contexto = resumo_processo.contexto_canonico({"etp": ETP}, "tr")
    if not any(c["n"] == clausula
               for c in perfis.PERFIS["etp"]["clausulas"]):
        pytest.skip(f"cláusula {clausula} não existe no perfil do ETP")
    assert f"conteudo-etp-{clausula}" in contexto, (
        f"a cláusula {clausula} do ETP foi declarada como necessária ao TR "
        "e não chegou nele — o TR vai decidir de novo o que o estudo já "
        "decidiu")


def test_a_solucao_escolhida_e_os_requisitos_nunca_ficam_de_fora():
    """
    As duas heranças sem as quais o TR é outro documento: a cláusula 4
    (requisitos) e a 6 (descrição da solução). Se alguém "otimizar" o
    mapa e tirar uma delas, é aqui que aparece.
    """
    for doc in ("mapa_riscos", "tr"):
        pedidas = resumo_processo.PRECISA_DE[doc]["etp"]
        assert 4 in pedidas and 6 in pedidas, (
            f"{doc}: sem requisitos (4) ou sem solução escolhida (6), o "
            "documento não herda a decisão do ETP — ele a substitui")


def test_o_dfd_entrega_ao_etp_a_necessidade_e_a_solucao_proposta():
    contexto = resumo_processo.contexto_canonico({"dfd": DFD}, "etp")
    for clausula in (2, 3, 4):
        assert f"conteudo-dfd-{clausula}" in contexto


# ---------------------------------------------------------------------------
# O que sai, sai de propósito
# ---------------------------------------------------------------------------
def test_a_tabela_de_itens_nao_viaja_no_contexto():
    """
    A tabela é determinística: nasce da planilha, é injetada por código e
    conferida item a item contra ela. No prompt do documento seguinte é
    peso morto — e era o maior item da conta.
    """
    contexto = resumo_processo.contexto_canonico({"etp": ETP}, "tr")
    assert "| 00001 |" not in contexto
    assert "Material 39" not in contexto
    assert "tabela de" in contexto and "omitida" in contexto, (
        "a tabela saiu sem deixar rastro: o modelo leria uma cláusula de "
        "quantitativo sem quantitativo e poderia concluir que o dado não "
        "existe")


def test_tabela_com_linha_em_branco_no_meio_nao_vira_um_aviso_por_linha():
    """
    Achado durante a implementação: a primeira versão fechava a tabela
    em qualquer linha em branco, então um documento com a tabela
    espaçada ganhava um aviso de omissão POR LINHA — e o contexto
    "reduzido" saía MAIOR que o original. O modo de falha era o oposto
    do objetivo e não levantava erro nenhum.
    """
    espacada = "\n\n".join(
        [f"| {i} | {i:05d} | Material {i} | R$ 1,00 |" for i in range(40)])
    texto = f"## 1. DO OBJETO\n\nprosa\n\n{espacada}\n\nfim da cláusula"
    limpo = resumo_processo.sem_tabelas(texto)
    assert limpo.count("omitida") == 1, limpo
    assert len(limpo) < len(texto) / 4


def test_o_levantamento_de_solucoes_nao_vai_para_o_tr():
    """
    A cláusula 5 do ETP (10 a 35 blocos) é a comparação entre
    alternativas que levou à escolha. O TR não reabre a escolha — a
    instrução dele proíbe. Mandá-la é pagar pelo raciocínio de outro
    documento.
    """
    contexto = resumo_processo.contexto_canonico({"etp": ETP}, "tr")
    assert "conteudo-etp-5" not in contexto


def test_nome_de_agente_nao_se_herda():
    """
    A regra 15 do system prompt: nome, cargo e matrícula só entram se
    constarem do processo. A EQUIPE DE PLANEJAMENTO do DFD (cláusula 9)
    não pode virar fonte para o ETP preencher a dele.
    """
    contexto = resumo_processo.contexto_canonico({"dfd": DFD}, "etp")
    assert "conteudo-dfd-9" not in contexto


def test_o_contexto_encolhe_de_verdade():
    medida = resumo_processo.economia({"dfd": DFD, "etp": ETP}, "tr")
    assert medida["caracteres_depois"] < medida["caracteres_antes"] * 0.5, (
        f"redução insuficiente: {medida}")


# ---------------------------------------------------------------------------
# Na dúvida, o documento inteiro
# ---------------------------------------------------------------------------
def test_documento_sem_a_numeracao_dos_perfis_vai_inteiro():
    """
    Documento importado, editado à mão ou renumerado: recortar "a
    cláusula 6" dele entregaria o texto errado com a etiqueta certa.
    A recusa de adivinhar é a defesa.
    """
    estranho = ("## 1. PREÂMBULO\n\nAlgo.\n\n"
                "## 2. OUTRA COISA QUALQUER\n\nTexto que não segue perfil.\n\n"
                "## 3. TERCEIRA\n\nMais texto.")
    contexto = resumo_processo.contexto_canonico({"etp": estranho}, "tr")
    assert "OUTRA COISA QUALQUER" in contexto
    assert "íntegra" in contexto, (
        "caiu para o documento inteiro sem dizer que caiu — o rastro "
        "precisa registrar por que aquele processo pagou o dobro")


def test_clausula_obrigatoria_faltando_derruba_o_recorte():
    """
    Meio documento é pior que documento inteiro: o modelo não sabe que
    está incompleto e preenche a lacuna por plausibilidade.
    """
    sem_requisitos = "\n\n".join(
        parte for parte in ETP.split("\n\n")
        if "4. DESCRIÇÃO DOS REQUISITOS" not in parte
        and "conteudo-etp-4" not in parte)
    contexto = resumo_processo.contexto_canonico({"etp": sem_requisitos}, "tr")
    assert "íntegra" in contexto


def test_clausula_condicional_ausente_nao_derruba_o_recorte():
    """
    A mutação que importa: tratar toda ausência como suspeita faria
    TODO processo sem registro de preços cair no documento integral — a
    cláusula 17 do ETP só existe em SRP. A economia iria a zero na
    maioria dos processos, em silêncio.
    """
    assert not next(c for c in perfis.PERFIS["etp"]["clausulas"]
                    if c["n"] == 17)["obrigatoria"]
    sem_srp = "\n\n".join(
        parte for parte in ETP.split("\n\n")
        if "17. POSSIBILIDADE DE RENOVAÇÃO" not in parte
        and "conteudo-etp-17" not in parte)
    contexto = resumo_processo.contexto_canonico({"etp": sem_srp}, "tr")
    assert "DECISÕES HERDADAS" in contexto
    assert "conteudo-etp-6" in contexto


def test_sem_nada_aprovado_o_contexto_e_none():
    assert resumo_processo.contexto_canonico({}, "etp") is None
    assert resumo_processo.contexto_canonico({"dfd": "   "}, "etp") is None


def test_flag_desligada_mantem_o_contexto_de_antes(monkeypatch):
    """
    Rollback é desligar a flag. Se o contexto canônico saísse com a flag
    desligada, não haveria rollback — haveria um caminho novo obrigatório.
    """
    import streamlit as st

    from src import state

    monkeypatch.setattr(resumo_processo, "ativo", lambda: False)
    monkeypatch.setattr(state, "sequencia", lambda: ["dfd", "etp", "tr"])
    st.session_state["documentos"] = {"dfd": DFD}
    st.session_state["aprovados"] = {"dfd"}
    contexto = state.contexto_para_documento("etp")
    assert "| 00001 |" in contexto, (
        "com a flag desligada o contexto tem de ser o antigo, tabela "
        "inclusive")
    assert "conteudo-dfd-9" in contexto
