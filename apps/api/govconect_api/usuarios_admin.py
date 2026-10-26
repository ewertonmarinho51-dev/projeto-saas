"""
`/api/v1/admin/usuarios` — usuários e papéis do município (M7c, ADR-010).

* listar: JWT do ADMIN em `usuarios` (RLS da 0020, `usuarios_admin_le`);
* desativar/reativar: `usuarios.ativo` pelo JWT do admin — corta a API na
  requisição seguinte, porque o verificador confere `ativo` sempre — E
  bloqueio da conta no Auth, que impede entrar e RENOVAR o token. Sem o
  bloqueio, o desativado seguiria falando com o PostgREST direto com o
  token renovado: nenhuma política do banco olha `ativo` (revisão de
  segurança, 26/10/2026). O token já emitido vale até vencer (≤ 1 h);
* convidar e trocar papel ou secretaria: `usuarios` e o `app_metadata` da
  conta no Auth, de onde a API e o RLS leem o escopo.

A Admin API atravessa o RLS; as fronteiras são daqui:
* o tenant é SEMPRE o do JWT do admin, e a conta alvo é LIDA e conferida
  antes de toda escrita;
* quem chama é conferido AO VIVO no Auth antes de mexer em papel e acesso:
  o papel do JWT pode ter até 1 h, e um admin recém-rebaixado não pode
  usar essa janela para rebaixar quem o rebaixou;
* ninguém altera o próprio papel nem se desativa, e o último administrador
  ativo do município não sai — por ninguém.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from .admin_auth import AdminDoAuth, ContaJaExiste, EmailRecusado, ErroAdminAuth
from .erros import ErroApi
from .processos import _falha
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
# A linha em `usuarios` exige senha_hash; a conta criada aqui entra pelo
# e-mail (Supabase Auth). Este valor não tem o formato pbkdf2: o login
# legado do Streamlit recusa (`auth.verificar_senha`).
SENHA_LEGADA_INUTILIZAVEL = "!sem-senha-legada"
COLUNAS = "id,nome,login,papel,ativo,secretaria_id,auth_user_id"
Papel = Literal["usuario", "admin"]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UsuarioDoMunicipio(BaseModel):
    id: str
    nome: str
    login: str
    papel: str
    ativo: bool
    secretaria_id: str | None
    # Sem conta no Auth: conta do login antigo, que não entra na interface nova.
    acesso_por_email: bool
    eu: bool


class OpcaoDeSecretaria(BaseModel):
    id: str
    nome: str


class Usuarios(BaseModel):
    usuarios: list[UsuarioDoMunicipio]
    secretarias: list[OpcaoDeSecretaria]
    # False: a chave da Admin API não está configurada — convidar, trocar
    # papel/secretaria e o bloqueio no Auth ficam indisponíveis.
    gestao_de_acesso: bool


class NovoUsuario(_Entrada):
    nome: str = Field(min_length=2, max_length=200)
    email: str = Field(min_length=5, max_length=254)
    papel: Papel = "usuario"
    secretaria_id: uuid.UUID | None = None


class Mudanca(_Entrada):
    papel: Papel | None = None
    # Presente com null = tirar o vínculo; ausente = não mexer.
    secretaria_id: uuid.UUID | None = None
    ativo: bool | None = None


def rotas() -> APIRouter:
    r = APIRouter(prefix="/admin/usuarios", tags=["administracao"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _admin_auth(request: Request) -> AdminDoAuth:
        admin = getattr(request.app.state, "admin_auth", None)
        if admin is None:
            raise ErroApi(503, "ADMIN_AUTH_UNAVAILABLE",
                          "Gestão de acesso indisponível: a chave da Admin API não está configurada no servidor.")
        return admin

    def _indisponivel() -> ErroApi:
        return ErroApi(503, "ADMIN_AUTH_UNAVAILABLE", "A Admin API não respondeu. Tente de novo.")

    def _exigir_admin(eu: Identidade) -> None:
        if eu.papel != "admin":
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

    def _admin_ao_vivo(admin: AdminDoAuth, eu: Identidade) -> None:
        """O papel do JWT pode estar velho (até 1 h): confere a conta agora."""
        try:
            conta = admin.conta(eu.auth_user_id)
        except ErroAdminAuth:
            raise _indisponivel() from None
        meta = (conta or {}).get("app_metadata") or {}
        bloqueado = str((conta or {}).get("banned_until") or "") not in ("", "none")
        if conta is None or meta.get("papel") != "admin" or str(meta.get("tenant_id") or "") != eu.tenant_id \
                or bloqueado:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

    def _linha(l: dict, eu: Identidade) -> UsuarioDoMunicipio:
        return UsuarioDoMunicipio(
            id=str(l["id"]), nome=str(l.get("nome") or ""), login=str(l.get("login") or ""),
            papel=str(l.get("papel") or "usuario"), ativo=bool(l.get("ativo", True)),
            secretaria_id=str(l["secretaria_id"]) if l.get("secretaria_id") else None,
            acesso_por_email=bool(l.get("auth_user_id")),
            eu=str(l.get("auth_user_id") or "") == eu.auth_user_id)

    def _um(rest: ClienteRest, eu: Identidade, usuario_id) -> dict:
        resposta = rest.requisitar(eu.token, "GET", "usuarios", params={
            "select": COLUNAS, "id": f"eq.{usuario_id}", "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    def _secretaria_do_tenant(rest: ClienteRest, eu: Identidade, secretaria_id) -> None:
        resposta = rest.requisitar(eu.token, "GET", "secretarias", params={
            "select": "id", "id": f"eq.{secretaria_id}", "tenant_id": f"eq.{eu.tenant_id}",
            "ativo": "is.true", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(422, "VALIDATION_ERROR", "Secretaria inexistente ou desativada neste município.")

    def _outro_admin_ativo(rest: ClienteRest, eu: Identidade, usuario_id) -> bool:
        resposta = rest.requisitar(eu.token, "GET", "usuarios", params={
            "select": "id", "tenant_id": f"eq.{eu.tenant_id}", "papel": "eq.admin", "ativo": "is.true",
            "id": f"neq.{usuario_id}", "limit": "1"})
        if resposta.status != 200:
            raise _falha(resposta)
        return bool(resposta.dados)

    def _gravar(rest: ClienteRest, eu: Identidade, usuario_id, campos: dict) -> dict:
        resposta = rest.requisitar(eu.token, "PATCH", "usuarios", params={
            "select": COLUNAS, "id": f"eq.{usuario_id}", "tenant_id": f"eq.{eu.tenant_id}"},
            corpo=campos, prefer="return=representation")
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    # -- listar --------------------------------------------------------------
    @r.get("", response_model=Usuarios)
    def listar(request: Request, eu: Identidade = Depends(exigir_identidade)) -> Usuarios:
        _exigir_admin(eu)
        rest = _rest(request)
        usuarios = rest.requisitar(eu.token, "GET", "usuarios", params={
            "select": COLUNAS, "tenant_id": f"eq.{eu.tenant_id}", "order": "nome.asc"})
        if usuarios.status != 200:
            raise _falha(usuarios)
        secretarias = rest.requisitar(eu.token, "GET", "secretarias", params={
            "select": "id,nome", "tenant_id": f"eq.{eu.tenant_id}", "ativo": "is.true", "order": "nome.asc"})
        return Usuarios(
            usuarios=[_linha(l, eu) for l in usuarios.dados or []],
            secretarias=[OpcaoDeSecretaria(id=str(s["id"]), nome=str(s.get("nome") or ""))
                         for s in (secretarias.dados or []) if secretarias.status == 200],
            gestao_de_acesso=getattr(request.app.state, "admin_auth", None) is not None)

    # -- convidar ------------------------------------------------------------
    @r.post("", status_code=201, response_model=UsuarioDoMunicipio,
            responses={409: {"description": "Já existe conta com este e-mail"},
                       503: {"description": "Admin API não configurada ou fora do ar"}})
    def convidar(corpo: NovoUsuario, request: Request,
                 eu: Identidade = Depends(exigir_identidade)) -> UsuarioDoMunicipio:
        _exigir_admin(eu)
        admin = _admin_auth(request)
        rest = _rest(request)
        email = corpo.email.lower()
        if not _EMAIL.fullmatch(email):
            raise ErroApi(422, "VALIDATION_ERROR", "E-mail inválido.")
        _admin_ao_vivo(admin, eu)
        if corpo.secretaria_id:
            _secretaria_do_tenant(rest, eu, corpo.secretaria_id)
        # O escopo vem do CHAMADOR: tenant do JWT do admin, nunca do corpo.
        escopo = {"papel": corpo.papel, "tenant_id": eu.tenant_id}
        if corpo.secretaria_id:
            escopo["secretaria_id"] = str(corpo.secretaria_id)
        try:
            uid = admin.criar(email, corpo.nome, escopo)
        except ContaJaExiste:
            raise ErroApi(409, "CONFLICT", "Já existe uma conta com este e-mail.") from None
        except EmailRecusado:
            raise ErroApi(422, "VALIDATION_ERROR", "O serviço de contas recusou este e-mail.") from None
        except ErroAdminAuth:
            raise _indisponivel() from None

        def desfazer() -> None:
            # Sem a linha em `usuarios`, a conta ocuparia o e-mail e, com o
            # escopo já gravado, renderia token aceito pelo PostgREST direto.
            try:
                admin.desfazer_criacao(uid)
            except ErroAdminAuth:
                _log.error("conta_orfa_no_auth uid=%s", uid)

        try:
            resposta = rest.requisitar(eu.token, "POST", "usuarios", prefer="return=representation",
                                       params={"select": COLUNAS}, corpo={
                                           "nome": corpo.nome, "login": email,
                                           "senha_hash": SENHA_LEGADA_INUTILIZAVEL, "papel": corpo.papel,
                                           "tenant_id": eu.tenant_id,
                                           "secretaria_id": str(corpo.secretaria_id) if corpo.secretaria_id else None,
                                           "auth_user_id": uid, "ativo": True})
        except Exception:
            desfazer()
            raise
        if resposta.status != 201 or not resposta.dados:
            desfazer()
            if resposta.codigo_pg == "23505":
                raise ErroApi(409, "CONFLICT", "Já existe um usuário com este login.")
            raise _falha(resposta)
        _log.info("usuario_convidado uid=%s papel=%s por=%s", uid, corpo.papel, eu.auth_user_id)
        return _linha(resposta.dados[0], eu)

    # -- alterar -------------------------------------------------------------
    @r.patch("/{usuario_id}", response_model=UsuarioDoMunicipio,
             responses={404: {"description": "Usuário fora do seu município"},
                        409: {"description": "Alteração em si mesmo ou no último administrador"},
                        503: {"description": "Admin API não configurada ou fora do ar"}})
    def alterar(usuario_id: uuid.UUID, corpo: Mudanca, request: Request,
                eu: Identidade = Depends(exigir_identidade)) -> UsuarioDoMunicipio:
        _exigir_admin(eu)
        rest = _rest(request)
        alvo = _um(rest, eu, usuario_id)
        mexe_secretaria = "secretaria_id" in corpo.model_fields_set
        if not (corpo.papel or mexe_secretaria or corpo.ativo is not None):
            raise ErroApi(422, "VALIDATION_ERROR", "Nada a alterar.")
        si_mesmo = str(alvo.get("auth_user_id") or "") == eu.auth_user_id
        if si_mesmo and (corpo.papel is not None or corpo.ativo is not None):
            raise ErroApi(409, "SELF_CHANGE",
                          "Você não altera o próprio papel nem se desativa: peça a outro administrador.")
        tira_admin = alvo.get("papel") == "admin" and alvo.get("ativo", True) and (
            corpo.papel == "usuario" or corpo.ativo is False)
        if tira_admin and not _outro_admin_ativo(rest, eu, usuario_id):
            raise ErroApi(409, "LAST_ADMIN",
                          "Este é o último administrador ativo do município: promova outra pessoa antes.")
        if mexe_secretaria and corpo.secretaria_id:
            _secretaria_do_tenant(rest, eu, corpo.secretaria_id)

        campos: dict = {}
        if corpo.papel is not None:
            campos["papel"] = corpo.papel
        if mexe_secretaria:
            campos["secretaria_id"] = str(corpo.secretaria_id) if corpo.secretaria_id else None

        # Conta do login antigo, sem Auth, só tem a linha.
        uid = str(alvo.get("auth_user_id") or "")
        precisa_do_auth = bool(uid) and (bool(campos) or corpo.ativo is not None)
        admin = getattr(request.app.state, "admin_auth", None)
        if precisa_do_auth and campos:
            _admin_auth(request)  # papel e secretaria sem a chave: 503
        # Desativar sem a chave ainda corta a API (o verificador lê `ativo`);
        # só o bloqueio no Auth fica para quando a chave existir.
        if precisa_do_auth and admin is not None:
            _admin_ao_vivo(admin, eu)
            try:
                conta = admin.conta(uid)
                meta = dict((conta or {}).get("app_metadata") or {})
                # A Admin API atravessa o RLS: ESTA conferência é a fronteira.
                if conta is None or str(meta.get("tenant_id") or "") != eu.tenant_id:
                    raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
                if campos:
                    mudanca: dict = {}
                    if "papel" in campos:
                        mudanca["papel"] = campos["papel"]
                    if "secretaria_id" in campos:
                        # O GoTrue mescla `app_metadata`: só `null` APAGA a chave.
                        mudanca["secretaria_id"] = campos["secretaria_id"]
                    admin.atualizar_escopo(uid, {**meta, **mudanca})
                if corpo.ativo is not None:
                    admin.bloquear(uid, not corpo.ativo)
            except ErroAdminAuth:
                raise _indisponivel() from None

        if corpo.ativo is not None:
            campos["ativo"] = corpo.ativo
        linha = _gravar(rest, eu, usuario_id, campos)
        _log.info("usuario_alterado alvo=%s campos=%s auth=%s por=%s", usuario_id, ",".join(sorted(campos)),
                  "sim" if precisa_do_auth and admin is not None else "nao", eu.auth_user_id)
        return _linha(linha, eu)

    return r
