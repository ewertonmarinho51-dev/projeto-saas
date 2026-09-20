"""
Qual instalação está rodando — e, sobretudo, se ela grava em produção.

POR QUE ISTO EXISTE

Em 19/09/2026 o operador decidiu manter o Streamlit Cloud no ar depois
de subir o VPS, para conferir alterações antes de promovê-las. E decidiu
também que ele continua apontando para o **banco de produção**.

As duas decisões são dele e estão registradas. A consequência não é
opinião:

    o Streamlit Cloud NÃO é um ambiente de teste.
    É um segundo acesso a produção, com outra URL.

Processo criado ali é processo real. Documento aprovado ali congela
snapshot real. Evento gravado ali entra na trilha de governança — que
desde a 0027 a credencial do app não apaga mais, então lixo de teste
fica. E as flags de `config_app` são GLOBAIS (a chave primária é só
`chave`), então ligar uma flag "para experimentar" muda produção na
hora, para todo mundo, inclusive para quem está no VPS.

Quem abre a tela precisa saber disso ANTES de clicar. É só o que este
módulo faz: dizer em que instalação você está e se o que você fizer
tem consequência real.

O QUE ELE NÃO FAZ

Não impede nada. Não há aqui um modo "seguro" que desligue escrita —
isso seria uma segunda verdade sobre o que o sistema faz, e ela
divergiria da primeira no primeiro caminho que alguém esquecesse de
cobrir. A contenção de verdade é apontar para outro banco, e essa
decisão foi tomada no outro sentido.
"""

from __future__ import annotations

import os

import streamlit as st

# Definida no ambiente de cada instalação. Ausente = produção, e o
# default é esse de propósito: uma instalação que esqueceu de se
# declarar deve ser tratada como a mais séria, não como a menos.
VARIAVEL = "GOVDOCS_AMBIENTE"

PRODUCAO = "producao"
HOMOLOGACAO = "homologacao"

ROTULOS = {
    PRODUCAO: "Produção",
    HOMOLOGACAO: "Homologação",
}


def atual() -> str:
    """O ambiente declarado. Desconhecido ou ausente → produção."""
    valor = (os.environ.get(VARIAVEL) or "").strip().lower()
    return valor if valor in ROTULOS else PRODUCAO


def rotulo() -> str:
    return ROTULOS[atual()]


def grava_em_producao() -> bool:
    """
    O banco desta instalação é o de produção?

    Hoje devolve True SEMPRE, e o motivo está no cabeçalho: a
    homologação aponta para o mesmo Supabase. A função existe separada
    de `atual()` justamente para que o dia em que isso mudar seja uma
    mudança de UMA linha com prova, e não uma caçada por todos os
    lugares que assumiram a coincidência.
    """
    return True


def render_aviso() -> None:
    """
    A tarja da homologação. Em produção não desenha nada.

    Moldura permanente ninguém lê — mas esta não é decoração: ela diz
    que o clique seguinte tem consequência real. Por isso fica no topo
    e por isso é `error`, e não `info`: o risco aqui não é o usuário
    achar que está em produção quando não está. É o contrário.
    """
    if atual() != HOMOLOGACAO:
        return

    if grava_em_producao():
        st.error(
            "**HOMOLOGAÇÃO — mas o banco é o de PRODUÇÃO.**  \n"
            "Tudo que você fizer aqui é real: processo criado é processo "
            "real, documento aprovado congela assinatura de verdade, e "
            "evento gravado entra na trilha de governança, de onde não "
            "sai mais. **Flag ligada aqui muda produção para todo mundo.**"
            "  \nUse esta instalação para conferir tela e comportamento "
            "de código — não para testar dados nem configuração."
        )
    else:
        st.info(
            "**Homologação.** Banco separado: o que você fizer aqui não "
            "alcança produção."
        )
