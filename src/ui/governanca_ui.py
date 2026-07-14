"""
Página "Governança" — Centro de Governança da Plataforma (pacote V6).

Visível SOMENTE quando `flag_governance_center` está ligada E o usuário
tem papel de governança (servidor comum nunca vê — T09). Os módulos
entram por fase; nesta Fase 2, Visão Geral + Catálogo de Cláusulas
(`flag_clause_catalog_admin`). A interface esconde programação:
formulários e botões, nunca JSON como forma principal de edição.
"""

import streamlit as st

from .. import auth, catalogo, db, governanca, politicas

_ROTULOS_STATUS = {
    "DRAFT": "rascunho",
    "UNDER_REVIEW": "em revisão",
    "APPROVED_FOR_SIMULATION": "aprovada p/ simulação",
    "SHADOW": "em shadow",
    "SCHEDULED": "agendada",
    "PUBLISHED": "PUBLICADA",
    "SUPERSEDED": "superada",
    "REVOKED": "revogada",
}

_ROTULOS_COMPORTAMENTO = {
    "FIXED_LOCKED": "Fixa (imutável)",
    "FIXED_PARAMETERIZED": "Fixa com parâmetros",
    "CONDITIONAL_LOCKED": "Condicional (texto fixo)",
    "HYBRID": "Híbrida",
    "AI_GENERATED": "Gerada por IA",
}


def disponivel() -> bool:
    return (db.flag_ativa(governanca.FLAG_CENTRO)
            and auth.acessa_centro_governanca())


def render_governanca() -> None:
    st.subheader("Centro de Governança")
    papel = auth.papel_governanca()
    st.caption(
        f"Seu papel: **{papel}**. Aqui o conhecimento documental é "
        "operado pela interface — cláusulas, políticas, modelos e "
        "templates versionados, com revisão, simulação e publicação. "
        "Nada é publicado automaticamente."
    )
    (aba_visao, aba_catalogo, aba_politicas, aba_familias,
     aba_templates, aba_heranca) = st.tabs(
        ["Visão geral", "Catálogo de cláusulas", "Políticas de aplicação",
         "Biblioteca de modelos", "Templates", "Herança"])
    with aba_visao:
        _render_visao_geral()
    with aba_catalogo:
        if db.flag_ativa(governanca.FLAG_CATALOGO):
            _render_catalogo()
        else:
            st.info("O Catálogo de Cláusulas está desligado "
                    "(flag_clause_catalog_admin).")
    with aba_politicas:
        if politicas.ativa():
            _render_politicas()
        else:
            st.info("O construtor de políticas está desligado "
                    "(flag_visual_policy_builder).")
    with aba_familias:
        _render_familias()
    with aba_templates:
        _render_templates()
    with aba_heranca:
        _render_heranca()


def _render_visao_geral() -> None:
    try:
        itens = catalogo.listar_com_situacao()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    publicadas = sum(1 for i in itens if i["publicada"])
    rascunhos = sum(1 for i in itens if i["ultima"]
                    and i["ultima"]["status"] in ("DRAFT", "UNDER_REVIEW"))
    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Cláusulas no catálogo", len(itens))
    col_b.metric("Publicadas (vigentes)", publicadas)
    col_c.metric("Em elaboração/revisão", rascunhos)
    st.caption(
        "Módulos por fase: Catálogo (ativo) · Políticas de Aplicação · "
        "Biblioteca de Modelos · Construtor de Templates · Herança · "
        "Assistente de Implantação · Pareceres · Laboratório · "
        "Publicações — chegam nas fases seguintes, cada um com sua flag."
    )


def _render_catalogo() -> None:
    somente_leitura = auth.somente_auditoria()

    if not somente_leitura:
        with st.expander("Nova cláusula"):
            _render_form_nova_clausula()
        if auth.pode_criar_governanca() and st.button(
            "Importar rascunhos dos perfis aprovados (DFD/ETP/TR)",
            help="Cada cláusula dos perfis institucionais vira um "
                 "RASCUNHO do catálogo — nada é publicado.",
        ):
            try:
                criadas = catalogo.semear_dos_perfis()
                st.success(f"{len(criadas)} rascunho(s) criado(s).")
                st.rerun()
            except (catalogo.ErroCatalogo, db.ErroBanco,
                    governanca.ErroContrato) as erro:
                st.error(str(erro))

    st.divider()
    try:
        itens = catalogo.listar_com_situacao()
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not itens:
        st.caption("Catálogo vazio. Crie uma cláusula ou importe os "
                   "perfis aprovados.")
        return
    for item in itens:
        _render_clausula(item, somente_leitura)


def _render_form_nova_clausula() -> None:
    with st.form("form_nova_clausula", clear_on_submit=True):
        col1, col2 = st.columns(2)
        chave = col1.text_input(
            "Chave estável", placeholder="clausula.tr.garantia",
            help="Identificador permanente (minúsculas, pontos, hífens).")
        titulo = col2.text_input("Título da cláusula")
        col3, col4 = st.columns(2)
        comportamento = col3.selectbox(
            "Comportamento", governanca.COMPORTAMENTOS_CLAUSULA,
            format_func=lambda c: _ROTULOS_COMPORTAMENTO.get(c, c))
        tipo_documental = col4.selectbox(
            "Tipo documental", ["dfd", "etp", "tr", "edital"])
        texto = st.text_area(
            "Texto da cláusula (um parágrafo por linha em branco)",
            height=160,
            help="Use {{parametro}} para os campos parametrizados.")
        parametros = st.text_input(
            "Parâmetros permitidos (separados por vírgula)",
            placeholder="prazo, percentual",
            help="Obrigatório para cláusulas fixas com parâmetros.")
        base_legal = st.text_input(
            "Base legal / fontes", placeholder="art. 96, Lei 14.133/2021")
        enviado = st.form_submit_button("Criar rascunho", type="primary",
                                        use_container_width=True)
    if enviado:
        payload = {
            "titulo": titulo.strip(),
            "tipo_documental": tipo_documental,
            "comportamento": comportamento,
            "blocos": [b.strip() for b in (texto or "").split("\n\n")
                       if b.strip()],
            "parametros_permitidos": [
                p.strip() for p in parametros.split(",") if p.strip()],
            "base_legal": [b.strip() for b in base_legal.split(";")
                           if b.strip()],
        }
        try:
            catalogo.criar_clausula(chave.strip(), payload)
            st.success(f"Rascunho '{chave}' criado.")
            st.rerun()
        except (catalogo.ErroCatalogo, db.ErroBanco,
                governanca.ErroContrato) as erro:
            st.error(str(erro))


def _render_clausula(item: dict, somente_leitura: bool) -> None:
    artefato, ultima = item["artefato"], item["ultima"]
    publicada = item["publicada"]
    situacao = (_ROTULOS_STATUS.get(ultima["status"], ultima["status"])
                if ultima else "sem versões")
    escopo = "plataforma" if artefato.get("tenant_id") is None \
        else "município"
    with st.expander(
        f"`{artefato['chave_estavel']}` — "
        f"{(ultima or {}).get('payload', {}).get('titulo', '')} "
        f"· v{(ultima or {}).get('versao', 0)} ({situacao}) · {escopo}"
    ):
        if publicada and publicada is not ultima:
            st.caption(
                f"Vigente: v{publicada['versao']} (hash "
                f"`{publicada['hash'][:12]}…`) — a edição abaixo é de "
                "uma versão em elaboração.")
        if not ultima:
            return
        payload = ultima["payload"]
        st.markdown(
            f"**Comportamento:** "
            f"{_ROTULOS_COMPORTAMENTO.get(payload.get('comportamento'))} · "
            f"**Documento:** {payload.get('tipo_documental', '—')} · "
            f"**Hash:** `{ultima['hash'][:12]}…`"
        )
        for bloco in payload.get("blocos", []):
            st.markdown(f"> {bloco}")
        if payload.get("parametros_permitidos"):
            st.caption("Parâmetros permitidos: "
                       + ", ".join(payload["parametros_permitidos"]))
        if payload.get("base_legal"):
            st.caption("Base legal: " + "; ".join(payload["base_legal"]))
        if somente_leitura:
            return

        if governanca.versao_artefato_editavel(ultima):
            novo_texto = st.text_area(
                "Editar texto do rascunho",
                value="\n\n".join(payload.get("blocos", [])),
                key=f"edita_{ultima['id']}", height=120)
            if st.button("Salvar rascunho", key=f"salva_{ultima['id']}"):
                try:
                    catalogo.editar_rascunho(
                        ultima, artefato["chave_estavel"],
                        {**payload, "blocos": [
                            b.strip() for b in novo_texto.split("\n\n")
                            if b.strip()]})
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco,
                        governanca.ErroContrato) as erro:
                    st.error(str(erro))
        elif ultima.get("status") == "PUBLISHED" and \
                auth.pode_criar_governanca():
            if st.button("Derivar nova versão (editar)",
                         key=f"deriva_{ultima['id']}"):
                try:
                    catalogo.derivar_nova_versao(artefato, ultima)
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                    st.error(str(erro))

        destinos = catalogo.proximas_transicoes(ultima)
        if destinos:
            col_sel, col_btn = st.columns([2, 1])
            destino = col_sel.selectbox(
                "Avançar para", destinos,
                format_func=lambda d: _ROTULOS_STATUS.get(d, d),
                key=f"destino_{ultima['id']}",
                label_visibility="collapsed")
            if col_btn.button("Aplicar", key=f"aplica_{ultima['id']}",
                              use_container_width=True):
                try:
                    catalogo.transicionar(artefato, ultima, destino)
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                    st.error(str(erro))


# ---------------------------------------------------------------------------
# Políticas de aplicação (V6 Fase 3) — construtor visual, sem código
# ---------------------------------------------------------------------------
_CAMPOS_SUGERIDOS = [
    "procedimento.srp", "procedimento.execucao_continuada",
    "objeto.natureza", "valor.total", "execucao.modelo", "orgao.nome",
]
_ROTULOS_ACAO = {
    "INCLUIR_CLAUSULA": "Incluir cláusula",
    "EXCLUIR_CLAUSULA": "Excluir cláusula incompatível",
    "EXIGIR_PARAMETRO": "Exigir parâmetro",
    "EXIGIR_CAMPO": "Exigir documento/campo",
    "SELECIONAR_FAMILIA": "Selecionar família de modelo",
    "ATIVAR_VALIDACAO": "Ativar validação",
    "BLOQUEAR_EMISSAO": "Bloquear emissão",
    "ALERTA": "Emitir alerta",
}


def _interpretar_valor(bruto: str):
    texto = (bruto or "").strip()
    if texto.lower() in ("true", "sim", "verdadeiro"):
        return True
    if texto.lower() in ("false", "não", "nao", "falso"):
        return False
    try:
        return float(texto) if "." in texto or "," in texto \
            else int(texto)
    except ValueError:
        return texto


def descrever_condicao(condicao: dict) -> str:
    if "op" in condicao:
        juntor = {"ALL": " E ", "ANY": " OU ", "NOT": "NÃO "}[condicao["op"]]
        partes = [descrever_condicao(f)
                  for f in condicao.get("children", [])]
        if condicao["op"] == "NOT":
            return f"NÃO ({partes[0]})"
        return "(" + juntor.join(partes) + ")"
    return (f"{condicao.get('field')} {condicao.get('operator')} "
            f"{condicao.get('value', '')}")


def _render_politicas() -> None:
    somente_leitura = auth.somente_auditoria()
    if not somente_leitura:
        with st.expander("Nova política"):
            _render_form_nova_politica()
    st.divider()
    try:
        itens = catalogo.listar_com_situacao("politica")
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not itens:
        st.caption("Nenhuma política criada ainda.")
        return
    for item in itens:
        _render_politica(item, somente_leitura)


def _render_form_nova_politica() -> None:
    st.caption(
        "Condições avaliadas por código sobre os fatos do processo — "
        "campos sugeridos: " + ", ".join(f"`{c}`" for c in _CAMPOS_SUGERIDOS)
    )
    with st.form("form_nova_politica", clear_on_submit=True):
        col1, col2, col3 = st.columns([2, 1, 1])
        chave = col1.text_input("Chave estável",
                                placeholder="politica.me-epp.srp-bens")
        prioridade = col2.number_input("Prioridade", 1, 1000, 100)
        operador_grupo = col3.selectbox(
            "As condições valem…", ["ALL", "ANY"],
            format_func=lambda o: "Todas juntas (E)" if o == "ALL"
            else "Qualquer uma (OU)")
        condicoes = []
        for i in range(3):
            c1, c2, c3 = st.columns([2, 1, 2])
            campo = c1.text_input(f"Campo {i + 1}",
                                  key=f"pol_campo_{i}",
                                  placeholder="procedimento.srp")
            operador = c2.selectbox(
                f"Operador {i + 1}", governanca.OPERADORES_FOLHA,
                key=f"pol_op_{i}")
            valor = c3.text_input(f"Valor {i + 1}", key=f"pol_valor_{i}",
                                  placeholder="sim / BENS / 50000")
            condicoes.append((campo, operador, valor))
        st.markdown("**Ações**")
        acoes = []
        for i in range(2):
            a1, a2 = st.columns([1, 2])
            tipo = a1.selectbox(
                f"Ação {i + 1}", ["—"] + list(governanca.TIPOS_ACAO),
                format_func=lambda t: _ROTULOS_ACAO.get(t, t),
                key=f"pol_acao_{i}")
            alvo = a2.text_input(f"Alvo/mensagem {i + 1}",
                                 key=f"pol_alvo_{i}",
                                 placeholder="clausula.tr.me-epp")
            acoes.append((tipo, alvo))
        justificativa = st.text_input(
            "Justificativa", placeholder="Por que esta regra existe?")
        fontes = st.text_input("Fontes", placeholder="lc-123-2006")
        enviado = st.form_submit_button("Criar rascunho", type="primary",
                                        use_container_width=True)
    if enviado:
        folhas = [
            {"field": campo.strip(), "operator": operador,
             **({} if operador == "EXISTS"
                else {"value": _interpretar_valor(valor)})}
            for campo, operador, valor in condicoes if campo.strip()
        ]
        condicao = (folhas[0] if len(folhas) == 1
                    else {"op": operador_grupo, "children": folhas})
        lista_acoes = []
        for tipo, alvo in acoes:
            if tipo == "—":
                continue
            acao = {"type": tipo}
            if tipo == "ALERTA":
                acao["mensagem"] = alvo.strip()
            elif tipo == "BLOQUEAR_EMISSAO":
                acao["motivo"] = alvo.strip()
            else:
                acao["target"] = alvo.strip()
            lista_acoes.append(acao)
        try:
            politicas.criar_politica(
                chave.strip(), condicao, lista_acoes, int(prioridade),
                justificativa,
                [f.strip() for f in fontes.split(";") if f.strip()])
            st.success(f"Rascunho '{chave}' criado.")
            st.rerun()
        except (catalogo.ErroCatalogo, governanca.ErroContrato,
                db.ErroBanco) as erro:
            st.error(str(erro))


def _render_politica(item: dict, somente_leitura: bool) -> None:
    artefato, ultima = item["artefato"], item["ultima"]
    if not ultima:
        return
    payload = ultima["payload"]
    situacao = _ROTULOS_STATUS.get(ultima["status"], ultima["status"])
    with st.expander(
        f"`{artefato['chave_estavel']}` · v{ultima['versao']} "
        f"({situacao}) · prioridade {payload.get('prioridade', 100)}"
    ):
        st.markdown(f"**SE** {descrever_condicao(payload.get('condicao', {}))}")
        for acao in payload.get("acoes", []):
            rotulo = _ROTULOS_ACAO.get(acao.get("type"), acao.get("type"))
            st.markdown(f"**ENTÃO** {rotulo}: "
                        f"`{acao.get('target') or acao.get('mensagem') or acao.get('motivo', '')}`")
        if payload.get("justificativa"):
            st.caption(f"Justificativa: {payload['justificativa']}")

        # simulação: o efeito antes de publicar
        with st.form(f"form_simula_{ultima['id']}"):
            st.markdown("**Simular com um processo de teste**")
            s1, s2, s3 = st.columns(3)
            srp = s1.checkbox("Registro de preços (SRP)", value=True,
                              key=f"sim_srp_{ultima['id']}")
            natureza = s2.selectbox(
                "Natureza", ["BENS", "SERVICOS", "OBRAS_ENGENHARIA"],
                key=f"sim_nat_{ultima['id']}")
            valor_total = s3.number_input(
                "Valor global", 0.0, value=50000.0,
                key=f"sim_valor_{ultima['id']}")
            simular = st.form_submit_button("Simular")
        if simular:
            decisao = politicas.simular(artefato, ultima, {
                "procedimento.srp": srp,
                "objeto.natureza": natureza,
                "valor.total": valor_total,
            })
            resultado = decisao["resultado"]
            aplicada = any(
                r["chave"] == artefato["chave_estavel"]
                for r in decisao["regras_versoes"])
            st.info(
                ("A política SE APLICARIA a este processo. " if aplicada
                 else "A política NÃO se aplicaria a este processo. ")
                + f"Resultado: incluir={resultado['clausulas_incluir']}, "
                  f"excluir={resultado['clausulas_excluir']}, "
                  f"bloqueios={len(resultado['bloqueios'])}, "
                  f"alertas={len(resultado['alertas'])}."
            )

        if somente_leitura:
            return
        destinos = catalogo.proximas_transicoes(ultima)
        if destinos:
            col_sel, col_btn = st.columns([2, 1])
            destino = col_sel.selectbox(
                "Avançar para", destinos,
                format_func=lambda d: _ROTULOS_STATUS.get(d, d),
                key=f"pol_destino_{ultima['id']}",
                label_visibility="collapsed")
            if col_btn.button("Aplicar", key=f"pol_aplica_{ultima['id']}",
                              use_container_width=True):
                try:
                    if destino == "PUBLISHED":
                        politicas.publicar(artefato, ultima)
                    else:
                        catalogo.transicionar(artefato, ultima, destino)
                    st.rerun()
                except (politicas.ErroPolitica, catalogo.ErroCatalogo,
                        db.ErroBanco) as erro:
                    st.error(str(erro))


# ---------------------------------------------------------------------------
# Biblioteca de famílias de modelos (V6 Fase 4)
# ---------------------------------------------------------------------------
def _render_familias() -> None:
    from .. import familias as familias_mod

    st.caption(
        "Famílias definem estrutura e cláusulas por tipo de contratação. "
        "O servidor NÃO escolhe modelo: o sistema resolve pelo contexto; "
        "só há pergunta objetiva quando existe ambiguidade real. "
        "Resolução em sombra/ativa pelas flags de família."
    )
    somente_leitura = auth.somente_auditoria()
    if not somente_leitura:
        with st.expander("Nova família de modelo"):
            _render_form_nova_familia(familias_mod)
    st.divider()
    try:
        itens = catalogo.listar_com_situacao("familia")
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not itens:
        st.caption("Nenhuma família criada ainda. Exemplos típicos: TR "
                   "para serviços contínuos, ETP para obras, DFD para "
                   "bens — crie as famílias efetivamente aprovadas.")
        return
    for item in itens:
        _render_familia(item, somente_leitura)


def _render_form_nova_familia(familias_mod) -> None:
    with st.form("form_nova_familia", clear_on_submit=True):
        col1, col2 = st.columns(2)
        chave = col1.text_input("Chave estável",
                                placeholder="familia.tr-servicos-continuos")
        nome = col2.text_input("Nome",
                               placeholder="TR para serviços contínuos")
        col3, col4 = st.columns(2)
        docs = col3.multiselect("Documentos suportados",
                                ["dfd", "etp", "tr", "edital"],
                                default=["tr"])
        prioridade = col4.number_input("Prioridade (desempate)", 1, 1000,
                                       100)
        st.markdown("**Critérios de elegibilidade** (todos precisam valer)")
        condicoes = []
        for i in range(3):
            c1, c2, c3 = st.columns([2, 1, 2])
            campo = c1.text_input(f"Campo {i + 1}", key=f"fam_campo_{i}",
                                  placeholder="procedimento.srp")
            operador = c2.selectbox(f"Operador {i + 1}",
                                    governanca.OPERADORES_FOLHA,
                                    key=f"fam_op_{i}")
            valor = c3.text_input(f"Valor {i + 1}", key=f"fam_valor_{i}")
            condicoes.append((campo, operador, valor))
        obrigatorias = st.text_input(
            "Cláusulas obrigatórias (separadas por ;)",
            placeholder="clausula.tr.dedicacao-exclusiva; clausula.tr.sla")
        proibidas = st.text_input(
            "Cláusulas proibidas (separadas por ;)")
        pergunta = st.text_input(
            "Pergunta de desambiguação (usada só em empate real)",
            placeholder="O serviço terá dedicação exclusiva de mão de obra?")
        enviado = st.form_submit_button("Criar rascunho", type="primary",
                                        use_container_width=True)
    if enviado:
        folhas = [
            {"field": campo.strip(), "operator": operador,
             **({} if operador == "EXISTS"
                else {"value": _interpretar_valor(valor)})}
            for campo, operador, valor in condicoes if campo.strip()
        ]
        criterios = (folhas[0] if len(folhas) == 1
                     else {"op": "ALL", "children": folhas})
        try:
            familias_mod.criar_familia(
                chave.strip(), nome.strip(), docs, criterios,
                [c.strip() for c in obrigatorias.split(";") if c.strip()],
                [c.strip() for c in proibidas.split(";") if c.strip()],
                int(prioridade), pergunta.strip())
            st.success(f"Rascunho '{chave}' criado.")
            st.rerun()
        except (catalogo.ErroCatalogo, governanca.ErroContrato,
                db.ErroBanco) as erro:
            st.error(str(erro))


def _render_familia(item: dict, somente_leitura: bool) -> None:
    artefato, ultima = item["artefato"], item["ultima"]
    if not ultima:
        return
    payload = ultima["payload"]
    situacao = _ROTULOS_STATUS.get(ultima["status"], ultima["status"])
    with st.expander(
        f"`{artefato['chave_estavel']}` — {payload.get('nome', '')} "
        f"· v{ultima['versao']} ({situacao}) · "
        f"docs: {', '.join(payload.get('documentos_suportados', []))}"
    ):
        st.markdown(
            f"**Elegível quando:** "
            f"{descrever_condicao(payload.get('criterios', {}))}")
        if payload.get("clausulas_obrigatorias"):
            st.caption("Obrigatórias: "
                       + "; ".join(payload["clausulas_obrigatorias"]))
        if payload.get("clausulas_proibidas"):
            st.caption("Proibidas: "
                       + "; ".join(payload["clausulas_proibidas"]))
        if somente_leitura:
            return
        destinos = catalogo.proximas_transicoes(ultima)
        if destinos:
            col_sel, col_btn = st.columns([2, 1])
            destino = col_sel.selectbox(
                "Avançar para", destinos,
                format_func=lambda d: _ROTULOS_STATUS.get(d, d),
                key=f"fam_destino_{ultima['id']}",
                label_visibility="collapsed")
            if col_btn.button("Aplicar", key=f"fam_aplica_{ultima['id']}",
                              use_container_width=True):
                try:
                    catalogo.transicionar(artefato, ultima, destino)
                    st.rerun()
                except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                    st.error(str(erro))


# ---------------------------------------------------------------------------
# Construtor de templates (V6 Fase 5)
# ---------------------------------------------------------------------------
def _render_templates() -> None:
    from .. import templates_gov

    if not templates_gov.ativa():
        st.info("O construtor de templates está desligado "
                "(flag_template_builder).")
        return
    st.caption(
        "Templates por BLOCOS (nunca editor livre): título, metadados, "
        "cláusulas do catálogo (com condição), tabelas, assinatura. A "
        "montagem é determinística e preserva versão/hash de cada "
        "cláusula usada."
    )
    try:
        itens = catalogo.listar_com_situacao("template")
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not auth.somente_auditoria():
        with st.expander("Novo template (a partir das cláusulas publicadas)"):
            _render_form_novo_template(templates_gov)
    st.divider()
    if not itens:
        st.caption("Nenhum template criado ainda.")
        return
    for item in itens:
        artefato, ultima = item["artefato"], item["ultima"]
        if not ultima:
            continue
        blocos_t = ultima["payload"].get("blocos", [])
        situacao = _ROTULOS_STATUS.get(ultima["status"], ultima["status"])
        with st.expander(f"`{artefato['chave_estavel']}` · "
                         f"v{ultima['versao']} ({situacao}) · "
                         f"{len(blocos_t)} bloco(s)"):
            st.markdown(" → ".join(
                f"`{b.get('tipo')}`" for b in blocos_t))
            if st.button("Pré-visualizar com contexto de teste",
                         key=f"tpl_prev_{ultima['id']}"):
                resultado = templates_gov.montar(
                    ultima["payload"],
                    {"procedimento.srp": True,
                     "orgao.nome": "Prefeitura (teste)"},
                    parametros={})
                st.markdown(resultado["texto"])
                for pendencia in resultado["pendencias"]:
                    st.warning(str(pendencia))
            destinos = catalogo.proximas_transicoes(ultima)
            if destinos and not auth.somente_auditoria():
                col_sel, col_btn = st.columns([2, 1])
                destino = col_sel.selectbox(
                    "Avançar para", destinos,
                    format_func=lambda d: _ROTULOS_STATUS.get(d, d),
                    key=f"tpl_destino_{ultima['id']}",
                    label_visibility="collapsed")
                if col_btn.button("Aplicar",
                                  key=f"tpl_aplica_{ultima['id']}",
                                  use_container_width=True):
                    try:
                        catalogo.transicionar(artefato, ultima, destino)
                        st.rerun()
                    except (catalogo.ErroCatalogo, db.ErroBanco) as erro:
                        st.error(str(erro))


def _render_form_novo_template(templates_gov) -> None:
    try:
        publicadas = [i["artefato"]["chave_estavel"]
                      for i in catalogo.listar_com_situacao("clausula")
                      if i["publicada"]]
    except db.ErroBanco:
        publicadas = []
    with st.form("form_novo_template", clear_on_submit=True):
        col1, col2 = st.columns(2)
        chave = col1.text_input("Chave estável",
                                placeholder="template.tr-base")
        titulo = col2.text_input("Título do documento",
                                 placeholder="TERMO DE REFERÊNCIA")
        clausulas_escolhidas = st.multiselect(
            "Cláusulas do catálogo (na ordem)", publicadas)
        com_tabela = st.checkbox("Incluir tabela de itens", value=True)
        enviado = st.form_submit_button("Criar rascunho", type="primary",
                                        use_container_width=True)
    if enviado:
        blocos_t = [{"id": "b-titulo", "tipo": "titulo", "texto": titulo}]
        blocos_t += [{"id": f"b-{i}", "tipo": "clausula_catalogo",
                      "clausula": c}
                     for i, c in enumerate(clausulas_escolhidas)]
        if com_tabela:
            blocos_t.append({"id": "b-tabela", "tipo": "tabela"})
        blocos_t.append({"id": "b-assina", "tipo": "assinatura"})
        try:
            templates_gov.criar_template(chave.strip(), blocos_t)
            st.success(f"Rascunho '{chave}' criado.")
            st.rerun()
        except (catalogo.ErroCatalogo, governanca.ErroContrato,
                db.ErroBanco) as erro:
            st.error(str(erro))


# ---------------------------------------------------------------------------
# Herança e precedência (V6 Fase 6)
# ---------------------------------------------------------------------------
def _render_heranca() -> None:
    from .. import heranca as heranca_mod

    if not heranca_mod.ativa():
        st.info("A administração de herança está desligada "
                "(flag_tenant_inheritance_admin).")
        return
    st.caption(
        "Precedência: secretaria > município > plataforma. O nível mais "
        "específico prevalece; sem override, vale a herança. Restaurar "
        "revoga o override local (o histórico permanece)."
    )
    tipo = st.selectbox("Tipo de artefato",
                        ["clausula", "politica", "familia", "template"])
    try:
        visao = heranca_mod.visao_heranca(tipo)
    except db.ErroBanco as erro:
        st.error(str(erro))
        return
    if not visao:
        st.caption("Nenhum artefato deste tipo ainda.")
        return
    for linha in visao:
        origem = linha["origem"] or "sem versão publicada"
        with st.expander(f"`{linha['chave']}` — origem: **{origem}**"
                         + (" · com override" if linha["tem_override"]
                            else "")):
            for escopo, item in sorted(linha["escopos"].items()):
                ultima = item["ultima"]
                st.caption(
                    f"{escopo}: v{ultima['versao']} "
                    f"({_ROTULOS_STATUS.get(ultima['status'])}) "
                    f"hash `{ultima['hash'][:12]}…`" if ultima
                    else f"{escopo}: sem versões")
            comparacao = heranca_mod.comparar(linha)
            if comparacao:
                st.caption(
                    "Comparação com a plataforma: "
                    + ("idênticas" if comparacao["iguais"] else
                       "difere em " + ", ".join(
                           comparacao["campos_diferentes"])))
            if auth.somente_auditoria():
                continue
            col_a, col_b = st.columns(2)
            if linha["origem"] == "plataforma" and \
                    "municipio" not in linha["escopos"]:
                if col_a.button("Sobrescrever neste município",
                                key=f"her_sob_{linha['chave']}"):
                    try:
                        heranca_mod.sobrescrever(linha)
                        st.rerun()
                    except (heranca_mod.ErroHeranca,
                            db.ErroBanco) as erro:
                        st.error(str(erro))
            if linha["tem_override"] and linha["origem"] != "plataforma":
                if col_b.button("Restaurar herança da plataforma",
                                key=f"her_rest_{linha['chave']}"):
                    try:
                        heranca_mod.restaurar_heranca(linha)
                        st.rerun()
                    except (heranca_mod.ErroHeranca,
                            db.ErroBanco) as erro:
                        st.error(str(erro))
