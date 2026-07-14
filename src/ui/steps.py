"""
Telas de cada etapa do wizard:
  0 — Formulário Matriz
  1..4 — Geração + preview editável de DFD, ETP, TR e Edital
  5 — Conclusão e exportação (.docx / .pdf / .zip)
"""

import streamlit as st

from .. import (achados, auth, conhecimento, contexto, corretor, db,
                explicacoes, export, fatos, planilha, qualidade, rag,
                state)
from . import revisao
from ..config import CAMPOS_FORMULARIO, DOCUMENTOS, SEQUENCIA_DOCUMENTOS
from ..llm import ErroGeracaoIA, gerar_documento
from .components import render_base_legal


def _render_planilha(dados: dict, meta: dict) -> list[dict]:
    """Editor da planilha orçamentária dentro do formulário matriz."""
    st.markdown(f"**{meta['rotulo']} \\***")
    st.caption(meta["help"])
    st.caption(
        "A coluna **Fonte / Link** já está disponível: cole o link de onde o "
        "preço foi obtido — no documento ele aparece compacto como 'link', "
        "mas continua clicável. Colunas adicionais (ex.: Marca) são "
        "preservadas quando você importa a planilha de um arquivo Excel."
    )

    # Colunas fixas editáveis + Fonte/Link + colunas extras vindas do XLSX.
    # O valor total e o valor global são derivados automaticamente.
    base_itens = dados.get("itens") or planilha.linhas_iniciais()
    extras = [e for e in planilha.colunas_extra(base_itens)
              if e != planilha.CAMPO_FONTE]
    colunas = planilha.CAMPOS_ITEM + [planilha.CAMPO_FONTE] + extras

    base = [{c: it.get(c, "") for c in colunas} for it in base_itens]

    config = {
        "codigo": st.column_config.TextColumn(planilha.ROTULOS["codigo"], width="small"),
        "descricao": st.column_config.TextColumn(planilha.ROTULOS["descricao"], width="large"),
        "unidade": st.column_config.TextColumn(planilha.ROTULOS["unidade"], width="small"),
        "quantidade": st.column_config.NumberColumn(
            planilha.ROTULOS["quantidade"], min_value=0.0, step=1.0, format="%.2f"),
        "valor_unitario": st.column_config.NumberColumn(
            planilha.ROTULOS["valor_unitario"], min_value=0.0, step=100.0, format="%.2f"),
        planilha.CAMPO_FONTE: st.column_config.LinkColumn(
            planilha.ROTULOS["fonte"], display_text="link",
            help="Cole o link de onde o preço foi obtido. No documento aparece "
            "compacto como 'link', mas continua clicável."),
    }
    for c in extras:
        config[c] = st.column_config.TextColumn(c)

    # a key muda ao importar XLSX ou ao adicionar coluna, forçando recarga
    versao = f"{st.session_state.get('_xlsx_lido') or 'manual'}_{len(colunas)}"
    editado = st.data_editor(
        base, key=f"editor_itens_{versao}", num_rows="dynamic",
        use_container_width=True, column_config=config,
    )
    itens = editado.to_dict("records") if hasattr(editado, "to_dict") else list(editado)
    _, valor_global = planilha.calcular(itens)
    st.caption(
        f"Valor global (estimativa): **{planilha.formatar_moeda(valor_global)}** "
        "— recalculado ao avançar."
    )
    return itens


# ---------------------------------------------------------------------------
# Etapa 0 — Formulário Matriz
# ---------------------------------------------------------------------------
def render_formulario() -> None:
    st.subheader("Formulário Matriz: dados da demanda")
    st.caption(
        "Preencha as informações essenciais da contratação. Elas alimentarão "
        "a redação sequencial dos quatro documentos. O ícone de ajuda de "
        "cada campo explica o que a Lei nº 14.133/2021 espera."
    )

    dados = st.session_state.dados

    # Documento inicial da demanda (memorando/ofício) — upload opcional que
    # extrai o texto para o campo. Fica fora do form para semear na hora.
    with st.expander("Documento inicial da demanda (memorando / ofício)"):
        st.caption(
            "Opcional, mas recomendado. Envie o memorando, ofício ou "
            "solicitação que originou a demanda (PDF, DOCX, TXT ou MD) — o "
            "texto é extraído e usado como contexto do processo atual (origem "
            "da demanda, unidade solicitante, justificativa e finalidade). "
            "Você também pode colar o texto direto no campo do formulário."
        )
        doc_inicial = st.file_uploader(
            "Arquivo do memorando/ofício", type=["pdf", "docx", "txt", "md"],
            key="upload_memorando",
        )
        if doc_inicial is not None and \
                st.session_state.get("_memorando_lido") != doc_inicial.file_id:
            try:
                texto = rag.extrair_texto(doc_inicial.name, doc_inicial.getvalue())
                dados["memorando"] = texto
                st.session_state.dados = dados
                st.session_state["_memorando_lido"] = doc_inicial.file_id
                st.success(
                    f"Memorando/ofício importado ({len(texto)} caracteres). "
                    "Revise o texto no campo abaixo."
                )
                st.rerun()
            except rag.ErroRAG as erro:
                st.error(str(erro))

    # Importação opcional da planilha via XLSX (fora do form, para
    # re-semear a tabela imediatamente após o upload)
    with st.expander("Importar planilha de um arquivo Excel (.xlsx)"):
        st.caption(
            "Opcional. Envie a planilha ANTES de preencher os demais campos. "
            "Colunas reconhecidas: código, descrição, unidade, quantidade e "
            "valor unitário (aceita variações de nome). O valor total e o "
            "valor global são recalculados."
        )
        st.download_button(
            "Baixar modelo de planilha (.xlsx)",
            data=planilha.modelo_xlsx(),
            file_name="modelo-planilha-orcamentaria.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="btn_modelo_xlsx",
        )
        arquivo = st.file_uploader("Arquivo .xlsx", type=["xlsx"], key="upload_itens")
        if arquivo is not None and st.session_state.get("_xlsx_lido") != arquivo.file_id:
            try:
                importados = planilha.importar_de_xlsx(arquivo.getvalue())
                dados["itens"] = importados
                st.session_state.dados = dados
                st.session_state["_xlsx_lido"] = arquivo.file_id
                st.success(f"{len(importados)} itens importados da planilha.")
                st.rerun()
            except planilha.ErroPlanilha as erro:
                st.error(str(erro))

    with st.form("formulario_matriz"):
        col1, col2 = st.columns(2)
        respostas: dict = {}

        # Distribui os campos simples em duas colunas para uma tela mais limpa
        colunas = {
            "orgao": col1, "responsavel": col2,
            "modelo_execucao": col2, "prazo": col1,
        }
        for chave, meta in CAMPOS_FORMULARIO.items():
            destino = colunas.get(chave, st)
            rotulo = meta["rotulo"] + (" *" if meta["obrigatorio"] else "")
            # Sem key: o valor vem sempre de `dados` (value=), para refletir o
            # memorando importado por upload e o retomar de um processo salvo.
            if meta["tipo"] == "texto":
                respostas[chave] = destino.text_input(
                    rotulo, value=dados.get(chave, ""),
                    placeholder=meta["placeholder"], help=meta["help"],
                )
            elif meta["tipo"] == "area":
                altura = 150 if chave == "memorando" else 110
                respostas[chave] = st.text_area(
                    rotulo, value=dados.get(chave, ""), height=altura,
                    placeholder=meta["placeholder"], help=meta["help"],
                )
            elif meta["tipo"] == "planilha":
                respostas["itens"] = _render_planilha(dados, meta)
            elif meta["tipo"] == "selecao":
                opcoes = meta["opcoes"]
                atual = dados.get(chave, opcoes[0])
                respostas[chave] = destino.selectbox(
                    rotulo, opcoes,
                    index=opcoes.index(atual) if atual in opcoes else 0,
                    help=meta["help"],
                )

        enviado = st.form_submit_button(
            "Iniciar elaboração dos documentos", type="primary",
            use_container_width=True,
        )

    if enviado:
        # Consolida a planilha: calcula totais e o valor global (estimativa)
        itens, valor_global = planilha.calcular(respostas.get("itens") or [])
        respostas["itens"] = itens
        respostas["valor_estimado"] = valor_global

        faltantes = []
        for chave, meta in CAMPOS_FORMULARIO.items():
            if not meta["obrigatorio"]:
                continue
            if chave == "itens":
                if not itens:
                    faltantes.append(meta["rotulo"])
            elif not respostas.get(chave):
                faltantes.append(meta["rotulo"])
        if faltantes:
            st.error(
                "Preencha os campos obrigatórios: **" + ", ".join(faltantes) + "**"
            )
            return
        if respostas != st.session_state.dados:
            # Dados mudaram: documentos já gerados ficam obsoletos
            state.invalidar_a_partir_de("formulario")
        st.session_state.dados = respostas
        st.session_state.etapa = 1
        state.autosalvar()  # cria/atualiza o processo no Supabase
        st.rerun()


# ---------------------------------------------------------------------------
# Etapas 1..4 — Geração e preview editável de cada documento
# ---------------------------------------------------------------------------
def render_etapa_documento(doc_key: str) -> None:
    meta = DOCUMENTOS[doc_key]
    st.subheader(f"{meta['titulo']} ({meta['sigla']})")
    render_base_legal(f"Base legal: {meta['base_legal']}. {meta['descricao']}")

    contexto_key = meta["usa_contexto_de"]
    contexto = st.session_state.documentos.get(contexto_key) if contexto_key else None

    # ---------- Documento ainda não gerado: tela de geração ----------
    if doc_key not in st.session_state.documentos:
        if contexto_key:
            st.info(
                f"Este documento será redigido pela IA usando o formulário e o "
                f"**{DOCUMENTOS[contexto_key]['sigla']} aprovado** como contexto."
            )
        if st.button(
            f"Gerar {meta['sigla']} com IA", type="primary",
            use_container_width=True,
        ):
            with st.spinner(
                f"Redigindo o {meta['sigla']}… isso pode levar até 2 minutos."
            ):
                try:
                    texto = gerar_documento(doc_key, st.session_state.dados, contexto)
                    st.session_state.documentos[doc_key] = texto
                    st.rerun()
                except ErroGeracaoIA as erro:
                    st.error(str(erro))
                    detalhe = getattr(erro, "detalhe", "")
                    if detalhe:
                        with st.expander("Detalhes técnicos (erro bruto da API)"):
                            st.code(detalhe)
        _botao_voltar(meta)
        return

    # ---------- Preview editável (controle humano obrigatório) ----------
    st.success(
        "Rascunho gerado. **Revise e edite livremente o texto abaixo.** Nada "
        "avança sem a sua aprovação."
    )
    aba_editar, aba_visualizar = st.tabs(["Editar", "Visualizar formatado"])
    with aba_editar:
        texto_editado = st.text_area(
            "Conteúdo do documento (editável)",
            value=st.session_state.documentos[doc_key],
            height=480,
            key=f"editor_{doc_key}",
            label_visibility="collapsed",
        )
    with aba_visualizar:
        st.markdown(texto_editado)

    col_voltar, col_regerar, col_aprovar = st.columns([1, 1, 2])
    if col_voltar.button("Voltar", use_container_width=True, key=f"volta_{doc_key}"):
        st.session_state.documentos[doc_key] = texto_editado  # preserva edições
        state.ir_para(meta["etapa"] - 1)
    if col_regerar.button(
        "Gerar novamente", use_container_width=True, key=f"regera_{doc_key}",
        help="Descarta este rascunho e solicita nova redação à IA.",
    ):
        state.descartar_documento(doc_key)
        st.rerun()
    if col_aprovar.button(
        f"Aprovar {meta['sigla']} e avançar", type="primary",
        use_container_width=True, key=f"aprova_{doc_key}",
    ):
        # Se o texto mudou em relação ao aprovado antes, invalida os seguintes
        if st.session_state.documentos.get(doc_key) != texto_editado:
            state.invalidar_a_partir_de(doc_key)
        state.aprovar_e_avancar(doc_key, texto_editado)


def _botao_voltar(meta: dict) -> None:
    if st.button("Voltar", key=f"volta_vazio_{meta['sigla']}"):
        state.ir_para(meta["etapa"] - 1)


def _render_fatos_canonicos(resultado: dict) -> None:
    """Fatos do processo + pendências de confirmação (V5 Fase 2)."""
    lista = resultado["fatos"]
    pendentes = [f for f in lista if f.get("status") == "extraido"]
    with st.expander(
        f"Fatos canônicos do processo ({len(lista)}) — "
        f"{len(pendentes)} aguardando confirmação"
    ):
        st.caption(
            "Registro material do processo, extraído do formulário e "
            "versionado: os documentos passam a referenciar estes valores. "
            "Confirme-os para elevar a confiança das validações."
        )
        st.dataframe(
            [{
                "Fato": f["path"],
                "Valor": str(f.get("valor")),
                "Status": f.get("status"),
                "Fonte": f.get("fonte"),
                "Versão": f.get("versao"),
                "Confiança": f.get("confianca"),
            } for f in lista],
            use_container_width=True,
        )
        for divergencia in resultado["divergencias"]:
            st.warning(f"**{divergencia['path']}** — "
                       f"{divergencia['mensagem']}.")
        if pendentes and st.button(
            f"Confirmar os {len(pendentes)} fato(s) extraído(s)",
            key="confirmar_fatos",
        ):
            usuario = st.session_state.get("usuario") or {}
            fatos.confirmar_todos(
                st.session_state.get("processo_id"), usuario.get("id"))
            st.session_state.pop("_fatos_cache", None)
            st.rerun()


def _render_decisao_conhecimento(decisao: dict) -> None:
    """Resultado do motor de conhecimento na tela final (V5 Fase 3)."""
    resultado = decisao["resultado"]
    for bloqueio in resultado["bloqueios"]:
        st.error(
            f"**Emissão bloqueada pelo motor de conhecimento** — regra "
            f"`{bloqueio['regra']}`: {bloqueio['motivo']}"
        )
    for conflito in resultado["conflitos"]:
        st.error(
            f"**Conflito de regras sobre `{conflito['clausula']}`** — "
            f"{', '.join(conflito['regras'])}: {conflito['motivo']}."
        )
    with st.expander(
        "Regras aplicadas ao processo (motor de conhecimento)"
    ):
        st.caption(
            "Decisão determinística sobre os fatos canônicos — registrada "
            "com as versões de regras e fatos utilizadas "
            f"(decisão `{decisao['input_hash'][:12]}…`)."
        )
        linhas = []
        for clausula in resultado["clausulas_incluir"]:
            linhas.append(f"- **Incluir cláusula** `{clausula}`")
        for clausula in resultado["clausulas_excluir"]:
            linhas.append(f"- **Excluir cláusula** `{clausula}`")
        for parametro in resultado["parametros_exigidos"]:
            linhas.append(f"- **Parâmetro exigido**: {parametro}")
        for campo in resultado["campos_exigidos"]:
            linhas.append(f"- **Campo exigido**: {campo}")
        if resultado["familia"]:
            linhas.append(f"- **Família de modelo**: {resultado['familia']}")
        for alerta in resultado["alertas"]:
            linhas.append(f"- ⚠ {alerta}")
        st.markdown("\n".join(linhas) or
                    "Nenhuma regra publicada se aplica a este processo.")
        if resultado["pendencias"]:
            st.warning(
                "Dados ausentes para avaliar todas as regras: "
                + ", ".join(f"`{p}`" for p in resultado["pendencias"])
            )

        # Explicabilidade (V5 Fase 4 — flag_explanations): tudo abaixo
        # vem EXCLUSIVAMENTE do registro de decisão — nada é inventado.
        if explicacoes.ativa():
            afetadas = (resultado["clausulas_incluir"]
                        + resultado["clausulas_excluir"])
            if afetadas:
                st.markdown("**Por que isso está aqui?**")
            for clausula in afetadas:
                explicacao = explicacoes.explicar_clausula(
                    decisao, clausula)
                st.markdown(
                    f"- {explicacoes.texto_usuario(explicacao)}"
                    if explicacao else
                    f"- `{clausula}`: não há registro de decisão para "
                    "esta cláusula."
                )
            if auth.eh_admin():
                st.caption("Trilha técnica (administrador):")
                for linha in explicacoes.texto_admin(decisao):
                    st.caption(f"· {linha}")
                st.json(explicacoes.registro_auditor(decisao),
                        expanded=False)


def _render_score_qualidade(resultado: dict) -> None:
    """Painel do índice de confiança (V5 Fase 6, gate ligado)."""
    avaliacao = qualidade.avaliar_gate(resultado)
    if avaliacao["bloqueia"]:
        st.error(
            f"**Emissão bloqueada pelo índice de confiança** — "
            f"{avaliacao['motivo']}."
        )
        for critico in resultado["criticos"]:
            st.markdown(f"- {critico}")
    elif avaliacao["motivo"]:
        st.warning(avaliacao["motivo"])
    with st.expander(
        f"Índice de confiança: {resultado['score']} / 100 "
        f"({resultado['config_versao']})"
    ):
        st.caption(
            "Calculado exclusivamente de componentes determinísticos e "
            "relatórios reais do processo. Ocorrência crítica bloqueia a "
            "emissão independentemente do score."
        )
        st.dataframe(
            [{"Dimensão": nome, "Valor": valor}
             for nome, valor in resultado["dimensoes"].items()],
            use_container_width=True,
        )


def _render_relatorio_estruturado(relatorio: dict) -> None:
    """Findings estruturados na tela final (flag_achados_estruturados)."""
    findings = relatorio["findings"]
    rotulo_status = {
        "APPROVED": "aprovado",
        "CORRECTIONS_REQUIRED": "correções necessárias",
        "BLOCKED": "exige intervenção humana",
    }.get(relatorio["status"], relatorio["status"])
    with st.expander(
        f"Relatório estruturado da revisão — {rotulo_status} "
        f"({len(findings)} finding(s))"
    ):
        st.caption(
            "Cada achado da revisão vira um finding com escopo autorizado "
            "por bloco — a base do corretor por patches (etapas seguintes). "
            "Nesta etapa nada é alterado nos documentos."
        )
        st.markdown(f"**{relatorio['summary']}**")
        if findings:
            st.dataframe(
                [{
                    "Documento": f["documentId"].upper(),
                    "Gravidade": f["severity"],
                    "Categoria": f["categoria"],
                    "Problema": f["descricao"],
                    "Corrigível": "sim" if f["autoCorrectable"] else "não",
                    "Escopo autorizado": ", ".join(f["allowedPaths"]) or "—",
                } for f in findings],
                use_container_width=True,
            )


# ---------------------------------------------------------------------------
# Etapa 5 — Conclusão e exportação
# ---------------------------------------------------------------------------
def render_sucesso() -> None:
    from .. import validacao

    st.subheader("Processo concluído")

    docs = st.session_state.documentos
    orgao = (st.session_state.dados.get("orgao") or "orgao").strip()
    prefixo = "".join(c if c.isalnum() else "-" for c in orgao)[:40].strip("-") or "dossie"

    # ------------------------------------------------------------------
    # Correção automática (Etapa 6 — flag_tela_progresso): substitui a
    # atribuição manual da revisão. 'aprovado' libera os downloads com o
    # bundle já corrigido; 'pendente' aguarda dado/decisão do servidor
    # (sem downloads); None mantém a tela antiga (flag OFF, aplicação
    # desligada ou saída manual escolhida pelo usuário).
    # ------------------------------------------------------------------
    veredito = revisao.render_correcao_automatica()
    if veredito == "aprovado":
        docs = st.session_state.documentos  # pode ter sido corrigido

    bloqueios: list[dict] = []
    if veredito is None:
        # --------------------------------------------------------------
        # Tela ANTERIOR (inalterada): pendências ([PREENCHER], marcadores
        # internos etc.) BLOQUEIAM o download — devem ser resolvidas na
        # revisão, nunca aparecer no PDF/DOCX definitivo.
        # --------------------------------------------------------------
        achados_brutos = validacao.validar_todos(docs)
        bloqueios = validacao.bloqueios(achados_brutos)
        avisos = validacao.avisos(achados_brutos)

        if bloqueios:
            st.error(
                f"**Emissão bloqueada — {len(bloqueios)} pendência(s) impedem o "
                "documento final.** Volte à etapa do documento, resolva no editor "
                "e aprove novamente."
            )
            for a in bloqueios:
                st.markdown(f"- **{a['documento']}** — {a['mensagem']}  \n"
                            f"  `…{a['trecho']}…`")
            etapas_com_pendencia = sorted({
                DOCUMENTOS[a["doc"]]["etapa"] for a in bloqueios if a["doc"] in DOCUMENTOS
            })
            if etapas_com_pendencia and st.button(
                "Ir para o primeiro documento com pendência", type="primary",
            ):
                state.ir_para(etapas_com_pendencia[0])
        if avisos:
            with st.expander(f"Avisos de qualidade ({len(avisos)}) — não bloqueiam"):
                for a in avisos:
                    st.markdown(f"- **{a['documento']}** — {a['mensagem']}")

        # Correção automática (Etapa 1 — flag_achados_estruturados): os mesmos
        # achados acima, estruturados com escopo autorizado por bloco. Flag
        # DESLIGADA: nada muda nesta tela (auditoria roda em shadow mode/log).
        # Nesta etapa o relatório é informativo — a emissão não é alterada.
        relatorio = achados.relatorio_para_tela(
            docs, st.session_state.get("processo_id"))
        if relatorio is not None:
            _render_relatorio_estruturado(relatorio)

        # Etapa 3 (flag_corretor_shadow): gera e REGISTRA o plano de patch em
        # modo sombra — nunca aplica nada e nenhuma falha chega à tela.
        # Roda uma única vez por versão do bundle (cache por hash na sessão).
        corretor.plano_em_shadow(docs, st.session_state.dados,
                                 st.session_state.get("processo_id"))

    # Fatos canônicos (V5 F2 — flag_canonical_facts): registro material
    # do processo, versionado, que os documentos referenciam. Flag OFF:
    # extração roda em shadow (só log) e a tela permanece idêntica.
    resultado_fatos = fatos.processar_na_tela(
        st.session_state.dados, docs, st.session_state.get("processo_id"))
    if resultado_fatos is not None:
        _render_fatos_canonicos(resultado_fatos)

    # Motor de conhecimento (V5 F3): regras estruturadas avaliadas sobre
    # os fatos canônicos. Shadow: apenas registra a decisão (log/banco).
    # Ativo: exibe o resultado e bloqueios de regra impedem a emissão.
    decisao_conhecimento = conhecimento.executar_na_tela(
        st.session_state.dados, st.session_state.get("processo_id"))
    if decisao_conhecimento is not None:
        _render_decisao_conhecimento(decisao_conhecimento)

    # Índice de confiança (V5 F6): shadow calcula e persiste em silêncio;
    # com o gate ligado, o painel aparece e crítico/score baixo bloqueia.
    score_qualidade = qualidade.processar_na_tela(
        docs, st.session_state.dados, st.session_state.get("processo_id"))
    if score_qualidade is not None:
        _render_score_qualidade(score_qualidade)

    registro = st.session_state.get("registro_geracoes") or []
    if registro:
        with st.expander("Registro técnico de geração (auditoria)"):
            st.caption(
                f"Motor de PDF ativo: **{export.motor_pdf()}** "
                "(libreoffice = DOCX convertido, padrão institucional fiel)."
            )
            st.dataframe(registro, use_container_width=True)

    if veredito == "pendente" or bloqueios:
        return  # nada de downloads com pendência

    if decisao_conhecimento is not None and \
            decisao_conhecimento["resultado"]["bloqueios"]:
        return  # bloqueio de regra do motor de conhecimento (flag ativa)

    if score_qualidade is not None and \
            qualidade.avaliar_gate(score_qualidade)["bloqueia"]:
        return  # gate do índice de confiança (crítico ou score baixo)

    # Gate técnico (Etapa 7 — flag_gate_emissao): sem aprovação do ciclo
    # para a versão ATUAL do bundle, a emissão é tecnicamente impossível.
    liberada, motivo_gate = revisao.emissao_liberada(docs)
    if not liberada:
        st.error(f"**Emissão bloqueada pelo gate técnico.** {motivo_gate}")
        return

    st.markdown(
        "Os **quatro documentos da fase preparatória** foram elaborados, "
        "aprovados e validados. Baixe o dossiê completo ou os arquivos "
        "individuais."
    )

    # Identidade visual (cabeçalho/rodapé/marca d'água). Com a flag da
    # Fase 2 ligada, ela é resolvida pelo VÍNCULO do usuário (secretaria >
    # município) — o servidor não escolhe timbrado. Com a flag desligada,
    # mantém a seleção manual antiga (resolvedor roda em shadow mode).
    branding = None
    if db.disponivel():
        resolvido = contexto.identidade_para_exportacao()
        if resolvido is not None:
            branding, origem = resolvido
            if branding is not None:
                rotulo_origem = {
                    "secretaria": "identidade da sua secretaria",
                    "municipio": "identidade padrão do município",
                }.get(origem, origem)
                st.caption(
                    "Identidade visual aplicada automaticamente: "
                    f"**{branding.get('nome') or branding.get('orgao') or ''}** "
                    f"({rotulo_origem})."
                )
            else:
                st.caption(
                    "Nenhuma identidade visual cadastrada para o seu vínculo; "
                    "os arquivos saem sem timbrado."
                )
        else:
            try:
                orgaos = db.listar_orgaos()
            except db.ErroBanco:
                orgaos = []
            if orgaos:
                rotulos = {o["orgao"]: o for o in orgaos}
                escolha = st.selectbox(
                    "Identidade visual dos arquivos",
                    ["Sem identidade visual", *rotulos],
                    index=1,  # a padrão vem primeiro na listagem
                    help="Cabeçalho e rodapé em todas as páginas; marca d'água no PDF.",
                )
                if escolha != "Sem identidade visual":
                    branding = rotulos[escolha]

    st.markdown("#### Dossiê completo (arquivo único)")
    col_pdf, col_docx = st.columns(2)
    col_pdf.download_button(
        "Baixar todos em PDF",
        data=export.gerar_pdf_consolidado(docs, branding),
        file_name=f"{prefixo}-fase-preparatoria.pdf",
        mime="application/pdf",
        type="primary", use_container_width=True,
    )
    col_docx.download_button(
        "Baixar todos em DOCX",
        data=export.gerar_docx_consolidado(docs, branding),
        file_name=f"{prefixo}-fase-preparatoria.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        type="primary", use_container_width=True,
    )

    st.markdown("#### Arquivos individuais (pacote .zip)")
    col_zip_pdf, col_zip_docx = st.columns(2)
    col_zip_pdf.download_button(
        "ZIP com os 4 PDFs",
        data=export.gerar_zip(docs, "pdf", branding),
        file_name=f"{prefixo}-documentos-pdf.zip",
        mime="application/zip", use_container_width=True,
    )
    col_zip_docx.download_button(
        "ZIP com os 4 DOCX",
        data=export.gerar_zip(docs, "docx", branding),
        file_name=f"{prefixo}-documentos-docx.zip",
        mime="application/zip", use_container_width=True,
    )

    with st.expander("Conferir documentos aprovados"):
        abas = st.tabs([DOCUMENTOS[k]["sigla"] for k in SEQUENCIA_DOCUMENTOS if k in docs])
        for aba, doc_key in zip(abas, [k for k in SEQUENCIA_DOCUMENTOS if k in docs]):
            with aba:
                st.markdown(docs[doc_key])

    st.divider()
    col_rev, col_novo = st.columns(2)
    if col_rev.button("Voltar para revisar a minuta", use_container_width=True):
        state.ir_para(4)
    if col_novo.button("Iniciar novo processo", use_container_width=True):
        state.reiniciar_processo()
