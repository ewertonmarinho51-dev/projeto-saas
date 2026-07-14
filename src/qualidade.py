"""
Índice de confiança (Fase 6 do pacote V5).

Score 0–100 calculado a partir de COMPONENTES DETERMINÍSTICOS e
relatórios reais já produzidos pelas fases anteriores — nunca de
opinião de modelo:

  - evidenceCoverage           fatos confirmados vs. apenas extraídos;
  - crossDocumentConsistency   findings C### (Fase 5);
  - policyCompliance           bloqueios/conflitos/alertas do motor (F3);
  - calculations               erro de cálculo (KQ-016);
  - documentCompleteness       bloqueios/avisos do validador + docs
                               faltantes do dossiê;
  - semanticQuality            findings da auditoria semântica (0.8
                               neutro quando ela não roda);
  - renderIntegrity            tabelas malformadas (renderização);
  - traceability               decisão registrada para o processo.

Config VERSIONADA (quality-config@1, pesos e limiares do pacote).
O score NÃO substitui gates: `criticalBlocksAlways` — qualquer
ocorrência crítica bloqueia a emissão mesmo com score alto (KQ-006).

Flags: `flag_confidence_score_shadow` calcula e PERSISTE o score sem
exibir nada (calibração com processos reais); depois
`flag_confidence_emission_gate` liga o painel e o bloqueio gradual.
"""

import logging

import streamlit as st

from . import achados, conhecimento, db, fatos as fatos_mod, governanca

_log = logging.getLogger("govdocs.qualidade")

CONFIG_PADRAO = {
    "versao": "quality-config@1",
    "pesos": {
        "evidenceCoverage": 0.2,
        "crossDocumentConsistency": 0.2,
        "policyCompliance": 0.15,
        "calculations": 0.1,
        "documentCompleteness": 0.1,
        "semanticQuality": 0.1,
        "renderIntegrity": 0.1,
        "traceability": 0.05,
    },
    "limiares": {"pronto": 95, "pronto_com_avisos": 90,
                 "correcao_necessaria": 75},
    "critico_sempre_bloqueia": True,
}

_DESCONTO_POR_SEVERIDADE = {"CRITICAL": 1.0, "HIGH": 0.25,
                            "MEDIUM": 0.15, "LOW": 0.1, "INFO": 0.05}


def _limitado(valor: float) -> float:
    return max(0.0, min(1.0, valor))


def _desconto(findings: list[dict]) -> float:
    return sum(_DESCONTO_POR_SEVERIDADE.get(f.get("severity"), 0.1)
               for f in findings)


# ---------------------------------------------------------------------------
# Dimensões (cada uma 0..1, determinística, com a evidência usada)
# ---------------------------------------------------------------------------
def _dimensoes(relatorio: dict, fatos: list[dict],
               decisao: dict | None, documentos: dict[str, str]) -> dict:
    findings = relatorio.get("findings", [])
    por_categoria = {}
    for f in findings:
        por_categoria.setdefault(f.get("categoria"), []).append(f)
    consistencia = [f for f in findings
                    if str(f.get("findingId", "")).startswith("C")]

    vigentes = [f for f in fatos if f.get("status") != "substituido"]
    confirmados = [f for f in vigentes if f.get("status") == "confirmado"]
    cobertura = (_limitado((len(confirmados)
                            + 0.6 * (len(vigentes) - len(confirmados)))
                           / len(vigentes)) if vigentes else 0.0)

    resultado_motor = (decisao or {}).get("resultado") or {}
    conformidade = 1.0
    if resultado_motor.get("bloqueios") or resultado_motor.get("conflitos"):
        conformidade = 0.0
    else:
        conformidade = _limitado(
            1.0 - 0.2 * len(resultado_motor.get("alertas", [])))

    calculo = 0.0 if por_categoria.get("consistencia_calculo") else 1.0

    validador = [f for f in findings
                 if str(f.get("findingId", "")).startswith("F")]
    bloqueantes = [f for f in validador if f.get("severity") == "HIGH"]
    completude = _limitado(
        (0.0 if bloqueantes else 1.0 - 0.1 * len(validador))
        - 0.25 * max(0, 4 - len([d for d in documentos.values()
                                 if (d or "").strip()])))

    semanticos = [f for f in findings if f.get("categoria") == "semantica"]
    # sem auditoria semântica não há como afirmar 1.0: neutro em 0.8
    semantica = _limitado(1.0 - _desconto(semanticos)) if semanticos else 0.8

    renderizacao = _limitado(
        1.0 - 0.5 * len(por_categoria.get("tabela_malformada", [])))

    return {
        "evidenceCoverage": round(cobertura, 3),
        "crossDocumentConsistency": round(
            _limitado(1.0 - _desconto(consistencia)), 3),
        "policyCompliance": round(conformidade, 3),
        "calculations": calculo,
        "documentCompleteness": round(completude, 3),
        "semanticQuality": round(semantica, 3),
        "renderIntegrity": renderizacao,
        "traceability": 1.0 if decisao else 0.5,
    }


def _criticos(relatorio: dict, decisao: dict | None) -> list[str]:
    criticos = [
        f"{f['findingId']}: {f['descricao'][:100]}"
        for f in relatorio.get("findings", [])
        if f.get("severity") == "CRITICAL"
    ]
    resultado = (decisao or {}).get("resultado") or {}
    criticos += [f"bloqueio de regra: {b['regra']} — {b['motivo'][:80]}"
                 for b in resultado.get("bloqueios", [])]
    criticos += [f"conflito de regras: {c['clausula']}"
                 for c in resultado.get("conflitos", [])]
    return criticos


def calcular(relatorio: dict, fatos: list[dict], decisao: dict | None,
             documentos: dict[str, str],
             config: dict | None = None) -> dict:
    """Score consolidado + dimensões + ocorrências críticas."""
    config = config or CONFIG_PADRAO
    dimensoes = _dimensoes(relatorio, fatos, decisao, documentos)
    score = round(sum(
        dimensoes[nome] * peso
        for nome, peso in config["pesos"].items()) * 100, 1)
    return {
        "score": score,
        "dimensoes": dimensoes,
        "criticos": _criticos(relatorio, decisao),
        "config_versao": config["versao"],
    }


def avaliar_gate(resultado: dict,
                 config: dict | None = None) -> dict:
    """
    O score não substitui gates: crítico SEMPRE bloqueia (KQ-006);
    abaixo de `correcao_necessaria` bloqueia; entre os limiares, emite
    com avisos.
    """
    config = config or CONFIG_PADRAO
    limiares = config["limiares"]
    if config["critico_sempre_bloqueia"] and resultado["criticos"]:
        return {"bloqueia": True, "nivel": "critico",
                "motivo": f"{len(resultado['criticos'])} ocorrência(s) "
                          "crítica(s) — a emissão exige resolução, "
                          "independentemente do score"}
    if resultado["score"] < limiares["correcao_necessaria"]:
        return {"bloqueia": True, "nivel": "correcao_necessaria",
                "motivo": f"score {resultado['score']} abaixo do mínimo "
                          f"({limiares['correcao_necessaria']})"}
    if resultado["score"] < limiares["pronto_com_avisos"]:
        return {"bloqueia": False, "nivel": "correcao_recomendada",
                "motivo": f"score {resultado['score']} — revisão "
                          "recomendada antes da emissão"}
    if resultado["score"] < limiares["pronto"]:
        return {"bloqueia": False, "nivel": "pronto_com_avisos",
                "motivo": ""}
    return {"bloqueia": False, "nivel": "pronto", "motivo": ""}


# ---------------------------------------------------------------------------
# Flags e execução na tela
# ---------------------------------------------------------------------------
def shadow_ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_SCORE_SHADOW)


def gate_ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_SCORE_GATE)


def processar_na_tela(documentos: dict[str, str], dados: dict,
                      processo_id: str | None) -> dict | None:
    """
    Gate LIGADO: retorna o resultado (painel + bloqueio na tela).
    Só shadow: calcula, PERSISTE (best-effort) e loga; retorna None.
    Ambos OFF: nada. Cache por conteúdo na sessão.
    """
    if not (gate_ativo() or shadow_ativo()):
        return None
    chave = governanca.hash_canonico(
        {"docs": documentos, "dados": dados, "proc": processo_id})
    cache = st.session_state.get("_score_cache")
    if cache and cache.get("chave") == chave:
        resultado = cache["resultado"]
    else:
        relatorio = achados.gerar_relatorio(documentos, processo_id)
        lista_fatos = fatos_mod.extrair_do_formulario(dados, processo_id)
        if db.disponivel() and processo_id:
            try:
                lista_fatos = db.listar_fatos(processo_id) or lista_fatos
            except db.ErroBanco:
                pass
        decisao = (st.session_state.get("_decisao_cache") or {}).get(
            "decisao")
        resultado = calcular(relatorio, lista_fatos, decisao, documentos)
        db.salvar_score({
            "processo_id": processo_id,
            "config_versao": resultado["config_versao"],
            "score": resultado["score"],
            "dimensoes": resultado["dimensoes"],
            "criticos": resultado["criticos"],
            "shadow": not gate_ativo(),
        })
        _log.info("score de qualidade: %.1f (críticos: %d, gate: %s)",
                  resultado["score"], len(resultado["criticos"]),
                  "ativo" if gate_ativo() else "shadow")
        st.session_state["_score_cache"] = {"chave": chave,
                                            "resultado": resultado}
    return resultado if gate_ativo() else None
