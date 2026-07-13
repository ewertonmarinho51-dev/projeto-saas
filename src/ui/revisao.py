"""
Tela de correção automática (Etapa 6 do pacote de correção — substitui
a atribuição manual quando `flag_tela_progresso` está ligada).

Experiência do servidor público (04_UX/00): uma única revisão contínua —
  1. Analisando os documentos;
  2. Preparando as correções;
  3. Corrigindo os pontos identificados;
  4. Validando novamente;
  5. Preparando os arquivos finais.

O progresso é PERSISTIDO (job em `revisoes`, via ciclo.executar_com_
persistencia): o usuário pode sair da tela e voltar sem repetir chamadas
de IA — a mesma versão do bundle retoma o resultado gravado.

Intervenção humana só nas exceções: falta de dado material (o app pede
SOMENTE o campo indispensável — nunca manda editar o documento),
bloqueio ou falha explícita. A tela antiga continua disponível como
saída de emergência ("usar a revisão manual") e é o comportamento
integral quando a flag está desligada.
"""

import re

import streamlit as st

from .. import blocos, ciclo, db, state

FLAG_TELA = "tela_progresso"

ETAPAS = [
    ("analisando", "Analisando os documentos"),
    ("preparando", "Preparando as correções"),
    ("corrigindo", "Corrigindo os pontos identificados"),
    ("validando", "Validando novamente"),
    ("finalizando", "Preparando os arquivos finais"),
]
_ROTULOS = dict(ETAPAS)


def ativa() -> bool:
    return db.flag_ativa(FLAG_TELA)


# ---------------------------------------------------------------------------
# Dado ausente: substituição PONTUAL por código (nunca IA, nunca editor)
# ---------------------------------------------------------------------------
def aplicar_dado_pontual(documentos: dict[str, str], documento: str,
                         campo: str, valor: str) -> dict[str, str]:
    """Substitui o marcador [PREENCHER: campo] pelo valor informado."""
    padrao = re.compile(
        r"\[PREENCHER:?\s*" + re.escape(campo) + r"\s*\]", re.IGNORECASE)
    novos = dict(documentos)
    novos[documento] = padrao.sub(valor, novos.get(documento, ""))
    return novos


# ---------------------------------------------------------------------------
# Execução com a barra de progresso (retomável por hash do bundle)
# ---------------------------------------------------------------------------
def _executar(docs: dict[str, str]) -> dict:
    hash_atual = blocos.hash_bundle(docs)
    cache = st.session_state.get("_ciclo_resultado")
    if cache and cache.get("hash") == hash_atual:
        return cache["resultado"]

    with st.status("Revisão e correção automática em andamento…",
                   expanded=True) as caixa:
        barra = st.progress(0.0, text=_ROTULOS["analisando"])
        ordem = [e for e, _ in ETAPAS]

        def ao_progresso(etapa: str) -> None:
            indice = ordem.index(etapa) if etapa in ordem else 0
            barra.progress((indice + 1) / len(ordem),
                           text=_ROTULOS.get(etapa, etapa))

        resultado = ciclo.executar_com_persistencia(
            docs, st.session_state.dados,
            st.session_state.get("processo_id") or "sessao-local",
            ao_progresso=ao_progresso,
        )
        aprovado = resultado["status"] == "APPROVED"
        caixa.update(
            label=("Revisão concluída: documentos aprovados." if aprovado
                   else "Revisão concluída: é necessária a sua atenção."),
            state="complete" if aprovado else "error",
            expanded=False,
        )
    st.session_state["_ciclo_resultado"] = {
        "hash": hash_atual, "resultado": resultado}
    return resultado


def _liberar_nova_tentativa(docs: dict[str, str]) -> None:
    """Reabre o job persistido (senão a idempotência retomaria a falha)."""
    st.session_state.pop("_ciclo_resultado", None)
    if not db.disponivel():
        return
    processo = st.session_state.get("processo_id") or "sessao-local"
    chave = f"ciclo-{processo}-{blocos.hash_bundle(docs)}"
    try:
        revisao = db.obter_revisao_por_chave(chave)
        if revisao:
            db.atualizar_revisao(revisao["id"], status="REVIEW_QUEUED")
    except db.ErroBanco:
        pass


# ---------------------------------------------------------------------------
# Estados finais na tela
# ---------------------------------------------------------------------------
def _render_aprovado(resultado: dict, docs: dict[str, str]) -> None:
    if resultado["documentos"] != docs:
        # correções aplicadas: a sessão passa a usar a versão corrigida
        st.session_state.documentos = resultado["documentos"]
        st.session_state["_ciclo_resultado"]["hash"] = blocos.hash_bundle(
            resultado["documentos"])
        state.autosalvar()
    st.success(
        "**Documentos revisados e aprovados para emissão.** "
        + (f"{resultado['ciclos']} ciclo(s) de correção automática "
           f"aplicado(s)." if resultado["ciclos"] else
           "Nenhuma correção foi necessária.")
    )
    with st.expander("Histórico da revisão (transparência)"):
        inicial = resultado["relatorios"][0] if resultado["relatorios"] else {}
        st.markdown(
            f"- **Auditoria inicial:** {inicial.get('summary', '—')}\n"
            f"- **Versão final do dossiê:** {resultado['versao']}\n"
            f"- **Operações aplicadas:** "
            f"{sum(len(p['operations']) for p in resultado['planos'])}"
        )
        for i, diff in enumerate(resultado["diffs"], start=1):
            tocados = [
                f"`{p}`" for d in diff["documentos"].values()
                for p in d["alterados"] + d["adicionados"] + d["removidos"]
            ]
            st.markdown(f"- **Ciclo {i}:** {', '.join(tocados) or '—'}")


def _render_aguardando_dados(resultado: dict, docs: dict[str, str]) -> None:
    st.warning(
        "**Falta uma informação essencial.** Informe apenas o(s) campo(s) "
        "abaixo — o sistema completa o documento e revalida sozinho."
    )
    with st.form("form_dados_pontuais"):
        respostas = {}
        for i, pedido in enumerate(resultado["campos_requeridos"]):
            rotulo = (f"{pedido['campo']} "
                      f"(documento {pedido['documento'].upper()})")
            respostas[i] = (pedido, st.text_input(rotulo, key=f"dado_{i}"))
        enviado = st.form_submit_button(
            "Enviar e revalidar", type="primary", use_container_width=True)
    if enviado:
        novos = docs
        for pedido, valor in respostas.values():
            if valor.strip():
                novos = aplicar_dado_pontual(
                    novos, pedido["documento"], pedido["campo"],
                    valor.strip())
        if novos != docs:
            st.session_state.documentos = novos
            st.session_state.pop("_ciclo_resultado", None)
            state.autosalvar()
            st.rerun()
        st.error("Preencha ao menos um campo para revalidar.")


def _render_bloqueado(resultado: dict, docs: dict[str, str]) -> None:
    mensagens = {
        "BLOCKED_MAX_CYCLES":
            "O limite seguro de ciclos de correção foi atingido sem "
            "aprovação. Um revisor humano precisa concluir.",
        "BLOCKED_BY_CONFLICT":
            "A revisão encontrou um problema que exige decisão humana "
            "(conflito ou item crítico).",
        "CORRECTION_FAILED":
            "A correção automática falhou e foi interrompida com "
            "segurança — nenhuma alteração parcial foi aplicada.",
        "REVIEW_FAILED":
            "A auditoria automática ficou indisponível. Tente novamente "
            "em instantes.",
    }
    st.error(f"**{mensagens.get(resultado['status'], resultado['status'])}**")
    ultimo = resultado["relatorios"][-1] if resultado["relatorios"] else {}
    pendentes = [f for f in ultimo.get("findings", [])
                 if not f["autoCorrectable"]]
    if pendentes:
        with st.expander(f"Pendências para o revisor ({len(pendentes)})"):
            for f in pendentes:
                st.markdown(f"- **{f['documentId'].upper()}** — "
                            f"{f['descricao']}")
    col_retry, col_manual = st.columns(2)
    if col_retry.button("Tentar novamente", type="primary",
                        use_container_width=True):
        _liberar_nova_tentativa(docs)
        st.rerun()
    if col_manual.button("Usar a revisão manual (tela anterior)",
                         use_container_width=True):
        st.session_state["_ciclo_manual"] = True
        st.rerun()


# ---------------------------------------------------------------------------
# Entrada única, chamada pela tela final
# ---------------------------------------------------------------------------
def render_correcao_automatica() -> str | None:
    """
    Fluxo automático da tela final:
      None        flag desligada / saída manual → usar a tela antiga;
      'aprovado'  emissão liberada (a tela final mostra os downloads);
      'pendente'  aguardando dado, bloqueado ou falho — sem downloads.
    """
    if st.session_state.get("_ciclo_manual") or not ativa():
        return None
    docs = st.session_state.documentos
    if not docs:
        return None
    resultado = _executar(docs)
    status = resultado["status"]
    if status == "REVIEW_COMPLETED":
        # aplicação automática desligada: o ciclo não corrige — a tela
        # antiga (bloqueios/avisos) continua sendo o comportamento
        return None
    if status == "APPROVED":
        _render_aprovado(resultado, docs)
        return "aprovado"
    if status == "WAITING_REQUIRED_DATA":
        _render_aguardando_dados(resultado, docs)
        return "pendente"
    _render_bloqueado(resultado, docs)
    return "pendente"
