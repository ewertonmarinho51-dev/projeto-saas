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
import logging
import os
import secrets

import streamlit as st

from . import db

_log = logging.getLogger(__name__)

PBKDF2_ITERACOES = 200_000


class ErroAuth(Exception):
    """Erro de autenticação com mensagem amigável."""


def _falha(acao: str, exc: Exception) -> str:
    """
    Mensagem genérica + identificador de correlação.

    Exceções do PostgREST carregam a credencial no cabeçalho e na URL;
    repassá-las para a tela vazava o segredo. O detalhe sanitizado vai
    para o log do servidor (ver db.registrar_incidente).
    """
    correlacao = db.registrar_incidente(exc, f"auth: {acao}")
    return (f"Falha ao {acao}. O detalhe técnico ficou registrado no "
            f"servidor. Referência: {correlacao}.")


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
        raise ErroAuth(_falha("consultar usuários", exc)) from exc


def criar_usuario(nome: str, login: str, senha: str, papel: str) -> dict:
    try:
        db.exigir_operacional()   # manutenção fecha o bootstrap do admin
    except db.ErroBanco as erro:
        raise ErroAuth(str(erro)) from erro
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
        raise ErroAuth(_falha("criar usuário", exc)) from exc


# ---------------------------------------------------------------------------
# Supabase Auth — a peça que faltava para a Etapa E
#
# Enquanto a autenticação for a tabela `usuarios` com `senha_hash`
# conferido aqui no Python, NÃO EXISTE JWT de usuário. Sem JWT, toda
# requisição vai com a credencial de servidor, que atravessa o RLS: as
# 28 políticas da 0020 nunca são avaliadas. É por isso que a Etapa E não
# fechava — não por falta de vontade, por falta desta função.
#
# A transição tem duas pontas e elas não podem ser trocadas de uma vez:
#
#   * o BANCO precisa da 0020 aplicada (coluna `auth_user_id`,
#     políticas, RPC);
#   * as CONTAS precisam existir no Supabase Auth, com papel, tenant e
#     secretaria em `app_metadata` — que só a Admin API grava.
#
# Enquanto as duas não estiverem prontas, `autenticar` tenta o Supabase
# Auth e, se não houver conta lá, cai para o caminho legado. A queda NÃO
# é silenciosa no que importa: sem JWT, a trilha de governança recusa
# (ver db.registrar_evento_governanca). Dá para entrar e usar o app; não
# dá para praticar ato de governança fingindo que foi registrado.
#
# `GOVDOCS_EXIGIR_SUPABASE_AUTH=1` fecha a porta legada. É o interruptor
# final da Etapa E, e o runbook manda ligá-lo depois do backfill.
# ---------------------------------------------------------------------------
FLAG_EXIGIR_SUPABASE_AUTH = "GOVDOCS_EXIGIR_SUPABASE_AUTH"


def exigir_supabase_auth() -> bool:
    """Porta legada fechada? Produção deve fechar depois do backfill."""
    return db._segredo(  # noqa: SLF001
        FLAG_EXIGIR_SUPABASE_AUTH).lower() in ("1", "true", "on", "sim")


def _cliente_de_login():
    """
    Cliente ANÔNIMO, só para trocar senha por token.

    Anônimo de propósito: o login é a única operação que acontece antes
    de existir identidade, e fazê-la com a credencial de servidor
    apagaria a diferença entre "o servidor autenticou alguém" e "o
    servidor decidiu que estava tudo bem".
    """
    from supabase import create_client

    url = db._segredo("SUPABASE_URL")            # noqa: SLF001
    publica = db._segredo(db.NOME_CHAVE_PUBLICA)  # noqa: SLF001
    if not (url and publica):
        return None
    return create_client(url, publica)


def autenticar_no_supabase(email: str, senha: str) -> tuple[str, str] | None:
    """
    (access_token, auth_user_id) do Supabase Auth — None se não deu.

    `None` significa apenas "por aqui não entrou", SEM afirmar por quê,
    e essa modéstia é a correção de um defeito que trancou o login em
    produção.

    A versão anterior tentava distinguir "senha errada" de "conta não
    existe" lendo a mensagem do GoTrue, e recusava na primeira hipótese
    para não dar "uma segunda chance contra outro banco de senhas". Só
    que o GoTrue devolve `Invalid login credentials` para OS DOIS CASOS,
    de propósito: distinguir permitiria enumerar usuários. A leitura era
    adivinhação, e adivinhou errado.

    O efeito: como ninguém tinha sido migrado ainda, TODA conta era
    inexistente no Supabase Auth, toda tentativa caía no ramo
    "senha errada" e todo mundo ficava trancado para fora — com a senha
    certa.

    A regra de "sem segunda chance" continua existindo, e agora mora
    onde dá para verificá-la: em `GOVDOCS_EXIGIR_SUPABASE_AUTH`. Com o
    interruptor ligado não há caminho legado nenhum para tentar. Com ele
    desligado, estamos em transição e o legado é o que faz o app
    funcionar — recusar ali seria trocar uma porta aberta por porta
    nenhuma.
    """
    cliente = _cliente_de_login()
    if cliente is None:
        return None
    try:
        sessao = cliente.auth.sign_in_with_password(
            {"email": email, "password": senha})
    except Exception as exc:  # noqa: BLE001
        # O motivo NÃO é interpretado. O registro é do servidor, e sai
        # sanitizado — a mensagem do GoTrue pode carregar o endereço.
        _log.info("supabase auth nao autenticou (ref %s)",
                  db.registrar_incidente(exc, "auth: supabase"))
        return None
    token = getattr(getattr(sessao, "session", None), "access_token", "")
    usuario = getattr(sessao, "user", None)
    if not token or usuario is None:
        return None
    return token, str(usuario.id)


def _usuario_por_auth_id(auth_user_id: str) -> dict | None:
    """Linha de `usuarios` vinculada à conta do Auth."""
    try:
        resposta = (_tabela().select("*")
                    .eq("auth_user_id", auth_user_id).limit(1).execute())
    except Exception:  # noqa: BLE001
        # coluna ausente = 0020 ainda não aplicada. É estado esperado
        # durante a transição, e não é erro de autenticação.
        return None
    return resposta.data[0] if resposta.data else None


def autenticar(login: str, senha: str) -> dict:
    """
    Valida credenciais e retorna o usuário (sem o hash).

    Ordem: Supabase Auth primeiro, legado depois. O usuário devolvido
    carrega `_token` quando veio pelo Supabase Auth — é o que `entrar()`
    guarda na sessão e o que faz o RLS valer nas requisições seguintes.
    """
    try:
        db.exigir_operacional()   # manutenção fecha o login
    except db.ErroBanco as erro:
        raise ErroAuth(str(erro)) from erro

    sessao = autenticar_no_supabase(login.strip().lower(), senha)
    if sessao is not None:
        token, auth_user_id = sessao
        usuario = _usuario_por_auth_id(auth_user_id)
        if usuario is None:
            raise ErroAuth(
                "Conta autenticada, mas sem vínculo institucional neste "
                "município. Procure o administrador.")
        if not usuario.get("ativo", True):
            raise ErroAuth("Usuário desativado. Procure o administrador.")
        usuario.pop("senha_hash", None)
        usuario["_token"] = token
        return usuario

    if exigir_supabase_auth():
        raise ErroAuth(
            "Este ambiente exige Supabase Auth e a conta não foi "
            "encontrada lá. Procure o administrador.")

    return _autenticar_legado(login, senha)


def _autenticar_legado(login: str, senha: str) -> dict:
    """
    Caminho de TRANSIÇÃO: senha conferida aqui, contra `usuarios`.

    Quem entra por aqui NÃO tem JWT, e portanto opera com a credencial
    de servidor — o RLS não é exercido. É o estado que a Etapa E existe
    para encerrar, e `GOVDOCS_EXIGIR_SUPABASE_AUTH=1` o encerra.
    """
    # select("*") em vez de lista fixa: o dicionário do usuário carrega as
    # colunas de vínculo institucional (tenant_id/secretaria_id) quando as
    # migrações 0006/0007 estão aplicadas — e continua funcionando antes.
    try:
        resposta = (
            _tabela()
            .select("*")
            .eq("login", login.strip().lower())
            .limit(1)
            .execute()
        )
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(_falha("consultar o banco", exc)) from exc

    usuario = resposta.data[0] if resposta.data else None
    if not usuario or not verificar_senha(senha, usuario["senha_hash"]):
        raise ErroAuth("Login ou senha incorretos.")
    if not usuario["ativo"]:
        raise ErroAuth("Usuário desativado. Procure o administrador.")
    usuario.pop("senha_hash")
    return usuario


def listar_usuarios() -> list[dict]:
    try:
        usuarios = (
            _tabela()
            .select("*")
            .order("criado_em")
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        raise ErroAuth(_falha("listar usuários", exc)) from exc
    for usuario in usuarios:
        usuario.pop("senha_hash", None)
    return usuarios


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
        raise ErroAuth(_falha("atualizar usuário", exc)) from exc


# ---------------------------------------------------------------------------
# Sessão / permissões
# ---------------------------------------------------------------------------
def entrar(usuario: dict) -> None:
    """
    Registra o usuário na sessão e deriva o contexto institucional do
    VÍNCULO dele (tenant; a secretaria fica no próprio dicionário) —
    nunca de um campo livre do frontend (Fase 2 da matriz).

    Guarda também o access token do Supabase Auth, quando houve um: é
    ele que `db.cliente_do_usuario()` anexa às requisições, e é o que
    faz o RLS ser avaliado em vez de atravessado. O token sai do
    dicionário do usuário — nada em `st.session_state.usuario` deve
    carregar credencial, porque esse dicionário é lido pela interface
    inteira.
    """
    token = usuario.pop("_token", "")
    st.session_state.usuario = usuario
    if usuario.get("tenant_id"):
        st.session_state.tenant_id = usuario["tenant_id"]
    if token:
        st.session_state[db.CHAVE_DA_SESSAO] = token


def usuario_logado() -> dict | None:
    return st.session_state.get("usuario")


def modo_aberto() -> bool:
    """
    Modo aberto = sem login, tudo liberado. Só vale para desenvolvimento
    e CI: exige a ausência de Supabase E a variável GOVDOCS_MODO_ABERTO=1.
    Em produção (deploy real), NUNCA cair em modo aberto silenciosamente —
    sem banco o app mostra a tela de configuração necessária.

    Manutenção NUNCA vira modo aberto: sem a credencial de servidor
    obrigatória, `disponivel()` é False, e sem esta guarda uma variável
    de ambiente esquecida transformaria a falha fechada em "app inteiro
    liberado sem login".
    """
    if db.em_manutencao():
        return False
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


# ---------------------------------------------------------------------------
# Papéis do Centro de Governança (pacote V6; usuarios.papel_governanca)
# ---------------------------------------------------------------------------
def papel_governanca() -> str | None:
    """
    Papel do usuário no Centro de Governança. None = servidor comum
    (NUNCA acessa governança). Administrador do app sem papel específico
    opera como admin_municipal do próprio tenant. Modo aberto (dev/CI)
    = proprietario.
    """
    if modo_aberto():
        return "proprietario"
    usuario = usuario_logado() or {}
    papel = usuario.get("papel_governanca")
    if papel:
        return papel
    return "admin_municipal" if usuario.get("papel") == "admin" else None


def acessa_centro_governanca() -> bool:
    return papel_governanca() is not None


def governa_plataforma() -> bool:
    """Padrões nacionais/da plataforma: só proprietário e admin global."""
    return papel_governanca() in ("proprietario", "admin_global")


def pode_criar_governanca() -> bool:
    return papel_governanca() in ("proprietario", "admin_global",
                                  "admin_municipal")


def pode_revisar_governanca() -> bool:
    return papel_governanca() in ("proprietario", "admin_global",
                                  "admin_municipal", "revisor_juridico")


def pode_publicar_governanca() -> bool:
    return papel_governanca() in ("proprietario", "admin_global",
                                  "admin_municipal", "publicador")


def somente_auditoria() -> bool:
    return papel_governanca() == "auditor"


def sair() -> None:
    st.session_state.usuario = None
    st.session_state.tenant_id = None
    # o token sai PRIMEIRO e sempre: uma sessão encerrada que deixasse
    # o JWT para trás continuaria autorizando requisições
    st.session_state[db.CHAVE_DA_SESSAO] = ""
    # limpa o processo em andamento da sessão anterior
    st.session_state.dados = {}
    st.session_state.documentos = {}
    st.session_state.aprovados = set()
    st.session_state.processo_id = None
    st.session_state.etapa = 0
