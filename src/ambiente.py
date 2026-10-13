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


def versao() -> dict:
    """Release e commit GRAVADOS NA IMAGEM (ver implantacao/Dockerfile)."""
    return {
        "release": (os.environ.get("GOVDOCS_RELEASE") or "").strip()
        or "desconhecida",
        "commit": (os.environ.get("GOVDOCS_COMMIT") or "").strip()
        or "desconhecido",
    }


def diagnostico() -> list[tuple[str, str, str]]:
    """
    (serviço, estado, detalhe) por subsistema — para o ADMINISTRADOR.

    O health do Streamlit só prova que o processo responde. Isto diz se
    banco, Auth, OpenRouter, embeddings e Jev estão em condição de
    trabalhar. Nada aqui carrega chave, token, URL de projeto ou
    mensagem crua de exceção — falha vira referência de correlação.
    """
    from . import db, governanca, llm

    linhas: list[tuple[str, str, str]] = []
    v = versao()
    linhas.append(("Versão", "ok" if v["commit"] != "desconhecido"
                   else "atenção", f"{v['release']} · {v['commit'][:12]}"))
    if db.em_manutencao():
        linhas.append(("Banco", "falha", "em manutenção (credencial)"))
    else:
        try:
            (db._cliente().table("config_app")  # noqa: SLF001
             .select("chave").limit(1).execute())
            linhas.append(("Banco", "ok", "consulta respondida"))
        except Exception as exc:  # noqa: BLE001
            linhas.append(("Banco", "falha", "referência "
                           + db.registrar_incidente(exc, "diagnostico: banco")))
    com_jwt = bool(db.sessao_do_usuario())
    linhas.append(("Auth", "ok" if com_jwt else "atenção",
                   "sessão Supabase Auth ativa" if com_jwt
                   else "login legado (sem JWT)"))
    chave = bool(llm.obter_openrouter_key())
    exclusivo = llm.modo_exclusivo_openrouter()
    linhas.append(("OpenRouter", "ok" if chave and exclusivo else "atenção",
                   ("provedor exclusivo" if exclusivo else "não exclusivo")
                   + (" · chave configurada" if chave else " · sem chave")))
    rota = llm.rota_de_embeddings()
    linhas.append(("Embeddings", "ok" if rota else "atenção",
                   f"vetorial via {rota[0]}" if rota else "textual degradado"))
    jev = db.flag_ativa(governanca.FLAG_JEV_PRECOS)
    linhas.append(("Jev", "ok" if jev and chave else "desligado",
                   "Decisions com revisão humana" if jev
                   else "flag desligada"))
    return linhas


# Endereços que PROVAM não ser o Supabase hospedado. A pilha de
# homologação local (`scripts/homologacao_stack.py`) serve o PostgREST
# em loopback; nada que responda em loopback é o banco da Prefeitura.
_HOSPEDEIROS_LOCAIS = ("127.0.0.1", "localhost", "::1", "[::1]")


def grava_em_producao() -> bool:
    """
    O banco desta instalação é o de produção?

    Devolve False só quando dá para PROVAR que não é — hoje, quando o
    banco é servido em loopback. Qualquer outra coisa devolve True,
    inclusive um projeto Supabase hospedado que não seja o de produção:
    "não consigo provar que é separado" tem de ser tratado como
    produção, que é a leitura mais séria.

    Até a auditoria pré-operacional de 24/09/2026 isto devolvia True sem
    condição, porque não existia instalação com banco separado. Passou a
    existir, e a tarja começou a MENTIR — anunciava "o banco é o de
    produção" numa instalação isolada. Aviso que erra desse lado é pior
    que aviso nenhum: ensina a ignorá-lo, e é o mesmo aviso que precisa
    ser levado a sério quando a instalação de fato escreve em produção.
    """
    from . import db

    url = db._segredo("SUPABASE_URL").strip().lower()  # noqa: SLF001
    if not url:
        return True
    try:
        from urllib.parse import urlsplit

        hospedeiro = (urlsplit(url).hostname or "").strip().lower()
    except ValueError:
        return True
    return hospedeiro not in _HOSPEDEIROS_LOCAIS


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
