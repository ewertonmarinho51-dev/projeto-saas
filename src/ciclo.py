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
import re
import unicodedata
from datetime import datetime, timezone

from . import achados, blocos, corretor, db, llm, patches, validacao
from .config import DOCUMENTOS

FLAG_REAUDITORIA = "reauditoria"

MAX_CICLOS_SEMANTICOS = 3

# Auditoria/correção são tarefas rápidas e estruturadas: não faz sentido
# esperar o teto de 180s da geração de documentos longos. Timeout curto e
# uma única tentativa por motor para o auditor desistir cedo (e a
# determinística seguir) em vez de travar a tela por minutos.
TIMEOUT_AUDITORIA_SEGUNDOS = 45

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


def _normalizar_campo(campo: str) -> str:
    """Comparação de nomes de campo: sem acento, caixa ou pontuação."""
    texto = unicodedata.normalize("NFKD", campo or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9 ]", " ", texto.lower()).strip()


def _chave_do_pedido(pendencia: dict) -> str:
    """
    Duas lacunas são a MESMA pergunta quando pedem o mesmo dado do
    processo — inclusive em documentos diferentes (o prazo de vigência do
    DFD e o do ETP são o mesmo fato, e devem ser perguntados uma vez só).

    Exceção: quando a lacuna é POSICIONAL — o nome veio da coluna da
    tabela, do título da cláusula ou do trecho, ou o alvo é um valor
    improvisado — o mesmo rótulo se repete em pontos que pedem valores
    diferentes (a matrícula da Ana não é a do Bruno). Ali a chave inclui
    o contexto, sob pena de a resposta de um ponto vazar para os demais.
    """
    campo = _normalizar_campo(pendencia.get("campo", ""))
    if pendencia.get("origem") in ("tabela", "clausula", "trecho",
                                   "valor_improvisado"):
        return f"{campo}|{pendencia.get('contexto', '')}"
    return campo


def _pendencias_do_finding(finding: dict) -> list[dict]:
    """Pendências estruturadas; findings antigos trazem só os nomes."""
    if finding.get("pendencias"):
        return finding["pendencias"]
    return [{"campo": campo, "qualificador": "", "marcador": "",
             "molde": "", "ocorrencia": 0, "clausula": "", "contexto": "",
             "origem": "regra"}
            for campo in finding.get("camposRequeridos", [])]


def _campos_requeridos(relatorio: dict) -> list[dict]:
    """
    O que pedir ao servidor: SOMENTE os campos indispensáveis, cada um
    perguntado UMA vez, com tudo o que a tela precisa para explicar a
    pergunta (cláusula e trecho) e para aplicar a resposta sem ambiguidade
    (`alvos`: documento + marcador exato + ocorrência).
    """
    pedidos: dict[str, dict] = {}
    ordem: list[str] = []
    for f in relatorio.get("findings") or []:
        if f.get("blockingReason") != achados.MOTIVO_DADO_AUSENTE:
            continue
        for pendencia in _pendencias_do_finding(f):
            chave = _chave_do_pedido(pendencia)
            alvo = {
                "documento": f["documentId"],
                "marcador": pendencia.get("marcador", ""),
                "molde": pendencia.get("molde", ""),
                "ocorrencia": pendencia.get("ocorrencia", 0),
                "findingId": f["findingId"],
            }
            pedido = pedidos.get(chave)
            if pedido is None:
                pedidos[chave] = {
                    "documento": f["documentId"],   # 1º documento afetado
                    "documentos": [f["documentId"]],
                    "campo": pendencia.get("campo", ""),
                    "qualificador": pendencia.get("qualificador", ""),
                    "findingId": f["findingId"],
                    "clausula": pendencia.get("clausula", ""),
                    "contexto": pendencia.get("contexto", ""),
                    "origem": pendencia.get("origem", "regra"),
                    "alvos": [alvo],
                }
                ordem.append(chave)
                continue
            if alvo not in pedido["alvos"]:
                pedido["alvos"].append(alvo)
            if f["documentId"] not in pedido["documentos"]:
                pedido["documentos"].append(f["documentId"])
    return [pedidos[chave] for chave in ordem]


def _decisoes_requeridas(relatorio: dict) -> list[dict]:
    """
    O que NÃO se pergunta em caixa de texto: escolhas do revisor
    (instituto jurídico, reescrita de cláusula, ordem do raciocínio).
    Cada uma aponta a etapa do wizard onde a decisão é tomada — o usuário
    não precisa descobrir sozinho onde agir.
    """
    decisoes = []
    for f in relatorio.get("findings") or []:
        if f.get("blockingReason") != achados.MOTIVO_DISCRICIONARIO:
            continue
        doc = DOCUMENTOS.get(f["documentId"], {})
        decisoes.append({
            "documento": f["documentId"],
            "sigla": doc.get("sigla", f["documentId"].upper()),
            "etapa": doc.get("etapa"),
            "descricao": f["descricao"],
            "esperado": f.get("resultadoEsperado", ""),
            "regra": f.get("regraViolada", ""),
            "evidencia": (f.get("evidencia") or [""])[0],
            "findingId": f["findingId"],
        })
    return decisoes


def _estado_sem_corrigiveis(relatorio: dict, documentos: dict,
                            dados: dict | None = None) -> str:
    """Nada mais é corrigível automaticamente: aprovar ou pedir ajuda."""
    if any(f.get("blockingReason") == achados.MOTIVO_DADO_AUSENTE
           for f in relatorio["findings"]):
        return "WAITING_REQUIRED_DATA"
    if any(f["severity"] == "CRITICAL" for f in relatorio["findings"]):
        return "BLOCKED_BY_CONFLICT"
    # restam apenas achados que o validador legado classifica como aviso
    # (não impedem a emissão) — mesmo critério da tela anterior
    if validacao.bloqueios(validacao.validar_todos(documentos, None, dados)):
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


# Acima deste nº de linhas consecutivas de tabela, o bloco é tratado
# como tabela DETERMINÍSTICA (planilha injetada) e sai do corpo enviado
# ao auditor semântico: a tabela é conferida por código, e centenas de
# linhas dela consumiam o orçamento de contexto deixando a prosa final
# (a parte que só a auditoria semântica cobre) fora da análise.
_LIMITE_TABELA_AUDITOR = 8


def _texto_para_auditor(texto: str) -> str:
    """Prosa do documento com as tabelas determinísticas resumidas."""
    linhas = (texto or "").splitlines()
    saida: list[str] = []
    bloco: list[str] = []

    def descarrega():
        if len(bloco) > _LIMITE_TABELA_AUDITOR:
            saida.append(
                f"[TABELA DETERMINÍSTICA DE {len(bloco)} LINHAS OMITIDA "
                "DESTA AUDITORIA — o conteúdo dela é conferido por "
                "validação determinística contra a planilha-fonte]")
        else:
            saida.extend(bloco)
        bloco.clear()

    for linha in linhas:
        if linha.lstrip().startswith("|"):
            bloco.append(linha)
            continue
        descarrega()
        saida.append(linha)
    descarrega()
    return "\n".join(saida)


def auditoria_semantica(documentos: dict[str, str], chamar=None) -> list[dict]:
    """
    Findings semânticos (IA) no mesmo formato dos determinísticos —
    sempre com autoCorrectable=False (a IA não autoriza a própria
    correção; escopo de patch nasce apenas de regra determinística).
    """
    if chamar is None:
        def chamar(system, user, finalidade):
            return llm.chamar_ia_texto(
                system, user, finalidade=finalidade,
                timeout=TIMEOUT_AUDITORIA_SEGUNDOS, tentativas=1)
    corpo = json.dumps(
        {k: _texto_para_auditor(v)[:20000] for k, v in documentos.items()},
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
             versao: int, semantica: bool, chamar,
             dados: dict | None = None) -> dict:
    """
    Auditoria determinística (obrigatória) + semântica (OPCIONAL).

    A auditoria semântica por IA é uma camada opcional (flag_reauditoria):
    se a IA falhar ou demorar (timeout), ela é PULADA com um aviso e a
    auditoria determinística — que já rodou e nunca depende de IA — segue
    carregando a revisão. Uma camada opcional NUNCA pode derrubar o ciclo
    inteiro: sem isto, uma lentidão da IA virava um falso "auditoria
    indisponível" e descartava o trabalho determinístico.
    """
    relatorio = achados.gerar_relatorio(documentos, processo_id, versao,
                                        dados)
    if not semantica:
        return relatorio
    try:
        extras = auditoria_semantica(documentos, chamar)
    except (corretor.ErroCorrecao, llm.ErroGeracaoIA) as erro:
        _log.warning(
            "auditoria semântica indisponível — seguindo apenas com a "
            "determinística: %s", erro)
        relatorio["semantica_indisponivel"] = True
        return relatorio
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
      campos_requeridos    o que PERGUNTAR ao servidor (dado ausente)
      decisoes_requeridas  o que o revisor precisa DECIDIR (discricionário)
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
                             reauditoria_semantica, chamar, dados)
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
            final = _estado_sem_corrigiveis(relatorio, docs, dados)
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
            final = _estado_sem_corrigiveis(relatorio, docs, dados)
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
                                 reauditoria_semantica, chamar, dados)
        except (corretor.ErroCorrecao, llm.ErroGeracaoIA) as erro:
            estado = _evento(eventos, estado, "REVIEW_FAILED",
                             str(erro), versao)
            break
        relatorios.append(relatorio)

    progresso("finalizando")
    ultimo = relatorios[-1] if relatorios else {"findings": []}
    return _resultado(estado, docs, versao, ciclos, relatorios, planos,
                      diffs, eventos, _campos_requeridos(ultimo),
                      _decisoes_requeridas(ultimo))


def _resultado(estado, docs, versao, ciclos, relatorios, planos, diffs,
               eventos, campos, decisoes=None) -> dict:
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
        "decisoes_requeridas": decisoes or [],
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

    # A chave amarra o veredito ao BUNDLE e às REGRAS que o auditaram:
    # um APPROVED emitido por um auditor antigo não é reaproveitado
    # depois que os validadores mudam — o job novo reaudita do zero.
    chave = (f"ciclo-{processo_id}-{blocos.hash_bundle(documentos)}"
             f"-r{validacao.versao_do_auditor()[:12]}")
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
            _campos_requeridos(ultimo), _decisoes_requeridas(ultimo),
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
