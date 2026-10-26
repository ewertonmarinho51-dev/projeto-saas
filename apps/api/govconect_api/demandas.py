"""
`/api/v1/processos/{id}/demandas` — Consolidar Demandas (M4).

O domínio é o de `src/demanda/*`, o mesmo da tela do Streamlit: ler os
Documentos de Formalização de Demanda (PDF), consolidar por código e
unidade, mostrar os conflitos de unidade, conferir a soma a partir das
parcelas e aplicar à planilha do processo.

Os PDFs não ficam guardados. A tela manda os arquivos a cada conferência
(em base64, no JSON) com as decisões do servidor — rótulos de secretaria
corrigidos e conflitos aceitos —, e a API refaz a leitura: a mesma
escolha do Streamlit, que relê a cada rerun para não acumular bytes em
sessão.

Diferença deliberada: no Streamlit, "Aplicar ao processo" só troca os
dados da sessão, e o descarte de documentos acontece depois, no
formulário. Aqui a aplicação grava no processo, então aplica JÁ a
cascata do formulário (M1): planilha mudou, documentos saem — só com
`confirmar_descarte`.

O módulo segue a flag/rollout `demand_consolidation`, resolvida para
quem está logado (`contexto.modulo_disponivel_aqui`), como o menu do
Streamlit.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import contexto, governanca, planilha
from src.config import DOCUMENTOS
from src.demanda import aplicacao, consolidacao, exportacao, ingestao
from src.precos.aplicacao import descartar_por_planilha
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .processos import _COLUNAS, _etag, _falha, _sem_aspas
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
LIMITE_POR_ARQUIVO = 10 * 1024 * 1024
LIMITE_TOTAL = 30 * 1024 * 1024
MAX_ARQUIVOS = 30

_STATUS = {
    consolidacao.LIDO: "lido",
    consolidacao.IMAGEM: "não lido — o PDF é uma imagem",
    consolidacao.ILEGIVEL: "não lido — sem quadro de itens",
}


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArquivoEnviado(_Entrada):
    nome: str = Field(min_length=1, max_length=200)
    # PDF em base64. O teto vale para o texto codificado (~4/3 do binário).
    conteudo: str = Field(min_length=1, max_length=LIMITE_POR_ARQUIVO * 4 // 3 + 8)


class PedidoDeConsolidacao(_Entrada):
    arquivos: list[ArquivoEnviado] = Field(min_length=1, max_length=MAX_ARQUIVOS)
    # nome do arquivo → secretaria corrigida pelo servidor
    rotulos: dict[str, str] = Field(default_factory=dict)
    conflitos_aceitos: list[str] = Field(default_factory=list, max_length=500)


class PedidoDeAplicacao(PedidoDeConsolidacao):
    confirmar_descarte: bool = False


class ArquivoLido(BaseModel):
    nome: str
    status: str
    status_texto: str
    secretaria: str
    precisa_confirmar: bool
    documentos: list[str]
    itens: int


class ErroDeArquivo(BaseModel):
    nome: str
    mensagem: str


class LinhaConsolidada(BaseModel):
    codigo: str
    descricao: str
    unidade: str
    por_secretaria: dict[str, str]
    total: str
    explicacao: str


class ConflitoDeUnidade(BaseModel):
    codigo: str
    unidades: list[str]
    secretarias: list[str]
    aceito: bool


class Consolidacao(BaseModel):
    arquivos: list[ArquivoLido]
    erros: list[ErroDeArquivo]
    secretarias: list[str]
    linhas: list[LinhaConsolidada]
    conflitos: list[ConflitoDeUnidade]
    fecha: bool
    divergencia: str
    ocorrencias: int
    duplicatas: list[str]
    nao_lidos: list[str]


class AplicacaoDaDemanda(BaseModel):
    itens: int
    secretarias: int
    ocorrencias: int
    nao_lidos: list[str]
    descartados: list[str]
    versao: str


class Modulos(BaseModel):
    consolidar_demandas: bool


def _qtd(valor: Decimal) -> str:
    """Quantidade em formato brasileiro, sem casas à toa (1.234,5)."""
    normalizado = valor.normalize()
    if normalizado == normalizado.to_integral_value():
        normalizado = normalizado.quantize(Decimal(1))
    inteiro, _, fracao = format(normalizado, "f").partition(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    grupos.insert(0, inteiro)
    return sinal + ".".join(grupos) + ("," + fracao if fracao else "")


def _nome(doc: str) -> str:
    meta = DOCUMENTOS.get(doc) or {}
    return str(meta.get("sigla") or meta.get("titulo") or doc)


def _ler(pedido: PedidoDeConsolidacao) -> tuple[list, list[ErroDeArquivo]]:
    total = 0
    origens, erros = [], []
    for arquivo in pedido.arquivos:
        try:
            conteudo = base64.b64decode(arquivo.conteudo, validate=True)
        except (binascii.Error, ValueError):
            raise ErroApi(422, "VALIDATION_ERROR", f"{arquivo.nome}: arquivo corrompido no envio") from None
        total += len(conteudo)
        if len(conteudo) > LIMITE_POR_ARQUIVO or total > LIMITE_TOTAL:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "Os arquivos passam do limite (10 MB cada, 30 MB no total)")
        if not conteudo.startswith(b"%PDF"):
            erros.append(ErroDeArquivo(nome=arquivo.nome, mensagem="Não é um PDF."))
            continue
        try:
            origens.append(ingestao.ler(arquivo.nome, conteudo,
                                        secretaria=(pedido.rotulos.get(arquivo.nome) or "").strip()[:120]))
        except ingestao.ErroIngestao as erro:
            erros.append(ErroDeArquivo(nome=arquivo.nome, mensagem=str(erro)[:300]))
    return origens, erros


def _contrato(origens, erros, consolidado, aceitos: set[str]) -> Consolidacao:
    laudo = consolidacao.conferir(consolidado)
    return Consolidacao(
        arquivos=[ArquivoLido(
            nome=o.arquivo, status=o.status, status_texto=_STATUS.get(o.status, o.status),
            secretaria=o.secretaria, precisa_confirmar=ingestao.precisa_de_confirmacao(o),
            documentos=[d.numero for d in o.dfds], itens=sum(len(d.itens) for d in o.dfds))
            for o in origens],
        erros=erros,
        secretarias=list(consolidado.secretarias),
        linhas=[LinhaConsolidada(
            codigo=l.codigo, descricao=l.descricao, unidade=l.unidade,
            por_secretaria={s: _qtd(q) for s, q in l.por_secretaria.items()},
            total=_qtd(l.total), explicacao=consolidacao.explicar(l))
            for l in consolidado.linhas],
        conflitos=[ConflitoDeUnidade(codigo=c.codigo, unidades=list(c.unidades),
                                     secretarias=list(c.secretarias), aceito=c.codigo in aceitos)
                   for c in consolidado.conflitos],
        fecha=laudo.fecha, divergencia=(laudo.divergencias[0] if laudo.divergencias else ""),
        ocorrencias=laudo.total_de_ocorrencias,
        duplicatas=list(consolidado.duplicatas), nao_lidos=list(consolidado.nao_lidos))


def rotas() -> APIRouter:
    r = APIRouter(tags=["demandas"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, {
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id, "nome": ""})

    def _disponivel(eu: Identidade) -> bool:
        with _sessao(eu):
            return contexto.modulo_disponivel_aqui(governanca.FLAG_CONSOLIDACAO)

    def _exigir_modulo(eu: Identidade) -> None:
        if not _disponivel(eu):
            # 404 e não 403: módulo desligado é tela que não existe.
            raise ErroApi(404, "MODULE_UNAVAILABLE", "Consolidar Demandas não está disponível para você")

    def _obter(rest: ClienteRest, eu: Identidade, processo_id: str) -> dict:
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}"})
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    @r.get("/modulos", response_model=Modulos)
    def modulos(eu: Identidade = Depends(exigir_identidade)) -> Modulos:
        """Módulos opcionais disponíveis para quem está logado (menu da tela)."""
        return Modulos(consolidar_demandas=_disponivel(eu))

    @r.post("/processos/{processo_id}/demandas/consolidacao", response_model=Consolidacao,
            responses={404: {"description": "Processo fora do seu acesso ou módulo desligado"},
                       413: {"description": "Arquivos acima do limite"}})
    def consolidar(processo_id: uuid.UUID, pedido: PedidoDeConsolidacao, request: Request,
                   eu: Identidade = Depends(exigir_identidade)) -> Consolidacao:
        _exigir_modulo(eu)
        _obter(_rest(request), eu, str(processo_id))
        origens, erros = _ler(pedido)
        consolidado = consolidacao.consolidar(origens)
        return _contrato(origens, erros, consolidado, set(pedido.conflitos_aceitos))

    @r.post("/processos/{processo_id}/demandas/planilha",
            responses={200: {"content": {MIME_XLSX: {}}},
                       404: {"description": "Processo fora do seu acesso ou módulo desligado"}})
    def planilha_consolidada(processo_id: uuid.UUID, pedido: PedidoDeConsolidacao, request: Request,
                             eu: Identidade = Depends(exigir_identidade)) -> Response:
        _exigir_modulo(eu)
        _obter(_rest(request), eu, str(processo_id))
        origens, _ = _ler(pedido)
        conteudo = exportacao.planilha_consolidada(consolidacao.consolidar(origens))
        return Response(content=conteudo, media_type=MIME_XLSX, headers={
            "Content-Disposition": 'attachment; filename="demanda-consolidada.xlsx"',
            "Cache-Control": "private, no-store"})

    @r.put("/processos/{processo_id}/demandas/aplicacao", response_model=AplicacaoDaDemanda,
           responses={404: {"description": "Processo fora do seu acesso ou módulo desligado"},
                      409: {"description": "Versão desatualizada ou descarte não confirmado"},
                      422: {"description": "Conflito pendente, soma que não fecha ou nada lido"},
                      428: {"description": "If-Match ausente"}})
    def aplicar(processo_id: uuid.UUID, pedido: PedidoDeAplicacao, request: Request, response: Response,
                if_match: str | None = Header(None, alias="If-Match"),
                eu: Identidade = Depends(exigir_identidade)) -> AplicacaoDaDemanda:
        if not if_match:
            raise ErroApi(428, "PRECONDITION_REQUIRED", "If-Match obrigatório: envie a versão que você leu")
        _exigir_modulo(eu)
        rest = _rest(request)
        atual = _obter(rest, eu, str(processo_id))
        versao = _sem_aspas(if_match)
        if versao != str(atual.get("atualizado_em")):
            raise ErroApi(409, "VERSION_CONFLICT", "O processo mudou desde a sua leitura")
        if eu.papel != "admin" and atual.get("auth_user_id") != eu.auth_user_id:
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")
        origens, _ = _ler(pedido)
        consolidado = consolidacao.consolidar(origens)
        dados = dict(atual.get("dados") or {})
        try:
            novos, resumo = aplicacao.aplicar(dados, consolidado,
                                              conflitos_aceitos=tuple(pedido.conflitos_aceitos))
        except aplicacao.ErroAplicacao as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)) from None
        # A planilha calculada como o formulário a grava (valor por item e global).
        itens, valor = planilha.calcular(novos["itens"])
        novos["itens"], novos["valor_estimado"] = itens, valor
        documentos, aprovados, descartados = descartar_por_planilha(
            dados, atual.get("documentos") or {}, atual.get("aprovados") or [])
        if descartados and not pedido.confirmar_descarte:
            raise ErroApi(409, "DESCARTE_PENDENTE",
                          "A planilha do processo muda, e estes documentos serão descartados: "
                          + ", ".join(_nome(d) for d in descartados) + ". Confirme o descarte para aplicar.")
        resposta = rest.requisitar(eu.token, "PATCH", "processos", params={
            "select": _COLUNAS, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}",
            "atualizado_em": f"eq.{versao}"},
            corpo={"dados": novos, "documentos": documentos, "aprovados": aprovados},
            prefer="return=representation")
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(409, "VERSION_CONFLICT", "O processo mudou desde a sua leitura")
        linha = resposta.dados[0]
        _log.info("demanda_aplicada processo=%s itens=%s descartados=%s",
                  processo_id, resumo["itens"], len(descartados))
        response.headers["ETag"] = _etag(linha)
        return AplicacaoDaDemanda(itens=resumo["itens"], secretarias=resumo["secretarias"],
                                  ocorrencias=resumo["ocorrencias"], nao_lidos=resumo["nao_lidos"],
                                  descartados=[_nome(d) for d in descartados],
                                  versao=str(linha.get("atualizado_em") or ""))

    return r
