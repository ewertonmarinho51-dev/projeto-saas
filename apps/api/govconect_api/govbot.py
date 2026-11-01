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
  bloco; aqui nada é aplicado. Intenção mutável vira explicação, e o
  `payload` do modelo não chega ao navegador. A exceção é a PROPOSTA de texto
  para o trecho que a pessoa escolheu: passa pelos mesmos guardas do núcleo
  (`criar_proposta_bloco`, `validar_valores_materiais`) e volta como
  sugestão, sem gravar nada. Aplicar é do editor documental, com CAS e
  trilha — não de uma conversa.
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
from src.blocos import dividir_em_blocos
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
ACOES_DE_PROPOSTA = frozenset({"suggest_section_patch", "apply_section_patch"})
AVISO_PROPOSTA_RECUSADA = (
    "A sugestão de texto foi recusada na conferência: ela trazia número, prazo "
    "ou decisão sem lastro no pedido, no trecho atual ou nas fontes citadas."
)
LIMITE_TRECHOS = 200


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
    # Trecho em foco, de `GET .../trechos`. Só com ele o GovBot propõe texto.
    bloco: str | None = Field(default=None, min_length=3, max_length=200)
    historico: list[Turno] = Field(default_factory=list, max_length=8)


class Citacao(BaseModel):
    source_id: str
    titulo: str
    categoria: str
    trecho: str
    dispositivos: list[str]
    # Posição na referência indexada ("trecho 7"), para conferir no original.
    localizacao: str | None = None


class PropostaDeTexto(BaseModel):
    """Sugestão para UM trecho. Nada foi gravado: quem decide é a pessoa."""

    documento: str
    alvo: str
    antes: str
    texto: str
    motivo: str
    # Sempre um subconjunto de `citacoes`.
    fontes: list[str]
    palavras: int


class TrechoDoDocumento(BaseModel):
    path: str
    clausula: int | None
    texto: str


class RespostaDoGovBot(BaseModel):
    resposta: str
    acao: str
    citacoes: list[Citacao]
    proposta: PropostaDeTexto | None = None
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
        ordem = str(ref.get("ordem") or "")
        saida.append(Citacao(
            source_id=str(fonte), titulo=str(ref.get("titulo") or "Base de Conhecimento"),
            categoria=rag.CATEGORIAS.get(categoria, categoria),
            trecho=str(ref.get("trecho") or "")[:LIMITE_TRECHO],
            dispositivos=[str(d) for d in (ref.get("dispositivos") or [])][:10],
            localizacao=f"trecho {int(ordem) + 1}" if ordem.isdecimal() else None))
    return saida


def _proposta(intent: nucleo.GovBotIntent, contexto: nucleo.GovBotContext,
              pergunta: str) -> PropostaDeTexto | None:
    """Os guardas do núcleo sobre o texto do modelo. Recusou, não há proposta."""
    alvo = contexto.bloco_em_foco
    if not alvo or intent.target != alvo:
        return None
    antes = str(contexto.valor_atual or "")
    depois = str(intent.payload.get("new_value") or "")
    motivo = str(intent.payload.get("reason") or "")
    citadas = {str(r.get("source_id")): str(r.get("trecho") or "") for r in contexto.referencias_rag}
    fontes = [f for f in intent.sources if f in citadas]
    try:
        criada = nucleo.criar_proposta_bloco(alvo, antes, depois, motivo, fontes)
        nucleo.validar_valores_materiais(
            depois, pedido=pergunta, antes=antes, fatos=contexto.fatos_relevantes,
            valores_fontes=[citadas[f] for f in fontes])
    except nucleo.ErroGovBot:
        return None
    return PropostaDeTexto(documento=alvo.split("/", 1)[0], alvo=alvo, antes=antes, texto=criada.after,
                           motivo=criada.reason, fontes=fontes, palavras=len(criada.after.split()))


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
    proposta = None
    if acao in ACOES_DE_PROPOSTA and contexto.bloco_em_foco:
        proposta = _proposta(intent, contexto, pergunta)
        if proposta is None:
            texto, acao = AVISO_PROPOSTA_RECUSADA, "explain_current"
        else:
            acao = "suggest_section_patch"
    elif acao not in ACOES_DE_LEITURA:
        texto = f"{texto} {AVISO_SEM_ALTERACAO}".strip() if acao != "undo_last_change" \
            else AVISO_SEM_ALTERACAO
        acao = "explain_current"
    # Motor chamado e resposta que não é a da queda (`responder_offline`).
    ia = bool(chamadas) and intent.response != nucleo.responder_offline(contexto, pergunta).response
    return RespostaDoGovBot(
        resposta=texto[:4000], acao=acao,
        citacoes=_citacoes(intent.sources, contexto.referencias_rag), proposta=proposta,
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

    def _processo(request: Request, eu: Identidade, processo_id: uuid.UUID, colunas: str) -> dict:
        rest: ClienteRest | None = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": colunas, "id": f"eq.{processo_id}",
            "tenant_id": f"eq.{eu.tenant_id}", "limit": "1"})
        if resposta.status != 200 or not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    @r.get("/processos/{processo_id}/documentos/{documento}/trechos",
           response_model=list[TrechoDoDocumento],
           responses={404: {"description": "Processo fora do seu acesso"},
                      422: {"description": "Documento que o GovBot não edita"}})
    def trechos(processo_id: uuid.UUID, documento: str, request: Request,
                eu: Identidade = Depends(exigir_identidade)) -> list[TrechoDoDocumento]:
        """Parágrafos do documento, para a pessoa escolher sobre qual o GovBot propõe."""
        if documento not in nucleo.DOCUMENTOS_EDITAVEIS:
            raise ErroApi(422, "VALIDATION_ERROR", "Documento desconhecido")
        linha = _processo(request, eu, processo_id, "id,documentos")
        texto = _documentos(linha.get("documentos")).get(documento, "")
        return [TrechoDoDocumento(path=b["path"], clausula=b.get("clausula"), texto=b["conteudo"])
                for b in dividir_em_blocos(documento, texto)
                if b.get("tipo") == "paragrafo"][:LIMITE_TRECHOS]

    @r.post("/perguntas", response_model=RespostaDoGovBot,
            responses={404: {"description": "Processo inexistente ou fora do seu acesso"},
                       422: {"description": "Pergunta, histórico ou documento inválido"}})
    def perguntar(corpo: Pergunta, request: Request,
                  eu: Identidade = Depends(exigir_identidade)) -> RespostaDoGovBot:
        if corpo.documento and corpo.documento not in DOCUMENTOS:
            raise ErroApi(422, "VALIDATION_ERROR", "Documento desconhecido")
        if corpo.bloco and not (corpo.processo_id and corpo.documento
                                and corpo.bloco.startswith(corpo.documento + "/")):
            raise ErroApi(422, "VALIDATION_ERROR", "Trecho fora do documento em foco")
        dados: dict = {}
        documentos: dict[str, str] = {}
        etapa = 0
        if corpo.processo_id:
            linha = _processo(request, eu, corpo.processo_id, "id,etapa,dados,documentos")
            dados = linha.get("dados") if isinstance(linha.get("dados"), dict) else {}
            documentos = _documentos(linha.get("documentos"))
            etapa = int(linha.get("etapa") or 0)

        try:
            contexto = nucleo.montar_contexto_minimo(
                processo_id=str(corpo.processo_id) if corpo.processo_id else None,
                etapa=etapa, dados=dados, documentos=documentos, documento=corpo.documento,
                foco=corpo.bloco)
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
