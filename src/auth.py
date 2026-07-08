"""
Autenticação e papéis de usuário.

- Senhas: PBKDF2-HMAC-SHA256 (stdlib), 200.000 iterações, salt por
  usuário. Formato armazenado: pbkdf2_sha256$<iterações>$<salt>$<hash>.
- Papéis: 'admin' (gerencia usuários, chaves de IA, identidade visual e
  Base de Conhecimento) e 'usuario' (apenas elabora documentos).
- Sem Supabase configurado, a aplicação roda em MODO ABERTO (sem login,
  permissões de admin) para desenvolvimento local e CI.
"""

import hashlib
import hmac
import os
import secrets

import streamlit as st

from . import db

PBKDF2_ITERACOES = 200_000


class ErroAuth(Exception):
    """Erro de autenticação com mensagem amigável."""


# ---------------------------------------------------------------------------
# Hash de senha (stdlib, sem dependências)
# ---------------------------------------------------------------------------
def gerar_hash_senha(senha: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", senha.encode(), salt.encode(), PBKDF2_ITERACOES
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERACOES}${salt}${digest}"


def verificar_senha(senha: str, senha_hash: str) -> bool:
    try:
        algoritmo, iteracoes, salt, digest = senha_hash.split("$")
        if algoritmo != "pbkdf2_sha256":
            return False
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), salt.encode(), int(iteracoes)
        ).hex()
        return hmac.compare_digest(calculado, digest)
    except (ValueError, AttributeError):
        return False


def validar_senha_forte(senha: str) -> str | None:
    """Retorna mensagem de erro ou None se a senha for aceitável."""
    if len(senha) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    return None


# ---------------------------------------------------------------------------
# Operações no banco
# ---------------------------------------------------------------------------
def _tabela():
    if not db.disponivel():
        raise ErroAuth(
            "Banco de dados não configurado. Defina SUPABASE_URL e "
            "SUPABASE_KEY (em .streamlit/secrets.toml, nas variáveis de "
            "ambiente ou nos Secrets do deploy) para habilitar login e "
            "cadastro de usuários."
        )
    return db._cliente().table("usuarios")  # noqa: SLF001


def tem_admin() -> bool:
    """True se já existe ao menos um administrador ativo cadastrado."""
    try:
        resposta = (
            _tabela().select("id").eq("papel", "admin").eq("ativo", True)
            .limit(1).execute()
        )
        return bool(resposta.data)
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(f"Falha ao consultar usuários: {exc}") from exc


def criar_usuario(nome: str, login: str, senha: str, papel: str) -> dict:
    if papel not in ("admin", "usuario"):
        raise ErroAuth("Papel inválido.")
    if not nome.strip() or not login.strip():
        raise ErroAuth("Nome e login são obrigatórios.")
    if erro := validar_senha_forte(senha):
        raise ErroAuth(erro)
    try:
        resposta = _tabela().insert(
            {
                "nome": nome.strip(),
                "login": login.strip().lower(),
                "senha_hash": gerar_hash_senha(senha),
                "papel": papel,
            }
        ).execute()
        return resposta.data[0]
    except ErroAuth:
        raise
    except Exception as exc:  # noqa: BLE001
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            raise ErroAuth(f"O login '{login}' já está em uso.") from exc
        raise ErroAuth(f"Falha ao criar usuário: {exc}") from exc


def autenticar(login: str, senha: str) -> dict:
    """Valida credenciais e retorna o usuário (sem o hash)."""
    try:
        resposta = (
            _tabela()
            .select("id, nome, login, papel, ativo, senha_hash")
            .eq("login", login.strip().lower())
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(f"Falha ao consultar o banco: {exc}") from exc

    usuario = resposta.data[0] if resposta.data else None
    if not usuario or not verificar_senha(senha, usuario["senha_hash"]):
        raise ErroAuth("Login ou senha incorretos.")
    if not usuario["ativo"]:
        raise ErroAuth("Usuário desativado. Procure o administrador.")
    usuario.pop("senha_hash")
    return usuario


def listar_usuarios() -> list[dict]:
    try:
        return (
            _tabela()
            .select("id, nome, login, papel, ativo, criado_em")
            .order("criado_em")
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(f"Falha ao listar usuários: {exc}") from exc


def atualizar_usuario(usuario_id: str, **campos) -> None:
    """Atualiza papel/ativo/senha. Senha chega em texto e vira hash."""
    if "senha" in campos:
        senha = campos.pop("senha")
        if erro := validar_senha_forte(senha):
            raise ErroAuth(erro)
        campos["senha_hash"] = gerar_hash_senha(senha)
    try:
        _tabela().update(campos).eq("id", usuario_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(f"Falha ao atualizar usuário: {exc}") from exc


# ---------------------------------------------------------------------------
# Sessão / permissões
# ---------------------------------------------------------------------------
def usuario_logado() -> dict | None:
    return st.session_state.get("usuario")


def modo_aberto() -> bool:
    """
    Modo aberto = sem login, tudo liberado. Só vale para desenvolvimento
    e CI: exige a ausência de Supabase E a variável GOVDOCS_MODO_ABERTO=1.
    Em produção (deploy real), NUNCA cair em modo aberto silenciosamente —
    sem banco o app mostra a tela de configuração necessária.
    """
    if db.disponivel():
        return False
    return os.getenv("GOVDOCS_MODO_ABERTO", "").strip() in ("1", "true", "True")


def precisa_configurar() -> bool:
    """Sem banco e sem modo aberto explícito: exige configuração do Supabase."""
    return not db.disponivel() and not modo_aberto()


def eh_admin() -> bool:
    """Admin logado, ou modo aberto (sem banco = sem restrições)."""
    if modo_aberto():
        return True
    usuario = usuario_logado()
    return bool(usuario and usuario.get("papel") == "admin")


def sair() -> None:
    st.session_state.usuario = None
    # limpa o processo em andamento da sessão anterior
    st.session_state.dados = {}
    st.session_state.documentos = {}
    st.session_state.aprovados = set()
    st.session_state.processo_id = None
    st.session_state.etapa = 0
