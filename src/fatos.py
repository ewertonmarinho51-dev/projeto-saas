"""
Fatos canônicos do processo (Fase 2 do pacote V5).

Extração DETERMINÍSTICA do Formulário Matriz para o registro canônico
(`fatos_canonicos`, migração 0009): objeto, natureza, SRP, execução,
prazo, valores e itens viram fatos versionados com fonte — a fonte da
verdade que os documentos passam a referenciar. Prosa (justificativa,
riscos, memorando) NÃO vira fato: fato é dado material.

Versionamento: mudou o valor no formulário ⇒ NOVA versão do fato
(status volta a 'extraido' — a confirmação anterior não vale para o
valor novo) e a versão anterior é marcada 'substituido'. Nada é
editado in-place (KQ-005).

Feature flag `flag_canonical_facts` (default OFF):
  - DESLIGADA: extração roda em SHADOW (log de fatos e divergências);
    nada persiste, nenhuma tela muda.
  - LIGADA: fatos sincronizados no banco e exibidos na tela final com
    pendências de confirmação e divergências documentais.
"""

import logging

import streamlit as st

from . import blocos, db, governanca, planilha

_log = logging.getLogger("govdocs.fatos")

NATUREZA_POR_EXECUCAO = {
    "Obra / serviço de engenharia": "OBRAS_ENGENHARIA",
    "Serviço de execução continuada": "SERVICOS",
    "Serviço por escopo (execução única)": "SERVICOS",
}


# ---------------------------------------------------------------------------
# Extração determinística (formulário → fatos)
# ---------------------------------------------------------------------------
def extrair_do_formulario(dados: dict,
                          processo_id: str | None = None) -> list[dict]:
    """Fatos materiais do Formulário Matriz (sempre com fonte)."""
    fatos: list[dict] = []

    def fato(path, valor, tipo, campo, confianca=0.9):
        fatos.append(governanca.novo_fato(
            processo_id, path, valor, tipo, f"formulario:{campo}",
            confianca=confianca))

    if (dados.get("orgao") or "").strip():
        fato("orgao.nome", dados["orgao"].strip(), "texto", "orgao")
    if (dados.get("responsavel") or "").strip():
        fato("responsavel.nome", dados["responsavel"].strip(), "texto",
             "responsavel")
    if (dados.get("objeto") or "").strip():
        fato("objeto.descricao", dados["objeto"].strip(), "texto", "objeto")

    execucao = (dados.get("modelo_execucao") or "").strip()
    if execucao:
        fato("execucao.modelo", execucao, "texto", "modelo_execucao")
        fato("procedimento.srp",
             execucao.startswith("Sistema de Registro de Preços"),
             "booleano", "modelo_execucao")
        fato("procedimento.execucao_continuada",
             "continuada" in execucao.lower(), "booleano",
             "modelo_execucao")
        # natureza derivada da execução: menor confiança (heurística
        # determinística — confirmação humana resolve)
        natureza = NATUREZA_POR_EXECUCAO.get(execucao, "BENS")
        fato("objeto.natureza", natureza, "texto", "modelo_execucao",
             confianca=0.7)

    if (dados.get("prazo") or "").strip():
        fato("prazo.descricao", dados["prazo"].strip(), "texto", "prazo")

    if dados.get("valor_estimado") is not None:
        fato("valor.total", float(dados["valor_estimado"]), "numero",
             "itens")

    for i, item in enumerate(dados.get("itens") or []):
        if not str(item.get("descricao") or "").strip():
            continue
        fato(f"itens[{i}].descricao", str(item["descricao"]).strip(),
             "texto", "itens")
        for campo, tipo in (("quantidade", "numero"),
                            ("unidade", "texto"),
                            ("valor_unitario", "numero")):
            valor = item.get(campo)
            if valor in (None, ""):
                continue
            fato(f"itens[{i}].{campo}",
                 float(valor) if tipo == "numero" else str(valor).strip(),
                 tipo, "itens")
    return fatos


# ---------------------------------------------------------------------------
# Versionamento (puro): o que inserir e o que marcar como substituído
# ---------------------------------------------------------------------------
def planejar_versionamento(
    novos: list[dict], existentes: list[dict]
) -> tuple[list[dict], list[str]]:
    """
    (a_inserir, ids_a_substituir). Compara por path com a versão vigente:
      - path novo             → insere versão 1;
      - valor idêntico        → mantém (inclusive a confirmação);
      - valor diferente       → insere versão n+1 (status 'extraido',
                                `substitui` aponta a anterior) e a
                                anterior é marcada 'substituido'.
    """
    vigentes: dict[str, dict] = {}
    for fato in existentes:
        if fato.get("status") == "substituido":
            continue
        atual = vigentes.get(fato["path"])
        if atual is None or fato.get("versao", 1) > atual.get("versao", 1):
            vigentes[fato["path"]] = fato

    inserir: list[dict] = []
    substituir: list[str] = []
    for novo in novos:
        vigente = vigentes.get(novo["path"])
        if vigente is None:
            inserir.append(novo)
            continue
        if governanca.hash_canonico(vigente.get("valor")) == \
                governanca.hash_canonico(novo.get("valor")):
            continue  # nada mudou: preserva versão (e confirmação)
        derivado = dict(novo)
        derivado["versao"] = int(vigente.get("versao", 1)) + 1
        derivado["substitui"] = vigente.get("id")
        derivado["hash"] = governanca.hash_canonico(
            {k: derivado[k] for k in ("path", "tipo", "valor", "versao")})
        inserir.append(derivado)
        if vigente.get("id"):
            substituir.append(vigente["id"])
    return inserir, substituir


def sincronizar(processo_id: str, dados: dict) -> list[dict]:
    """Extrai, versiona e persiste; retorna os fatos vigentes."""
    novos = extrair_do_formulario(dados, processo_id)
    existentes = db.listar_fatos(processo_id, apenas_vigentes=False)
    inserir, substituir = planejar_versionamento(novos, existentes)
    if inserir:
        db.salvar_fatos(inserir)
    for fato_id in substituir:
        db.atualizar_fato(fato_id, status="substituido")
    return db.listar_fatos(processo_id)


def confirmar_todos(processo_id: str, usuario_id: str | None) -> int:
    """Confirma os fatos 'extraido' vigentes; retorna quantos confirmou."""
    confirmados = 0
    for fato in db.listar_fatos(processo_id):
        if fato.get("status") == "extraido":
            db.atualizar_fato(fato["id"], status="confirmado",
                              confirmado_por=usuario_id)
            confirmados += 1
    return confirmados


# ---------------------------------------------------------------------------
# Divergências documentais (presença de fatos materiais nos documentos;
# a consistência cruzada completa é a Fase 5)
# ---------------------------------------------------------------------------
def divergencias_documentais(fatos: list[dict],
                             documentos: dict[str, str]) -> list[dict]:
    divergencias = []
    docs_com_texto = {k: v for k, v in (documentos or {}).items()
                      if (v or "").strip()}
    if not docs_com_texto:
        return []
    por_path = {f["path"]: f for f in fatos
                if f.get("status") != "substituido"}

    valor = por_path.get("valor.total")
    if valor and float(valor.get("valor") or 0) > 0:
        moeda = planilha.formatar_moeda(float(valor["valor"]))
        ausentes = [doc for doc, texto in docs_com_texto.items()
                    if moeda not in texto]
        if len(ausentes) == len(docs_com_texto):
            divergencias.append({
                "path": "valor.total",
                "tipo": "fato_nao_refletido",
                "mensagem": (f"o valor global {moeda} (fato canônico) não "
                             "aparece em nenhum documento"),
                "documentos": sorted(ausentes),
            })

    prazo = por_path.get("prazo.descricao")
    if prazo and len(str(prazo.get("valor") or "")) > 4:
        alvo = " ".join(str(prazo["valor"]).split())
        presente = any(
            blocos.localizar_bloco(
                blocos.dividir_em_blocos(doc, texto), alvo)
            for doc, texto in docs_com_texto.items()
        )
        if not presente:
            divergencias.append({
                "path": "prazo.descricao",
                "tipo": "fato_nao_refletido",
                "mensagem": "o prazo informado no formulário não foi "
                            "localizado em nenhum documento",
                "documentos": sorted(docs_com_texto),
            })
    return divergencias


# ---------------------------------------------------------------------------
# Entrada única da tela final (flag + shadow)
# ---------------------------------------------------------------------------
def ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_FATOS)


def processar_na_tela(dados: dict, documentos: dict[str, str],
                      processo_id: str | None) -> dict | None:
    """
    Flag LIGADA (com banco): sincroniza e retorna
    {"fatos": vigentes, "divergencias": [...]} para exibição.
    Flag DESLIGADA: shadow — extrai, compara e LOGA; retorna None
    (tela idêntica). Cache por conteúdo na sessão evita retrabalho.
    """
    chave = governanca.hash_canonico(
        {"dados": dados, "docs": documentos, "proc": processo_id})
    cache = st.session_state.get("_fatos_cache")
    if cache and cache.get("chave") == chave:
        return cache["resultado"]

    if not ativo() or not (db.disponivel() and processo_id):
        fatos = extrair_do_formulario(dados, processo_id)
        divergencias = divergencias_documentais(fatos, documentos)
        _log.info(
            "shadow: %d fato(s) canônico(s) extraído(s), %d divergência(s) "
            "documental(is)", len(fatos), len(divergencias))
        st.session_state["_fatos_cache"] = {"chave": chave,
                                            "resultado": None}
        return None

    fatos = sincronizar(processo_id, dados)
    resultado = {
        "fatos": fatos,
        "divergencias": divergencias_documentais(fatos, documentos),
    }
    st.session_state["_fatos_cache"] = {"chave": chave,
                                        "resultado": resultado}
    return resultado
