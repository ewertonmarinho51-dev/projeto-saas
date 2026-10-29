"""
`/api/v1/governanca` — Centro de Governança (M8a leitura, M8b escrita).

O que a tela do Streamlit (`ui/governanca_ui`) mostra: visão geral,
catálogo de cláusulas, políticas de aplicação, biblioteca de modelos
(famílias) e templates — cada artefato com a última versão e a vigente.
O domínio é o mesmo (`catalogo.listar_com_situacao`), com o JWT do
usuário: as políticas de leitura da 0020 já cobrem.

Escrever (M8b) passa SÓ pelas RPCs da 0036, que levam ao banco a separação
de funções (a matriz da 0020: admins tudo; revisor jurídico aprova;
publicador publica/revoga; auditor nada) e a máquina de estados das
versões. A API valida o CONTEÚDO antes (`governanca.nova_versao_artefato`:
contrato do payload por tipo e hash canônico) — a RPC confere forma, não
semântica. Quem decide se a pessoa PODE é o banco; o código de erro dele
vira o HTTP certo.

Acesso, a regra do Streamlit: flag `governance_center` ligada E papel de
governança (`app_metadata.papel_governanca`; admin sem papel opera como
`admin_municipal`). Flag desligada é 404: a tela não existe.
"""

from __future__ import annotations

from typing import Literal

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from src import catalogo, db, governanca
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest, RespostaRest

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
    # A trava de ambiente da escrita na interface nova (GOVCONECT_GOVERNANCA_ESCRITA).
    escrita: bool
    abas: list[Aba]
    resumo: Resumo


class Versao(BaseModel):
    id: str
    versao: int
    status: str
    status_rotulo: str
    hash: str
    payload: dict
    # Trava otimista da edição: o If-Match manda este valor.
    atualizado_em: str = ""
    # Destinos que a máquina de estados admite a partir daqui. Quem PODE
    # cada um é o banco que decide (a tela só oferece).
    proximos: list[str] = []


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class NovoArtefato(_Entrada):
    tipo: TipoDeArtefato
    chave: str = Field(min_length=3, max_length=200)
    payload: dict


class Edicao(_Entrada):
    payload: dict


class Transicao(_Entrada):
    status: Literal["UNDER_REVIEW", "DRAFT", "APPROVED_FOR_SIMULATION", "SHADOW", "SCHEDULED",
                    "PUBLISHED", "REVOKED"]
    vigencia_inicio: datetime | None = None


class Escrita(BaseModel):
    versao_id: str
    status: str


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
                  payload=v.get("payload") if isinstance(v.get("payload"), dict) else {},
                  atualizado_em=str(v.get("atualizado_em") or ""),
                  proximos=[d for d in governanca.ESTADOS_ARTEFATO
                            if d != "SUPERSEDED" and governanca.transicao_artefato_valida(status, d)])


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
    def centro(request: Request, eu: Identidade = Depends(exigir_identidade)) -> Centro:
        def ler(papel: str) -> Centro:
            clausulas = catalogo.listar_com_situacao("clausula") if db.flag_ativa(governanca.FLAG_CATALOGO) else []
            return Centro(
                papel=papel,
                escrita=request.app.state.config.governanca_escrita,
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

    # -- escrita (M8b): só pelas RPCs da 0036 --------------------------------
    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    # O código do banco decide o HTTP: a regra (quem pode, que transição) é dele.
    _ERROS_DA_RPC = {
        "42501": (403, "FORBIDDEN", "Seu papel de governança não permite este ato, ou o artefato está fora do seu alcance."),
        "22023": (422, "VALIDATION_ERROR", "Transição ou conteúdo inválido para a máquina de estados."),
        # PT409 é o SQLSTATE do PostgREST que vira HTTP 409 (40001/55000 viriam
        # como 500, e o cliente traduziria em "banco indisponível").
        "PT409": (409, "VERSION_CONFLICT",
                  "A versão mudou desde a sua leitura ou já não pode ser alterada (publicada é imutável: "
                  "derive uma nova). Recarregue e refaça."),
    }

    def _rpc(rest: ClienteRest, eu: Identidade, funcao: str, corpo: dict) -> RespostaRest:
        resposta = rest.requisitar(eu.token, "POST", f"rpc/{funcao}", corpo=corpo)
        if resposta.status not in (200, 204):
            status, codigo, mensagem = _ERROS_DA_RPC.get(
                resposta.codigo_pg or "", (400, "BAD_REQUEST", "O banco recusou o pedido."))
            raise ErroApi(status, codigo, mensagem)
        return resposta

    def _contrato(tipo: str, chave: str, payload: dict, **extra) -> dict:
        try:
            return governanca.nova_versao_artefato(tipo, chave, payload, **extra)
        except governanca.ErroContrato as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None

    def _versao_com_artefato(rest: ClienteRest, eu: Identidade, versao_id) -> dict:
        resposta = rest.requisitar(eu.token, "GET", "governanca_versoes", params={
            "select": "id,versao,status,atualizado_em,artefato:governanca_artefatos(tipo_artefato,chave_estavel,tenant_id)",
            "id": f"eq.{versao_id}", "limit": "1"})
        linha = (resposta.dados or [None])[0] if resposta.status == 200 else None
        artefato = (linha or {}).get("artefato") or {}
        if not linha or str(artefato.get("tenant_id") or "") != eu.tenant_id:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return linha

    def _proxima(rest: ClienteRest, eu: Identidade, artefato_id: str | None) -> int:
        """O número da próxima versão: entra no hash canônico, e a RPC o confere."""
        if not artefato_id:
            return 1
        resposta = rest.requisitar(eu.token, "GET", "governanca_versoes", params={
            "select": "versao", "artefato_id": f"eq.{artefato_id}", "order": "versao.desc", "limit": "1"})
        linhas = resposta.dados if resposta.status == 200 else []
        return int((linhas or [{}])[0].get("versao") or 0) + 1

    def _guarda(eu: Identidade, request: Request) -> None:
        # Flag e papel ANTES do banco: a tela não existe sem eles.
        _executar(eu, lambda _papel: None)
        # E a trava do ambiente: ler na interface nova não implica escrever.
        if not request.app.state.config.governanca_escrita:
            raise ErroApi(403, "GOVERNANCE_WRITE_DISABLED",
                          "A escrita do Centro na interface nova está desligada neste ambiente. "
                          "Altere pelo GovDocs.")

    @r.post("/artefatos", status_code=201, response_model=Escrita,
            responses={403: {"description": "Papel sem competência"}, 422: {"description": "Contrato inválido"}})
    def criar(corpo: NovoArtefato, request: Request, eu: Identidade = Depends(exigir_identidade)) -> Escrita:
        _guarda(eu, request)
        rest = _rest(request)
        existente = rest.requisitar(eu.token, "GET", "governanca_artefatos", params={
            "select": "id", "tenant_id": f"eq.{eu.tenant_id}", "tipo_artefato": f"eq.{corpo.tipo}",
            "chave_estavel": f"eq.{corpo.chave}", "secretaria_id": "is.null", "limit": "1"})
        artefato_id = str(((existente.dados or [{}])[0] if existente.status == 200 else {}).get("id") or "")
        proxima = _proxima(rest, eu, artefato_id or None)
        contrato = _contrato(corpo.tipo, corpo.chave, corpo.payload, versao=proxima)
        resposta = _rpc(rest, eu, "governanca_criar_versao", {
            "p_tipo": corpo.tipo, "p_chave": corpo.chave, "p_payload": contrato["payload"],
            "p_hash": contrato["hash"], "p_versao": proxima})
        return Escrita(versao_id=str(resposta.dados), status="DRAFT")

    def _esperado(if_match: str | None) -> str:
        """A versão que a pessoa leu (trava otimista): editar e transicionar."""
        if not if_match:
            raise ErroApi(428, "PRECONDITION_REQUIRED", "If-Match obrigatório: envie a versão que você leu")
        return if_match.strip().removeprefix("W/").strip('"')

    @r.put("/versoes/{versao_id}", response_model=Escrita,
           responses={409: {"description": "Versão mudou ou é imutável"}, 428: {"description": "If-Match ausente"}})
    def editar(versao_id: uuid.UUID, corpo: Edicao, request: Request,
               if_match: str | None = Header(None, alias="If-Match"),
               eu: Identidade = Depends(exigir_identidade)) -> Escrita:
        esperado = _esperado(if_match)
        _guarda(eu, request)
        rest = _rest(request)
        atual = _versao_com_artefato(rest, eu, versao_id)
        artefato = atual["artefato"]
        contrato = _contrato(artefato["tipo_artefato"], artefato["chave_estavel"], corpo.payload,
                             versao=int(atual.get("versao") or 1), status=str(atual.get("status") or "DRAFT"))
        _rpc(rest, eu, "governanca_editar_rascunho", {
            "p_versao": str(versao_id), "p_payload": contrato["payload"], "p_hash": contrato["hash"],
            "p_esperado": esperado})
        return Escrita(versao_id=str(versao_id), status=str(atual.get("status") or ""))

    @r.post("/versoes/{versao_id}/derivacao", status_code=201, response_model=Escrita)
    def derivar(versao_id: uuid.UUID, request: Request, eu: Identidade = Depends(exigir_identidade)) -> Escrita:
        _guarda(eu, request)
        rest = _rest(request)
        origem = rest.requisitar(eu.token, "GET", "governanca_versoes", params={
            "select": "payload,artefato_id,artefato:governanca_artefatos(tipo_artefato,chave_estavel,tenant_id)",
            "id": f"eq.{versao_id}", "limit": "1"})
        linha = (origem.dados or [None])[0] if origem.status == 200 else None
        artefato = (linha or {}).get("artefato") or {}
        if not linha or str(artefato.get("tenant_id") or "") != eu.tenant_id:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        proxima = _proxima(rest, eu, str(linha["artefato_id"]))
        # O conteúdo é o da publicada (a RPC copia do banco); daqui sai só o hash
        # canônico da versão NOVA, que inclui o número dela.
        contrato = _contrato(artefato["tipo_artefato"], artefato["chave_estavel"], linha.get("payload") or {},
                             versao=proxima)
        resposta = _rpc(rest, eu, "governanca_derivar_versao", {
            "p_versao": str(versao_id), "p_hash": contrato["hash"], "p_proxima": proxima})
        return Escrita(versao_id=str(resposta.dados), status="DRAFT")

    @r.post("/versoes/{versao_id}/transicao", response_model=Escrita,
            responses={409: {"description": "Versão mudou desde a leitura"}, 428: {"description": "If-Match ausente"}})
    def transicionar(versao_id: uuid.UUID, corpo: Transicao, request: Request,
                     if_match: str | None = Header(None, alias="If-Match"),
                     eu: Identidade = Depends(exigir_identidade)) -> Escrita:
        # Aprova/publica o texto que a pessoa LEU: o banco recusa se mudou.
        esperado = _esperado(if_match)
        _guarda(eu, request)
        _rpc(_rest(request), eu, "governanca_transicionar", {
            "p_versao": str(versao_id), "p_novo": corpo.status, "p_esperado": esperado,
            "p_vigencia_inicio": corpo.vigencia_inicio.isoformat() if corpo.vigencia_inicio else None})
        return Escrita(versao_id=str(versao_id), status=corpo.status)

    return r
