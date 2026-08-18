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
from ..config import DOCUMENTOS

FLAG_TELA = "tela_progresso"
FLAG_GATE = "gate_emissao"

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
                         campo: str, valor: str, marcador: str = "",
                         ocorrencia: int = 0,
                         molde: str = "") -> dict[str, str]:
    """
    Substitui a lacuna pelo valor informado pelo servidor — por CÓDIGO,
    nunca por IA e nunca abrindo o documento para edição livre.

    Com `marcador`/`ocorrencia` a substituição é cirúrgica: exatamente
    aquele trecho, exatamente aquela ocorrência (marcadores "secos" são
    idênticos entre si — sem a ocorrência, responder a pergunta de uma
    linha sobrescreveria as outras). Sem eles, mantém-se o comportamento
    histórico: o marcador reconstruído a partir do campo.

    `molde` cobre o dado improvisado (matrícula provisória, CNPJ
    inválido), em que o alvo não é um marcador e sim o valor errado no
    meio do texto: "matrícula: {valor}" preserva o rótulo em volta.
    """
    novos = dict(documentos)
    texto = novos.get(documento, "")
    if marcador:
        padrao = re.compile(re.escape(marcador), re.IGNORECASE)
    else:
        padrao = re.compile(
            r"\[PREENCHER:?\s*" + re.escape(campo) + r"\s*\]", re.IGNORECASE)
    novo_texto = molde.replace("{valor}", valor) if molde else valor

    if not ocorrencia:
        novos[documento] = padrao.sub(lambda _: novo_texto, texto)
        return novos

    contador = {"n": 0}

    def trocar(m: re.Match) -> str:
        contador["n"] += 1
        return novo_texto if contador["n"] == ocorrencia else m.group(0)

    novos[documento] = padrao.sub(trocar, texto)
    return novos


def aplicar_respostas(documentos: dict[str, str], respostas) -> dict[str, str]:
    """
    Aplica TODAS as respostas do formulário de uma vez.

    A ordem importa: marcadores secos são idênticos entre si e são
    localizados pelo NÚMERO da ocorrência. Substituir a ocorrência 1
    primeiro faria a ocorrência 5 virar a 4 — e a resposta seguinte
    cairia na lacuna errada. Aplicando da ÚLTIMA para a primeira, cada
    substituição só desloca ocorrências que já foram resolvidas.
    """
    aplicacoes = []
    for pedido, valor in respostas:
        if not (valor or "").strip():
            continue
        for alvo in pedido.get("alvos") or [{"documento": pedido["documento"]}]:
            aplicacoes.append((alvo, pedido["campo"], valor.strip()))
    aplicacoes.sort(key=lambda a: a[0].get("ocorrencia", 0), reverse=True)

    novos = documentos
    for alvo, campo, valor in aplicacoes:
        novos = aplicar_dado_pontual(
            novos, alvo["documento"], campo, valor,
            marcador=alvo.get("marcador", ""),
            ocorrencia=alvo.get("ocorrencia", 0),
            molde=alvo.get("molde", ""))
    return novos


def _rotulo_do_pedido(pedido: dict) -> str:
    """
    Rótulo do campo na tela. O nome do campo vem PRIMEIRO — é o que o
    servidor precisa ler para saber o que responder. Os documentos
    afetados vêm depois, entre parênteses, porque uma única resposta
    completa todos eles.
    """
    documentos = pedido.get("documentos") or [pedido["documento"]]
    siglas = ", ".join(
        DOCUMENTOS.get(d, {}).get("sigla", d.upper()) for d in documentos)
    campo = pedido["campo"]
    # o qualificador distingue lacunas homônimas (a "Ação preventiva" do
    # risco A não é a do risco B) — sem ele, duas perguntas iguais
    if pedido.get("qualificador"):
        campo = f"{campo} — {pedido['qualificador']}"
    return f"{campo} ({siglas})"


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
    # Camada semântica (IA) opcional indisponível: a revisão foi concluída
    # pela auditoria determinística — informa sem alarmar.
    if any(r.get("semantica_indisponivel")
           for r in resultado.get("relatorios", [])):
        st.caption(
            "Observação: a auditoria semântica por IA ficou indisponível "
            "nesta execução; a revisão foi concluída pelas validações "
            "determinísticas (obrigatórias)."
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


def _render_decisoes(decisoes: list[dict]) -> None:
    """
    Decisão discricionária NÃO é caixa de texto: o sistema não pode
    receber a resposta como dado. Cada item diz o que precisa ser
    decidido, onde o problema está e leva o revisor à etapa do documento.
    """
    if not decisoes:
        return
    st.markdown("##### Decisões que dependem de você")
    st.caption(
        "Estes pontos não são dados que faltam: são escolhas do revisor. "
        "O botão leva ao documento correspondente para você ajustar o "
        "texto."
    )
    for i, decisao in enumerate(decisoes):
        with st.container(border=True):
            st.markdown(f"**{decisao['sigla']} — {decisao['descricao']}**")
            if decisao.get("esperado"):
                st.markdown(f"O que se espera: {decisao['esperado']}")
            if decisao.get("evidencia"):
                st.caption(f"Trecho: “{decisao['evidencia']}”")
            etapa = decisao.get("etapa")
            if etapa and st.button(
                    f"Ir para o {decisao['sigla']}",
                    key=f"decisao_{decisao['findingId']}_{i}",
                    use_container_width=True):
                state.ir_para(etapa)


def _render_aguardando_dados(resultado: dict, docs: dict[str, str]) -> None:
    pedidos = resultado["campos_requeridos"]
    decisoes = resultado.get("decisoes_requeridas") or []
    if not pedidos:
        # WAITING sem pergunta formulável seria exatamente o defeito que
        # esta tela existe para eliminar — cai no bloqueio explicado.
        _render_bloqueado(resultado, docs)
        return

    st.warning(
        f"**Faltam {len(pedidos)} informação(ões) do processo.** Informe "
        "abaixo o que o sistema não tem como saber — ele completa os "
        "documentos e revalida sozinho. Nada é preenchido por dedução."
    )
    with st.form("form_dados_pontuais"):
        respostas = {}
        for i, pedido in enumerate(pedidos):
            respostas[i] = (
                pedido,
                st.text_input(_rotulo_do_pedido(pedido), key=f"dado_{i}"),
            )
            detalhe = []
            if pedido.get("clausula"):
                detalhe.append(f"Cláusula {pedido['clausula']}")
            if pedido.get("contexto"):
                detalhe.append(f"“{pedido['contexto']}”")
            if len(pedido.get("documentos") or []) > 1:
                detalhe.append(
                    "a mesma resposta completa todos os documentos acima")
            if detalhe:
                st.caption(" · ".join(detalhe))
        enviado = st.form_submit_button(
            "Enviar e revalidar", type="primary", use_container_width=True)
    if enviado:
        novos = aplicar_respostas(docs, respostas.values())
        if novos != docs:
            st.session_state.documentos = novos
            st.session_state.pop("_ciclo_resultado", None)
            state.autosalvar()
            st.rerun()
        st.error("Preencha ao menos um campo para revalidar.")
    _render_decisoes(decisoes)


def _render_bloqueado(resultado: dict, docs: dict[str, str]) -> None:
    mensagens = {
        "WAITING_REQUIRED_DATA":
            "A revisão identificou dado faltante, mas não conseguiu "
            "formular a pergunta a partir do texto. Os pontos em aberto "
            "estão listados abaixo, com o trecho de cada um.",
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

    # Decisões primeiro: são o que efetivamente destrava o processo, com
    # o caminho até o documento. A lista completa de achados fica depois,
    # recolhida, como transparência — não como tarefa a decifrar.
    _render_decisoes(resultado.get("decisoes_requeridas") or [])

    pendentes = [f for f in ultimo.get("findings", [])
                 if not f["autoCorrectable"]]
    if pendentes:
        with st.expander(f"Todos os pontos em aberto ({len(pendentes)})"):
            for f in pendentes:
                sigla = DOCUMENTOS.get(f["documentId"], {}).get(
                    "sigla", f["documentId"].upper())
                st.markdown(f"- **{sigla}** — {f['descricao']}")
                evidencia = (f.get("evidencia") or [""])[0]
                if evidencia:
                    st.caption(f"   Trecho: “{evidencia}”")
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
# Gate técnico de emissão (Etapa 7 — flag_gate_emissao)
# ---------------------------------------------------------------------------
def emissao_liberada(docs: dict[str, str]) -> tuple[bool, str]:
    """
    Com a flag ligada, a emissão exige um ciclo APPROVED para o conteúdo
    ATUAL do bundle (editar qualquer documento invalida a aprovação — o
    hash muda e a revisão precisa rodar de novo). Com a flag desligada,
    vale o comportamento anterior (o gate é o validador da tela).

    Manutenção bloqueia ANTES da flag: com o app em manutenção não há
    emissão, com ou sem gate técnico ligado.
    """
    if db.em_manutencao():
        return False, db.motivo_de_manutencao()
    if not db.flag_ativa(FLAG_GATE):
        return True, ""
    cache = st.session_state.get("_ciclo_resultado") or {}
    resultado = cache.get("resultado") or {}
    if (cache.get("hash") == blocos.hash_bundle(docs)
            and resultado.get("status") == "APPROVED"):
        return True, ""
    return False, (
        "O gate técnico de emissão está ligado: os arquivos só são "
        "liberados após a revisão automática APROVAR a versão atual dos "
        "documentos. Conclua a revisão automática (qualquer edição exige "
        "nova aprovação) — ou o administrador pode desligar o gate na "
        "aba Revisão."
    )


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
