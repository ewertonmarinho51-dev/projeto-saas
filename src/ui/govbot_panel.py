"""Integração do núcleo GovBot com o wizard Streamlit.

Esta é a única camada que conhece ao mesmo tempo ``st.session_state`` e o
componente v2. O navegador envia apenas um envelope não confiável; o módulo
``src.govbot`` valida o envelope e continua sendo a autoridade para propostas,
aplicação, idempotência e desfazer.
"""

from __future__ import annotations

import copy
import hashlib
import logging
import re
import unicodedata
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import streamlit as st

from .. import achados, blocos, fatos, govbot, state
from ..config import SEQUENCIA_DOCUMENTOS
from .govbot_component import render_govbot


_log = logging.getLogger("govdocs.govbot.ui")
_CHAVE_HIDRATACAO = "_widget_hydration"
_CHAVE_UI_ESTADO = "_ui_state"
_CHAVE_UI_STATUS = "_ui_status"
_CHAVE_UI_ABRIR = "_ui_force_open"
_CHAVE_META = "_adapter"


def _sessao() -> MutableMapping[str, Any]:
    return st.session_state


def _documento_atual(sessao: Mapping[str, Any]) -> str | None:
    etapa = int(sessao.get("etapa") or 0)
    if 1 <= etapa <= len(SEQUENCIA_DOCUMENTOS):
        return SEQUENCIA_DOCUMENTOS[etapa - 1]
    return None


def _focos_da_tela(sessao: Mapping[str, Any]) -> set[str]:
    if int(sessao.get("etapa") or 0) == 0:
        return set(govbot.CAMPOS_ESCALARES)
    documento = _documento_atual(sessao)
    return {f"editor_{documento}"} if documento else set()


def _guardar_valor_de_widget(
    bucket: MutableMapping[str, Any], alvo: str, valor: str,
) -> None:
    hidratacao = bucket.setdefault(_CHAVE_HIDRATACAO, {})
    hidratacao[alvo] = valor


def _aplicar_hidratacao(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    *, reidratar_bucket: bool = False,
) -> None:
    """Semeia widgets sem apagar valores mais novos enviados pelo browser.

    Um ``form_draft`` representa a última captura do componente, não
    necessariamente o valor mais recente do widget. Por isso ele só pode
    substituir um widget existente quando houve uma mutação explícita (fila
    ``_widget_hydration``) ou quando outro bucket acabou de ser selecionado.
    """
    rascunho = dict(bucket.get("form_draft") or {})
    pendentes = bucket.pop(_CHAVE_HIDRATACAO, {})
    chaves_pendentes: set[str] = set()
    if isinstance(pendentes, Mapping):
        for alvo, valor in pendentes.items():
            if alvo in govbot.CAMPOS_ESCALARES or alvo in {
                f"editor_{doc}" for doc in SEQUENCIA_DOCUMENTOS
            }:
                rascunho[str(alvo)] = str(valor or "")
                chaves_pendentes.add(str(alvo))
    bucket["form_draft"] = rascunho
    sessao[govbot.CHAVE_RASCUNHO] = copy.deepcopy(rascunho)

    for alvo, valor in rascunho.items():
        if alvo in govbot.CAMPOS_ESCALARES:
            chave_widget = f"govbot_campo_{alvo}"
        elif alvo in {f"editor_{doc}" for doc in SEQUENCIA_DOCUMENTOS}:
            chave_widget = alvo
        else:
            continue
        if reidratar_bucket or alvo in chaves_pendentes \
                or chave_widget not in sessao:
            sessao[chave_widget] = valor


def preparar_sessao() -> MutableMapping[str, Any] | None:
    """Seleciona o bucket e reidrata rascunhos antes do wizard renderizar.

    Quando a flag está desligada, ``inicializar_se_ativo`` retorna antes de
    criar qualquer chave; assim a regressão do wizard não ganha estado oculto.
    """
    sessao = _sessao()
    raiz_anterior = sessao.get(govbot.CHAVE_SESSAO)
    bucket_anterior = (
        raiz_anterior.get("current_bucket")
        if isinstance(raiz_anterior, Mapping) else None
    )
    bucket = govbot.inicializar_se_ativo(
        sessao, sessao.get("processo_id"))
    if bucket is None:
        return None
    raiz_atual = sessao.get(govbot.CHAVE_SESSAO)
    bucket_atual = (
        raiz_atual.get("current_bucket")
        if isinstance(raiz_atual, Mapping) else None
    )
    _aplicar_hidratacao(
        sessao, bucket,
        reidratar_bucket=bucket_anterior != bucket_atual,
    )
    return bucket


def confirmar_formulario() -> None:
    """Descarta o rascunho separado depois de um submit real do formulário."""
    sessao = _sessao()
    raiz = sessao.get(govbot.CHAVE_SESSAO)
    if not isinstance(raiz, Mapping):
        return
    processo_id = sessao.get("processo_id")
    if processo_id and sessao.get("_save_status") == "salvo":
        bucket = govbot.reindexar_bucket(sessao, str(processo_id))
    else:
        bucket = govbot.obter_bucket(sessao, processo_id)
    bucket["form_draft"] = {}
    sessao[govbot.CHAVE_RASCUNHO] = {}


def _sem_acento(texto: str) -> str:
    normalizado = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(
        caractere for caractere in normalizado
        if not unicodedata.combining(caractere)
    ).casefold()


def _bloco_do_pedido(documento: str, texto: str, pedido: str) -> str | None:
    """Resolve um único bloco sem adivinhar entre candidatos ambíguos."""
    candidatos = blocos.dividir_em_blocos(documento, texto)
    conteudo = [bloco for bloco in candidatos if bloco.get("tipo") != "titulo"]
    if not conteudo:
        return None

    for trecho in re.findall(r"[“\"']([^\"'”]{8,})[”\"']", pedido or ""):
        localizado = blocos.localizar_bloco(candidatos, trecho)
        if localizado and localizado.get("tipo") != "titulo":
            return str(localizado["path"])

    numero = re.search(
        r"\b(?:clausula|secao|item|topico)\s*(\d{1,3})\b",
        _sem_acento(pedido),
    )
    if numero:
        da_clausula = [
            bloco for bloco in conteudo
            if bloco.get("clausula") == int(numero.group(1))
        ]
        if len(da_clausula) == 1:
            return str(da_clausula[0]["path"])

    palavras_pedido = {
        palavra for palavra in re.findall(r"[a-z]{4,}", _sem_acento(pedido))
        if palavra not in {"melhore", "corrija", "aplique", "texto", "bloco"}
    }
    pontuados: list[tuple[int, str]] = []
    for indice, bloco in enumerate(candidatos):
        if bloco.get("tipo") != "titulo":
            continue
        palavras_titulo = set(re.findall(
            r"[a-z]{4,}", _sem_acento(str(bloco.get("conteudo") or ""))))
        pontos = len(palavras_pedido & palavras_titulo)
        if not pontos:
            continue
        seguinte = next((
            item for item in candidatos[indice + 1:]
            if item.get("clausula") == bloco.get("clausula")
            and item.get("tipo") != "titulo"
        ), None)
        if seguinte:
            pontuados.append((pontos, str(seguinte["path"])))
    if pontuados:
        maior = max(pontos for pontos, _path in pontuados)
        melhores = {path for pontos, path in pontuados if pontos == maior}
        if len(melhores) == 1:
            return next(iter(melhores))
    return str(conteudo[0]["path"]) if len(conteudo) == 1 else None


def _resolver_foco(
    sessao: Mapping[str, Any], foco: str | None, pedido: str,
    documentos: Mapping[str, str],
) -> str | None:
    if not foco:
        documento = _documento_atual(sessao)
        foco = f"editor_{documento}" if documento else None
    if not foco or not foco.startswith("editor_"):
        return foco
    if not str(pedido or "").strip():
        return foco
    documento = foco.removeprefix("editor_")
    if documento not in govbot.DOCUMENTOS_EDITAVEIS:
        return foco
    path = _bloco_do_pedido(
        documento, str(documentos.get(documento) or ""), pedido)
    return path or foco


def _fatos_canonicos(sessao: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        return fatos.extrair_do_formulario(
            dict(sessao.get("dados") or {}), sessao.get("processo_id"))
    except Exception as exc:  # evidência adicional não derruba o chat
        _log.warning("govbot contexto=fatos resultado=falha tipo=%s",
                     type(exc).__name__)
        return []


def _decisoes_da_sessao(sessao: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cache = sessao.get("_decisao_cache")
    decisao = cache.get("decisao") if isinstance(cache, Mapping) else None
    return [decisao] if isinstance(decisao, Mapping) else []


def _achados_atuais(sessao: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    documentos = dict(sessao.get("documentos") or {})
    if not documentos:
        return []
    try:
        relatorio = achados.gerar_relatorio(
            documentos, sessao.get("processo_id"),
            dados=dict(sessao.get("dados") or {}),
        )
        lista = relatorio.get("findings") if isinstance(relatorio, Mapping) else []
        return list(lista or [])
    except Exception as exc:  # auditoria contextual é best-effort e read-only
        _log.warning("govbot contexto=achados resultado=falha tipo=%s",
                     type(exc).__name__)
        return []


def _referencias_da_sessao(
    sessao: Mapping[str, Any], documento: str | None,
) -> list[Mapping[str, Any]]:
    traces = sessao.get("_rag_trace")
    if not documento or not isinstance(traces, Mapping):
        return []
    trace = traces.get(documento)
    referencias = trace.get("referencias") if isinstance(trace, Mapping) else []
    return list(referencias or [])


def _montar_contexto(
    sessao: Mapping[str, Any], foco: str | None, pedido: str = "",
    *, evidencias: bool = True,
) -> govbot.GovBotContext:
    rascunho = sessao.get(govbot.CHAVE_RASCUNHO)
    rascunho = dict(rascunho) if isinstance(rascunho, Mapping) else {}
    dados = copy.deepcopy(dict(sessao.get("dados") or {}))
    documentos = copy.deepcopy(dict(sessao.get("documentos") or {}))

    foco_normalizado = govbot.normalizar_foco(foco)
    if foco_normalizado and foco_normalizado.startswith("editor_") \
            and foco_normalizado in rascunho:
        documentos[foco_normalizado.removeprefix("editor_")] = \
            rascunho[foco_normalizado]

    foco_resolvido = _resolver_foco(
        sessao, foco_normalizado, pedido, documentos)
    documento = (
        foco_resolvido.split("/", 1)[0]
        if foco_resolvido and "/" in foco_resolvido
        else (foco_resolvido.removeprefix("editor_")
              if foco_resolvido and foco_resolvido.startswith("editor_")
              else _documento_atual(sessao))
    )
    return govbot.montar_contexto_minimo(
        processo_id=sessao.get("processo_id"),
        etapa=int(sessao.get("etapa") or 0),
        dados=dados,
        documentos=documentos,
        foco=foco_resolvido,
        fatos_relevantes=_fatos_canonicos(sessao) if evidencias else (),
        decisoes_conhecimento=(
            _decisoes_da_sessao(sessao) if evidencias else ()),
        achados=_achados_atuais(sessao) if evidencias else (),
        referencias_rag=(
            _referencias_da_sessao(sessao, documento) if evidencias else ()),
        documento=documento,
        rascunhos_visiveis={
            chave: valor for chave, valor in rascunho.items()
            if chave in _focos_da_tela(sessao)
        },
    )


def _alvos_permitidos(contexto: govbot.GovBotContext) -> set[str]:
    alvos = {
        contexto.campo_em_foco, contexto.bloco_em_foco, contexto.documento,
    }
    if contexto.documento:
        # ``editor_*`` é o alvo válido de explain_current; o identificador
        # cru do documento continua disponível apenas para a intenção compare.
        alvos.add(f"editor_{contexto.documento}")
    alvos.update(
        str(item.get("findingId")) for item in contexto.achados
        if item.get("findingId")
    )
    return {alvo for alvo in alvos if alvo}


def _valores_de_fontes(
    contexto: govbot.GovBotContext, fontes: Sequence[str],
) -> list[str]:
    solicitadas = {str(fonte).strip().casefold() for fonte in fontes}
    if not solicitadas:
        return []
    valores: list[str] = []
    for referencia in contexto.referencias_rag:
        aliases = {
            str(referencia.get(chave) or "").strip().casefold()
            for chave in ("source_id", "documento_id", "titulo")
        }
        aliases.update(
            str(item).strip().casefold()
            for item in (referencia.get("dispositivos") or ())
        )
        if solicitadas & aliases and referencia.get("trecho"):
            valores.append(str(referencia["trecho"]))
    return valores


def _valor_canonico(
    sessao: Mapping[str, Any], alvo: str,
) -> tuple[Any, str | None]:
    if alvo in govbot.CAMPOS_ESCALARES:
        return copy.deepcopy((sessao.get("dados") or {}).get(alvo)), None
    if "/" in alvo:
        documento = alvo.split("/", 1)[0]
        por_path = {
            bloco["path"]: bloco for bloco in blocos.dividir_em_blocos(
                documento,
                str((sessao.get("documentos") or {}).get(documento) or ""),
            )
        }
        if alvo not in por_path:
            raise govbot.ErroHashObsoleto("o bloco proposto não existe mais")
        return por_path[alvo]["conteudo"], documento
    raise govbot.ErroAlvo("alvo da proposta fora da lista permitida")


def _anotar_proposta(
    sessao: Mapping[str, Any], bucket: MutableMapping[str, Any],
    resposta: govbot.GovBotReply, contexto: govbot.GovBotContext,
    pedido: str,
) -> None:
    proposta = resposta.proposal
    if proposta is None:
        return
    armazenada = (bucket.get("proposals") or {}).get(proposta.proposal_id)
    if not isinstance(armazenada, MutableMapping):
        return
    canonico, documento = _valor_canonico(sessao, proposta.target)
    payload = dict(armazenada.get("payload") or {})
    payload[_CHAVE_META] = {
        "request_text": pedido,
        "canonical_hash": govbot.hash_canonico(canonico),
        "context_hash": govbot.hash_canonico(proposta.before),
        "source_values": _valores_de_fontes(contexto, proposta.sources),
        "document": documento,
    }
    armazenada["payload"] = payload


def _proposta_revalidada(
    sessao: MutableMapping[str, Any], proposta: govbot.GovBotProposal,
) -> tuple[govbot.GovBotProposal, dict[str, str] | None]:
    meta = proposta.payload.get(_CHAVE_META)
    if not isinstance(meta, Mapping):
        return proposta, None
    canonico, documento = _valor_canonico(sessao, proposta.target)
    if govbot.hash_canonico(canonico) != meta.get("canonical_hash"):
        raise govbot.ErroHashObsoleto(
            "o alvo mudou depois da criação da proposta")

    rascunho = sessao.get(govbot.CHAVE_RASCUNHO)
    rascunho = dict(rascunho) if isinstance(rascunho, Mapping) else {}
    chave_rascunho = proposta.target if documento is None else f"editor_{documento}"
    mescla: dict[str, str] | None = None
    if chave_rascunho in rascunho:
        valor_rascunho: Any = rascunho[chave_rascunho]
        if documento:
            por_path = {
                bloco["path"]: bloco for bloco in blocos.dividir_em_blocos(
                    documento, str(valor_rascunho or ""))
            }
            atual = por_path.get(proposta.target)
            if atual is None:
                raise govbot.ErroHashObsoleto(
                    "o bloco não existe mais no rascunho do editor")
            valor_contexto = atual["conteudo"]
        else:
            valor_contexto = valor_rascunho
        if govbot.hash_canonico(valor_contexto) != meta.get("context_hash"):
            raise govbot.ErroHashObsoleto(
                "o rascunho mudou depois da criação da proposta")
        if documento and str(valor_rascunho) != str(
                (sessao.get("documentos") or {}).get(documento) or ""):
            mescla = {"document": documento, "draft": str(valor_rascunho)}

    revalidada = govbot.GovBotProposal(
        proposal_id=proposta.proposal_id,
        action=proposta.action,
        target=proposta.target,
        before=copy.deepcopy(canonico),
        after=copy.deepcopy(proposta.after),
        reason=proposta.reason,
        sources=proposta.sources,
        origin_hash=govbot.hash_canonico(canonico),
        payload=proposta.payload,
    )
    return revalidada, mescla


def _alvo_de_proposta_na_tela(
    sessao: Mapping[str, Any], alvo: str,
) -> bool:
    """Restringe aplicação à etapa onde a proposta foi apresentada."""
    etapa = int(sessao.get("etapa") or 0)
    if alvo in govbot.CAMPOS_ESCALARES:
        return etapa == 0
    documento = _documento_atual(sessao)
    return bool(documento and alvo.startswith(f"{documento}/"))


def _substituir_bloco(texto: str, path: str, novo_valor: str) -> str:
    lista = blocos.dividir_em_blocos(path.split("/", 1)[0], texto)
    correspondentes = [item for item in lista if item.get("path") == path]
    if len(correspondentes) != 1:
        raise govbot.ErroHashObsoleto(
            "não foi possível preservar o rascunho do editor")
    correspondentes[0]["conteudo"] = novo_valor
    return blocos.reconstruir(lista)


def _reindexar_apos_autosave(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    processo_id = sessao.get("processo_id")
    if processo_id and sessao.get("_save_status") == "salvo":
        return govbot.reindexar_bucket(sessao, str(processo_id))
    return bucket


def _registrar_resultado(
    bucket: MutableMapping[str, Any], resposta: govbot.GovBotReply,
) -> None:
    govbot.adicionar_mensagem(bucket, "system", resposta.response)
    bucket[_CHAVE_UI_ESTADO] = resposta.state
    bucket[_CHAVE_UI_STATUS] = (
        resposta.response if resposta.applied else "Resposta pronta"
    )
    bucket[_CHAVE_UI_ABRIR] = True


def _atualizar_widget_apos_mutacao(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    alvo: str,
) -> None:
    if alvo in govbot.CAMPOS_ESCALARES:
        valor = str((sessao.get("dados") or {}).get(alvo) or "")
        chave = alvo
    else:
        documento = alvo.split("/", 1)[0]
        valor = str((sessao.get("edicoes_pendentes") or {}).get(
            documento, (sessao.get("documentos") or {}).get(documento) or ""))
        chave = f"editor_{documento}"
    rascunho = dict(bucket.get("form_draft") or {})
    rascunho[chave] = valor
    govbot.guardar_rascunho(sessao, rascunho)
    _guardar_valor_de_widget(bucket, chave, valor)


def _aplicar_proposta(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    proposal_id: str, action_id: str,
) -> bool:
    proposta_original = govbot.obter_proposta(bucket, proposal_id)
    if not _alvo_de_proposta_na_tela(sessao, proposta_original.target):
        raise govbot.ErroAlvo(
            "a proposta não pertence à etapa atualmente visível")
    proposta, mescla = _proposta_revalidada(sessao, proposta_original)
    meta = proposta.payload.get(_CHAVE_META)
    pedido = str(meta.get("request_text") or "") if isinstance(meta, Mapping) else ""
    valores_fontes = (
        list(meta.get("source_values") or ()) if isinstance(meta, Mapping) else [])
    fatos_atuais = _fatos_canonicos(sessao)
    documento_alvo = (
        proposta.target.split("/", 1)[0] if "/" in proposta.target else None)
    chave_widget = (
        f"editor_{documento_alvo}" if documento_alvo else proposta.target)
    rascunho_antes = sessao.get(govbot.CHAVE_RASCUNHO)
    rascunho_antes = (
        dict(rascunho_antes) if isinstance(rascunho_antes, Mapping) else {})
    valor_widget_antes = rascunho_antes.get(
        chave_widget,
        (sessao.get("documentos") or {}).get(documento_alvo, "")
        if documento_alvo else proposta_original.before,
    )
    if mescla:
        sessao.setdefault("edicoes_pendentes", {})[mescla["document"]] = \
            mescla["draft"]
    resposta = govbot.aplicar_proposta(
        sessao, bucket, proposta, action_id,
        pedido=pedido,
        fatos=fatos_atuais,
        valores_fontes=valores_fontes,
        invalidar_a_partir_de=state.invalidar_a_partir_de,
        autosalvar=state.autosalvar,
    )
    bucket = _reindexar_apos_autosave(sessao, bucket)
    if bucket.get("changes") and not resposta.duplicate:
        bucket["changes"][-1].setdefault("undo_data", {})["widget_before"] = {
            "target": chave_widget,
            "value": str(valor_widget_antes or ""),
        }
    if mescla:
        documento = mescla["document"]
        preservado = _substituir_bloco(
            mescla["draft"], proposta.target, str(proposta.after))
        sessao.setdefault("edicoes_pendentes", {})[documento] = preservado
        if bucket.get("changes"):
            bucket["changes"][-1]["post_hash"] = govbot.hash_estado(sessao)
        resposta = govbot.GovBotReply(
            request_id=resposta.request_id,
            response=(resposta.response +
                      " As demais edições não enviadas foram preservadas."),
            state=resposta.state,
            intent=resposta.intent,
            proposal=resposta.proposal,
            applied=resposta.applied,
            saved=resposta.saved,
            duplicate=resposta.duplicate,
            error=resposta.error,
        )
    bucket.setdefault("proposals", {}).clear()
    _atualizar_widget_apos_mutacao(sessao, bucket, proposta.target)
    _registrar_resultado(bucket, resposta)
    return True


def _desfazer(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    action_id: str,
) -> bool:
    alteracoes = bucket.get("changes") or []
    alvo = str(alteracoes[-1].get("target") or "") if alteracoes else ""
    undo_data = alteracoes[-1].get("undo_data") if alteracoes else None
    widget_antes = (
        undo_data.get("widget_before") if isinstance(undo_data, Mapping) else None)
    rascunho = sessao.get(govbot.CHAVE_RASCUNHO)
    rascunho = dict(rascunho) if isinstance(rascunho, Mapping) else {}
    if alvo in govbot.CAMPOS_ESCALARES and alvo in rascunho:
        atual = str((sessao.get("dados") or {}).get(alvo) or "")
        if str(rascunho[alvo]) != atual:
            raise govbot.ErroConflitoDesfazer(
                "há edição não enviada no campo; restauração bloqueada")
    elif alvo:
        documento = alvo.split("/", 1)[0]
        chave_editor = f"editor_{documento}"
        if chave_editor in rascunho:
            atual = str((sessao.get("edicoes_pendentes") or {}).get(
                documento,
                (sessao.get("documentos") or {}).get(documento) or "",
            ))
            if str(rascunho[chave_editor]) != atual:
                raise govbot.ErroConflitoDesfazer(
                    "há edição não enviada no documento; restauração bloqueada")
    resposta = govbot.desfazer_ultima_alteracao(
        sessao, bucket, action_id, autosalvar=state.autosalvar)
    bucket = _reindexar_apos_autosave(sessao, bucket)
    bucket.setdefault("proposals", {}).clear()
    if alvo:
        _atualizar_widget_apos_mutacao(sessao, bucket, alvo)
    if isinstance(widget_antes, Mapping):
        chave = str(widget_antes.get("target") or "")
        valor = str(widget_antes.get("value") or "")
        if chave in govbot.CAMPOS_ESCALARES or chave in {
            f"editor_{doc}" for doc in SEQUENCIA_DOCUMENTOS
        }:
            rascunho_restaurado = dict(bucket.get("form_draft") or {})
            rascunho_restaurado[chave] = valor
            govbot.guardar_rascunho(sessao, rascunho_restaurado)
            _guardar_valor_de_widget(bucket, chave, valor)
    _registrar_resultado(bucket, resposta)
    return True


def _corrigir_achado(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    contexto: govbot.GovBotContext, finding_id: str, action_id: str,
) -> bool:
    finding = next((
        item for item in contexto.achados
        if item.get("findingId") == finding_id
    ), None)
    if not finding:
        raise govbot.ErroAlvo("achado não pertence ao contexto atual")
    documento = str(finding.get("documentId") or "")
    if documento not in govbot.DOCUMENTOS_EDITAVEIS:
        raise govbot.ErroAlvo(
            "achados de Edital ou ARP devem ser corrigidos na origem")
    rascunho = sessao.get(govbot.CHAVE_RASCUNHO)
    chave_editor = f"editor_{documento}"
    if isinstance(rascunho, Mapping) and chave_editor in rascunho \
            and str(rascunho[chave_editor]) != str(
                (sessao.get("documentos") or {}).get(documento) or ""):
        raise govbot.ErroHashObsoleto(
            "há edições não enviadas no documento; revise-as antes "
            "da correção automática")
    resposta = govbot.corrigir_achado(
        sessao, bucket, finding_id, action_id,
        invalidar_a_partir_de=state.invalidar_a_partir_de,
        autosalvar=state.autosalvar,
    )
    bucket = _reindexar_apos_autosave(sessao, bucket)
    bucket.setdefault("proposals", {}).clear()
    # ``reply.intent.target`` identifica o finding para auditoria, mas a
    # hidratação precisa apontar para o documento efetivamente corrigido.
    _atualizar_widget_apos_mutacao(sessao, bucket, documento)
    _registrar_resultado(bucket, resposta)
    return True


def _id_de_acao(request_id: str, sufixo: str) -> str:
    digest = hashlib.sha256(
        f"{request_id}:{sufixo}".encode("utf-8")).hexdigest()[:24]
    return f"govbot-{sufixo}-{digest}"


def _mensagem_de_erro(
    bucket: MutableMapping[str, Any], request_id: str, mensagem: str,
) -> None:
    texto = str(mensagem or "Operação recusada pelo validador.")[:1000]
    govbot.adicionar_mensagem(bucket, "system", texto)
    if govbot.resultado_processado(bucket, request_id) is None:
        try:
            govbot.marcar_processado(bucket, request_id, {
                "response": texto, "state": "ERROR", "applied": False,
                "saved": False,
            })
        except govbot.ErroGovBot:
            pass
    bucket[_CHAVE_UI_ESTADO] = "ERROR"
    bucket[_CHAVE_UI_STATUS] = "Não foi possível concluir a operação"
    bucket[_CHAVE_UI_ABRIR] = True


def _processar_evento(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
    bruto: Mapping[str, Any],
) -> bool:
    focos_da_tela = _focos_da_tela(sessao)
    evento = govbot.parsear_evento(
        bruto, bucket, focos_permitidos=focos_da_tela,
        rascunhos_permitidos=focos_da_tela,
    )
    if evento.focus is not None:
        bucket["_last_focus"] = evento.focus
    govbot.guardar_rascunho(sessao, evento.draft)

    if evento.event_type == "apply_proposal":
        return _aplicar_proposta(
            sessao, bucket, str(evento.proposal_id), evento.request_id)
    if evento.event_type == "undo":
        return _desfazer(sessao, bucket, evento.request_id)

    contexto = _montar_contexto(sessao, evento.focus, evento.text)
    resposta = govbot.processar_mensagem(
        evento, contexto, bucket,
        alvos_permitidos=_alvos_permitidos(contexto),
    )
    _anotar_proposta(sessao, bucket, resposta, contexto, evento.text)
    bucket[_CHAVE_UI_ESTADO] = resposta.state
    bucket[_CHAVE_UI_STATUS] = (
        "Sugestão pronta para revisão"
        if resposta.proposal else "Resposta pronta")
    bucket[_CHAVE_UI_ABRIR] = True

    if resposta.proposal and govbot.deve_aplicar_imediatamente(
            evento.text, resposta.intent):
        return _aplicar_proposta(
            sessao, bucket, resposta.proposal.proposal_id,
            _id_de_acao(evento.request_id, "apply"),
        )
    if resposta.intent and govbot.deve_desfazer_imediatamente(
            evento.text, resposta.intent):
        return _desfazer(
            sessao, bucket, _id_de_acao(evento.request_id, "undo"))
    if resposta.intent and resposta.intent.action == "fix_finding" \
            and govbot.deve_aplicar_imediatamente(evento.text, resposta.intent):
        return _corrigir_achado(
            sessao, bucket, contexto, str(resposta.intent.target),
            _id_de_acao(evento.request_id, "fix"),
        )
    return False


def _view_model(
    sessao: MutableMapping[str, Any], bucket: MutableMapping[str, Any],
) -> dict[str, Any]:
    foco_anterior = bucket.get("_last_focus")
    if foco_anterior not in _focos_da_tela(sessao):
        foco_anterior = None
    contexto = _montar_contexto(
        sessao, foco_anterior, evidencias=False)
    raiz = sessao.get(govbot.CHAVE_SESSAO)
    raiz = raiz if isinstance(raiz, Mapping) else {}
    view = govbot.montar_view_model(
        bucket, contexto,
        state=str(bucket.get(_CHAVE_UI_ESTADO) or "IDLE"),
        status_text=str(bucket.get(_CHAVE_UI_STATUS) or "GovBot pronto"),
        open=bool(raiz.get("open", True)),
        force_open=bool(bucket.pop(_CHAVE_UI_ABRIR, False)),
    )
    view["proactive"] = bool(raiz.get("proactive", True))
    dados = sessao.get("dados") if isinstance(sessao.get("dados"), Mapping) else {}
    draft = (sessao.get(govbot.CHAVE_RASCUNHO)
             if isinstance(sessao.get(govbot.CHAVE_RASCUNHO), Mapping) else {})
    escalares_atuais = {
        campo: draft.get(campo, dados.get(campo))
        for campo in govbot.CAMPOS_ESCALARES
    }
    view["form_version"] = govbot.hash_canonico(escalares_atuais)
    # Exibe apenas a proposta mais recente; as anteriores continuam no bucket
    # para auditoria efêmera, mas não viram botões potencialmente obsoletos.
    view["proposals"] = [
        proposta for proposta in view.get("proposals", [])
        if _alvo_de_proposta_na_tela(
            sessao, str(proposta.get("target") or ""))
    ][-1:]
    return view


@st.fragment
def render() -> None:
    """Monta o GovBot no wizard; conversas comuns rerodam só o fragmento."""
    if not govbot.ativo():
        return
    sessao = _sessao()
    bucket = govbot.obter_bucket(sessao, sessao.get("processo_id"))
    evento_bruto = render_govbot(
        _view_model(sessao, bucket), key="govbot-wizard")
    if evento_bruto is None:
        return
    try:
        mutou = _processar_evento(sessao, bucket, evento_bruto)
    except govbot.IdentificadorRepetido:
        return
    except govbot.ErroGovBot as exc:
        _mensagem_de_erro(
            bucket, str(evento_bruto.get("request_id") or ""), str(exc))
        st.rerun(scope="fragment")
        return
    except Exception as exc:  # não vaza detalhes técnicos para o navegador
        _log.error("govbot evento resultado=falha tipo=%s",
                   type(exc).__name__)
        _mensagem_de_erro(
            bucket, str(evento_bruto.get("request_id") or ""),
            "Não foi possível concluir a solicitação. Nenhuma ação "
            "foi executada.",
        )
        st.rerun(scope="fragment")
        return
    if mutou:
        st.rerun()
    else:
        st.rerun(scope="fragment")


__all__ = ["confirmar_formulario", "preparar_sessao", "render"]
