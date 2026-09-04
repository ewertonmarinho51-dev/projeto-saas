"""
Gerenciamento de estado do wizard (st.session_state).

O Streamlit reexecuta o script a cada interação; tudo que precisa
sobreviver entre os passos (dados do formulário, documentos gerados,
aprovações) vive em st.session_state, inicializado aqui.
"""

import streamlit as st

from . import contexto, db
from .config import (INSTRUMENTOS_DERIVADOS, SEQUENCIA_DOCUMENTOS, adota_srp,
                     exportaveis_do_processo)


def inicializar() -> None:
    """Garante que todas as chaves de estado existam antes do 1º render."""
    padroes = {
        "etapa": 0,            # 0=formulário | 1..4=documentos | 5=sucesso
        "dados": {},           # respostas do Formulário Matriz
        "documentos": {},      # doc_key -> texto gerado/editado
        "aprovados": set(),    # doc_keys aprovados pelo usuário
        "edicoes_pendentes": {},  # doc_key -> edição ainda não aprovada
        "processo_id": None,   # uuid do processo no Supabase (None = não salvo)
        "usuario": None,       # {id, nome, login, papel} após o login
        "modo_demo": False,
        "api_key_manual": "",
        "openai_key_manual": "",
        "_save_status": "nao_salvo",  # refletido pela topbar; nunca decorativo
    }
    for chave, valor in padroes.items():
        if chave not in st.session_state:
            st.session_state[chave] = valor


def autosalvar() -> None:
    """
    Salva o processo no Supabase (se configurado). Falhas de banco nunca
    interrompem o fluxo do wizard — viram apenas um aviso na tela.
    """
    if not st.session_state.dados:
        st.session_state["_save_status"] = "nao_salvo"
        return
    if not db.disponivel():
        st.session_state["_save_status"] = "local"
        return
    st.session_state["_save_status"] = "salvando"
    try:
        usuario = st.session_state.get("usuario") or {}
        # `auth_user_id` sai do CONTEXTO INSTITUCIONAL, que deriva da
        # sessão autenticada — nunca de campo do formulário. É ele que
        # as políticas da 0020 comparam com `auth.uid()`; `usuarios.id`
        # é outro identificador e não serve.
        institucional = contexto.contexto_institucional()
        st.session_state.processo_id = db.salvar_processo(
            st.session_state.processo_id,
            st.session_state.dados,
            st.session_state.documentos,
            st.session_state.aprovados,
            st.session_state.etapa,
            usuario_id=usuario.get("id"),
            secretaria_id=contexto.secretaria_para_processo(),
            auth_user_id=institucional.get("auth_user_id"),
        )
        st.session_state["_save_status"] = "salvo"
    except db.ErroBanco as erro:
        st.session_state["_save_status"] = "erro"
        st.warning(f"Progresso não salvo no banco: {erro}")


def carregar_processo_salvo(proc: dict) -> None:
    """Restaura um processo salvo no Supabase para a sessão atual."""
    _limpar_widgets_formulario()
    st.session_state.processo_id = proc["id"]
    st.session_state.dados = proc.get("dados") or {}
    st.session_state.documentos = proc.get("documentos") or {}
    st.session_state.aprovados = set(proc.get("aprovados") or [])
    st.session_state.edicoes_pendentes = {}
    st.session_state["_save_status"] = "salvo"
    ir_para(int(proc.get("etapa") or 0))


def ir_para(etapa: int) -> None:
    st.session_state.etapa = etapa
    st.rerun()


def doc_da_etapa(etapa: int) -> str:
    """Etapas 1..4 correspondem a dfd, etp, tr, edital."""
    return SEQUENCIA_DOCUMENTOS[etapa - 1]


def calcular_etapas_navegaveis(
    dados: dict,
    documentos: dict,
    aprovados: set[str],
) -> set[int]:
    """Retorna as etapas que podem ser visitadas sem quebrar a sequência.

    O formulário está sempre disponível. Cada documento seguinte só é
    liberado quando todos os anteriores existem e foram aprovados. A tela de
    conclusão exige o pacote completo. Assim o stepper serve como navegação,
    mas nunca vira um atalho para pular uma decisão humana obrigatória.
    """
    disponiveis = {0}
    if not dados:
        return disponiveis

    concluidos = {
        doc_key for doc_key in SEQUENCIA_DOCUMENTOS
        if doc_key in documentos and doc_key in aprovados
    }
    for etapa, _doc_key in enumerate(SEQUENCIA_DOCUMENTOS, start=1):
        anteriores = set(SEQUENCIA_DOCUMENTOS[: etapa - 1])
        if anteriores.issubset(concluidos):
            disponiveis.add(etapa)

    if set(SEQUENCIA_DOCUMENTOS).issubset(concluidos):
        disponiveis.add(5)
    return disponiveis


def etapas_navegaveis() -> set[int]:
    """Etapas acessíveis no processo carregado na sessão atual."""
    return calcular_etapas_navegaveis(
        st.session_state.dados,
        st.session_state.documentos,
        st.session_state.aprovados,
    )


def guardar_edicao_pendente(doc_key: str, texto: str) -> None:
    """Preserva uma edição ao navegar, sem alterar a versão aprovada."""
    pendentes = st.session_state.setdefault("edicoes_pendentes", {})
    original = st.session_state.documentos.get(doc_key)
    if original is None or texto == original:
        pendentes.pop(doc_key, None)
    else:
        pendentes[doc_key] = texto


def _preservar_editor_atual() -> None:
    """Copia o editor visível para o buffer antes de trocar de etapa."""
    etapa = int(st.session_state.get("etapa") or 0)
    if not 1 <= etapa <= len(SEQUENCIA_DOCUMENTOS):
        return
    doc_key = doc_da_etapa(etapa)
    chave_editor = f"editor_{doc_key}"
    if (chave_editor in st.session_state
            and doc_key in st.session_state.documentos):
        guardar_edicao_pendente(doc_key, st.session_state[chave_editor])


def navegar_pelo_stepper(etapa: int) -> None:
    """Callback do stepper clicável; etapas futuras são ignoradas."""
    if etapa not in etapas_navegaveis():
        return
    _preservar_editor_atual()
    st.session_state.etapa = etapa


def aprovar_e_avancar(doc_key: str, texto_editado: str) -> None:
    """Salva a versão editada pelo usuário, marca como aprovado e avança."""
    from . import db

    if db.em_manutencao():
        # Aprovação é ato de processo: não pode acontecer sem rastro
        # persistido. Em manutenção nada avança.
        st.error(db.motivo_de_manutencao())
        return

    # V5 Fase 7 (flag_institutional_learning_capture): a edição humana
    # sobre o rascunho é um SINAL de aprendizado — capturada anonimizada,
    # por bloco, best-effort (jamais atrapalha a aprovação). Flag OFF: nada.
    from . import aprendizado

    aprendizado.capturar_edicao(
        doc_key, st.session_state.documentos.get(doc_key) or "",
        texto_editado, st.session_state.processo_id)

    st.session_state.documentos[doc_key] = texto_editado
    st.session_state.setdefault("edicoes_pendentes", {}).pop(doc_key, None)
    st.session_state.aprovados.add(doc_key)
    st.session_state.etapa += 1
    autosalvar()  # persiste cada avanço no Supabase (quando configurado)
    st.rerun()


def descartar_documento(doc_key: str) -> None:
    """
    Remove o documento gerado (usado no 'Gerar novamente').

    Leva junto os instrumentos DERIVADOS dele — a Ata é emitida com o
    edital, então um edital descartado não pode deixar para trás uma Ata
    que já não corresponde a nada. Reaproveitamento silencioso de Ata
    antiga é o defeito que esta cascata existe para impedir.
    """
    st.session_state.documentos.pop(doc_key, None)
    st.session_state.setdefault("edicoes_pendentes", {}).pop(doc_key, None)
    st.session_state.aprovados.discard(doc_key)
    for derivado in INSTRUMENTOS_DERIVADOS.get(doc_key, ()):
        st.session_state.documentos.pop(derivado, None)
        st.session_state.setdefault("edicoes_pendentes", {}).pop(derivado, None)
        st.session_state.aprovados.discard(derivado)


def invalidar_a_partir_de(doc_key: str) -> None:
    """
    Ao voltar e alterar um documento (ou o formulário), os documentos
    seguintes ficam desatualizados — remove-os para forçar nova geração.

    O próprio documento alterado não é removido (ele acabou de ser
    editado), mas os instrumentos derivados DELE são: mudar o edital
    torna a Ata que saiu com ele obsoleta.
    """
    if doc_key == "formulario":
        posteriores = list(SEQUENCIA_DOCUMENTOS)
    else:
        idx = SEQUENCIA_DOCUMENTOS.index(doc_key)
        posteriores = SEQUENCIA_DOCUMENTOS[idx + 1:]
        for derivado in INSTRUMENTOS_DERIVADOS.get(doc_key, ()):
            descartar_documento(derivado)
    for chave in posteriores:
        descartar_documento(chave)


# Caches e marcadores que pertencem a UM processo (contratação) e são
# limpos ao reiniciar. LISTA EXPLÍCITA — nunca limpar por prefixo "_":
# há chaves "_" de estado GLOBAL da sessão (ex.: _modelo_chave/_modelo_img,
# preview de branding do admin) que não têm relação com o processo.
# Estado global preservado: usuario, tenant_id, api_key_manual,
# openai_key_manual, modo_demo, pagina, _modelo_chave, _modelo_img.
_CHAVES_DO_PROCESSO = (
    "_ciclo_resultado",     # cache da revisão/correção automática
    "_ciclo_manual",        # opt-out manual do ciclo desta sessão
    "_shadow_plano_hash",   # dedupe do corretor em shadow
    "_fatos_cache",         # fatos canônicos do processo
    "_decisao_cache",       # decisão do motor de conhecimento
    "_score_cache",         # índice de confiança
    "_rag_trace",           # rastro do RAG por documento (lastro das citações)
    "registro_geracoes",    # histórico técnico das gerações
)
_PREFIXOS_DO_PROCESSO = (
    "_familia_escolha_",    # escolha de família de modelo por documento
    "govbot_campo_",        # widgets estáveis do formulário com GovBot ativo
    "editor_",              # editores de documentos/planilha do processo
)


def _limpar_widgets_formulario() -> None:
    """Remove valores de widgets que não podem atravessar processos."""
    for chave in [
        k for k in list(st.session_state.keys())
        if isinstance(k, str)
        and k.startswith(("govbot_campo_", "editor_"))
    ]:
        st.session_state.pop(chave, None)


def reiniciar_processo() -> None:
    """Limpa tudo e volta ao Formulário Matriz (novo processo no banco)."""
    # Se o GovBot já foi habilitado nesta sessão, desassocia o bucket sem
    # apagar históricos de processos salvos. A próxima preparação criará um
    # UUID local novo. Flag OFF nunca cria esta raiz e não passa por aqui.
    raiz_govbot = st.session_state.get("govbot")
    if isinstance(raiz_govbot, dict):
        raiz_govbot["current_bucket"] = None
        raiz_govbot["local_process_id"] = None
        st.session_state.pop("govbot_form_draft", None)
    for chave in ("dados", "documentos", "edicoes_pendentes"):
        st.session_state[chave] = {}
    st.session_state.aprovados = set()
    st.session_state.processo_id = None
    st.session_state["_save_status"] = "nao_salvo"
    _limpar_widgets_formulario()
    # Estado TRANSITÓRIO do processo anterior (caches do ciclo/fatos/score,
    # escolha de família, uploads lidos, histórico de gerações) não pode
    # vazar para a próxima contratação.
    for widget, marcador in (("upload_memorando", "_memorando_lido"),
                             ("upload_itens", "_xlsx_lido")):
        try:
            if widget in st.session_state:
                del st.session_state[widget]
            st.session_state.pop(marcador, None)
        except Exception:  # noqa: BLE001
            # uploader não pôde ser limpo: mantém o marcador para o arquivo
            # antigo não ser reimportado no novo processo
            pass
    for chave in _CHAVES_DO_PROCESSO:
        st.session_state.pop(chave, None)
    for chave in [k for k in list(st.session_state.keys())
                  if isinstance(k, str)
                  and k.startswith(_PREFIXOS_DO_PROCESSO)]:
        st.session_state.pop(chave, None)
    ir_para(0)


def usa_srp(dados: dict) -> bool:
    """
    O processo adota Sistema de Registro de Preços?

    Critério ÚNICO e explícito: o modelo de execução informado no
    Formulário Matriz. Não se deduz SRP de objeto, quantidade ou
    parcelamento — adotar SRP é decisão do estudo, não inferência.

    A regra mora em `config.adota_srp`: a exportação precisa do MESMO
    critério sem depender da sessão, e dois critérios com o mesmo nome
    seriam a maneira de eles divergirem.
    """
    return adota_srp(dados)


def exportaveis() -> list[str]:
    """Chaves exportáveis do processo ATUAL, na ordem do dossiê."""
    return exportaveis_do_processo(st.session_state.get("dados"),
                                   st.session_state.get("documentos"))
