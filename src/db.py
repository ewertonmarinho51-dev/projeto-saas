"""
Persistência dos processos no Supabase (PostgreSQL).

Cada "processo" é uma linha na tabela public.processos contendo o
Formulário Matriz (jsonb), os documentos gerados/editados (jsonb), a
lista de aprovados e a etapa atual — permitindo salvar o andamento e
retomá-lo depois, de qualquer máquina.

Configuração (obrigatória apenas se quiser persistência):
    .streamlit/secrets.toml  ➜  SUPABASE_URL e SUPABASE_KEY
    ou variáveis de ambiente SUPABASE_URL / SUPABASE_KEY
A aplicação funciona normalmente sem Supabase — o painel "Processos
salvos" apenas fica desativado.
"""

import os
from datetime import datetime

import streamlit as st


class ErroBanco(Exception):
    """Erro de banco já traduzido em mensagem amigável para a interface."""


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "")
    chave = os.getenv("SUPABASE_KEY", "")
    try:
        url = str(st.secrets.get("SUPABASE_URL", url))
        chave = str(st.secrets.get("SUPABASE_KEY", chave))
    except Exception:
        pass  # sem arquivo secrets.toml — usa apenas o ambiente
    return url.strip(), chave.strip()


def disponivel() -> bool:
    """True se as credenciais do Supabase estiverem configuradas."""
    url, chave = _config()
    return bool(url and chave)


@st.cache_resource(show_spinner=False)
def _cliente():
    from supabase import create_client  # import tardio: app abre sem a lib

    url, chave = _config()
    return create_client(url, chave)


def _traduzir_erro(exc: Exception) -> ErroBanco:
    texto = str(exc).lower()
    if "connection" in texto or "timeout" in texto or "resolve" in texto:
        return ErroBanco(
            "Não foi possível conectar ao Supabase. Verifique sua internet "
            "e se o projeto está ativo (projetos gratuitos pausam por inatividade)."
        )
    if "jwt" in texto or "api key" in texto or "invalid" in texto and "key" in texto:
        return ErroBanco(
            "Credenciais do Supabase inválidas. Confira SUPABASE_URL e "
            "SUPABASE_KEY em .streamlit/secrets.toml."
        )
    return ErroBanco(f"Falha ao acessar o banco de dados: {exc}")


def salvar_processo(
    processo_id: str | None,
    dados: dict,
    documentos: dict,
    aprovados: set,
    etapa: int,
) -> str:
    """Cria ou atualiza o processo e retorna seu id (uuid)."""
    registro = {
        "orgao": dados.get("orgao") or "",
        "objeto": dados.get("objeto") or "",
        "etapa": etapa,
        "dados": dados,
        "documentos": documentos,
        "aprovados": sorted(aprovados),
    }
    try:
        tabela = _cliente().table("processos")
        if processo_id:
            resposta = tabela.update(registro).eq("id", processo_id).execute()
            if resposta.data:
                return processo_id
            # id não encontrado (ex.: excluído em outra sessão) — insere novo
        resposta = tabela.insert(registro).execute()
        return resposta.data[0]["id"]
    except Exception as exc:  # noqa: BLE001 — traduzimos qualquer falha
        raise _traduzir_erro(exc) from exc


def listar_processos(limite: int = 20) -> list[dict]:
    """Processos mais recentes (resumo para o painel lateral)."""
    try:
        resposta = (
            _cliente()
            .table("processos")
            .select("id, orgao, objeto, etapa, atualizado_em")
            .order("atualizado_em", desc=True)
            .limit(limite)
            .execute()
        )
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def carregar_processo(processo_id: str) -> dict | None:
    try:
        resposta = (
            _cliente().table("processos").select("*").eq("id", processo_id).execute()
        )
        return resposta.data[0] if resposta.data else None
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def excluir_processo(processo_id: str) -> None:
    try:
        _cliente().table("processos").delete().eq("id", processo_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def rotulo_processo(proc: dict) -> str:
    """Rótulo curto e legível para o seletor de processos salvos."""
    quando = (proc.get("atualizado_em") or "")[:16].replace("T", " ")
    try:
        quando = datetime.fromisoformat(proc["atualizado_em"]).strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
    orgao = (proc.get("orgao") or "sem órgão")[:35]
    objeto = (proc.get("objeto") or "sem objeto")[:45]
    return f"{quando} — {orgao} — {objeto}"
