"""Camada contextual do WordCraft sobre os owners existentes do GovConnect.

Este módulo não salva documentos, não aplica patches, não consulta RAG e não
decide fatos administrativos. Ele transforma decisões já validadas pelos
módulos donos em entradas fechadas para ``DocumentoService.preparar_patches``
e produz snapshots somente leitura para o painel único do editor.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import hashlib
import json
from typing import Iterable, Mapping


class ErroCapacidade(ValueError):
    """Entrada contextual não pode ser vinculada ao snapshot auditado."""


class Capacidade(StrEnum):
    GOVBOT = "govbot"
    AUDITORIA = "auditoria"
    PARECER = "parecer"
    TEMPLATE = "template"
    EVIDENCIAS = "evidencias"
    MONTAGEM = "montagem"


ABAS = ("GovBot", "Auditoria", "Parecer", "Evidências", "Histórico")


def painel_unico() -> dict:
    """Contrato estável da barra lateral; as seis capacidades vivem nela."""
    return {
        "schema": "gc-wordcraft-context-panel/v1",
        "abas": list(ABAS),
        "capacidades": [capacidade.value for capacidade in Capacidade],
        "mutacoes": [Capacidade.GOVBOT.value, Capacidade.AUDITORIA.value,
                      Capacidade.PARECER.value],
        "somente_leitura": [Capacidade.TEMPLATE.value,
                            Capacidade.EVIDENCIAS.value,
                            Capacidade.MONTAGEM.value],
    }


def _canonico(valor) -> bytes:
    return json.dumps(valor, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False,
                      default=str).encode("utf-8")


def _hash(valor) -> str:
    return hashlib.sha256(_canonico(valor)).hexdigest()


def _copia_canonica(valor):
    """Cópia profunda JSON; recusa objetos que não formam um snapshot."""
    try:
        return json.loads(_canonico(valor))
    except (TypeError, ValueError, OverflowError):
        raise ErroCapacidade("Valor não pode formar snapshot canônico.") from None


def _indices(relatorio: dict, snapshot: dict) -> tuple[dict, dict]:
    try:
        findings = {item["findingId"]: item for item in relatorio["findings"]}
        blocos = {bloco["path"]: bloco
                  for documento in snapshot["documentos"].values()
                  for bloco in documento["blocos"]}
    except (KeyError, TypeError, AttributeError):
        raise ErroCapacidade("Relatório ou snapshot nativo inválido.") from None
    if len(findings) != len(relatorio["findings"]):
        raise ErroCapacidade("Finding duplicado no relatório.")
    return findings, blocos


@dataclass(frozen=True, slots=True)
class CorrecaoContextual:
    capacidade: Capacidade
    finding_id: str
    novo_texto: str
    motivo: str
    source_ids: tuple[str, ...] = ()


def compilar_correcao(correcao: CorrecaoContextual, *, relatorio: dict,
                      snapshot: dict, caminho: str | None = None) -> dict:
    """Compila uma única correção para o contrato canônico do owner G4.

    O chamador pode escolher um caminho entre os autorizados, mas não fornece
    documento nem hash. Ambos são obtidos do estado auditado corrente.
    """
    if correcao.capacidade not in {Capacidade.GOVBOT, Capacidade.AUDITORIA,
                                  Capacidade.PARECER}:
        raise ErroCapacidade("Capacidade somente leitura não produz patch.")
    if not isinstance(correcao.novo_texto, str) or not correcao.novo_texto.strip():
        raise ErroCapacidade("Correção sem texto objetivo.")
    findings, blocos = _indices(relatorio, snapshot)
    finding = findings.get(correcao.finding_id)
    if not finding or not finding.get("autoCorrectable"):
        raise ErroCapacidade("Finding ausente ou não autocorrigível.")
    permitidos = tuple(finding.get("allowedPaths") or ())
    bloqueados = set(finding.get("blockedPaths") or ())
    alvo = caminho or (permitidos[0] if len(permitidos) == 1 else None)
    if not alvo or alvo not in permitidos or alvo in bloqueados:
        raise ErroCapacidade("Caminho não autorizado ou escolha ambígua.")
    bloco = blocos.get(alvo)
    if not bloco or not isinstance(bloco.get("hash"), str):
        raise ErroCapacidade("Bloco autorizado não existe no snapshot.")
    documento = finding.get("documentId")
    if not isinstance(documento, str) or not alvo.startswith(documento + "/"):
        raise ErroCapacidade("Finding não corresponde ao documento nativo.")
    exigidas = tuple(finding.get("sourceIds") or ())
    fontes = tuple(dict.fromkeys(correcao.source_ids))
    if exigidas and not set(fontes).intersection(exigidas):
        raise ErroCapacidade("Correção factual não referencia fonte exigida.")
    if any(not isinstance(item, str) or not item for item in fontes):
        raise ErroCapacidade("Identificador de fonte inválido.")
    return {
        "operations": [{
            "findingId": correcao.finding_id,
            "documentId": documento,
            "op": "replace",
            "path": alvo,
            "expectedOldHash": bloco["hash"],
            "newValue": correcao.novo_texto,
            "sourceIds": list(fontes),
            "reason": correcao.motivo.strip() or "Correção contextual validada.",
        }],
        "unresolvedFindings": [],
    }


def propositor(correcao: CorrecaoContextual, *, caminho: str | None = None):
    """Callable compatível com ``DocumentoService.preparar_patches``."""
    def propor(*, relatorio, snapshot, contexto):
        del contexto  # fontes já foram autenticadas pelo owner; não ampliam escopo
        return compilar_correcao(correcao, relatorio=relatorio,
                                 snapshot=snapshot, caminho=caminho)
    return propor


def propositor_selecao(*, doc_key: str, texto_selecionado: str,
                       novo_texto: str, motivo: str):
    """Resolve seleção não confiável contra um único bloco/finding autorizado.

    A seleção só escolhe entre paths que o owner acabou de projetar e auditar.
    Como o aplicador atual substitui parágrafo inteiro, a seleção também precisa
    corresponder ao conteúdo integral de um único bloco.
    """
    if (not isinstance(doc_key, str) or not doc_key or
            not isinstance(texto_selecionado, str) or not texto_selecionado.strip()):
        raise ErroCapacidade("Seleção contextual vazia.")

    def propor(*, relatorio, snapshot, contexto):
        del contexto
        try:
            blocos_doc = snapshot["documentos"][doc_key]["blocos"]
            paths = [item["path"] for item in blocos_doc
                     if item.get("conteudo") == texto_selecionado]
            candidatos = [(finding, path) for finding in relatorio["findings"]
                if finding.get("documentId") == doc_key
                and finding.get("autoCorrectable") is True
                and not finding.get("sourceIds")
                for path in paths if path in (finding.get("allowedPaths") or ())
                and path not in set(finding.get("blockedPaths") or ())]
        except (KeyError, TypeError, AttributeError):
            raise ErroCapacidade("Seleção não corresponde ao snapshot nativo.") from None
        if len(paths) != 1 or len(candidatos) != 1:
            raise ErroCapacidade("Seleção ambígua, parcial ou sem finding autocorrigível único.")
        finding, path = candidatos[0]
        return compilar_correcao(CorrecaoContextual(
            Capacidade.GOVBOT, finding["findingId"], novo_texto, motivo),
            relatorio=relatorio, snapshot=snapshot, caminho=path)
    return propor


def propositor_govbot_selecao(*, doc_key: str, texto_selecionado: str,
                              pedido: str, chamar=None):
    """Usa o gateway GovBot existente e recompila a resposta pelo owner G4."""
    if not isinstance(pedido, str) or not pedido.strip():
        raise ErroCapacidade("Pedido ao GovBot vazio.")

    def propor(*, relatorio, snapshot, contexto):
        # Primeiro resolve o único alvo permitido sem confiar no navegador.
        probe = propositor_selecao(doc_key=doc_key, texto_selecionado=texto_selecionado,
                                   novo_texto="__probe__", motivo="probe")
        operation = probe(relatorio=relatorio, snapshot=snapshot, contexto=contexto)["operations"][0]
        path = operation["path"]
        finding = next(item for item in relatorio["findings"]
                       if item.get("findingId") == operation["findingId"])
        from . import govbot
        process = contexto.get("processo") if isinstance(contexto, dict) else {}
        facts = contexto.get("fatos") if isinstance(contexto, dict) else ()
        ctx = govbot.GovBotContext(
            processo_id=str((process or {}).get("id") or "") or None,
            etapa=0, documento=doc_key, bloco_em_foco=path,
            valor_atual=texto_selecionado,
            dados_relevantes=(process or {}).get("dados") or {},
            fatos_relevantes=tuple(facts or ()), achados=(finding,))
        intent = govbot.consultar_ia(ctx, pedido, chamar,
            alvos_permitidos=(path,), fontes_permitidas=())
        if (intent.action not in {"suggest_section_patch", "apply_section_patch"}
                or intent.target != path or intent.sources):
            raise ErroCapacidade("GovBot não produziu proposta textual aplicável à seleção.")
        value = intent.payload.get("new_value")
        reason = str(intent.payload.get("reason") or intent.response or "Sugestão GovBot.")
        return compilar_correcao(CorrecaoContextual(
            Capacidade.GOVBOT, operation["findingId"], value, reason),
            relatorio=relatorio, snapshot=snapshot, caminho=path)
    return propor


def parecer_para_correcao(apontamento, *, novo_texto: str,
                          source_ids: Iterable[str] = ()) -> CorrecaoContextual | dict:
    """Só apontamento objetivo vira proposta; os demais ficam pendentes."""
    from . import parecer_correcao
    if apontamento.situacao != parecer_correcao.CORRECAO_AUTOMATICA:
        return {"findingId": apontamento.id,
                "reason": apontamento.motivo or
                          parecer_correcao.ROTULO_DA_SITUACAO[apontamento.situacao],
                "requiresHumanInput": True}
    return CorrecaoContextual(Capacidade.PARECER, apontamento.id, novo_texto,
                              apontamento.recomendacao, tuple(source_ids))


def verificar_evidencia(fonte: Mapping | None, *, citacao: str | None = None) -> dict:
    """Classifica evidência conhecida sem transformar busca vazia em ausência."""
    if fonte is None:
        estado, motivo = "NAO_VERIFICADA", "Fonte não foi localizada no catálogo consultado."
        identificador = None
    else:
        identificador = fonte.get("id") or fonte.get("source_id")
        if not identificador:
            raise ErroCapacidade("Fonte sem identificador verificável.")
        if fonte.get("vigente") is False or fonte.get("ativo") is False:
            estado, motivo = "INDISPONIVEL", "Fonte conhecida, porém inativa ou não vigente."
        else:
            estado, motivo = "VERIFICADA", "Fonte ativa e identificada no catálogo."
    if citacao and fonte is not None:
        referencias = {str(x) for x in fonte.get("citacoes", ())}
        if citacao not in referencias:
            estado, motivo = "PENDENTE", "Citação não corresponde às referências da fonte."
    return {"schema": "gc-wordcraft-evidence/v1", "source_id": identificador,
            "citacao": citacao, "estado": estado, "motivo": motivo}


def snapshot_template(template_publicado: Mapping, contexto_institucional: Mapping,
                      montagem: Mapping) -> dict:
    """Congela a versão publicada, identidade e resultado determinístico."""
    base = {"schema": "gc-wordcraft-template-snapshot/v1",
            "template": _copia_canonica(template_publicado),
            "institucional": _copia_canonica(contexto_institucional),
            "montagem": _copia_canonica(montagem)}
    return {**base, "hash": _hash(base)}


def montar_itens(itens: Iterable[Mapping]) -> dict:
    """Resumo determinístico para a montagem existente, sem arredondar valores."""
    linhas, total = [], Decimal("0")
    for indice, item in enumerate(itens, start=1):
        try:
            quantidade = Decimal(str(item["quantidade"]))
            unitario = Decimal(str(item["valor_unitario"]))
        except (KeyError, InvalidOperation, ValueError):
            raise ErroCapacidade(f"Item {indice} sem quantidade ou valor válido.") from None
        if quantidade < 0 or unitario < 0:
            raise ErroCapacidade(f"Item {indice} possui valor negativo.")
        subtotal = quantidade * unitario
        total += subtotal
        linhas.append({"numero": indice, "codigo": str(item.get("codigo") or indice),
                       "descricao": str(item.get("descricao") or "").strip(),
                       "quantidade": str(quantidade), "valor_unitario": str(unitario),
                       "subtotal": str(subtotal)})
    base = {"schema": "gc-wordcraft-assembly/v1", "quantidade_itens": len(linhas),
            "itens": linhas, "valor_total": str(total)}
    return {**base, "hash": _hash(base)}
