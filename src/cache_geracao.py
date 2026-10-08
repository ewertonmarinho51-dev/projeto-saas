"""
Cache de geração — a mesma pergunta não se paga duas vezes.

O QUE ELE RESOLVE

Quatro caminhos levavam à mesma chamada paga acontecer de novo sem que
nada tivesse mudado no processo:

  * clique duplo no botão de gerar;
  * rerun do Streamlit (toda interação reexecuta o script inteiro);
  * reload da página, que apaga `st.session_state` por completo;
  * "Tentar novamente" depois de uma falha que aconteceu DEPOIS de o
    provedor já ter gerado e cobrado — timeout de leitura é o caso
    clássico.

Os três primeiros o cache resolve devolvendo o texto guardado. O quarto
não tem solução do lado de cá: se a resposta não chegou, não há o que
guardar. Para ele existe a CHAVE DE IDEMPOTÊNCIA enviada ao provedor
(`llm._cabecalhos_de_idempotencia`), que faz a repetição devolver a
resposta original em vez de gerar uma segunda.

A CHAVE

É o hash do que efetivamente determina a saída: motor, modelo, e os dois
prompts já montados — com formulário, planilha calculada, contexto da
cadeia aprovada, RAG recuperado e diretrizes dentro deles. Usar o prompt
pronto, e não uma lista de campos escolhida a dedo, é o que impede o
erro clássico deste tipo de cache: alguém acrescenta uma fonte ao prompt,
esquece de somá-la à chave, e o sistema passa a servir documento montado
com contexto velho. Aqui isso é impossível por construção — se o prompt
mudou, a chave mudou.

`VERSAO_DO_FORMATO` entra na chave para que uma mudança no formato do
registro invalide o guardado sem ninguém precisar limpar tabela.

ESCOPO

Tenant e processo. O acerto de cache de um município nunca alcança
outro: a chave inclui o conteúdo do processo, mas a CONSULTA é filtrada
por `tenant_id` — a mesma contenção de `db.py`, pela mesma razão (o
`service_role` ignora RLS, então o `.eq("tenant_id", ...)` é a defesa
real e não um enfeite).

O QUE NUNCA ENTRA NO CACHE

Geração que falhou, geração do Modo Demonstração e instrumento
determinístico (edital/ARP não chamam modelo nenhum — cacheá-los seria
guardar o resultado de uma função pura).
"""

from __future__ import annotations

import hashlib
import logging

import streamlit as st

from . import db

FLAG = "cache_geracao"

# Muda quando muda o que a chave cobre ou o formato do guardado.
VERSAO_DO_FORMATO = 1

TABELA = "cache_geracoes"
CHAVE_NA_SESSAO = "_cache_geracao"

_log = logging.getLogger("govdocs.cache")


def ativo() -> bool:
    try:
        return db.flag_ativa(FLAG)
    except Exception:  # noqa: BLE001 — banco fora não pode derrubar geração
        return False


def chave(motor: str, modelo: str, system_prompt: str,
          user_prompt: str) -> str:
    """
    Identidade da geração: o que sai do modelo só depende disto.

    `modelo` pode vir vazio quando o motor ainda não escolheu qual
    tentará — nesse caso a chave cobre a LISTA de candidatos, que é o
    que de fato determina a resposta.
    """
    material = "\u0000".join((
        str(VERSAO_DO_FORMATO), motor or "", modelo or "",
        system_prompt or "", user_prompt or "",
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Camada 1 — sessão. Cobre clique duplo e rerun, sem tocar no banco.
# ---------------------------------------------------------------------------
def _da_sessao(chave_hash: str) -> dict | None:
    return (st.session_state.get(CHAVE_NA_SESSAO) or {}).get(chave_hash)


def _para_a_sessao(chave_hash: str, registro: dict) -> None:
    guardado = st.session_state.setdefault(CHAVE_NA_SESSAO, {})
    guardado[chave_hash] = registro
    # Teto pequeno de propósito: um processo tem cinco documentos, e o
    # que interessa é o da sessão corrente. Sem teto, uma sessão longa
    # carregaria dezenas de documentos inteiros na memória do servidor.
    if len(guardado) > 12:
        for antiga in list(guardado)[:-12]:
            guardado.pop(antiga, None)


# ---------------------------------------------------------------------------
# Camada 2 — banco. Cobre reload e sessão nova.
# ---------------------------------------------------------------------------
def _do_banco(chave_hash: str, processo_id: str | None) -> dict | None:
    if not processo_id or not db.disponivel():
        return None
    try:
        resposta = (
            db._cliente().table(TABELA)          # noqa: SLF001
            .select("texto, modelo, motor, tokens_entrada, tokens_saida")
            .eq("tenant_id", db.tenant_atual())
            .eq("processo_id", processo_id)
            .eq("chave", chave_hash)
            .limit(1).execute()
        )
    except Exception:  # noqa: BLE001 — sem a migração 0028, segue sem cache
        return None
    return resposta.data[0] if resposta.data else None


def _para_o_banco(chave_hash: str, processo_id: str | None, doc_key: str,
                  registro: dict) -> None:
    if not processo_id or not db.disponivel():
        return
    linha = {
        "tenant_id": db.tenant_atual(),
        "processo_id": processo_id,
        "documento": doc_key,
        "chave": chave_hash,
        "motor": registro.get("motor", ""),
        "modelo": registro.get("modelo", ""),
        "texto": registro.get("texto", ""),
        "tokens_entrada": registro.get("tokens_entrada"),
        "tokens_saida": registro.get("tokens_saida"),
    }
    try:
        db._cliente().table(TABELA).upsert(   # noqa: SLF001
            linha, on_conflict="tenant_id,chave").execute()
    except Exception as erro:  # noqa: BLE001
        # Guardar no cache NUNCA pode derrubar a geração que acabou de
        # dar certo. O documento já existe; o cache é conveniência.
        _log.warning("cache de geração não gravado: %s", type(erro).__name__)


# ---------------------------------------------------------------------------
# Fachada
# ---------------------------------------------------------------------------
def buscar(chave_hash: str, processo_id: str | None) -> dict | None:
    """Registro guardado para esta chave, ou None. Nunca levanta."""
    if not ativo():
        return None
    try:
        return _da_sessao(chave_hash) or _do_banco(chave_hash, processo_id)
    except Exception:  # noqa: BLE001
        return None


def guardar(chave_hash: str, processo_id: str | None, doc_key: str,
            registro: dict) -> None:
    """Guarda uma geração BEM-SUCEDIDA. Nunca levanta."""
    if not ativo() or not (registro.get("texto") or "").strip():
        return
    try:
        _para_a_sessao(chave_hash, registro)
        _para_o_banco(chave_hash, processo_id, doc_key, registro)
    except Exception:  # noqa: BLE001
        pass


def invalidar_processo(processo_id: str | None) -> None:
    """
    Apaga o cache de um processo.

    Existe para o caminho em que o servidor quer MESMO outra redação do
    mesmo pedido — "gerar de novo" com os dados idênticos. Sem isto, o
    cache transformaria um botão de regerar em um botão sem efeito, o
    que é pior que a chamada repetida: o servidor clicaria achando que
    pediu texto novo.
    """
    st.session_state.pop(CHAVE_NA_SESSAO, None)
    if not processo_id or not db.disponivel():
        return
    try:
        (db._cliente().table(TABELA).delete()   # noqa: SLF001
         .eq("tenant_id", db.tenant_atual())
         .eq("processo_id", processo_id).execute())
    except Exception:  # noqa: BLE001
        pass
