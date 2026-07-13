"""
Orquestrador do ciclo de correção automática (Etapa 5 —
pacote_correcao_automatica_documentos_v1, 01_ARQUITETURA/02).

    auditoria → corretor por patches → aplicação determinística →
    NOVA AUDITORIA (obrigatória) → aprovação, novo ciclo ou bloqueio

Limites (04_limites_e_excecoes): no máximo MAX_CICLOS_SEMANTICOS por
execução; cada chamada de IA tem as tentativas técnicas do corretor;
falha vira ESTADO explícito (REVIEW_FAILED / CORRECTION_FAILED) — nunca
fallback silencioso. Estados de intervenção humana:
  - WAITING_REQUIRED_DATA: falta dado material (o app pede ao servidor
    SOMENTE o campo indispensável — nunca o documento inteiro);
  - BLOCKED_BY_CONFLICT: finding crítico/conflito de fontes;
  - BLOCKED_MAX_CYCLES: limite de ciclos esgotado sem aprovação.

Flags (consultadas AQUI; os módulos de baixo são puros):
  - flag_correcao_automatica: liga a aplicação dos patches. Desligada,
    o ciclo para em REVIEW_COMPLETED sem tocar nos documentos.
  - flag_reauditoria: liga a auditoria SEMÂNTICA por IA além da
    determinística (achados.py). Findings semânticos não autorizam
    correção (autoCorrectable=False); CRITICAL bloqueia para humano.

Isolamento por tenant: o job de revisão nasce com o tenant da sessão
(db.criar_revisao) e só é retomado se pertencer ao tenant atual.
"""

import json
import logging
from datetime import datetime, timezone

from . import achados, blocos, corretor, db, llm, patches, validacao

FLAG_REAUDITORIA = "reauditoria"

MAX_CICLOS_SEMANTICOS = 3

# etapas exibidas na tela de progresso (Etapa 6)
ETAPAS_UI = (
    "analisando",    # 1. Analisando os documentos
    "preparando",    # 2. Preparando as correções
    "corrigindo",    # 3. Corrigindo os pontos identificados
    "validando",     # 4. Validando novamente
    "finalizando",   # 5. Preparando os arquivos finais
)

_log = logging.getLogger("govdocs.ciclo")


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


def _evento(eventos: list, de: str, para: str, motivo: str,
            versao: int) -> str:
    eventos.append({"de": de, "para": para, "motivo": motivo,
                    "versao": versao, "quando": _agora()})
    _log.info("ciclo: %s -> %s (%s)", de, para, motivo)
    return para


def _campos_requeridos(relatorio: dict) -> list[dict]:
    """O que pedir ao servidor: SOMENTE os campos indispensáveis."""
    pedidos = []
    for f in relatorio["findings"]:
        if f.get("blockingReason") == achados.MOTIVO_DADO_AUSENTE:
            for campo in f.get("camposRequeridos", []):
                pedidos.append({"documento": f["documentId"],
                                "campo": campo,
                                "findingId": f["findingId"]})
    return pedidos


def _estado_sem_corrigiveis(relatorio: dict, documentos: dict) -> str:
    """Nada mais é corrigível automaticamente: aprovar ou pedir ajuda."""
    if any(f.get("blockingReason") == achados.MOTIVO_DADO_AUSENTE
           for f in relatorio["findings"]):
        return "WAITING_REQUIRED_DATA"
    if any(f["severity"] == "CRITICAL" for f in relatorio["findings"]):
        return "BLOCKED_BY_CONFLICT"
    # restam apenas achados que o validador legado classifica como aviso
    # (não impedem a emissão) — mesmo critério da tela anterior
    if validacao.bloqueios(validacao.validar_todos(documentos)):
        return "BLOCKED_BY_CONFLICT"
    return "APPROVED"


# ---------------------------------------------------------------------------
# Auditoria semântica por IA (flag_reauditoria) — NUNCA altera documentos
# ---------------------------------------------------------------------------
_SYSTEM_AUDITOR = """Você é o agente AUDITOR de documentos de contratação pública (Lei nº 14.133/2021): DFD, ETP, TR e Edital.

Analise coerência entre documentos, fundamentação legal, contradições factuais (valores, prazos, quantidades divergentes entre documentos) e riscos jurídicos. NÃO reescreva nada.

Devolva EXCLUSIVAMENTE JSON:
{"findings": [{"documentId": "dfd", "descricao": "...", "severity": "INFO|LOW|MEDIUM|HIGH|CRITICAL", "evidencia": ["trecho"], "regraViolada": "..."}]}
Sem problemas: {"findings": []}. Use CRITICAL apenas para vício que impeça a emissão."""


def auditoria_semantica(documentos: dict[str, str], chamar=None) -> list[dict]:
    """
    Findings semânticos (IA) no mesmo formato dos determinísticos —
    sempre com autoCorrectable=False (a IA não autoriza a própria
    correção; escopo de patch nasce apenas de regra determinística).
    """
    chamar = chamar or llm.chamar_ia_texto
    corpo = json.dumps(
        {k: (v or "")[:20000] for k, v in documentos.items()},
        ensure_ascii=False)
    bruto = chamar(_SYSTEM_AUDITOR, corpo, finalidade="auditor")
    resposta = corretor.extrair_json(bruto)
    findings = []
    for n, f in enumerate(resposta.get("findings") or [], start=1):
        severidade = str(f.get("severity", "MEDIUM")).upper()
        if severidade not in ("INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"):
            severidade = "MEDIUM"
        findings.append({
            "findingId": f"S{n:03d}",
            "documentId": str(f.get("documentId", "")),
            "clauseId": None,
            "categoria": "semantica",
            "severity": severidade,
            "descricao": str(f.get("descricao", "")),
            "evidencia": [str(e) for e in (f.get("evidencia") or [])],
            "regraViolada": str(f.get("regraViolada", "")),
            "resultadoEsperado": "Avaliação do revisor humano.",
            "autoCorrectable": False,
            "allowedPaths": [],
            "blockedPaths": [],
            "sourceIds": [],
            "blockingReason": None,
        })
    return findings


def _auditar(documentos: dict[str, str], processo_id: str | None,
             versao: int, semantica: bool, chamar) -> dict:
    """Auditoria determinística + (opcional) semântica consolidadas."""
    relatorio = achados.gerar_relatorio(documentos, processo_id, versao)
    if semantica:
        extras = auditoria_semantica(documentos, chamar)
        relatorio["findings"] = relatorio["findings"] + extras
        if any(f["severity"] == "CRITICAL" for f in extras):
            relatorio["status"] = "BLOCKED"
        elif extras and relatorio["status"] == "APPROVED":
            relatorio["status"] = "CORRECTIONS_REQUIRED"
    return relatorio


# ---------------------------------------------------------------------------
# O ciclo (função pura em relação a banco; flags/LLM injetáveis)
# ---------------------------------------------------------------------------
def executar_ciclo(documentos: dict[str, str], dados: dict,
                   processo_id: str | None = None, chamar=None,
                   ao_progresso=None, max_ciclos: int = MAX_CICLOS_SEMANTICOS,
                   aplicar_patches: bool | None = None,
                   reauditoria_semantica: bool | None = None) -> dict:
    """
    Executa o ciclo completo e retorna:
      status           estado final da máquina (APPROVED, WAITING_…, …)
      documentos       bundle final (novo dict; o original não muda)
      versao, ciclos   versão final do bundle e ciclos consumidos
      relatorios/planos/diffs/eventos   histórico completo
      campos_requeridos  o que pedir ao servidor (quando WAITING_…)
    """
    progresso = ao_progresso or (lambda etapa: None)
    if aplicar_patches is None:
        aplicar_patches = db.flag_ativa(patches.FLAG_APLICACAO)
    if reauditoria_semantica is None:
        reauditoria_semantica = db.flag_ativa(FLAG_REAUDITORIA)

    docs = dict(documentos)
    eventos: list[dict] = []
    relatorios: list[dict] = []
    planos: list[dict] = []
    diffs: list[dict] = []
    versao = 1
    estado = _evento(eventos, "REVIEW_QUEUED", "REVIEWING",
                     "auditoria inicial", versao)

    progresso("analisando")
    try:
        relatorio = _auditar(docs, processo_id, versao,
                             reauditoria_semantica, chamar)
    except (corretor.ErroCorrecao, llm.ErroGeracaoIA) as erro:
        estado = _evento(eventos, estado, "REVIEW_FAILED", str(erro), versao)
        return _resultado(estado, docs, versao, 0, relatorios, planos,
                          diffs, eventos, [])
    relatorios.append(relatorio)
    estado = _evento(eventos, estado, "REVIEW_COMPLETED",
                     relatorio["summary"], versao)

    ciclos = 0
    while True:
        if relatorio["status"] == "APPROVED":
            estado = _evento(eventos, estado, "APPROVED",
                             "auditoria sem findings", versao)
            break
        corrigiveis = [f for f in relatorio["findings"]
                       if f["autoCorrectable"]]
        if not corrigiveis or not aplicar_patches:
            if not aplicar_patches and corrigiveis:
                # aplicação automática desligada: comportamento antigo
                break
            final = _estado_sem_corrigiveis(relatorio, docs)
            estado = _evento(eventos, estado, final,
                             "sem correções automáticas restantes", versao)
            break
        if ciclos >= max_ciclos:
            estado = _evento(eventos, estado, "BLOCKED_MAX_CYCLES",
                             f"{max_ciclos} ciclos sem aprovação", versao)
            break
        ciclos += 1

        progresso("preparando")
        estado = _evento(eventos, estado, "CORRECTION_PLANNING",
                         f"ciclo {ciclos}", versao)
        try:
            plano = corretor.gerar_plano(relatorio, docs, dados,
                                         chamar=chamar)
        except corretor.ErroCorrecao as erro:
            estado = _evento(eventos, estado, "CORRECTION_FAILED",
                             str(erro), versao)
            break
        planos.append(plano)
        if not plano["operations"]:
            final = _estado_sem_corrigiveis(relatorio, docs)
            estado = _evento(eventos, estado, final,
                             "corretor não propôs operações", versao)
            break

        progresso("corrigindo")
        estado = _evento(eventos, estado, "CORRECTING",
                         f"{len(plano['operations'])} operação(ões)", versao)
        try:
            aplicado = patches.aplicar_plano(plano, docs, relatorio)
        except patches.ErroAplicacao as erro:
            estado = _evento(eventos, estado, "CORRECTION_FAILED",
                             str(erro), versao)
            break
        docs, versao = aplicado["documentos"], aplicado["versao"]
        diffs.append(aplicado["diff"])
        estado = _evento(eventos, estado, "CORRECTION_APPLIED",
                         "patch aplicado", versao)

        progresso("validando")
        estado = _evento(eventos, estado, "REVALIDATING",
                         "nova auditoria obrigatória", versao)
        try:
            relatorio = _auditar(docs, processo_id, versao,
                                 reauditoria_semantica, chamar)
        except (corretor.ErroCorrecao, llm.ErroGeracaoIA) as erro:
            estado = _evento(eventos, estado, "REVIEW_FAILED",
                             str(erro), versao)
            break
        relatorios.append(relatorio)

    progresso("finalizando")
    return _resultado(estado, docs, versao, ciclos, relatorios, planos,
                      diffs, eventos, _campos_requeridos(
                          relatorios[-1] if relatorios else {"findings": []}))


def _resultado(estado, docs, versao, ciclos, relatorios, planos, diffs,
               eventos, campos) -> dict:
    return {
        "status": estado,
        "documentos": docs,
        "versao": versao,
        "ciclos": ciclos,
        "relatorios": relatorios,
        "planos": planos,
        "diffs": diffs,
        "eventos": eventos,
        "campos_requeridos": campos,
    }


# ---------------------------------------------------------------------------
# Persistência do ciclo (retomável — tela de progresso da Etapa 6)
# ---------------------------------------------------------------------------
def revisao_do_tenant(revisao: dict | None) -> dict | None:
    """Isolamento: só devolve o job se pertencer ao tenant da sessão."""
    if revisao and revisao.get("tenant_id") == db.tenant_atual():
        return revisao
    return None


def executar_com_persistencia(documentos: dict[str, str], dados: dict,
                              processo_id: str, chamar=None,
                              ao_progresso=None) -> dict:
    """
    Roda o ciclo persistindo o progresso em `revisoes` (migração 0008):
    o job nasce com idempotency_key por processo+conteúdo (reexecutar a
    mesma versão retoma o resultado já gravado em vez de repetir IA), e
    cada etapa atualiza status/etapa_ui — a tela pode ser fechada e
    retomada. Sem banco, roda em memória (mesmo resultado, sem retomada).
    """
    if not db.disponivel():
        return executar_ciclo(documentos, dados, processo_id, chamar,
                              ao_progresso)

    chave = f"ciclo-{processo_id}-{blocos.hash_bundle(documentos)}"
    snapshot = blocos.snapshot_bundle(documentos, versao=1)
    revisao = revisao_do_tenant(db.obter_revisao_por_chave(chave))
    if revisao and revisao.get("status") not in ("REVIEW_QUEUED",
                                                 "REVIEWING"):
        _log.info("ciclo: job %s retomado (%s)", revisao["id"],
                  revisao["status"])
        snapshots = revisao.get("snapshots") or []
        docs_salvos = (snapshots[-1].get("_documentos")
                       if snapshots else None) or dict(documentos)
        relatorios_salvos = revisao.get("relatorios") or []
        ultimo = (relatorios_salvos[-1] if relatorios_salvos
                  else {"findings": []})
        return _resultado(
            revisao["status"], docs_salvos,
            revisao.get("versao_atual", 1), revisao.get("ciclo", 0),
            relatorios_salvos, revisao.get("planos") or [],
            revisao.get("diffs") or [], revisao.get("eventos") or [],
            _campos_requeridos(ultimo),
        )
    if revisao is None:
        revisao = db.criar_revisao(processo_id, snapshot, {}, chave)

    revisao_id = revisao["id"]

    def progresso(etapa: str) -> None:
        try:
            db.atualizar_revisao(revisao_id, etapa_ui=etapa,
                                 status="REVIEWING")
        except db.ErroBanco:
            pass  # progresso é best-effort; o resultado final não é
        if ao_progresso:
            ao_progresso(etapa)

    resultado = executar_ciclo(documentos, dados, processo_id, chamar,
                               progresso)

    snap_final = blocos.snapshot_bundle(resultado["documentos"],
                                        versao=resultado["versao"])
    snap_final["_documentos"] = resultado["documentos"]
    db.atualizar_revisao(
        revisao_id,
        status=resultado["status"],
        ciclo=resultado["ciclos"],
        etapa_ui="finalizando",
        versao_atual=resultado["versao"],
        bundle_hash=snap_final["hash"],
        snapshots=(revisao.get("snapshots") or []) + [snap_final],
        relatorios=resultado["relatorios"],
        planos=resultado["planos"],
        diffs=resultado["diffs"],
        eventos=resultado["eventos"],
        bloqueio=("" if resultado["status"] == "APPROVED"
                  else resultado["status"]),
    )
    return resultado
