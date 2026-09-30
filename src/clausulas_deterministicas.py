"""
Conteúdo que o CÓDIGO sabe e o modelo não deveria estar escrevendo.

O PRINCÍPIO

Informação determinística não se pede a um modelo de linguagem. Não
porque custe caro — custa, e essa é a razão de este módulo existir
agora —, mas porque o modelo não tem como saber, e o que ele produz no
lugar é o marcador `[PREENCHER: …]` na melhor hipótese e um nome
plausível na pior.

O QUE JÁ ERA DETERMINÍSTICO ANTES DESTE MÓDULO

A tabela de itens (`planilha.injetar_tabela`), o edital e a Ata
inteiros (`templates_gov.montar_oficial`), o timbrado e o bloco de
assinaturas (`instituicional_bridge`). Este módulo acrescenta a EQUIPE
DE PLANEJAMENTO, que é cláusula obrigatória do DFD (9) e do ETP (16) e
até aqui saía como `[PREENCHER: nome e matrícula do agente]` mesmo nas
instalações em que a portaria de designação está cadastrada.

A MECÂNICA É A MESMA DA TABELA, DE PROPÓSITO

O modelo escreve o marcador `[[EQUIPE_PLANEJAMENTO]]`; o código o
substitui pelo conteúdo real. Reusar o padrão que já existe é melhor
que inventar o segundo: quem entende a injeção da tabela entende esta.

O QUE ESTE MÓDULO NÃO FAZ, E POR QUÊ

Não escreve cláusula jurídica padronizada (sanções, liquidação, prazo
e forma de pagamento do TR). Elas parecem candidatas óbvias — são
sempre iguais — e não são: o texto delas precisa vir de documento
APROVADO pela Administração, como veio o catálogo de cláusulas do
edital. Redigi-las aqui seria eu escolhendo a redação de um ato
administrativo, que é exatamente o que o catálogo versionado existe
para impedir. O caminho está aberto (`templates_gov.CLAUSULAS_BASE`);
o que falta é a fonte aprovada, não o mecanismo.

Feature flag `clausulas_deterministicas` (default OFF).
"""

from __future__ import annotations

import logging

from . import db

FLAG = "clausulas_deterministicas"

MARCADOR_EQUIPE = "[[EQUIPE_PLANEJAMENTO]]"

# Cláusulas que passam a receber o marcador, por documento. Declarado,
# e não deduzido do título, para que acrescentar uma seja um ato
# deliberado e visível.
CLAUSULAS_DA_EQUIPE = {"dfd": 9, "etp": 16}

_log = logging.getLogger("govdocs.clausulas")


def ativo() -> bool:
    try:
        return db.flag_ativa(FLAG)
    except Exception:  # noqa: BLE001 — nunca derrubar a geração
        return False


def _portaria_do_processo() -> dict | None:
    """
    Portaria vigente da equipe de planejamento, com os membros, ou None.

    Usa a MESMA resolução do bloco de assinaturas
    (`instituicional_bridge`): mesma secretaria, mesma data de
    referência — que é a CRIAÇÃO DO PROCESSO, não hoje. Se as duas
    divergissem, o documento citaria uma portaria no corpo e outra no
    rodapé, e um DFD de janeiro reaberto em dezembro passaria a citar
    outra equipe.

    NUNCA LEVANTA. Ausência de portaria é resposta legítima e comum —
    quem trata a ausência é `texto_da_equipe`, com o marcador de
    pendência.
    """
    import streamlit as st

    from . import contexto, emissao, portarias

    try:
        secretaria_id = contexto.contexto_institucional().get("secretaria_id")
        referencia = emissao.data_de_referencia(
            {"criado_em": st.session_state.get("processo_criado_em")})
        portaria = portarias.resolver(
            db.listar_portarias(secretaria_id=secretaria_id),
            secretaria_id=secretaria_id, data_referencia=referencia)
    except Exception as erro:  # noqa: BLE001 — ver a docstring
        # Conflito de portarias NÃO é resolvido por arbítrio aqui, do
        # mesmo jeito que em `instituicional_bridge`: o documento sai
        # com a pendência e o painel administrativo é onde se conserta.
        _log.warning("portaria da equipe não resolvida: %s",
                     type(erro).__name__)
        return None
    if not portaria:
        return None
    try:
        portaria = {**portaria,
                    "membros": db.listar_membros_de_portaria(portaria["id"])}
    except Exception:  # noqa: BLE001
        portaria = {**portaria, "membros": []}
    return portaria


def texto_da_equipe(portaria: dict | None) -> str:
    """
    A cláusula, escrita por código.

    Sem portaria cadastrada devolve o MARCADOR DE PENDÊNCIA, e não uma
    frase evasiva: a emissão fica bloqueada até alguém informar quem é
    a equipe, que é o comportamento correto e o que já acontecia — só
    que agora por decisão do código, e não por o modelo não saber.
    """
    from . import portarias as _portarias

    if not portaria:
        return ("[PREENCHER: portaria de designação da equipe de "
                "planejamento, com nome, cargo e matrícula de cada "
                "membro]")
    membros = _portarias.membros_vigentes(portaria.get("membros") or [])
    if not membros:
        return ("A equipe de planejamento é a designada pela "
                f"{_portarias.citacao(portaria)}. "
                "[PREENCHER: nome, cargo e matrícula de cada membro]")
    linhas = [
        f"A equipe de planejamento desta contratação é a designada pela "
        f"{_portarias.citacao(portaria)}, assim composta:",
        "",
        "| Nome | Cargo/Função | Matrícula |",
        "|---|---|---|",
    ]
    for membro in membros:
        linhas.append(
            f"| {membro.get('nome') or '[PREENCHER: nome]'} "
            f"| {membro.get('funcao') or membro.get('cargo') or '[PREENCHER: função]'} "
            f"| {membro.get('matricula') or '[PREENCHER: matrícula]'} |")
    return "\n".join(linhas)


def instrucao_para_o_prompt(doc_key: str) -> str:
    """
    O que o modelo recebe no lugar da cláusula: a ordem de não escrevê-la.

    Vale alguns tokens de entrada e economiza a cláusula inteira de
    saída — que é a troca certa, porque entrada custa menos que saída em
    todo provedor em uso.
    """
    if not ativo() or doc_key not in CLAUSULAS_DA_EQUIPE:
        return ""
    numero = CLAUSULAS_DA_EQUIPE[doc_key]
    return (
        f"\n\nCLÁUSULA {numero} (EQUIPE DE PLANEJAMENTO) — NÃO A ESCREVA. "
        f"Produza o título da cláusula e, como único conteúdo dela, a "
        f"marca {MARCADOR_EQUIPE} numa linha própria. O sistema a "
        f"substitui pela designação real, lida da portaria cadastrada. "
        f"É PROIBIDO escrever nome, cargo ou matrícula de agente nesta "
        f"cláusula, e é PROIBIDO acrescentar qualquer texto além da "
        f"marca.")


def injetar(texto: str, doc_key: str) -> str:
    """
    Substitui o marcador pela cláusula real.

    Espelha `planilha.injetar_tabela` nas duas garantias que importam:
    marcador repetido não duplica o conteúdo, e marcador ausente não
    deixa o documento sem a cláusula — só que aqui a ausência é
    resolvida deixando o que o modelo escreveu, porque a cláusula
    existe no perfil e o modelo a terá escrito do jeito antigo.
    """
    if not ativo() or MARCADOR_EQUIPE not in (texto or ""):
        return texto or ""
    conteudo = texto_da_equipe(_portaria_do_processo())
    antes, _, depois = texto.partition(MARCADOR_EQUIPE)
    depois = depois.replace(MARCADOR_EQUIPE, "")
    return (antes.rstrip() + "\n\n" + conteudo + "\n\n"
            + depois.lstrip()).strip()
