"""
Aprendizado institucional controlado (Fase 7 do pacote V5).

Captura SINAIS reais (edições que o servidor faz nos rascunhos gerados)
e os leva por um fluxo de curadoria HUMANA — nada vira regra, cláusula
ou prompt automaticamente (KQ-010):

  CAPTURED → NORMALIZED → UNDER_REVIEW → APPROVED_FOR_SHADOW →
  SHADOW_VALIDATED → PUBLISHED → DEPRECATED   (REJECTED a qualquer passo)

Salvaguardas (05_APRENDIZADO_INSTITUCIONAL do pacote):
  - todo conteúdo é ANONIMIZADO na captura (CPF/CNPJ/e-mail/telefone/
    matrícula — KQ-009) e só os BLOCOS alterados são guardados, nunca o
    documento inteiro;
  - publicar exige a flag própria (`flag_institutional_learning_publish`)
    além da captura — e é sempre um ato humano no painel de curadoria;
  - rollback = PUBLISHED → DEPRECATED (nova decisão, nada é apagado);
  - isolamento por tenant vem do banco (tenant da sessão na gravação).

Flags: `flag_institutional_learning_capture` liga a captura;
`flag_institutional_learning_publish` habilita o passo de publicação.
Ambas OFF (default): nenhuma captura, painel oculto, zero mudanças.
"""

import logging

from . import blocos, db, governanca

_log = logging.getLogger("govdocs.aprendizado")

MAX_TRECHO = 600  # nunca guardar textos longos — sinal, não documento


class ErroAprendizado(Exception):
    """Transição ou publicação fora das regras de curadoria."""


def captura_ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_APRENDIZADO_CAPTURA)


def publicacao_ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_APRENDIZADO_PUBLICACAO)


# ---------------------------------------------------------------------------
# Captura: edição humana sobre o rascunho gerado
# ---------------------------------------------------------------------------
def diferencas_por_bloco(doc_key: str, antes: str,
                         depois: str) -> list[dict]:
    """Pares (antes, depois) apenas dos blocos que o usuário alterou."""
    blocos_antes = {b["path"]: b for b in
                    blocos.dividir_em_blocos(doc_key, antes or "")}
    blocos_depois = {b["path"]: b for b in
                     blocos.dividir_em_blocos(doc_key, depois or "")}
    alteracoes = []
    for path in sorted(set(blocos_antes) | set(blocos_depois)):
        a = blocos_antes.get(path)
        d = blocos_depois.get(path)
        if a and d and a["hash"] == d["hash"]:
            continue
        alteracoes.append({
            "path": path,
            "antes": governanca.anonimizar_texto(
                (a or {}).get("conteudo", ""))[:MAX_TRECHO],
            "depois": governanca.anonimizar_texto(
                (d or {}).get("conteudo", ""))[:MAX_TRECHO],
        })
    return alteracoes


def capturar_edicao(doc_key: str, antes: str, depois: str,
                    processo_id: str | None) -> dict | None:
    """
    Registra a edição como feedback CAPTURED (anonimizado). Best-effort:
    a captura JAMAIS pode atrapalhar a aprovação do documento.
    """
    if not captura_ativa():
        return None
    if (antes or "").strip() == (depois or "").strip():
        return None  # nada mudou: sem ruído na curadoria
    alteracoes = diferencas_por_bloco(doc_key, antes, depois)
    if not alteracoes:
        return None
    feedback = governanca.novo_feedback(processo_id, "edicao_documento", {
        "documento": doc_key,
        "resumo": f"{len(alteracoes)} bloco(s) editado(s) pelo servidor "
                  "antes da aprovação",
    })
    feedback["evidencias"] = alteracoes
    if not db.disponivel():
        _log.info("captura (sem banco): %s", feedback["conteudo"]["resumo"])
        return feedback
    try:
        return db.salvar_feedback(feedback)
    except db.ErroBanco as erro:
        _log.warning("captura não persistida: %s", erro)
        return feedback


# ---------------------------------------------------------------------------
# Curadoria: transições sempre humanas, publicação atrás de flag
# ---------------------------------------------------------------------------
def transicionar(feedback: dict, novo_status: str,
                 curador: str | None = None,
                 versao_publicada: str = "") -> dict:
    """
    Aplica uma transição de curadoria. PUBLISHED exige a flag de
    publicação (nada publica sozinho — KQ-018); transição inválida é
    erro explícito; rollback = PUBLISHED → DEPRECATED (KQ-019).
    """
    atual = feedback.get("status", "CAPTURED")
    if not governanca.transicao_feedback_valida(atual, novo_status):
        raise ErroAprendizado(
            f"transição inválida: {atual} → {novo_status}")
    if novo_status == "PUBLISHED":
        if not publicacao_ativa():
            raise ErroAprendizado(
                "publicação desabilitada (flag_institutional_learning_"
                "publish desligada) — valide em shadow e habilite a flag")
        if not versao_publicada:
            raise ErroAprendizado(
                "publicação exige o rótulo da versão publicada")
    campos = {"status": novo_status}
    if curador:
        campos["curador"] = curador
    if versao_publicada:
        campos["versao_publicada"] = versao_publicada
    if db.disponivel() and feedback.get("id"):
        db.atualizar_feedback(feedback["id"], **campos)
    return {**feedback, **campos}


def proximos_estados(feedback: dict) -> list[str]:
    """Transições válidas a partir do estado atual (para o painel)."""
    atual = feedback.get("status", "CAPTURED")
    validos = [destino for destino in governanca.ESTADOS_FEEDBACK
               if governanca.transicao_feedback_valida(atual, destino)]
    if not publicacao_ativa() and "PUBLISHED" in validos:
        validos.remove("PUBLISHED")
    return validos
