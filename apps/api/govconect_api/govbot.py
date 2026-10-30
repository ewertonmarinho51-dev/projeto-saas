"""
`/api/v1/govbot` — a conversa do GovBot na interface nova (M4, fatia 1).

O cérebro NÃO mora aqui. Mora em `src/govbot.py`, o mesmo núcleo do painel
do Streamlit: contexto mínimo (`montar_contexto_minimo`), roteamento da
Base de Conhecimento (`planejar_consulta_rag`), prompt com allowlist de
alvos e de fontes, validação estrita do JSON do modelo, uma correção só, e
a regra de que resposta sobre a Base exige trecho recuperado CITADO e sem
número estranho a ele (`_validar_resposta_fundamentada`). Motor fora do ar
cai para a orientação local, nunca para uma ação.

O que esta fatia acrescenta é a fronteira da arquitetura nova:

* **Só leitura.** O núcleo sabe propor e aplicar mudança em campo e em
  bloco; aqui nada disso sai. Toda intenção mutável vira explicação, e o
  `payload` do modelo não chega ao navegador. Aplicar mudança é do editor
  documental (M1/M2), com CAS e trilha — não de uma conversa.
* **O processo vem do banco, pelo token do usuário.** O navegador manda o
  id; `dados`, `documentos` e a etapa são lidos com o JWT verificado, e o
  RLS da 0001 decide. Processo de outro órgão é 404, como no resto da API.
* **Citação verificável.** Cada fonte citada volta com o trecho que a
  sustenta, recortado do que a busca devolveu NESTA requisição. Fonte que
  o modelo citou e que não estava no recorte não existe para o usuário.
* **Conversa efêmera**, como no Streamlit: o servidor não grava pergunta
  nem resposta. O histórico que o navegador manda é contexto (no máximo 8
  turnos curtos), nunca autoridade — o prompt do núcleo já o trata como
  dado não confiável.

Atrás de `GOVCONECT_GOVBOT`, desligada por padrão.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import replace
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from src import govbot as nucleo
from src import rag
from src.config import DOCUMENTOS
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect.govbot")

# Intenções que só EXPLICAM. As demais (propor/aplicar campo ou bloco,
# corrigir achado, desfazer) existem no núcleo, mas não nesta rota.
ACOES_DE_LEITURA = frozenset({
    "explain_current", "explain_finding", "show_missing_information",
    "compare_with_previous_document",
})
AVISO_SEM_ALTERACAO = (
    "Por aqui eu só explico e consulto: alterações no processo são feitas no "
    "formulário ou no editor do documento, onde ficam registradas."
)
LIMITE_TRECHO = 400


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class Turno(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    papel: Literal["user", "assistant"]
    texto: str = Field(min_length=1, max_length=2000)


class Pergunta(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pergunta: str = Field(min_length=1, max_length=2000)
    processo_id: uuid.UUID | None = None
    # Documento em foco (dfd, etp, tr…). Fora do catálogo é 422.
    documento: str | None = Field(default=None, pattern=r"^[a-z_]{2,30}$")
    historico: list[Turno] = Field(default_factory=list, max_length=8)


class Citacao(BaseModel):
    source_id: str
    titulo: str
    categoria: str
    trecho: str
    dispositivos: list[str]


class RespostaDoGovBot(BaseModel):
    resposta: str
    acao: str
    citacoes: list[Citacao]
    # Houve consulta à Base nesta pergunta, e com que resultado.
    base: Literal["dispensada", "recuperado", "suficiente", "sem_referencias", "falha"]
    # O motor de IA respondeu (True) ou valeu a orientação local (False).
    ia: bool
    # O motor FOI chamado e falhou: não é o mesmo que nem ter precisado dele.
    motor_falhou: bool
    pendencias: list[str]


# ---------------------------------------------------------------------------
# Tradução
# ---------------------------------------------------------------------------
def _documentos(bruto) -> dict[str, str]:
    if not isinstance(bruto, dict):
        return {}
    return {str(k): v for k, v in bruto.items() if k in DOCUMENTOS and isinstance(v, str)}


def _citacoes(fontes, referencias) -> list[Citacao]:
    por_id = {str(r.get("source_id")): r for r in referencias if r.get("source_id")}
    saida = []
    for fonte in fontes:
        ref = por_id.get(str(fonte))
        if ref is None:
            continue    # citou o que não foi recuperado: não vira citação
        categoria = str(ref.get("categoria") or "")
        saida.append(Citacao(
            source_id=str(fonte), titulo=str(ref.get("titulo") or "Base de Conhecimento"),
            categoria=rag.CATEGORIAS.get(categoria, categoria),
            trecho=str(ref.get("trecho") or "")[:LIMITE_TRECHO],
            dispositivos=[str(d) for d in (ref.get("dispositivos") or [])][:10]))
    return saida


def responder(contexto: nucleo.GovBotContext, pergunta: str, historico: list[dict], *,
              objeto: str, buscar: Callable[..., list], chamar: Callable[..., str] | None
              ) -> RespostaDoGovBot:
    """O caminho de uma pergunta, sem HTTP — o mesmo do painel do Streamlit."""
    consulta, motivo = nucleo.planejar_consulta_rag(contexto, pergunta, objeto=objeto)
    if motivo == "suficiente":
        contexto = replace(contexto, recuperacao_rag="suficiente")
    elif motivo == "necessaria":
        try:
            brutas = buscar(consulta, qtd=6, contextual=True)
            atuais = [r for r in nucleo._recortar_referencias(brutas, None) if r.get("trecho")]
            contexto = replace(
                contexto, recuperacao_rag="recuperado" if atuais else "sem_referencias",
                referencias_rag=nucleo._recortar_referencias(
                    [*atuais, *contexto.referencias_rag], contexto.documento))
        except Exception:  # noqa: BLE001 — erro do provedor nunca vaza consulta nem chave
            contexto = replace(contexto, recuperacao_rag="falha")

    chamadas: list[bool] = []

    def motor(*args, **kwargs) -> str:
        # Conta se o motor foi chamado: com a orientação local ou com a Base
        # fora do ar, `consultar_ia` responde sem chamá-lo.
        chamadas.append(True)
        if chamar is not None:
            return chamar(*args, **kwargs)
        from src import llm

        return llm.chamar_ia_texto(*args, **kwargs)

    intent = nucleo.consultar_ia(
        contexto, pergunta, motor, historico=historico,
        fontes_permitidas=nucleo.fontes_validadas_do_contexto(contexto))
    texto, acao = intent.response, intent.action
    if acao not in ACOES_DE_LEITURA:
        texto = f"{texto} {AVISO_SEM_ALTERACAO}".strip() if acao != "undo_last_change" \
            else AVISO_SEM_ALTERACAO
        acao = "explain_current"
    # Motor chamado e resposta que não é a da queda (`responder_offline`).
    ia = bool(chamadas) and intent.response != nucleo.responder_offline(contexto, pergunta).response
    return RespostaDoGovBot(
        resposta=texto[:4000], acao=acao,
        citacoes=_citacoes(intent.sources, contexto.referencias_rag),
        base=contexto.recuperacao_rag or "dispensada", ia=ia,
        motor_falhou=bool(chamadas) and not ia,
        pendencias=list(contexto.pendencias_obrigatorias)[:30])


# ---------------------------------------------------------------------------
# Rota
# ---------------------------------------------------------------------------
def exigir_govbot_habilitado(request: Request) -> None:
    if not request.app.state.config.govbot_habilitado:
        raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")


def rotas() -> APIRouter:
    r = APIRouter(prefix="/govbot", tags=["govbot"],
                  dependencies=[Depends(exigir_govbot_habilitado)])

    @r.post("/perguntas", response_model=RespostaDoGovBot,
            responses={404: {"description": "Processo inexistente ou fora do seu acesso"},
                       422: {"description": "Pergunta, histórico ou documento inválido"}})
    def perguntar(corpo: Pergunta, request: Request,
                  eu: Identidade = Depends(exigir_identidade)) -> RespostaDoGovBot:
        if corpo.documento and corpo.documento not in DOCUMENTOS:
            raise ErroApi(422, "VALIDATION_ERROR", "Documento desconhecido")
        dados: dict = {}
        documentos: dict[str, str] = {}
        etapa = 0
        if corpo.processo_id:
            rest: ClienteRest | None = getattr(request.app.state, "rest", None)
            if rest is None:
                raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
            resposta = rest.requisitar(eu.token, "GET", "processos", params={
                "select": "id,etapa,dados,documentos", "id": f"eq.{corpo.processo_id}",
                "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
            if resposta.status != 200 or not resposta.dados:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            linha = resposta.dados[0]
            dados = linha.get("dados") if isinstance(linha.get("dados"), dict) else {}
            documentos = _documentos(linha.get("documentos"))
            etapa = int(linha.get("etapa") or 0)

        try:
            contexto = nucleo.montar_contexto_minimo(
                processo_id=str(corpo.processo_id) if corpo.processo_id else None,
                etapa=etapa, dados=dados, documentos=documentos, documento=corpo.documento)
        except nucleo.ErroGovBot:
            raise ErroApi(422, "VALIDATION_ERROR", "Contexto do processo inválido") from None

        historico = [{"role": t.papel, "text": t.texto} for t in corpo.historico]
        estado = request.app.state
        with sessao_da_requisicao(eu.token, eu.tenant_id, {
                "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
                "secretaria_id": eu.secretaria_id, "nome": ""}):
            saida = responder(
                contexto, corpo.pergunta, historico,
                objeto=str(dados.get("objeto") or ""),
                buscar=getattr(estado, "govbot_buscar", None) or rag.buscar_referencias,
                chamar=getattr(estado, "govbot_chamar", None))
        _log.info("govbot_pergunta processo=%s base=%s ia=%s citacoes=%d acao=%s",
                  bool(corpo.processo_id), saida.base, saida.ia, len(saida.citacoes), saida.acao)
        return saida

    return r
