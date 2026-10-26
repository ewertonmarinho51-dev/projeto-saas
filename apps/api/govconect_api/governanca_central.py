"""
`/api/v1/governanca` — Centro de Governança, em LEITURA (M8a).

O que a tela do Streamlit (`ui/governanca_ui`) mostra: visão geral,
catálogo de cláusulas, políticas de aplicação, biblioteca de modelos
(famílias) e templates — cada artefato com a última versão e a vigente.
O domínio é o mesmo (`catalogo.listar_com_situacao`), com o JWT do
usuário: as políticas de leitura da 0020 já cobrem.

Escrever (criar, revisar, publicar) fica para a M8b: no banco, as versões
são só leitura para o JWT do usuário e as políticas não conhecem o papel
de governança — o Streamlit escreve com a credencial de servidor. Levar a
separação de funções (autor, revisor, publicador) para o banco pede
migração própria, com ritual e revisão.

Acesso, a regra do Streamlit: flag `governance_center` ligada E papel de
governança (`app_metadata.papel_governanca`; admin sem papel opera como
`admin_municipal`). Flag desligada é 404: a tela não existe.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from src import catalogo, db, governanca
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade

TipoDeArtefato = Literal["clausula", "politica", "familia", "template"]

ROTULOS_STATUS = {
    "DRAFT": "rascunho", "UNDER_REVIEW": "em revisão",
    "APPROVED_FOR_SIMULATION": "aprovada para simulação", "SHADOW": "em shadow",
    "SCHEDULED": "agendada", "PUBLISHED": "publicada", "SUPERSEDED": "superada",
    "REVOKED": "revogada",
}

# (tipo, rótulo da aba, flag própria — None = segue só a flag do Centro)
ABAS = (
    ("clausula", "Catálogo de cláusulas", governanca.FLAG_CATALOGO),
    ("politica", "Políticas de aplicação", governanca.FLAG_POLITICAS_VISUAL),
    ("familia", "Biblioteca de modelos", None),
    ("template", "Templates", None),
)


def papel_efetivo(eu: Identidade) -> str | None:
    if eu.papel_governanca:
        return eu.papel_governanca
    return "admin_municipal" if eu.papel == "admin" else None


class Aba(BaseModel):
    tipo: str
    rotulo: str
    ativa: bool


class Resumo(BaseModel):
    clausulas: int
    publicadas: int
    em_elaboracao: int


class Centro(BaseModel):
    papel: str
    abas: list[Aba]
    resumo: Resumo


class Versao(BaseModel):
    id: str
    versao: int
    status: str
    status_rotulo: str
    hash: str
    payload: dict


class Artefato(BaseModel):
    id: str
    chave: str
    escopo: Literal["plataforma", "municipio"]
    ultima: Versao | None
    vigente: Versao | None
    versoes: int
    # Política: a condição em linguagem de gente (a mesma do Streamlit).
    descricao: str


def centro_disponivel(eu: Identidade) -> bool:
    """Para o menu: flag ligada e papel de governança (lido no `/me`)."""
    if papel_efetivo(eu) is None:
        return False
    with sessao_da_requisicao(eu.token, eu.tenant_id):
        return db.flag_ativa(governanca.FLAG_CENTRO)


def _versao(v: dict | None) -> Versao | None:
    if not v:
        return None
    status = str(v.get("status") or "")
    return Versao(id=str(v.get("id") or ""), versao=int(v.get("versao") or 0), status=status,
                  status_rotulo=ROTULOS_STATUS.get(status, status.lower()),
                  hash=str(v.get("hash") or "")[:12],
                  payload=v.get("payload") if isinstance(v.get("payload"), dict) else {})


def rotas() -> APIRouter:
    r = APIRouter(prefix="/governanca", tags=["governanca"])

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, {
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id, "papel": eu.papel,
            "papel_governanca": papel_efetivo(eu), "secretaria_id": eu.secretaria_id, "nome": ""})

    def _executar(eu: Identidade, funcao):
        papel = papel_efetivo(eu)
        if papel is None:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")
        try:
            with _sessao(eu):
                if not db.flag_ativa(governanca.FLAG_CENTRO):
                    raise ErroApi(404, "MODULE_UNAVAILABLE", "Centro de Governança desligado")
                return funcao(papel)
        except db.ErroBanco as erro:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", str(erro)[:300]) from None

    @r.get("", response_model=Centro, responses={404: {"description": "Centro desligado"}})
    def centro(eu: Identidade = Depends(exigir_identidade)) -> Centro:
        def ler(papel: str) -> Centro:
            clausulas = catalogo.listar_com_situacao("clausula") if db.flag_ativa(governanca.FLAG_CATALOGO) else []
            return Centro(
                papel=papel,
                abas=[Aba(tipo=t, rotulo=rotulo, ativa=flag is None or db.flag_ativa(flag))
                      for t, rotulo, flag in ABAS],
                resumo=Resumo(
                    clausulas=len(clausulas),
                    publicadas=sum(1 for i in clausulas if i["publicada"]),
                    em_elaboracao=sum(1 for i in clausulas if i["ultima"]
                                      and i["ultima"].get("status") in ("DRAFT", "UNDER_REVIEW"))))
        return _executar(eu, ler)

    @r.get("/artefatos", response_model=list[Artefato],
           responses={404: {"description": "Centro ou aba desligados"}})
    def artefatos(tipo: TipoDeArtefato = Query(...),
                  eu: Identidade = Depends(exigir_identidade)) -> list[Artefato]:
        def ler(_papel: str) -> list[Artefato]:
            flag = next(f for t, _, f in ABAS if t == tipo)
            if flag is not None and not db.flag_ativa(flag):
                raise ErroApi(404, "MODULE_UNAVAILABLE", "Esta aba do Centro está desligada")
            saida = []
            for item in catalogo.listar_com_situacao(tipo):
                artefato, ultima = item["artefato"], item["ultima"]
                payload = (ultima or {}).get("payload") or {}
                descricao = ""
                if tipo == "politica" and isinstance(payload.get("condicao"), dict):
                    descricao = governanca.descrever_condicao(payload["condicao"])
                elif tipo == "familia" and isinstance(payload.get("criterios"), dict):
                    descricao = governanca.descrever_condicao(payload["criterios"])
                saida.append(Artefato(
                    id=str(artefato.get("id") or ""), chave=str(artefato.get("chave_estavel") or ""),
                    escopo="plataforma" if artefato.get("tenant_id") is None else "municipio",
                    ultima=_versao(ultima), vigente=_versao(item["publicada"]),
                    versoes=len(item.get("versoes") or []), descricao=descricao))
            return saida
        return _executar(eu, ler)

    return r
