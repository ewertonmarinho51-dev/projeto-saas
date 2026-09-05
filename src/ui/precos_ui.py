"""
Pesquisa de Preços — superfície GovConnect (Fases 4 e 5).

O §16 pede um módulo que **pareça parte natural do GovConnect**, sem
copiar o sistema de referência tela a tela. Por isso aqui não há CSS
novo: tudo usa `components.render_page_header`,
`render_section_heading`, `render_guidance` e os tokens que o resto do
app já usa. O que muda é o conteúdo, não a linguagem visual.

Três decisões estruturais, e as três têm consequência prática:

**1. A navegação mora em `st.session_state`, não em rota de URL.**
O app inteiro é um script run do Streamlit; inventar rota aqui criaria
um segundo modelo de navegação convivendo com o `pagina` da sidebar.

**2. Nenhuma chamada externa acontece durante o desenho da tela.**
A pesquisa roda em lotes reentrantes (`precos.execucao`), e cada lote
devolve o controle para o navegador. É o que o §46 exige e o que
`docs/pesquisa-precos-fase0-auditoria.md` seção I registrou como opção
escolhida — sem introduzir infraestrutura nova em silêncio.

**3. Sem sessão do Supabase Auth, a tela DIZ isso.**
O repositório recusa operar com a credencial de servidor (Fase 3), e a
interface não disfarça a recusa com uma lista vazia: ela explica que
falta autenticação. Lista vazia por falta de permissão é a pior tela
possível — parece que não há nada, quando na verdade não se pode ver.

**4. A aplicação ao processo (§26) nunca é silenciosa.**
O diff de cada item, o que a pesquisa não cobre e a lista NOMINAL dos
documentos que serão descartados aparecem antes de qualquer escrita.
"""

from __future__ import annotations

import html
import io
from datetime import date
from decimal import Decimal, InvalidOperation

import streamlit as st

from .. import auth, db, planilha
from ..precos import (aplicacao, execucao, filtros as filtros_mod,
                      orientacao, perfil, relatorio)
from ..precos import semantica as precos_semantica
from ..precos import repositorio as repo
from ..precos.estados import EstadoItem, EstadoPesquisa
from . import components

# Chaves de navegação interna do módulo.
TELA = "precos_tela"
PESQUISA = "precos_pesquisa_id"
ITEM = "precos_item_id"
RELATO = "precos_relato"

LISTA, NOVA, ITENS, EXECUCAO, REVISAO, RESUMO = (
    "lista", "nova", "itens", "execucao", "revisao", "resumo")

# Rótulos dos estados. O vocabulário do banco é inglês (§42); o que o
# servidor lê é português — e a tradução mora num lugar só.
ROTULO_PESQUISA = {
    EstadoPesquisa.RASCUNHO.value: "Rascunho",
    EstadoPesquisa.NA_FILA.value: "Na fila",
    EstadoPesquisa.EXECUTANDO.value: "Pesquisando",
    EstadoPesquisa.PARCIAL.value: "Com pendências",
    EstadoPesquisa.EM_REVISAO.value: "Em revisão",
    EstadoPesquisa.CONCLUIDA.value: "Concluída",
    EstadoPesquisa.APLICADA.value: "Aplicada ao processo",
    EstadoPesquisa.ARQUIVADA.value: "Arquivada",
    EstadoPesquisa.FALHOU.value: "Falhou",
}

ROTULO_ITEM = {
    EstadoItem.PENDENTE.value: "Pendente",
    EstadoItem.BUSCANDO.value: "Buscando",
    EstadoItem.CLASSIFICANDO.value: "Classificando",
    EstadoItem.EM_REVISAO.value: "Revisar",
    EstadoItem.COMPLETO.value: "Concluído",
    EstadoItem.INCOMPLETO.value: "Incompleto",
    EstadoItem.ERRO.value: "Erro",
}

ROTULO_STATUS = {
    "selected": "Na cesta",
    "candidate": "Candidata",
    "rejected": "Excluída",
    "warning": "Sinalizada",
    "manual_review": "Abaixo do piso",
}

# Recortes da lista (§29).
RECORTES = {
    "Em andamento": (EstadoPesquisa.RASCUNHO.value, EstadoPesquisa.NA_FILA.value,
                     EstadoPesquisa.EXECUTANDO.value,
                     EstadoPesquisa.EM_REVISAO.value),
    "Com pendências": (EstadoPesquisa.PARCIAL.value,
                       EstadoPesquisa.FALHOU.value),
    "Concluídas": (EstadoPesquisa.CONCLUIDA.value,
                   EstadoPesquisa.APLICADA.value),
    "Arquivadas": (EstadoPesquisa.ARQUIVADA.value,),
}


# ---------------------------------------------------------------------------
# Porta de entrada
# ---------------------------------------------------------------------------
def disponivel() -> bool:
    """
    O módulo aparece na navegação?

    Só a flag. A sessão NÃO entra aqui de propósito: se a ausência de
    sessão escondesse o menu, o servidor veria o módulo sumir sem
    explicação. Ele aparece, e a tela diz o que falta.
    """
    return db.flag_ativa(repo.FLAG)


def _identidade() -> tuple[str, str | None]:
    """(auth_user_id, secretaria_id) do usuário da sessão."""
    usuario = auth.usuario_logado() or {}
    return (str(usuario.get("auth_user_id") or ""),
            usuario.get("secretaria_id") or None)


def _moeda(valor) -> str:
    if valor in (None, ""):
        return "—"
    try:
        return planilha.formatar_moeda(float(Decimal(str(valor))))
    except (InvalidOperation, ValueError, TypeError):
        return "—"


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ir(tela: str, **estado) -> None:
    st.session_state[TELA] = tela
    for chave, valor in estado.items():
        st.session_state[chave] = valor


def render_precos() -> None:
    """Roteador do módulo. Uma tela por vez, estado na sessão."""
    components.render_page_header(
        "Pesquisa de Preços",
        "Formação do preço estimado a partir de fontes oficiais, com "
        "memória de cálculo auditável.",
        legacy_subheader="Pesquisa de Preços",
    )

    if not _exigir_sessao():
        return

    tela = st.session_state.get(TELA) or LISTA
    try:
        if tela == NOVA:
            _render_nova()
        elif tela == ITENS:
            _render_itens()
        elif tela == EXECUCAO:
            _render_execucao()
        elif tela == REVISAO:
            _render_revisao()
        elif tela == RESUMO:
            _render_resumo()
        else:
            _render_lista()
    except repo.SemSessao as erro:
        st.warning(str(erro))
    except db.ErroBanco as erro:
        st.error(str(erro))


def _exigir_sessao() -> bool:
    """
    Diz, em vez de esconder, quando falta autenticação.

    O repositório opera pelo JWT do usuário e recusa cair para a
    credencial de servidor — é o que faz o RLS provado na Fase 3 valer
    de fato. Sem sessão não há o que listar, e mostrar uma lista vazia
    faria parecer que não existe pesquisa nenhuma.
    """
    if db.cliente_do_usuario() is not None:
        return True
    st.info(
        "A Pesquisa de Preços opera com a sua identidade — é ela que o "
        "banco usa para decidir o que você alcança. Entre no sistema com "
        "sua conta para abrir o módulo."
    )
    components.render_guidance(
        "Esta tela não usa a credencial de servidor do aplicativo. Se ela "
        "usasse, as políticas de acesso do banco deixariam de ser "
        "avaliadas — e passariam a apenas parecer que protegem."
    )
    return False


# ---------------------------------------------------------------------------
# §29 — Lista de pesquisas
# ---------------------------------------------------------------------------
def _render_lista() -> None:
    components.render_section_heading(
        "Minhas pesquisas",
        "Cada linha é uma pesquisa de preços com histórico próprio.")

    esquerda, direita = st.columns([3, 1])
    with esquerda:
        recorte = st.radio(
            "Recorte", options=["Todas", *RECORTES],
            horizontal=True, key="precos_recorte",
            label_visibility="collapsed")
    with direita:
        if st.button("Nova pesquisa", type="primary",
                     use_container_width=True):
            _ir(NOVA, **{PESQUISA: None})
            st.rerun()

    pesquisas = repo.listar_pesquisas(limite=100)
    if recorte in RECORTES:
        estados_do_recorte = RECORTES[recorte]
        pesquisas = [p for p in pesquisas
                     if str(p.get("estado")) in estados_do_recorte]
    elif recorte == "Todas":
        # Arquivada não polui a visão padrão: ela tem recorte próprio.
        pesquisas = [p for p in pesquisas
                     if str(p.get("estado")) != EstadoPesquisa.ARQUIVADA.value]

    if not pesquisas:
        st.caption("Nenhuma pesquisa neste recorte.")
        return

    for linha in pesquisas:
        _linha_da_lista(linha)


def _linha_da_lista(linha: dict) -> None:
    pesquisa_id = str(linha.get("id"))
    estado = str(linha.get("estado") or "")
    colunas = st.columns([4, 2, 2, 2, 2])

    with colunas[0]:
        versao = int(linha.get("versao") or 1)
        sufixo = f" · revisão {versao}" if versao > 1 else ""
        st.markdown(
            f"**{html.escape(str(linha.get('nome') or 'Sem nome'))}**"
            f"{sufixo}")
        objeto = str(linha.get("objeto") or "")
        if objeto:
            st.caption(objeto[:120])
    with colunas[1]:
        st.caption("Situação")
        st.write(ROTULO_PESQUISA.get(estado, estado))
    with colunas[2]:
        st.caption("Processo")
        st.write("vinculada" if linha.get("processo_id") else "autônoma")
    with colunas[3]:
        st.caption("Valor estimado")
        st.write(_moeda(linha.get("valor_global")))
    with colunas[4]:
        if st.button("Abrir", key=f"abrir_{pesquisa_id}",
                     use_container_width=True):
            _ir(ITENS, **{PESQUISA: pesquisa_id})
            st.rerun()
        _acoes_da_linha(linha, pesquisa_id, estado)
    st.divider()


def _acoes_da_linha(linha: dict, pesquisa_id: str, estado: str) -> None:
    """
    Duplicar, vincular e arquivar (§29).

    **Exportar** não está aqui: é a Fase 6, e um botão que gerasse
    relatório antes dela entregaria menos do que parece entregar.

    **Excluir** não existe e não vai existir por esta tela. A 0021 não
    concede DELETE a ninguém, e o §29 manda analisar a política antes de
    apagar pesquisa auditável — arquivar é o caminho.
    """
    with st.expander("Mais ações"):
        if st.button("Duplicar", key=f"dup_{pesquisa_id}",
                     use_container_width=True,
                     help="Cria uma pesquisa NOVA com os mesmos itens e "
                          "nenhum preço — para repetir a coleta noutra "
                          "data-base."):
            novo = _duplicar(linha)
            if novo:
                _ir(ITENS, **{PESQUISA: novo})
                st.rerun()

        processo_atual = st.session_state.get("processo_id")
        ja_vinculada = bool(linha.get("processo_id"))
        if st.button("Vincular ao processo aberto",
                     key=f"vinc_{pesquisa_id}", use_container_width=True,
                     disabled=not processo_atual or ja_vinculada,
                     help=("Nenhum processo aberto nesta sessão."
                           if not processo_atual else
                           "Já vinculada." if ja_vinculada else
                           "A pesquisa autônoma passa a pertencer ao "
                           "processo aberto.")):
            repo.atualizar_pesquisa(pesquisa_id, processo_id=processo_atual)
            st.rerun()

        if st.button("Arquivar", key=f"arq_{pesquisa_id}",
                     use_container_width=True,
                     disabled=estado == EstadoPesquisa.ARQUIVADA.value,
                     help="Arquivar não apaga: a pesquisa continua legível."):
            repo.mover_pesquisa(pesquisa_id, EstadoPesquisa.ARQUIVADA, estado)
            repo.registrar_evento(pesquisa_id, "pesquisa_arquivada")
            st.rerun()


def _duplicar(origem: dict) -> str | None:
    """
    Cópia para uma pesquisa NOVA — e não uma revisão.

    A diferença importa, e é a razão de as duas coisas coexistirem:
    `revisar()` cria outra versão da MESMA pesquisa lógica, para quando
    o resultado muda; duplicar cria outra pesquisa, com linhagem
    própria, para quando se repete a coleta no ano seguinte. Misturá-las
    faria o histórico de 2027 aparecer pendurado na pesquisa de 2026.

    Os PREÇOS não vêm junto, de propósito: eles são o que a nova coleta
    vai formar, e herdá-los daria a impressão de pesquisa já feita.
    """
    auth_user_id, secretaria_id = _identidade()
    if not auth_user_id:
        st.warning("Sua conta precisa estar vinculada ao Supabase Auth "
                   "para criar uma pesquisa.")
        return None

    completa = repo.obter_pesquisa(str(origem["id"]))
    if not completa:
        return None

    copia = repo.criar_pesquisa(
        f"{completa.get('nome') or 'Pesquisa'} (cópia)",
        auth_user_id=auth_user_id, secretaria_id=secretaria_id,
        objeto=str(completa.get("objeto") or ""),
        responsavel=str(completa.get("responsavel") or ""),
        local_referencia=str(completa.get("local_referencia") or ""),
        perfil_normativo=str(completa.get("perfil_normativo") or "lei_14133"),
        filtros=dict(completa.get("filtros") or {}),
    )
    itens = repo.listar_itens(str(origem["id"]))
    if itens:
        repo.salvar_itens(str(copia["id"]), [{
            "numero": item.get("numero"),
            "codigo": item.get("codigo"),
            "tipo_catalogo": item.get("tipo_catalogo"),
            "descricao": item.get("descricao"),
            "unidade": item.get("unidade"),
            "quantidade": item.get("quantidade"),
        } for item in itens])
    repo.registrar_evento(
        str(copia["id"]), "pesquisa_criada", ator=auth_user_id,
        descricao=f"duplicada de {origem.get('nome')}",
        payload={"origem": str(origem["id"])})
    return str(copia["id"])


# ---------------------------------------------------------------------------
# §18 Etapa 1 — Identificação
# ---------------------------------------------------------------------------
def _render_nova() -> None:
    components.render_section_heading(
        "Nova pesquisa",
        "A identificação vai para o relatório e sustenta a decisão meses "
        "depois.")

    auth_user_id, secretaria_id = _identidade()
    if not auth_user_id:
        st.warning(
            "Sua conta ainda não está vinculada ao Supabase Auth. A "
            "pesquisa precisa de um autor identificado para ser criada.")
        if st.button("Voltar"):
            _ir(LISTA)
            st.rerun()
        return

    processo_atual = st.session_state.get("processo_id")

    with st.form("precos_nova"):
        nome = st.text_input("Nome da pesquisa *",
                             placeholder="Aquisição de material de expediente")
        objeto = st.text_area("Objeto", height=80)
        colunas = st.columns(2)
        with colunas[0]:
            responsavel = st.text_input("Responsável")
            local = st.text_input("Local de referência",
                                  placeholder="Paragominas/PA")
        with colunas[1]:
            data_base = st.date_input("Data-base", value=date.today())
            perfil_id = st.selectbox(
                "Perfil normativo",
                options=list(perfil.PERFIS),
                format_func=lambda p: perfil.PERFIS[p].nome)
        vincular = st.checkbox(
            "Vincular ao processo aberto nesta sessão",
            value=bool(processo_atual), disabled=not processo_atual,
            help=("Nenhum processo aberto nesta sessão."
                  if not processo_atual else
                  "A pesquisa pode nascer autônoma e ser vinculada depois."))
        enviado = st.form_submit_button("Criar pesquisa", type="primary")

    st.caption(
        "O perfil escolhido fica gravado na pesquisa: o relatório precisa "
        "dizer sob qual regra o valor foi formado. A IN 65/2021 não é "
        "norma municipal automática — só a adote se o seu ente a adotar.")

    if enviado:
        if not nome.strip():
            st.error("A pesquisa precisa de um nome.")
            return
        criada = repo.criar_pesquisa(
            nome.strip(), auth_user_id=auth_user_id,
            secretaria_id=secretaria_id,
            processo_id=processo_atual if vincular else None,
            objeto=objeto.strip(), responsavel=responsavel.strip(),
            local_referencia=local.strip(), data_base=data_base,
            perfil_normativo=perfil_id,
            filtros={"janela_dias": execucao.JANELA_PADRAO_DIAS},
        )
        repo.registrar_evento(
            str(criada["id"]), "pesquisa_criada",
            ator=auth_user_id, descricao=nome.strip())
        _ir(ITENS, **{PESQUISA: str(criada["id"])})
        st.rerun()

    if st.button("Voltar para a lista"):
        _ir(LISTA)
        st.rerun()


# ---------------------------------------------------------------------------
# §18 Etapa 2 — Itens
# ---------------------------------------------------------------------------
def _pesquisa_atual() -> dict | None:
    pesquisa_id = st.session_state.get(PESQUISA)
    if not pesquisa_id:
        return None
    return repo.obter_pesquisa(str(pesquisa_id))


def _cabecalho_da_pesquisa(pesquisa: dict) -> None:
    estado = str(pesquisa.get("estado") or "")
    perfil_do_banco = perfil.obter(pesquisa.get("perfil_normativo"))
    colunas = st.columns([5, 2, 2])
    with colunas[0]:
        versao = int(pesquisa.get("versao") or 1)
        st.markdown(
            f"### {html.escape(str(pesquisa.get('nome') or 'Sem nome'))}"
            + (f"  ·  revisão {versao}" if versao > 1 else ""))
        st.caption(f"Perfil: {perfil_do_banco.nome}")
    with colunas[1]:
        st.metric("Situação", ROTULO_PESQUISA.get(estado, estado))
    with colunas[2]:
        st.metric("Valor estimado", _moeda(pesquisa.get("valor_global")))


def _render_itens() -> None:
    pesquisa = _pesquisa_atual()
    if not pesquisa:
        _ir(LISTA)
        st.rerun()
        return

    _cabecalho_da_pesquisa(pesquisa)
    itens = repo.listar_itens(str(pesquisa["id"]))
    _barra_de_navegacao(pesquisa, itens)

    components.render_section_heading(
        "Itens da contratação",
        "Um item por linha. Código CATMAT/CATSER é bem-vindo quando existe "
        "— e nunca obrigatório.")

    _render_importacao(pesquisa, itens)

    if itens:
        _render_tabela_de_itens(pesquisa, itens)
    else:
        st.caption("Nenhum item ainda. Importe do processo, de uma planilha, "
                   "ou digite abaixo.")

    _render_editor_de_itens(pesquisa, itens)


def _render_importacao(pesquisa: dict, itens: list[dict]) -> None:
    """
    §17-C: importar do processo aberto ou de XLSX.

    Reusa `planilha.importar_de_xlsx` — a estrutura canônica do item já
    existe no projeto, e criar um segundo formato incompatível é
    exatamente o que o prompt proíbe.
    """
    do_processo, do_arquivo = st.columns(2)

    with do_processo:
        da_sessao = (st.session_state.get("dados") or {}).get("itens") or []
        validos = [i for i in da_sessao if planilha.item_valido(i)]
        if st.button(
                f"Importar {len(validos)} item(ns) do processo aberto",
                disabled=not validos, use_container_width=True,
                help=("Nenhum item válido na planilha desta sessão."
                      if not validos else
                      "Traz código, descrição, unidade e quantidade.")):
            _salvar_importados(pesquisa, validos)
            st.rerun()

    with do_arquivo:
        arquivo = st.file_uploader(
            "Importar planilha (XLSX)", type=["xlsx"],
            key=f"precos_xlsx_{pesquisa['id']}")
        if arquivo is not None:
            try:
                lidos = planilha.importar_de_xlsx(arquivo.getvalue())
            except Exception as erro:  # noqa: BLE001 — arquivo é entrada do usuário
                st.error(f"Não foi possível ler a planilha: {erro}")
            else:
                validos = [i for i in lidos if planilha.item_valido(i)]
                st.caption(f"{len(validos)} item(ns) válido(s) na planilha.")
                if validos and st.button("Confirmar importação",
                                         use_container_width=True):
                    _salvar_importados(pesquisa, validos)
                    st.rerun()


def _salvar_importados(pesquisa: dict, itens_canonicos: list[dict]) -> None:
    """
    Grava os itens importados.

    A numeração é a POSIÇÃO na planilha, e é ela a chave (pesquisa,
    número): importar a mesma planilha duas vezes atualiza os mesmos 210
    itens em vez de criar 420. O `valor_unitario` da origem é ignorado
    de propósito — é justamente ele que a pesquisa vai formar.
    """
    registros = []
    for posicao, item in enumerate(itens_canonicos, start=1):
        registros.append({
            "numero": posicao,
            "codigo": str(item.get("codigo") or "").strip() or None,
            "descricao": str(item.get("descricao") or "").strip(),
            "unidade": str(item.get("unidade") or "").strip(),
            "quantidade": item.get("quantidade"),
        })
    repo.salvar_itens(str(pesquisa["id"]), registros)


def _render_tabela_de_itens(pesquisa: dict, itens: list[dict]) -> None:
    """A tabela do §18, com o estado e o preço de cada item."""
    for item in itens:
        estado = str(item.get("estado") or EstadoItem.PENDENTE.value)
        colunas = st.columns([1, 4, 1, 1, 2, 2, 2])
        colunas[0].markdown(f"**{int(item.get('numero') or 0):02d}**")
        with colunas[1]:
            st.write(str(item.get("descricao") or ""))
            if item.get("codigo"):
                st.caption(f"{item.get('tipo_catalogo') or 'código'} "
                           f"{item.get('codigo')}")
        colunas[2].write(str(item.get("unidade") or "—"))
        colunas[3].write(_texto_quantidade(item.get("quantidade")))
        colunas[4].write(ROTULO_ITEM.get(estado, estado))
        colunas[5].write(_moeda(item.get("preco_estimado")))
        with colunas[6]:
            revisavel = estado in (
                EstadoItem.EM_REVISAO.value, EstadoItem.COMPLETO.value,
                EstadoItem.INCOMPLETO.value)
            if st.button("Revisar", key=f"rev_{item['id']}",
                         disabled=not revisavel, use_container_width=True,
                         help=("Disponível depois que a pesquisa deste item "
                               "rodar." if not revisavel else
                               "Abrir a cesta e a memória de cálculo.")):
                _ir(REVISAO, **{ITEM: str(item["id"])})
                st.rerun()


def _texto_quantidade(valor) -> str:
    numero = _decimal(valor)
    if numero is None:
        return "—"
    inteiro = numero.to_integral_value()
    return f"{inteiro:,.0f}".replace(",", ".") if numero == inteiro \
        else f"{numero:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _render_editor_de_itens(pesquisa: dict, itens: list[dict]) -> None:
    """
    Edição manual, com a mesma linguagem do editor da planilha do wizard.

    Não há botão "Remover" com exclusão física: a numeração é chave, e
    apagar item que já tem referências coletadas destruiria evidência.
    Item que não deve ser pesquisado fica de fora da fila pelo estado.
    """
    with st.expander("Adicionar ou corrigir itens"):
        base = [{
            "numero": int(i.get("numero") or 0),
            "codigo": str(i.get("codigo") or ""),
            "descricao": str(i.get("descricao") or ""),
            "unidade": str(i.get("unidade") or ""),
            "quantidade": float(_decimal(i.get("quantidade")) or 0),
        } for i in itens] or [{
            "numero": 1, "codigo": "", "descricao": "",
            "unidade": "", "quantidade": 0.0}]

        editado = st.data_editor(
            base, key=f"precos_editor_{pesquisa['id']}_{len(itens)}",
            num_rows="dynamic", use_container_width=True,
            column_config={
                "numero": st.column_config.NumberColumn(
                    "Item", min_value=1, step=1, format="%d"),
                "codigo": st.column_config.TextColumn(
                    "CATMAT/CATSER", width="small",
                    help="Opcional. Quando existe, melhora muito o "
                         "casamento — mas a pesquisa roda sem ele."),
                "descricao": st.column_config.TextColumn(
                    "Descrição", width="large"),
                "unidade": st.column_config.TextColumn(
                    "Unidade", width="small"),
                "quantidade": st.column_config.NumberColumn(
                    "Quantidade", min_value=0.0, step=1.0, format="%.2f"),
            })
        linhas = (editado.to_dict("records") if hasattr(editado, "to_dict")
                  else list(editado))

        if st.button("Salvar itens", type="primary"):
            validos = [linha for linha in linhas
                       if str(linha.get("descricao") or "").strip()]
            if not validos:
                st.error("Um item precisa, no mínimo, de descrição.")
                return
            repo.salvar_itens(str(pesquisa["id"]), [{
                "numero": int(linha.get("numero") or posicao),
                "codigo": str(linha.get("codigo") or "").strip() or None,
                "descricao": str(linha.get("descricao") or "").strip(),
                "unidade": str(linha.get("unidade") or "").strip(),
                "quantidade": linha.get("quantidade"),
            } for posicao, linha in enumerate(validos, start=1)])
            st.rerun()


def _barra_de_navegacao(pesquisa: dict, itens: list[dict]) -> None:
    """Ações da pesquisa, sempre visíveis, com o progresso ao lado."""
    progresso = execucao.progresso_de(itens)
    estado = str(pesquisa.get("estado") or "")
    encerrada = estado in (EstadoPesquisa.ARQUIVADA.value,
                           EstadoPesquisa.APLICADA.value)

    colunas = st.columns([2, 2, 2, 2, 2])
    with colunas[0]:
        if st.button("← Lista", use_container_width=True):
            _ir(LISTA, **{PESQUISA: None})
            st.rerun()
    with colunas[1]:
        if st.button("Itens", use_container_width=True,
                     disabled=st.session_state.get(TELA) == ITENS):
            _ir(ITENS)
            st.rerun()
    with colunas[2]:
        pode_pesquisar = bool(itens) and not encerrada
        if st.button("Pesquisar preços", type="primary",
                     use_container_width=True, disabled=not pode_pesquisar,
                     help=("Adicione itens antes de pesquisar."
                           if not itens else
                           "Roda em lotes: a tela continua respondendo.")):
            _iniciar_execucao(pesquisa, itens)
            st.rerun()
    with colunas[3]:
        if st.button("Resumo", use_container_width=True, disabled=not itens):
            _ir(RESUMO)
            st.rerun()
    with colunas[4]:
        st.caption("Progresso")
        st.write(progresso.resumo())


def _iniciar_execucao(pesquisa: dict, itens: list[dict]) -> None:
    """Leva a pesquisa para a fila e abre a tela de execução."""
    estado = str(pesquisa.get("estado") or EstadoPesquisa.RASCUNHO.value)
    if estado != EstadoPesquisa.NA_FILA.value:
        repo.mover_pesquisa(str(pesquisa["id"]), EstadoPesquisa.NA_FILA,
                            estado)
    st.session_state[RELATO] = []
    _ir(EXECUCAO)


# ---------------------------------------------------------------------------
# §19 — Pesquisa automática em lotes reentrantes
# ---------------------------------------------------------------------------
def _render_execucao() -> None:
    """
    Um lote por script run, e o navegador respira entre eles.

    O §46 proíbe congelar a interface, e a Fase 0 registrou que este
    projeto não tem infraestrutura de jobs. A saída escolhida é
    reentrância: processa N itens, grava, chama `st.rerun()`. O
    progresso vem do BANCO, então fechar a aba não perde nada — reabrir
    a pesquisa continua de onde parou.
    """
    pesquisa = _pesquisa_atual()
    if not pesquisa:
        _ir(LISTA)
        st.rerun()
        return

    _cabecalho_da_pesquisa(pesquisa)
    itens = repo.listar_itens(str(pesquisa["id"]))
    progresso = execucao.progresso_de(itens)

    components.render_section_heading(
        "Pesquisando preços",
        "O motor consulta as fontes oficiais, normaliza a unidade e monta "
        "a cesta. Nada é inventado para completar a amostra.")

    # A participação da IA é declarada ANTES da busca, não descoberta
    # depois. Prometer "pesquisa com IA" e rodar determinístico seria a
    # mentira mais fácil de contar aqui — e a mais difícil de o servidor
    # detectar, porque o resultado tem a mesma cara.
    if _motor_semantico() is not None:
        st.caption(
            "Camada semântica ATIVA: a IA sugere termos equivalentes para "
            "ampliar a busca, e só isso. Ela não informa preço, não "
            "pontua referência e não calcula estatística — quem faz isso é "
            "o motor determinístico, com ou sem ela.")
    else:
        st.caption(
            "Camada semântica INDISPONÍVEL (sem motor de IA configurado). "
            "A pesquisa roda determinística: busca por descrição e por "
            "CATMAT/CATSER, matching e estatística iguais. O que se perde "
            "são sugestões de sinônimo para ampliar a busca.")

    st.progress(progresso.fracao, text=progresso.resumo())

    cancelar, continuar = st.columns([1, 1])
    with cancelar:
        parar = st.button("Interromper", use_container_width=True,
                          help="O que já foi pesquisado fica salvo.")
    with continuar:
        st.caption(
            f"Lotes de {execucao.LOTE_PADRAO} itens. Você pode fechar esta "
            "aba: a pesquisa retoma de onde parou.")

    for linha in st.session_state.get(RELATO) or []:
        st.text(linha)

    if parar:
        _encerrar_execucao(pesquisa, itens, interrompida=True)
        st.rerun()
        return

    if progresso.terminou:
        _encerrar_execucao(pesquisa, itens)
        st.rerun()
        return

    estado = str(pesquisa.get("estado") or "")
    if estado == EstadoPesquisa.NA_FILA.value:
        repo.mover_pesquisa(str(pesquisa["id"]), EstadoPesquisa.EXECUTANDO,
                            estado)

    with st.spinner("Consultando fontes oficiais…"):
        _, relato = execucao.executar_lote(
            pesquisa, itens, _fontes(), repo,
            perfil=perfil.obter(pesquisa.get("perfil_normativo")),
            motor_semantico=_motor_semantico())

    acumulado = list(st.session_state.get(RELATO) or [])
    st.session_state[RELATO] = (acumulado + relato)[-40:]
    st.rerun()


def _motor_semantico():
    """
    O motor de IA da rodada — `None` quando não há credencial.

    Injetável para que as provas exercitem o caminho com dublê. Sem
    credencial devolve `None`, e o pipeline roda determinístico: a tela
    diz isso em vez de fingir que a IA participou.
    """
    return precos_semantica.motor_do_projeto()


def _fontes():
    """
    As fontes da rodada.

    Função à parte para que o teste possa trocá-las por dublês sem
    tocar na tela — e para deixar num lugar só a decisão de quais fontes
    entram, que o §12 governa.
    """
    from ..precos import fontes_padrao

    return fontes_padrao()


def _encerrar_execucao(pesquisa: dict, itens: list[dict], *,
                       interrompida: bool = False) -> None:
    """
    Fecha a rodada movendo a pesquisa para o estado que os ITENS dizem.

    Interromper não é um estado próprio: é parar de enfileirar. O que já
    rodou continua valendo, e o que não rodou volta na próxima vez — que
    é exatamente o comportamento do §19 para cancelamento com retomada.
    """
    destino = execucao.estado_apos_lote(itens)
    if interrompida and destino is EstadoPesquisa.EXECUTANDO:
        # Ainda há itens na fila; sem uma rodada em curso, o retrato
        # honesto é "com pendências", não "pesquisando".
        destino = EstadoPesquisa.PARCIAL
    atual = str(pesquisa.get("estado") or "")
    try:
        repo.mover_pesquisa(str(pesquisa["id"]), destino, atual)
    except Exception:  # noqa: BLE001 — transição inválida não perde o trabalho
        pass
    repo.registrar_evento(
        str(pesquisa["id"]),
        "busca_falhou" if destino is EstadoPesquisa.FALHOU
        else "busca_concluida",
        automatico=True,
        descricao="interrompida pelo usuário" if interrompida else "",
        idempotency_key=f"rodada:{pesquisa['id']}:{destino.value}")
    _ir(ITENS)


# ---------------------------------------------------------------------------
# §20–§24 — Revisão por item
# ---------------------------------------------------------------------------
def _render_revisao() -> None:
    pesquisa = _pesquisa_atual()
    item_id = st.session_state.get(ITEM)
    if not pesquisa or not item_id:
        _ir(ITENS)
        st.rerun()
        return

    itens = repo.listar_itens(str(pesquisa["id"]))
    item = next((i for i in itens if str(i.get("id")) == str(item_id)), None)
    if item is None:
        _ir(ITENS)
        st.rerun()
        return

    _cabecalho_do_item(pesquisa, item)

    referencias = repo.listar_referencias(str(item["id"]))
    _render_govbot(orientacao.do_item(
        item, referencias, perfil.obter(pesquisa.get("perfil_normativo"))))
    _render_explicacao(item, referencias)
    _render_painel_estatistico(pesquisa, item, referencias)
    escolhidos = _render_filtros(referencias)
    _render_resultados(item, referencias, escolhidos)
    _render_encerramento_do_item(item)


def _cabecalho_do_item(pesquisa: dict, item: dict) -> None:
    if st.button("← Voltar aos itens"):
        _ir(ITENS, **{ITEM: None})
        st.rerun()

    components.render_section_heading(
        f"Item {int(item.get('numero') or 0):02d} — "
        f"{str(item.get('descricao') or '')}",
        f"Quantidade: {_texto_quantidade(item.get('quantidade'))}  ·  "
        f"Unidade: {item.get('unidade') or '—'}")


def _render_govbot(orientacoes: list[orientacao.Orientacao]) -> None:
    """
    §28 — a orientação do GovBot, com a severidade traduzida em componente.

    Duas escolhas que valem registro:

    **Nada aqui vem de modelo de linguagem.** As três mensagens que o §28
    exemplifica são leitura do que o motor já calculou; gerá-las com IA
    seria pagar latência e risco de invenção para dizer um número que já
    está na mesa. Consequência prática: o painel continua funcionando com
    a IA fora do ar.

    **A severidade escolhe o componente, e a ordem vem do módulo.** Com
    210 itens, `st.error` para o que impede e `st.info` para o que apenas
    informa é o que evita que o aviso decisivo se perca no meio da lista.
    """
    if not orientacoes:
        return
    with st.expander(f"GovBot — {len(orientacoes)} observação(ões)",
                     expanded=any(o.severidade == orientacao.IMPEDE
                                  for o in orientacoes)):
        for aviso in orientacoes:
            texto = f"{aviso.prefixo} {aviso.texto}"
            if aviso.severidade == orientacao.IMPEDE:
                st.error(texto)
            elif aviso.severidade == orientacao.CONFIRA:
                st.warning(texto)
            else:
                st.info(texto)
            st.caption(f"Base do aviso: {aviso.origem}")


def _render_explicacao(item: dict, referencias: list[dict]) -> None:
    """
    §21 — a explicação acima da lista, e os descartados NUNCA escondidos.
    """
    contagem = filtros_mod.contar_por_status(referencias)
    na_cesta = contagem.get("selected", 0)
    st.markdown(
        f"O motor analisou **{len(referencias)}** referência(s) e levou "
        f"**{na_cesta}** para a cesta, por comparabilidade e prioridade "
        "normativa da fonte — nunca por preço.")

    fora = len(referencias) - na_cesta
    if fora:
        st.caption(
            f"As outras {fora} continuam listadas abaixo, com o motivo de "
            "cada uma. Nenhuma foi apagada.")

    selecionada = next((r for r in referencias
                        if str(r.get("status")) == "selected"
                        and r.get("fatores")), None)
    if selecionada:
        with st.expander("Critérios considerados"):
            st.caption(
                "Fatores da referência mais bem colocada. O total é "
                "identidade × circunstâncias: produto diferente zera a "
                "nota por melhor que seja o resto.")
            for fator in selecionada.get("fatores") or []:
                marca = "✓" if fator.get("conforme") else "!"
                st.write(f"{marca} {fator.get('explicacao', '')}")


def _render_painel_estatistico(pesquisa: dict, item: dict,
                               referencias: list[dict]) -> None:
    """§22 — o painel, e a troca de método com justificativa."""
    memoria = item.get("estatisticas") or {}
    estatisticas = memoria.get("estatisticas") or {}

    if estatisticas:
        colunas = st.columns(6)
        colunas[0].metric("Válidos", estatisticas.get("quantidade", 0))
        colunas[1].metric("Menor", _moeda(estatisticas.get("menor")))
        colunas[2].metric("Média", _moeda(estatisticas.get("media")))
        colunas[3].metric("Mediana", _moeda(estatisticas.get("mediana")))
        colunas[4].metric("Maior", _moeda(estatisticas.get("maior")))
        cv = _decimal(estatisticas.get("coeficiente_variacao"))
        colunas[5].metric("CV", f"{cv:.2f}" if cv is not None else "—")

    resumo = st.columns([2, 2, 3])
    resumo[0].metric("Método", str(item.get("metodo") or "—"))
    resumo[1].metric("Preço estimado", _moeda(item.get("preco_estimado")))
    resumo[2].metric("Total do item", _moeda(item.get("preco_total")))

    if item.get("justificativa"):
        with st.expander("Memória de cálculo"):
            st.text(str(item.get("justificativa")))

    _render_anomalias(memoria)


def _render_anomalias(memoria: dict) -> None:
    """
    §23 — sinaliza sem julgar.

    O texto diz a distância da mediana e sugere revisão. Não diz "preço
    inexequível" nem "preço ilegal": uma fórmula estatística não produz
    conclusão jurídica, e escrever isso na tela transformaria um sinal
    em acusação.
    """
    anomalias = memoria.get("anomalias") or []
    if not anomalias:
        return
    st.warning(
        f"{len(anomalias)} candidato(s) discrepante(s) sinalizado(s). "
        "Nenhum foi excluído automaticamente — quem decide é você.")
    for anomalia in anomalias:
        st.caption(f"⚠ {_moeda(anomalia.get('valor'))} — "
                   f"{anomalia.get('motivo', '')} "
                   f"(critério {anomalia.get('criterio', '')})")


def _render_filtros(referencias: list[dict]) -> filtros_mod.Filtros:
    """§20 — os filtros. Escondem; nunca apagam."""
    contagem = filtros_mod.contar_por_status(referencias)
    with st.expander(
            f"Filtros  ·  {contagem.get('selected', 0)} na cesta, "
            f"{contagem.get('rejected', 0)} excluída(s), "
            f"{contagem.get('manual_review', 0)} abaixo do piso"):
        linha1 = st.columns(4)
        fontes = dict(filtros_mod.fontes_presentes(referencias))
        escolhidas = linha1[0].multiselect(
            "Fonte", options=list(fontes), format_func=lambda f: fontes[f])
        status = linha1[1].multiselect(
            "Situação", options=list(ROTULO_STATUS),
            format_func=lambda s: ROTULO_STATUS[s])
        uf = linha1[2].selectbox(
            "UF", options=["", *filtros_mod.ufs_presentes(referencias)])
        unidade = linha1[3].selectbox(
            "Unidade", options=["", *filtros_mod.unidades_presentes(referencias)])

        linha2 = st.columns(4)
        desde = linha2[0].date_input("Desde", value=None)
        ate = linha2[1].date_input("Até", value=None)
        tipo = linha2[2].selectbox("Catálogo", options=["", "CATMAT", "CATSER"])
        alta = linha2[3].checkbox(
            "Somente alta compatibilidade",
            help=f"Score ≥ {filtros_mod.ALTA_COMPATIBILIDADE:.0%}.")

        texto = st.text_input("Buscar na descrição, órgão, fornecedor ou marca")

    return filtros_mod.Filtros(
        fontes=set(escolhidas), status=set(status), uf=uf or "",
        unidade=unidade or "", tipo_catalogo=tipo or "",
        desde=desde or None, ate=ate or None,
        somente_alta_compatibilidade=bool(alta), texto=texto or "")


def _render_resultados(item: dict, referencias: list[dict],
                       escolhidos: filtros_mod.Filtros) -> None:
    """A lista do §20 com o detalhe do §24 em cada linha."""
    visiveis = filtros_mod.aplicar(referencias, escolhidos)
    if escolhidos.algum:
        st.caption(f"{len(visiveis)} de {len(referencias)} referência(s) "
                   "visíveis com os filtros atuais.")
    if not visiveis:
        st.caption("Nenhuma referência atende aos filtros escolhidos.")
        return

    for linha in visiveis:
        _render_referencia(item, linha)


def _render_referencia(item: dict, linha: dict) -> None:
    status = str(linha.get("status") or "")
    na_cesta = status == "selected"
    score = _decimal(linha.get("score"))
    percentual = f"{score:.0%}" if score is not None else "—"

    colunas = st.columns([6, 2, 2, 2])
    with colunas[0]:
        marca = "✓" if na_cesta else "○"
        st.markdown(f"{marca} **{html.escape(str(linha.get('descricao_original') or ''))[:140]}**")
        st.caption(
            " · ".join(p for p in (
                str(linha.get("orgao") or ""),
                str(linha.get("uf") or ""),
                str(linha.get("data_resultado") or linha.get("data_compra") or ""),
                str(linha.get("fonte_nome") or ""),
            ) if p))
    colunas[1].metric("Unitário", _moeda(
        linha.get("valor_unitario_normalizado")
        or linha.get("valor_unitario_original")))
    colunas[2].metric("Compatível", percentual)
    with colunas[3]:
        st.caption(ROTULO_STATUS.get(status, status))
        rotulo = "Excluir da cesta" if na_cesta else "Usar na cesta"
        if st.button(rotulo, key=f"cesta_{linha['id']}",
                     use_container_width=True):
            st.session_state[f"motivo_aberto_{linha['id']}"] = True

    if st.session_state.get(f"motivo_aberto_{linha['id']}"):
        _render_motivo(item, linha, na_cesta)

    with st.expander("Ver detalhes"):
        _render_detalhe(linha)


def _render_motivo(item: dict, linha: dict, na_cesta: bool) -> None:
    """
    Incluir e excluir exigem MOTIVO.

    A 0021 não concede DELETE a ninguém: tirar da cesta é mudar status.
    Sem motivo registrado a mudança seria exclusão silenciosa com outro
    nome — e é justamente isso que precisa aparecer no relatório.
    """
    with st.form(f"motivo_{linha['id']}"):
        motivo = st.text_input(
            "Motivo (obrigatório)",
            placeholder="fora da curva; quantidade muito diferente; "
                        "unidade não comparável…")
        confirmar = st.form_submit_button("Confirmar")
    if not confirmar:
        return
    if not motivo.strip():
        st.error("Registre o motivo: ele vai para a memória de cálculo.")
        return
    repo.reclassificar_referencia(
        str(linha["id"]), "rejected" if na_cesta else "selected",
        motivo.strip())
    repo.registrar_evento(
        str(st.session_state.get(PESQUISA)),
        "referencia_excluida" if na_cesta else "referencia_incluida",
        item_id=str(item["id"]), descricao=motivo.strip(),
        payload={"referencia": str(linha["id"])})
    st.session_state[f"motivo_aberto_{linha['id']}"] = False
    st.rerun()


def _render_detalhe(linha: dict) -> None:
    """§24 — tudo o que sustenta a referência, inclusive a evidência."""
    esquerda, direita = st.columns(2)
    with esquerda:
        st.caption("O que a fonte informou")
        st.write(f"Preço original: {_moeda(linha.get('valor_unitario_original'))}")
        st.write(f"Unidade original: {linha.get('unidade_original') or '—'}")
        st.write(f"Quantidade: {_texto_quantidade(linha.get('quantidade_original'))}")
        st.write(f"Fornecedor: {linha.get('fornecedor') or '—'}")
        st.write(f"Marca: {linha.get('marca') or '—'}")
        st.write(f"Município: {linha.get('municipio') or '—'}")
    with direita:
        st.caption("O que o motor derivou com prova")
        st.write(f"Preço normalizado: "
                 f"{_moeda(linha.get('valor_unitario_normalizado'))}")
        st.write(f"Unidade normalizada: "
                 f"{linha.get('unidade_normalizada') or '—'}")
        catalogo = linha.get("codigo_catalogo")
        st.write(f"Catálogo: "
                 f"{(linha.get('tipo_catalogo') or '') + ' ' + catalogo if catalogo else '—'}")
        st.write(f"Identificador externo: {linha.get('id_externo') or '—'}")
        st.write(f"Referência oficial: {linha.get('referencia_externa') or '—'}")
        st.write(f"Captura: {linha.get('coletado_em') or '—'}")

    motivos = linha.get("motivos") or []
    if motivos:
        st.caption("Motivos registrados")
        for motivo in motivos:
            st.write(f"• {motivo}")

    fatores = linha.get("fatores") or []
    if fatores:
        st.caption("Composição do score")
        for fator in fatores:
            marca = "✓" if fator.get("conforme") else "!"
            st.write(f"{marca} {fator.get('nome')}: "
                     f"{fator.get('explicacao', '')}")

    st.caption(f"Impressão digital da evidência (sha256): "
               f"{str(linha.get('raw_hash') or '')[:16]}…")


def _render_encerramento_do_item(item: dict) -> None:
    """O ato humano que fecha o item — REVISÃO → CONCLUÍDO."""
    estado = str(item.get("estado") or "")
    if estado != EstadoItem.EM_REVISAO.value:
        st.caption(f"Situação do item: {ROTULO_ITEM.get(estado, estado)}.")
        return

    st.divider()
    with st.form(f"concluir_{item['id']}"):
        justificativa = st.text_area(
            "Observação do revisor (opcional)",
            help="Registre aqui por que aceitou a cesta como está — por "
                 "exemplo, ao manter um discrepante sinalizado.")
        concluir = st.form_submit_button("Concluir este item",
                                         type="primary")
    if concluir:
        repo.confirmar_item(str(item["id"]), atual=EstadoItem.EM_REVISAO,
                            justificativa=justificativa.strip())
        repo.registrar_evento(
            str(st.session_state.get(PESQUISA)), "item_concluido",
            item_id=str(item["id"]), descricao=justificativa.strip())
        _ir(ITENS, **{ITEM: None})
        st.rerun()


# ---------------------------------------------------------------------------
# §25 — Resultado global
# ---------------------------------------------------------------------------
def _render_resumo() -> None:
    pesquisa = _pesquisa_atual()
    if not pesquisa:
        _ir(LISTA)
        st.rerun()
        return

    _cabecalho_da_pesquisa(pesquisa)
    itens = repo.listar_itens(str(pesquisa["id"]))
    _barra_de_navegacao(pesquisa, itens)

    progresso = execucao.progresso_de(itens)
    total, sem_preco = _valor_global(itens)

    components.render_section_heading(
        "Resultado da pesquisa",
        "O valor global é a soma dos itens concluídos. Item sem preço não "
        "entra na conta — e aparece nomeado abaixo.")

    colunas = st.columns(4)
    colunas[0].metric("Itens", progresso.total)
    colunas[1].metric("Concluídos", progresso.concluidos)
    colunas[2].metric("Pendentes",
                      progresso.total - progresso.concluidos)
    colunas[3].metric("Valor global estimado", _moeda(total))

    if sem_preco:
        st.warning(
            f"{len(sem_preco)} item(ns) sem preço formado: "
            f"{', '.join(str(n) for n in sem_preco[:12])}"
            + (" …" if len(sem_preco) > 12 else "")
            + ". O valor global acima NÃO os inclui.")

    # O panorama vem antes da lista: com 210 itens, o servidor precisa
    # saber por onde começar, não rolar a tela até encontrar.
    _render_govbot(orientacao.da_pesquisa(pesquisa, itens))

    st.divider()
    for item in itens:
        estado = str(item.get("estado") or "")
        colunas = st.columns([1, 4, 1, 2, 2, 2])
        colunas[0].write(f"{int(item.get('numero') or 0):02d}")
        colunas[1].write(str(item.get("descricao") or ""))
        colunas[2].write(_texto_quantidade(item.get("quantidade")))
        colunas[3].write(str(item.get("metodo") or "—"))
        colunas[4].write(_moeda(item.get("preco_estimado")))
        colunas[5].write(ROTULO_ITEM.get(estado, estado))

    _render_acoes_do_resumo(pesquisa, progresso)


def _valor_global(itens: list[dict]) -> tuple[Decimal, list[int]]:
    """
    Soma os itens CONCLUÍDOS e devolve quem ficou de fora.

    Somar apenas o que está pronto e dizer quantos faltam é o oposto de
    somar tudo e apresentar um total que parece completo. O §25 pede a
    contagem de pendentes justamente para que o número não engane.
    """
    total = Decimal("0")
    sem_preco: list[int] = []
    for item in itens:
        valor = _decimal(item.get("preco_total"))
        concluido = str(item.get("estado")) == EstadoItem.COMPLETO.value
        if concluido and valor is not None:
            total += valor
        else:
            sem_preco.append(int(item.get("numero") or 0))
    return total, sem_preco


def _render_acoes_do_resumo(pesquisa: dict,
                            progresso: execucao.Progresso) -> None:
    estado = str(pesquisa.get("estado") or "")
    st.divider()
    concluir, revisar, arquivar = st.columns(3)

    with concluir:
        pode = (estado == EstadoPesquisa.EM_REVISAO.value
                and progresso.concluidos == progresso.total
                and progresso.total > 0)
        if st.button("Concluir pesquisa", type="primary",
                     use_container_width=True, disabled=not pode,
                     help=("Todos os itens precisam estar concluídos."
                           if not pode else
                           "Fecha a pesquisa para aplicação ao processo.")):
            repo.mover_pesquisa(str(pesquisa["id"]),
                                EstadoPesquisa.CONCLUIDA, estado)
            repo.registrar_evento(str(pesquisa["id"]), "pesquisa_concluida")
            st.rerun()

    with revisar:
        pode = estado not in (EstadoPesquisa.ARQUIVADA.value,
                              EstadoPesquisa.RASCUNHO.value)
        if st.button("Nova revisão", use_container_width=True,
                     disabled=not pode,
                     help="Cria uma revisão nova preservando esta na íntegra."):
            st.session_state["precos_revisar"] = True
        if st.session_state.get("precos_revisar"):
            with st.form("precos_motivo_revisao"):
                motivo = st.text_input("Motivo da revisão")
                confirmar = st.form_submit_button("Criar revisão")
            if confirmar:
                if not motivo.strip():
                    st.error("A revisão precisa de um motivo registrado.")
                else:
                    novo = repo.revisar(str(pesquisa["id"]), motivo.strip())
                    st.session_state["precos_revisar"] = False
                    _ir(ITENS, **{PESQUISA: str(novo)})
                    st.rerun()

    with arquivar:
        pode = estado != EstadoPesquisa.ARQUIVADA.value
        if st.button("Arquivar", use_container_width=True, disabled=not pode,
                     help="Arquivar não apaga: a pesquisa continua legível."):
            repo.mover_pesquisa(str(pesquisa["id"]),
                                EstadoPesquisa.ARQUIVADA, estado)
            repo.registrar_evento(str(pesquisa["id"]), "pesquisa_arquivada")
            _ir(LISTA, **{PESQUISA: None})
            st.rerun()

    _render_relatorios(pesquisa)
    _render_aplicacao(pesquisa)


# ---------------------------------------------------------------------------
# §31–§33 — relatórios e exportações
# ---------------------------------------------------------------------------
# Custo MEDIDO nesta máquina, com 30 referências por item (ver a seção da
# Fase 6 no relatório de auditoria). Serve para AVISAR antes do clique, e
# não para esconder o botão: uma pesquisa grande gera um relatório
# grande, e isso é a natureza da memória de cálculo, não um defeito.
_SEGUNDOS_POR_ITEM_NO_COMPLETO = 0.15
_ITENS_PARA_AVISAR = 30


def _render_relatorios(pesquisa: dict) -> None:
    """
    Os relatórios do §31 e §32, pelo motor institucional do §33.

    Nada é gerado ao desenhar a tela: cada formato sai por um clique, e o
    clique avisa antes quanto deve demorar. Gerar tudo a cada rerun
    tornaria a tela de resumo inutilizável numa pesquisa de 210 itens.
    """
    st.divider()
    components.render_section_heading(
        "Relatórios",
        "O relatório completo é a memória do ato: traz também o que foi "
        "descartado, e por quê.")

    itens = repo.listar_itens(str(pesquisa["id"]))
    if not itens:
        st.caption("Sem itens, não há o que relatar.")
        return

    referencias = {str(item["id"]): repo.listar_referencias(str(item["id"]))
                   for item in itens}
    identificador = relatorio.identificador_da_versao(
        pesquisa, itens, referencias)

    st.caption(
        f"Identificador desta versão do resultado: `{identificador[:16]}…` — "
        "o mesmo resultado gera sempre o mesmo identificador, "
        "independentemente da data de emissão.")

    if len(itens) >= _ITENS_PARA_AVISAR:
        demora = len(itens) * _SEGUNDOS_POR_ITEM_NO_COMPLETO
        st.info(
            f"Esta pesquisa tem {len(itens)} itens. O relatório completo "
            "inclui **todas** as referências, inclusive as descartadas — "
            f"a geração leva cerca de {demora:.0f} s e a tela fica "
            "aguardando. A memória analítica sai na hora e traz o mesmo "
            "conteúdo em formato conferível.")

    colunas = st.columns(4)
    with colunas[0]:
        _botao_de_download("Relatório completo (PDF)", pesquisa, itens,
                           referencias, formato="pdf", tipo="completo")
    with colunas[1]:
        _botao_de_download("Quadro resumido (PDF)", pesquisa, itens,
                           referencias, formato="pdf", tipo="resumido")
    with colunas[2]:
        _botao_de_download("Relatório completo (DOCX)", pesquisa, itens,
                           referencias, formato="docx", tipo="completo")
    with colunas[3]:
        _botao_de_download("Memória analítica (XLSX)", pesquisa, itens,
                           referencias, formato="xlsx", tipo="analitico")

    _botao_do_pacote(pesquisa, itens, referencias)


def _conteudo_do_relatorio(pesquisa: dict, itens: list[dict],
                           referencias: dict, *, formato: str,
                           tipo: str) -> tuple[bytes, str, str]:
    """
    Gera um formato. Devolve (bytes, nome do arquivo, mimetype).

    PDF e DOCX passam por `export.gerar_pdf`/`gerar_docx` — o motor
    institucional que já existe, com os estilos, as larguras de tabela e
    o gate de geometria provados. O §33 é explícito: nada de um segundo
    pipeline de PDF.
    """
    from .. import export

    if formato == "xlsx":
        return (relatorio.xlsx_analitico(pesquisa, itens, referencias),
                relatorio.nome_do_arquivo(pesquisa, "memoria-analitica",
                                          "xlsx"),
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet")

    if tipo == "resumido":
        markdown = relatorio.resumido(pesquisa, itens, referencias)
        titulo = "Pesquisa de Preços — Quadro Resumido"
    else:
        markdown = relatorio.completo(pesquisa, itens, referencias)
        titulo = "Relatório de Pesquisa de Preços"

    branding = st.session_state.get("branding") or None
    if formato == "docx":
        return (export.gerar_docx(titulo, markdown, branding),
                relatorio.nome_do_arquivo(pesquisa, tipo, "docx"),
                "application/vnd.openxmlformats-officedocument."
                "wordprocessingml.document")
    return (export.gerar_pdf(titulo, markdown, branding),
            relatorio.nome_do_arquivo(pesquisa, tipo, "pdf"),
            "application/pdf")


def _botao_de_download(rotulo: str, pesquisa: dict, itens: list[dict],
                       referencias: dict, *, formato: str,
                       tipo: str) -> None:
    """
    Gera sob demanda e entrega.

    `st.download_button` exige os bytes prontos, então a geração acontece
    no clique de um botão comum e o download aparece em seguida. É um
    passo a mais para o usuário, e é ele que impede a tela de gerar
    quatro documentos a cada rerun.
    """
    chave = f"precos_export_{tipo}_{formato}_{pesquisa['id']}"
    if st.button(rotulo, key=f"btn_{chave}", use_container_width=True):
        with st.spinner(f"Gerando {rotulo.lower()}…"):
            try:
                st.session_state[chave] = _conteudo_do_relatorio(
                    pesquisa, itens, referencias,
                    formato=formato, tipo=tipo)
            except Exception as erro:  # noqa: BLE001 — exportação não derruba a tela
                identificador = db.registrar_incidente(
                    erro, contexto="relatório da pesquisa de preços")
                st.error(
                    "Não foi possível gerar este relatório agora. "
                    f"Identificador para suporte: {identificador}")
                return

    pronto = st.session_state.get(chave)
    if pronto:
        conteudo, nome, mimetype = pronto
        st.download_button(f"Baixar {nome}", data=conteudo, file_name=nome,
                           mime=mimetype, key=f"dl_{chave}",
                           use_container_width=True)


def _botao_do_pacote(pesquisa: dict, itens: list[dict],
                     referencias: dict) -> None:
    """
    §33 — o pacote ZIP com tudo o que instrui o processo.

    Um arquivo só para anexar: relatório completo, quadro resumido e
    memória analítica. É o formato em que o servidor entrega a pesquisa
    a quem vai auditá-la.
    """
    chave = f"precos_pacote_{pesquisa['id']}"
    if st.button("Pacote completo (ZIP)", use_container_width=True,
                 help="Relatório completo em PDF, quadro resumido em PDF e "
                      "memória analítica em XLSX, num arquivo só."):
        with st.spinner("Montando o pacote…"):
            try:
                st.session_state[chave] = _montar_pacote(
                    pesquisa, itens, referencias)
            except Exception as erro:  # noqa: BLE001
                identificador = db.registrar_incidente(
                    erro, contexto="pacote da pesquisa de preços")
                st.error("Não foi possível montar o pacote agora. "
                         f"Identificador para suporte: {identificador}")
                return

    pronto = st.session_state.get(chave)
    if pronto:
        nome = relatorio.nome_do_arquivo(pesquisa, "pacote", "zip")
        st.download_button(f"Baixar {nome}", data=pronto, file_name=nome,
                           mime="application/zip", key=f"dl_{chave}",
                           use_container_width=True)


def montar_pacote(pesquisa: dict, itens: list[dict],
                  referencias: dict) -> bytes:
    """Público para que o teste monte o pacote sem passar pela tela."""
    return _montar_pacote(pesquisa, itens, referencias)


def _montar_pacote(pesquisa: dict, itens: list[dict],
                   referencias: dict) -> bytes:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for formato, tipo in (("pdf", "completo"), ("pdf", "resumido"),
                              ("xlsx", "analitico")):
            conteudo, nome, _ = _conteudo_do_relatorio(
                pesquisa, itens, referencias, formato=formato, tipo=tipo)
            zf.writestr(nome, conteudo)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# §26 — Aplicação ao processo
# ---------------------------------------------------------------------------
def _render_aplicacao(pesquisa: dict) -> None:
    """
    O diff vem ANTES. Sempre.

    O §26 é explícito: "não alterar documento silenciosamente". Aqui isso
    significa três coisas visíveis na tela antes de qualquer escrita: o
    preço de cada item antes e depois, o que a pesquisa NÃO cobre, e a
    lista nominal dos documentos que serão descartados.
    """
    st.divider()
    components.render_section_heading(
        "Aplicar ao processo",
        "O preço estimado passa a ser o valor da contratação — e é ele "
        "que vai para o DFD, o ETP, o TR e o edital.")

    impedimento = _impedimento_para_aplicar(pesquisa)
    if impedimento:
        st.info(impedimento)
        return

    dados = st.session_state.get("dados") or {}
    itens_pesquisa = repo.listar_itens(str(pesquisa["id"]))
    _, mudancas, recusas = aplicacao.aplicar(dados, pesquisa, itens_pesquisa)

    if not mudancas:
        st.warning(
            "Nenhum item da planilha do processo casou com um item "
            "concluído desta pesquisa. Nada seria alterado.")
        _render_recusas(recusas)
        return

    _render_diff(dados, mudancas, recusas)
    _render_confirmacao(pesquisa, itens_pesquisa)


def _impedimento_para_aplicar(pesquisa: dict) -> str:
    """
    Por que ainda não dá para aplicar — em texto, e não em botão cinza.

    Botão desabilitado sem explicação faz o servidor procurar o defeito
    no lugar errado.
    """
    estado = str(pesquisa.get("estado") or "")
    if estado == EstadoPesquisa.APLICADA.value:
        return ("Esta pesquisa já foi aplicada. Para mudar os preços do "
                "processo, crie uma revisão e aplique a revisão.")
    if estado == EstadoPesquisa.ARQUIVADA.value:
        return "Pesquisa arquivada não se aplica a processo."
    if estado != EstadoPesquisa.CONCLUIDA.value:
        return ("Conclua a pesquisa antes de aplicá-la. Enquanto houver "
                "item por revisar, o preço ainda não passou por decisão "
                "humana.")

    processo_da_pesquisa = pesquisa.get("processo_id")
    processo_aberto = st.session_state.get("processo_id")
    if not processo_da_pesquisa:
        return ("Esta pesquisa é autônoma. Vincule-a a um processo (na "
                "lista, em “Mais ações”) antes de aplicar.")
    if not processo_aberto:
        return ("Abra o processo vinculado a esta pesquisa para aplicar os "
                "preços — a aplicação escreve na planilha dele.")
    if str(processo_da_pesquisa) != str(processo_aberto):
        # A guarda que impede o pior erro possível desta tela: escrever
        # o preço na planilha de OUTRA contratação.
        return ("A pesquisa está vinculada a outro processo. Abra o "
                "processo correto antes de aplicar.")
    if not (st.session_state.get("dados") or {}).get("itens"):
        return "O processo aberto ainda não tem planilha de itens."
    return ""


def _render_diff(dados: dict, mudancas: list, recusas: list[str]) -> None:
    """O antes e o depois, item a item, no formato do §26."""
    atual = _decimal(dados.get("valor_estimado")) or Decimal("0")
    novo = aplicacao.valor_global_apos(dados, mudancas)

    colunas = st.columns(3)
    colunas[0].metric("Itens a atualizar", len(mudancas))
    colunas[1].metric("Valor global atual", _moeda(atual))
    colunas[2].metric("Valor global depois", _moeda(novo),
                      delta=_moeda(novo - atual))

    for mudanca in mudancas:
        linhas = st.columns([1, 4, 2, 2])
        linhas[0].write(f"{mudanca.posicao:02d}")
        linhas[1].write(mudanca.descricao[:70])
        linhas[2].write(f"Atual: {_moeda(mudanca.unitario_atual)}")
        linhas[3].write(f"Novo: {_moeda(mudanca.unitario_novo)}")
        for aviso in mudanca.avisos:
            st.caption(f"↳ {aviso}")

    _render_recusas(recusas)


def _render_recusas(recusas: list[str]) -> None:
    """
    O que a pesquisa NÃO cobre.

    Aparece com o mesmo destaque do que será alterado: "48 de 50 itens" é
    a informação que decide se vale aplicar agora ou terminar a pesquisa
    antes.
    """
    if not recusas:
        return
    with st.expander(f"{len(recusas)} item(ns) não serão alterados",
                     expanded=True):
        for recusa in recusas:
            st.write(f"• {recusa}")


def _render_confirmacao(pesquisa: dict, itens_pesquisa: list[dict]) -> None:
    """A confirmação, com a lista NOMINAL do que será descartado."""
    aprovados = sorted(st.session_state.get("aprovados") or set())
    documentos = sorted(st.session_state.get("documentos") or {})
    a_descartar = documentos or aprovados

    if a_descartar:
        st.warning(
            "Aplicar altera a planilha do Formulário Matriz. Pela regra do "
            "processo, os documentos gerados a partir dela ficam "
            "desatualizados e serão descartados para nova geração: "
            + ", ".join(d.upper() for d in a_descartar) + ".")
    else:
        st.caption("Nenhum documento gerado ainda — nada será descartado.")

    with st.form("precos_aplicar"):
        confirmado = st.checkbox(
            "Entendi que os documentos acima serão descartados e "
            "precisarão ser gerados novamente.",
            disabled=not a_descartar, value=not a_descartar)
        aplicar = st.form_submit_button("Aplicar preços ao processo",
                                        type="primary")
    if aplicar:
        if not confirmado:
            st.error("Confirme o descarte dos documentos para continuar.")
            return
        _aplicar_de_fato(pesquisa, itens_pesquisa)


def _aplicar_de_fato(pesquisa: dict, itens_pesquisa: list[dict]) -> None:
    """
    A escrita, na ordem que sobrevive a uma queda no meio.

    1. o processo é alterado e SALVO — sem isso, invalidar documentos
       deixaria o processo sem documento e sem preço novo;
    2. os documentos posteriores são invalidados pela regra que já
       existe em `state`, e não por uma cópia dela aqui;
    3. a pesquisa vira APLICADA e a trilha registra o ato.

    A trilha vem por último de propósito: ela descreve um ato consumado,
    e registrar antes deixaria a marca de algo que pode não ter
    acontecido.
    """
    from .. import state

    dados = st.session_state.get("dados") or {}
    novos_dados, mudancas, _ = aplicacao.aplicar(
        dados, pesquisa, itens_pesquisa)

    st.session_state["dados"] = novos_dados
    state.autosalvar()
    # A planilha vive no Formulário Matriz: mudá-la desatualiza toda a
    # cadeia documental. A cascata é a do `state`, com os instrumentos
    # derivados junto — não uma reimplementação daqui.
    state.invalidar_a_partir_de("formulario")

    estado = str(pesquisa.get("estado") or "")
    try:
        repo.mover_pesquisa(str(pesquisa["id"]), EstadoPesquisa.APLICADA,
                            estado)
    except Exception as erro:  # noqa: BLE001 — o processo já foi alterado
        st.warning(
            "Os preços foram aplicados ao processo, mas a pesquisa não "
            f"pôde ser marcada como aplicada: {erro}")

    repo.registrar_evento(
        str(pesquisa["id"]), "pesquisa_aplicada",
        item_id=None,
        descricao=f"{len(mudancas)} item(ns) atualizado(s)",
        payload={
            "processo": str(st.session_state.get("processo_id") or ""),
            "valor_global": str(novos_dados.get("valor_estimado")),
            "itens": [m.posicao for m in mudancas],
        },
        idempotency_key=f"aplicacao:{pesquisa['id']}")

    st.success(
        f"{len(mudancas)} item(ns) atualizado(s). Valor global do processo: "
        f"{_moeda(novos_dados.get('valor_estimado'))}. Os documentos "
        "precisam ser gerados novamente.")
    st.rerun()


# ---------------------------------------------------------------------------
# §30 — Card do dashboard
# ---------------------------------------------------------------------------
def render_card_dashboard() -> None:
    """
    Resumo do módulo para o painel do GovConnect.

    Falha em silêncio quando não há sessão ou banco: um card é
    informação lateral, e derrubar a página inicial por causa dele seria
    desproporcional. Quem precisa da explicação a recebe ao abrir o
    módulo.
    """
    if not disponivel():
        return
    try:
        pesquisas = repo.listar_pesquisas(limite=100)
    except (repo.SemSessao, db.ErroBanco):
        return

    em_andamento = [p for p in pesquisas if str(p.get("estado")) in
                    RECORTES["Em andamento"]]
    pendentes = [p for p in pesquisas if str(p.get("estado")) in
                 RECORTES["Com pendências"]]
    concluidas = [p for p in pesquisas if str(p.get("estado")) in
                  RECORTES["Concluídas"]]
    total = sum((_decimal(p.get("valor_global")) or Decimal("0"))
                for p in concluidas)

    components.render_section_heading("Pesquisa de Preços")
    colunas = st.columns(4)
    colunas[0].metric("Em andamento", len(em_andamento))
    colunas[1].metric("Com pendências", len(pendentes))
    colunas[2].metric("Concluídas", len(concluidas))
    colunas[3].metric("Valor pesquisado", _moeda(total))

    if pendentes:
        st.caption(
            f"{len(pendentes)} pesquisa(s) com item sem preço formado — "
            "elas precisam de decisão humana, não de nova rodada.")

    for pesquisa in pesquisas[:3]:
        st.caption(
            f"• {pesquisa.get('nome')} — "
            f"{ROTULO_PESQUISA.get(str(pesquisa.get('estado')), '')}")
