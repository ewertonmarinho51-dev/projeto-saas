"""
Biblioteca de famílias de modelos (Fase 4 do Centro de Governança V6).

Famílias são ARTEFATOS versionados (tipo "familia"): nome, documentos
suportados, CRITÉRIOS de elegibilidade (mesmo formato de condição do
motor V5), estrutura de cláusulas obrigatórias/opcionais/proibidas e
prioridade de desempate.

Resolução AUTOMÁTICA (o servidor não escolhe modelo em lista técnica):
  - o contexto vem dos FATOS canônicos do processo;
  - 1 família elegível → resolvida (T12);
  - várias com prioridades distintas → a maior vence (determinístico);
  - EMPATE real → situação "ambigua" com PERGUNTA OBJETIVA e opções
    rotuladas (T13) — nunca uma lista técnica de modelos;
  - nenhuma → "nenhuma": o app segue com o perfil institucional atual
    (comportamento de hoje, sem regressão).
Toda resolução gera registro de decisão reproduzível (tipo
"familia_modelo").

Flags: `flag_model_family_resolution_shadow` registra a decisão sem
afetar nada; `flag_model_family_resolution_active` passa a injetar a
estrutura da família na geração e a fazer a pergunta quando ambígua.
"""

import logging

import streamlit as st

from . import catalogo, conhecimento, db, fatos as fatos_mod, governanca

_log = logging.getLogger("govdocs.familias")


def shadow_ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_FAMILIAS_SHADOW)


def resolucao_ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_FAMILIAS_ATIVA)


# ---------------------------------------------------------------------------
# Criação (payload validado pelo contrato "familia")
# ---------------------------------------------------------------------------
def criar_familia(chave_estavel: str, nome: str,
                  documentos_suportados: list[str], criterios: dict,
                  clausulas_obrigatorias: list[str] | None = None,
                  clausulas_proibidas: list[str] | None = None,
                  prioridade: int = 100,
                  pergunta_desambiguacao: str = "",
                  plataforma: bool = False) -> tuple[dict, dict]:
    payload = {
        "nome": nome,
        "documentos_suportados": list(documentos_suportados),
        "criterios": criterios,
        "clausulas_obrigatorias": list(clausulas_obrigatorias or []),
        "clausulas_proibidas": list(clausulas_proibidas or []),
        "prioridade": int(prioridade),
        "pergunta_desambiguacao": pergunta_desambiguacao,
    }
    return catalogo.criar_artefato("familia", chave_estavel, payload,
                                   plataforma)


def familias_publicadas() -> list[dict]:
    """[{artefato, versao}] das famílias vigentes visíveis ao tenant."""
    return [{"artefato": item["artefato"], "versao": item["publicada"]}
            for item in catalogo.listar_com_situacao("familia")
            if item["publicada"]]


# ---------------------------------------------------------------------------
# Resolução determinística (função pura sobre fatos + famílias)
# ---------------------------------------------------------------------------
def resolver(doc_key: str, fatos: list[dict],
             familias: list[dict],
             escolha_manual: str | None = None) -> dict:
    """
    {"situacao": unica|ambigua|nenhuma, "familia": {...}|None,
     "pergunta": str, "opcoes": [...], "decisao": registro}
    `escolha_manual` = chave respondida pelo servidor na ambiguidade.
    """
    contexto = conhecimento.contexto_dos_fatos(fatos)
    elegiveis = []
    trilha = []
    for item in familias:
        payload = item["versao"].get("payload") or {}
        if doc_key not in (payload.get("documentos_suportados") or []):
            continue
        avaliacao = conhecimento.avaliar_condicao(
            payload.get("criterios") or {}, contexto)
        trilha.append({"chave": item["artefato"]["chave_estavel"],
                       "versao": item["versao"]["versao"],
                       "elegivel": avaliacao["resultado"],
                       "folhas": avaliacao["folhas"]})
        if avaliacao["resultado"]:
            elegiveis.append(item)

    if escolha_manual:
        elegiveis = [i for i in elegiveis
                     if i["artefato"]["chave_estavel"] == escolha_manual]

    situacao, escolhida, pergunta, opcoes = "nenhuma", None, "", []
    if len(elegiveis) == 1:
        situacao, escolhida = "unica", elegiveis[0]
    elif len(elegiveis) > 1:
        maior = max(i["versao"]["payload"].get("prioridade", 100)
                    for i in elegiveis)
        no_topo = [i for i in elegiveis
                   if i["versao"]["payload"].get("prioridade", 100) == maior]
        if len(no_topo) == 1:
            situacao, escolhida = "unica", no_topo[0]
        else:
            situacao = "ambigua"
            perguntas = [i["versao"]["payload"].get(
                "pergunta_desambiguacao") for i in no_topo]
            pergunta = next((p for p in perguntas if p),
                            "Qual opção descreve melhor esta contratação?")
            opcoes = [{"chave": i["artefato"]["chave_estavel"],
                       "rotulo": i["versao"]["payload"]["nome"]}
                      for i in sorted(
                          no_topo,
                          key=lambda x: x["artefato"]["chave_estavel"])]

    resultado = {
        "situacao": situacao,
        "familia": (escolhida["artefato"]["chave_estavel"]
                    if escolhida else None),
        "pergunta": pergunta,
        "opcoes": opcoes,
        "escolha_manual": escolha_manual,
    }
    decisao = governanca.nova_decisao(
        None, "familia_modelo", resultado, [],
        [f for f in fatos if f.get("status") != "substituido"],
        explicacao={"familias_avaliadas": trilha}, documento=doc_key,
        ator_tipo="usuario" if escolha_manual else "sistema")
    return {**resultado,
            "payload": (escolhida["versao"]["payload"]
                        if escolhida else None),
            "decisao": decisao}


# ---------------------------------------------------------------------------
# Estrutura da família para o prompt de geração (aditivo ao perfil)
# ---------------------------------------------------------------------------
def bloco_para_prompt(payload: dict) -> str:
    linhas = [
        f"\n\nFAMÍLIA DE MODELO APLICÁVEL: {payload['nome']} — siga as "
        "diretrizes abaixo, definidas pela Administração:"
    ]
    if payload.get("clausulas_obrigatorias"):
        linhas.append("Cláusulas OBRIGATÓRIAS desta família: "
                      + "; ".join(payload["clausulas_obrigatorias"]) + ".")
    if payload.get("clausulas_proibidas"):
        linhas.append("Cláusulas PROIBIDAS nesta família (não incluir em "
                      "hipótese alguma): "
                      + "; ".join(payload["clausulas_proibidas"]) + ".")
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Resolução para o processo atual (flags shadow/ativa)
# ---------------------------------------------------------------------------
def resolver_para_processo(doc_key: str, dados: dict,
                           processo_id: str | None,
                           escolha_manual: str | None = None
                           ) -> dict | None:
    """
    ATIVA: retorna a resolução (geração usa; ambígua vira pergunta).
    Só SHADOW: registra a decisão (log/banco) e retorna None.
    Ambas OFF: None sem trabalho algum.
    """
    if not (resolucao_ativa() or shadow_ativa()):
        return None
    try:
        familias = familias_publicadas() if db.disponivel() else []
    except db.ErroBanco:
        familias = []
    lista_fatos = fatos_mod.extrair_do_formulario(dados, processo_id)
    resolucao = resolver(doc_key, lista_fatos, familias, escolha_manual)

    chave_cache = f"_familia_decisao_{doc_key}"
    hash_atual = resolucao["decisao"]["input_hash"]
    if st.session_state.get(chave_cache) != hash_atual:
        st.session_state[chave_cache] = hash_atual
        if db.disponivel():
            try:
                db.registrar_decisao(resolucao["decisao"])
            except db.ErroBanco as erro:
                _log.warning("decisão de família não persistida: %s", erro)
        _log.info("família p/ %s: %s (%s)", doc_key,
                  resolucao["familia"], resolucao["situacao"])
    if not resolucao_ativa():
        return None
    return resolucao
