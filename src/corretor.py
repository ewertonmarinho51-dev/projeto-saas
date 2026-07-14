"""
Corretor por patches (Etapa 3 da correção automática —
pacote_correcao_automatica_documentos_v1, 02_PROMPTS/02).

Papel ÚNICO: receber os findings corrigíveis automaticamente e devolver
um PLANO de operações de patch. O corretor:
  - nunca devolve documentos completos (só operações atômicas);
  - nunca altera caminhos fora do escopo autorizado de cada finding;
  - nunca inventa fato material sem fonte;
  - não aplica nada — quem aplica é o código determinístico (Etapa 4).

Todo plano devolvido pela IA passa por `validar_plano` (código puro):
operação desconhecida, finding não autorizado, caminho fora do escopo,
caminho bloqueado, excesso de operações, fonte ausente ou hash de origem
divergente REJEITAM o plano. Falha técnica tem até 2 tentativas
(config do pacote) e depois vira erro explícito — sem fallback
silencioso.

Feature flag `flag_corretor_shadow` (config_app, default OFF):
  - DESLIGADA: nada acontece (nem chamada de IA).
  - LIGADA: o plano é gerado e REGISTRADO (log + revisoes.planos) sem
    aplicar nenhuma alteração — validação em produção antes do corte
    (a aplicação de verdade é a Etapa 4, com outra flag).
"""

import json
import logging
import uuid
from datetime import datetime, timezone

import streamlit as st

from . import achados, blocos, db, llm

FLAG_CORRETOR = "corretor_shadow"

MAX_OPERACOES = 30           # máximo de operações por plano de patch
MAX_TENTATIVAS_TECNICAS = 2  # tentativas por chamada (config do pacote)

OPERACOES_VALIDAS = ("replace", "add", "remove")

_log = logging.getLogger("govdocs.corretor")


class ErroCorrecao(Exception):
    """Plano de patch inválido ou falha técnica do corretor."""


# ---------------------------------------------------------------------------
# Prompt do corretor
# ---------------------------------------------------------------------------
_SYSTEM_CORRETOR = """Você é o agente CORRETOR de documentos de contratação pública (Lei nº 14.133/2021).

Receberá findings de auditoria aprovados para correção automática, os blocos atuais dos documentos (com caminho e hash) e as fontes disponíveis.

Sua ÚNICA tarefa é devolver um plano de patch em JSON. Regras obrigatórias:

1. Corrija todos os findings recebidos (todos têm autoCorrectable=true).
2. Altere SOMENTE caminhos listados em allowedPaths do finding correspondente.
3. Preserve todo o restante exatamente como está — nada de melhorias estilísticas fora do escopo.
4. Nunca devolva um documento completo: apenas operações atômicas por bloco.
5. Toda alteração factual deve indicar em sourceIds a fonte que a sustenta (use os sourceIds do finding). Não invente fatos, valores, quantidades nem datas.
6. Não remova conteúdo para "resolver" uma inconsistência, salvo se a remoção for a correção adequada — e justifique.
7. Se um finding não puder ser corrigido com as fontes disponíveis, liste-o em unresolvedFindings com o motivo e requiresHumanInput.
8. Em `expectedOldHash`, copie o hash atual do bloco alterado (pré-condição da aplicação).

Devolva EXCLUSIVAMENTE o JSON (sem comentários, sem markdown):
{
  "operations": [
    {
      "findingId": "F001",
      "documentId": "dfd",
      "op": "replace" | "add" | "remove",
      "path": "dfd/clausula/2/1",
      "expectedOldHash": "hash do bloco atual (null para add)",
      "newValue": "novo conteúdo Markdown do bloco (null para remove)",
      "sourceIds": ["formulario:itens"],
      "reason": "justificativa curta",
      "expectedImpact": "efeito esperado no documento"
    }
  ],
  "unresolvedFindings": [
    {"findingId": "F002", "reason": "motivo", "requiresHumanInput": true}
  ]
}"""


def _fontes_do_formulario(dados: dict) -> dict:
    """Fatos materiais disponíveis como fonte (sourceId → conteúdo)."""
    fontes = {}
    for campo, valor in (dados or {}).items():
        if campo == "itens":
            continue
        if isinstance(valor, (str, int, float)) and str(valor).strip():
            fontes[f"formulario:{campo}"] = str(valor)
    itens = (dados or {}).get("itens")
    if itens:
        fontes["formulario:itens"] = json.dumps(
            itens, ensure_ascii=False)[:4000]
    return fontes


def montar_prompt(findings: list[dict], documentos: dict[str, str],
                  dados: dict) -> tuple[str, str]:
    """(system, user) do corretor: findings + blocos do escopo + fontes."""
    por_doc = {k: blocos.dividir_em_blocos(k, v or "")
               for k, v in documentos.items()}
    caminhos_no_escopo = {p for f in findings for p in f["allowedPaths"]}
    blocos_escopo = [
        {"path": b["path"], "hash": b["hash"], "conteudo": b["conteudo"]}
        for bs in por_doc.values() for b in bs
        if b["path"] in caminhos_no_escopo
    ]
    payload = {
        "findings": [
            {
                "findingId": f["findingId"],
                "documentId": f["documentId"],
                "descricao": f["descricao"],
                "regraViolada": f["regraViolada"],
                "resultadoEsperado": f["resultadoEsperado"],
                "evidencia": f["evidencia"],
                "allowedPaths": f["allowedPaths"],
                "sourceIds": f["sourceIds"],
            }
            for f in findings
        ],
        "blocosAtuais": blocos_escopo,
        "fontes": _fontes_do_formulario(dados),
    }
    return _SYSTEM_CORRETOR, json.dumps(payload, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Validação determinística do plano (código, não IA)
# ---------------------------------------------------------------------------
def extrair_json(texto: str) -> dict:
    """JSON da resposta da IA, tolerante a cercas de código."""
    bruto = (texto or "").strip()
    if bruto.startswith("```"):
        bruto = bruto.split("\n", 1)[-1].rsplit("```", 1)[0]
    inicio, fim = bruto.find("{"), bruto.rfind("}")
    if inicio < 0 or fim <= inicio:
        raise ErroCorrecao("resposta do corretor não contém JSON")
    try:
        return json.loads(bruto[inicio:fim + 1])
    except json.JSONDecodeError as exc:
        raise ErroCorrecao(f"JSON inválido do corretor: {exc}") from exc


def validar_plano(plano: dict, relatorio: dict, snapshot: dict) -> list[str]:
    """
    Regras objetivas sobre o plano — QUALQUER violação rejeita o plano
    inteiro (o corretor não é confiável por construção; o código é o
    guardião). Retorna a lista de violações.
    """
    violacoes: list[str] = []
    autorizados = {f["findingId"]: f for f in relatorio["findings"]
                   if f["autoCorrectable"]}
    hashes = {
        b["path"]: b["hash"]
        for doc in snapshot["documentos"].values() for b in doc["blocos"]
    }
    operacoes = plano.get("operations")
    if not isinstance(operacoes, list):
        return ["plano sem lista de operações"]
    if len(operacoes) > MAX_OPERACOES:
        violacoes.append(
            f"máximo de {MAX_OPERACOES} operações excedido "
            f"({len(operacoes)})")
    for i, op in enumerate(operacoes):
        rotulo = f"operação {i + 1}"
        finding = autorizados.get(op.get("findingId"))
        if finding is None:
            violacoes.append(
                f"{rotulo}: finding não autorizado "
                f"({op.get('findingId')!r})")
            continue
        if op.get("op") not in OPERACOES_VALIDAS:
            violacoes.append(f"{rotulo}: tipo inválido {op.get('op')!r}")
        path = op.get("path") or ""
        if path not in finding["allowedPaths"]:
            violacoes.append(
                f"{rotulo}: caminho fora do escopo autorizado ({path})")
        if path in finding["blockedPaths"]:
            violacoes.append(f"{rotulo}: caminho bloqueado ({path})")
        if op.get("op") in ("replace", "remove"):
            esperado = op.get("expectedOldHash")
            if esperado and hashes.get(path) and esperado != hashes[path]:
                violacoes.append(
                    f"{rotulo}: hash de origem divergente em {path}")
            if path not in hashes:
                violacoes.append(
                    f"{rotulo}: bloco inexistente para {op.get('op')} "
                    f"({path})")
        if op.get("op") in ("replace", "add"):
            if not str(op.get("newValue") or "").strip():
                violacoes.append(f"{rotulo}: newValue vazio")
        if finding["sourceIds"] and not (
            set(op.get("sourceIds") or []) & set(finding["sourceIds"])
        ):
            violacoes.append(
                f"{rotulo}: alteração factual sem a fonte exigida "
                f"({finding['sourceIds']})")
    return violacoes


def _envelope(operacoes: list[dict], nao_resolvidos: list[dict],
              relatorio: dict, snapshot: dict) -> dict:
    """Envelope do patch-plan montado por CÓDIGO (não pela IA)."""
    for i, op in enumerate(operacoes, start=1):
        op.setdefault("operationId", f"OP{i:03d}")
    return {
        "patchPlanId": uuid.uuid4().hex,
        "bundleId": relatorio["bundleId"],
        "sourceBundleVersion": snapshot["versao"],
        "sourceBundleHash": snapshot["hash"],
        "operations": operacoes,
        "unresolvedFindings": nao_resolvidos,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }


def gerar_plano(relatorio: dict, documentos: dict[str, str], dados: dict,
                chamar=None) -> dict:
    """
    Plano de patch VALIDADO para os findings corrigíveis do relatório.
    `chamar` é injetável para teste (default: llm.chamar_ia_texto).
    Até MAX_TENTATIVAS_TECNICAS chamadas: a segunda recebe o motivo da
    rejeição da primeira. Esgotadas, levanta ErroCorrecao (estado
    explícito — nunca fallback silencioso).
    """
    chamar = chamar or llm.chamar_ia_texto
    snapshot = blocos.snapshot_bundle(
        documentos, versao=relatorio.get("bundleVersion", 1))
    corrigiveis = [f for f in relatorio["findings"] if f["autoCorrectable"]]
    manuais = [
        {
            "findingId": f["findingId"],
            "reason": f.get("blockingReason") or "correção não automática",
            "requiresHumanInput": True,
            "requiredFields": f.get("camposRequeridos", []),
        }
        for f in relatorio["findings"] if not f["autoCorrectable"]
    ]
    if not corrigiveis:
        return _envelope([], manuais, relatorio, snapshot)

    system, user = montar_prompt(corrigiveis, documentos, dados)
    feedback = ""
    ultima_falha = "sem resposta"
    for _ in range(MAX_TENTATIVAS_TECNICAS):
        try:
            bruto = chamar(system, user + feedback, finalidade="corretor")
            resposta = extrair_json(bruto)
            plano = _envelope(
                list(resposta.get("operations") or []),
                list(resposta.get("unresolvedFindings") or []) + manuais,
                relatorio, snapshot,
            )
            violacoes = validar_plano(plano, relatorio, snapshot)
            if violacoes:
                raise ErroCorrecao("; ".join(violacoes))
            return plano
        except (ErroCorrecao, llm.ErroGeracaoIA) as erro:
            ultima_falha = str(erro)
            _log.warning("corretor: tentativa rejeitada: %s", ultima_falha)
            feedback = (
                "\n\nATENÇÃO: sua resposta anterior foi rejeitada pelo "
                f"validador: {ultima_falha}. Corrija e devolva apenas o "
                "JSON no formato exigido."
            )
    raise ErroCorrecao(
        f"Corretor falhou após {MAX_TENTATIVAS_TECNICAS} tentativa(s): "
        f"{ultima_falha}"
    )


# ---------------------------------------------------------------------------
# Shadow mode (flag_corretor_shadow) — gera e registra, NUNCA aplica
# ---------------------------------------------------------------------------
def ativo() -> bool:
    return db.flag_ativa(FLAG_CORRETOR)


def plano_em_shadow(documentos: dict[str, str], dados: dict,
                    processo_id: str | None = None) -> None:
    """
    Com a flag ligada, gera o plano UMA vez por versão do bundle (cache
    por hash na sessão), registra em log e no job de revisão (quando o
    banco e a migração 0008 existem). Nenhuma alteração é aplicada e
    nenhuma falha chega à tela — shadow mode não pode afetar o fluxo.
    """
    if not ativo():
        return
    hash_atual = blocos.hash_bundle(documentos)
    if st.session_state.get("_shadow_plano_hash") == hash_atual:
        return  # já registrado para esta versão do bundle
    try:
        relatorio = achados.gerar_relatorio(documentos, processo_id)
        plano = gerar_plano(relatorio, documentos, dados)
        st.session_state["_shadow_plano_hash"] = hash_atual
        _log.info(
            "shadow: plano %s — %d operação(ões), %d não resolvido(s)",
            plano["patchPlanId"], len(plano["operations"]),
            len(plano["unresolvedFindings"]),
        )
        _persistir_shadow(processo_id, documentos, relatorio, plano)
    except Exception as exc:  # noqa: BLE001 — shadow nunca derruba a tela
        st.session_state["_shadow_plano_hash"] = hash_atual
        _log.warning("shadow: corretor indisponível: %s", exc)


def _persistir_shadow(processo_id: str | None, documentos: dict[str, str],
                      relatorio: dict, plano: dict) -> None:
    """Best-effort: guarda relatório e plano no job de revisão (0008)."""
    if not (processo_id and db.disponivel()):
        return
    try:
        revisao = db.obter_revisao(processo_id)
        if revisao is None:
            revisao = db.criar_revisao(
                processo_id,
                blocos.snapshot_bundle(documentos, versao=1),
                relatorio,
                idempotency_key=(
                    f"shadow-{processo_id}-{relatorio['bundleHash']}"),
            )
        db.atualizar_revisao(
            revisao["id"],
            planos=(revisao.get("planos") or []) + [plano],
            relatorios=(revisao.get("relatorios") or []) + [relatorio],
        )
    except db.ErroBanco as exc:
        _log.warning("shadow: persistência indisponível: %s", exc)
