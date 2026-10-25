"""
`/api/v1/processos/{id}/formulario` — o Formulário Matriz (M1).

As regras são as de `src/formulario_matriz.py`, que reproduz o wizard do
Streamlit: os mesmos campos e rótulos, a planilha calculada pelo mesmo
`planilha.calcular`, os mesmos obrigatórios para iniciar a elaboração e a
mesma cascata de descarte quando o dado muda.

Escrita com o JWT do usuário e `If-Match` (a versão lida); quem decide o
acesso é o RLS da 0020. Mudar o formulário de um processo que já tem
documento exige `confirmar_descarte`: a tela mostra a lista ANTES, e a API
recusa (409 DESCARTE_PENDENTE) se ela não veio confirmada — o descarte
nunca acontece por surpresa.

Os dois envios de arquivo (planilha XLSX e memorando) só LEEM o arquivo e
devolvem o resultado para a pessoa conferir; quem grava é o PUT.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import formulario_matriz as fm
from src import planilha, rag
from src.config import DOCUMENTOS

from .erros import ErroApi
from .processos import _COLUNAS, _etag, _falha, _sem_aspas
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LIMITE_PLANILHA = 5 * 1024 * 1024
LIMITE_MEMORANDO = 15 * 1024 * 1024
EXTENSOES_MEMORANDO = ("pdf", "docx", "txt", "md")


class CampoDoFormulario(BaseModel):
    chave: str
    tipo: str
    rotulo: str
    ajuda: str
    exemplo: str
    placeholder: str
    obrigatorio: bool
    opcoes: list[str]


class Formulario(BaseModel):
    campos: list[CampoDoFormulario]
    valores: dict[str, str]
    itens: list[dict[str, Any]]
    valor_estimado: float
    valor_estimado_exibicao: str
    faltantes: list[str]
    # Documentos que sairiam se o formulário mudasse agora (nome legível).
    a_descartar: list[str]
    etapa: int
    versao: str


class GravacaoDoFormulario(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valores: dict[str, Any] = Field(default_factory=dict)
    # "Iniciar elaboração dos documentos": exige os obrigatórios.
    iniciar: bool = False
    # A pessoa viu a lista de documentos que saem e concordou.
    confirmar_descarte: bool = False


class FormularioGravado(Formulario):
    descartados: list[str]
    mudou: bool


class PlanilhaLida(BaseModel):
    itens: list[dict[str, Any]]
    valor_estimado: float
    valor_estimado_exibicao: str


class MemorandoLido(BaseModel):
    texto: str
    caracteres: int


def _nome(doc: str) -> str:
    meta = DOCUMENTOS.get(doc) or {}
    return str(meta.get("sigla") or meta.get("titulo") or doc).strip()


def _contrato(linha: dict) -> Formulario:
    dados = dict(linha.get("dados") or {})
    itens, valor = planilha.calcular([dict(i) for i in (dados.get("itens") or []) if isinstance(i, dict)])
    return Formulario(
        campos=[CampoDoFormulario(**c) for c in fm.campos()],
        valores={k: str(dados.get(k) or "") for k in fm.CAMPOS_DE_TEXTO},
        itens=itens,
        valor_estimado=float(valor or 0),
        valor_estimado_exibicao=planilha.formatar_moeda(valor or 0),
        faltantes=fm.faltantes(dados),
        a_descartar=[_nome(d) for d in fm.a_descartar(linha)],
        etapa=int(linha.get("etapa") or 0),
        versao=str(linha.get("atualizado_em") or ""),
    )


def rotas() -> APIRouter:
    r = APIRouter(prefix="/processos", tags=["formulario"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _obter(rest: ClienteRest, eu: Identidade, processo_id: str) -> dict:
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}"})
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            # 404 também para o de outro município: não confirma que existe.
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    # Rota estática ANTES das que levam {processo_id}: senão o caminho cairia
    # na conversão para UUID e voltaria 422.
    @r.get("/modelo-planilha.xlsx", responses={200: {"content": {MIME_XLSX: {}}}})
    def modelo(eu: Identidade = Depends(exigir_identidade)) -> Response:  # noqa: ARG001 — exige sessão
        return Response(content=planilha.modelo_xlsx(), media_type=MIME_XLSX, headers={
            "Content-Disposition": 'attachment; filename="modelo-planilha-orcamentaria.xlsx"',
            "Cache-Control": "private, no-store"})

    @r.get("/{processo_id}/formulario", response_model=Formulario,
           responses={404: {"description": "Inexistente ou fora do seu acesso"}})
    def ler(processo_id: uuid.UUID, request: Request, response: Response,
            eu: Identidade = Depends(exigir_identidade)) -> Formulario:
        linha = _obter(_rest(request), eu, str(processo_id))
        response.headers["ETag"] = _etag(linha)
        return _contrato(linha)

    @r.put("/{processo_id}/formulario", response_model=FormularioGravado,
           responses={404: {"description": "Inexistente ou fora do seu acesso"},
                      409: {"description": "Versão desatualizada (VERSION_CONFLICT) ou descarte "
                                           "não confirmado (DESCARTE_PENDENTE)"},
                      422: {"description": "Campo inválido ou obrigatório vazio (nada gravado)"},
                      428: {"description": "If-Match ausente"}})
    def gravar(processo_id: uuid.UUID, corpo: GravacaoDoFormulario, request: Request,
               response: Response, if_match: str | None = Header(None, alias="If-Match"),
               eu: Identidade = Depends(exigir_identidade)) -> FormularioGravado:
        if not if_match:
            raise ErroApi(428, "PRECONDITION_REQUIRED", "If-Match obrigatório: envie a versão que você leu")
        rest = _rest(request)
        atual = _obter(rest, eu, str(processo_id))
        versao = _sem_aspas(if_match)
        if versao != str(atual.get("atualizado_em")):
            raise ErroApi(409, "VERSION_CONFLICT", "O processo mudou desde a sua leitura")
        # Espelha `processos_edita`: o dono ou o admin. O RLS é quem garante.
        if eu.papel != "admin" and atual.get("auth_user_id") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")
        try:
            resultado = fm.gravar(atual, corpo.valores, iniciar=corpo.iniciar)
        except fm.ErroDoFormulario as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
        if resultado.descartados and not corpo.confirmar_descarte:
            raise ErroApi(409, "DESCARTE_PENDENTE",
                          "Estes documentos ficam desatualizados e serão descartados: "
                          + ", ".join(_nome(d) for d in resultado.descartados)
                          + ". Confirme o descarte para gravar.")
        registro = {
            "dados": resultado.dados, "documentos": resultado.documentos,
            "aprovados": resultado.aprovados, "etapa": resultado.etapa,
            # As colunas espelham o formulário, como no Streamlit.
            "orgao": resultado.dados.get("orgao", ""), "objeto": resultado.dados.get("objeto", ""),
        }
        resposta = rest.requisitar(eu.token, "PATCH", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}",
            # Trava otimista: o gatilho troca `atualizado_em` a cada update.
            "atualizado_em": f"eq.{versao}"},
            corpo=registro, prefer="return=representation")
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(409, "VERSION_CONFLICT", "O processo mudou desde a sua leitura")
        linha = resposta.dados[0]
        _log.info("formulario_gravado processo=%s iniciar=%s mudou=%s descartados=%s",
                  processo_id, corpo.iniciar, resultado.mudou, len(resultado.descartados))
        response.headers["ETag"] = _etag(linha)
        base = _contrato(linha)
        return FormularioGravado(**base.model_dump(),
                                 descartados=[_nome(d) for d in resultado.descartados],
                                 mudou=resultado.mudou)

    @r.post("/{processo_id}/formulario/planilha", response_model=PlanilhaLida,
            openapi_extra={"requestBody": {"required": True, "content": {
                MIME_XLSX: {"schema": {"type": "string", "format": "binary"}}}}},
            responses={413: {"description": "Planilha acima do limite"},
                       415: {"description": "Não é XLSX"},
                       422: {"description": "Planilha ilegível ou sem itens"}})
    async def ler_planilha(processo_id: uuid.UUID, request: Request,
                           eu: Identidade = Depends(exigir_identidade)) -> PlanilhaLida:
        tipo = (request.headers.get("content-type") or "").split(";")[0].strip()
        if tipo != MIME_XLSX:
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "Envie a planilha em XLSX")
        if int(request.headers.get("content-length") or 0) > LIMITE_PLANILHA:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "A planilha passa de 5 MB")
        conteudo = await request.body()
        if len(conteudo) > LIMITE_PLANILHA:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "A planilha passa de 5 MB")
        if not conteudo.startswith(b"PK"):
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "O arquivo não é um XLSX válido")
        _obter(_rest(request), eu, str(processo_id))  # só quem enxerga o processo
        try:
            importados = planilha.importar_de_xlsx(conteudo)
        except planilha.ErroPlanilha as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
        except Exception:  # noqa: BLE001 — openpyxl recusa arquivo malformado
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "O arquivo não é um XLSX legível") from None
        itens, valor = planilha.calcular(importados)
        return PlanilhaLida(itens=itens, valor_estimado=float(valor or 0),
                            valor_estimado_exibicao=planilha.formatar_moeda(valor or 0))

    @r.post("/{processo_id}/formulario/memorando", response_model=MemorandoLido,
            responses={413: {"description": "Arquivo acima do limite"},
                       415: {"description": "Formato não suportado"},
                       422: {"description": "Sem texto extraível"}})
    async def ler_memorando(processo_id: uuid.UUID, request: Request,
                            nome: str = Query(..., min_length=1, max_length=200),
                            eu: Identidade = Depends(exigir_identidade)) -> MemorandoLido:
        extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
        if extensao not in EXTENSOES_MEMORANDO:
            raise ErroApi(415, "UNSUPPORTED_MEDIA_TYPE", "Envie PDF, DOCX, TXT ou MD")
        if int(request.headers.get("content-length") or 0) > LIMITE_MEMORANDO:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "O arquivo passa de 15 MB")
        conteudo = await request.body()
        if len(conteudo) > LIMITE_MEMORANDO:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "O arquivo passa de 15 MB")
        _obter(_rest(request), eu, str(processo_id))
        try:
            texto = rag.extrair_texto(nome, conteudo)
        except rag.ErroRAG as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
        texto = texto[: fm.LIMITE_MEMORANDO]
        return MemorandoLido(texto=texto, caracteres=len(texto))

    return r
