"""
Motor de conhecimento (Fase 3 do pacote V5).

Resolve, ANTES da geração/emissão, o que as regras estruturadas
determinam sobre os FATOS CANÔNICOS do processo: cláusulas a incluir/
excluir, parâmetros e campos exigidos, validações, alertas e bloqueios.

Garantias (03_servico_decisao do pacote):
  - avaliação 100% DETERMINÍSTICA por código (a IA não participa);
  - precedência explícita: camada mais específica vence (processo >
    secretaria > município > plataforma > controle > nacional); dentro
    da camada, prioridade maior vence;
  - conflito NÃO determinístico (mesma camada e prioridade, ações
    opostas) NUNCA é resolvido em silêncio: a decisão sai BLOQUEADA
    com as duas regras expostas (KQ-015);
  - fonte revogada não sustenta regra: a regra é ignorada e anotada
    (KQ-003); regra fora de vigência idem;
  - toda execução gera um REGISTRO DE DECISÃO append-only e
    reproduzível (input/output hash — KQ-014), com a trilha real das
    condições avaliadas (base da explicabilidade, F4).

Flags: `flag_knowledge_engine_shadow` registra decisões sem afetar o
fluxo; `flag_knowledge_engine_active` passa a exibir o resultado (e os
bloqueios) na tela final. Ambas OFF (default) = comportamento idêntico.
"""

import logging
from datetime import datetime, timezone

import streamlit as st

from . import db, fatos as fatos_mod, governanca

_log = logging.getLogger("govdocs.conhecimento")

# precedência: índice maior vence
_PESO_CAMADA = {camada: i for i, camada in enumerate(governanca.CAMADAS)}


# ---------------------------------------------------------------------------
# Contexto: fatos vigentes → {path: valor}
# ---------------------------------------------------------------------------
def contexto_dos_fatos(fatos: list[dict]) -> dict:
    contexto: dict = {}
    versao: dict[str, int] = {}
    for fato in fatos:
        if fato.get("status") == "substituido":
            continue
        path = fato["path"]
        if versao.get(path, 0) < int(fato.get("versao", 1)):
            versao[path] = int(fato.get("versao", 1))
            contexto[path] = fato.get("valor")
    return contexto


# ---------------------------------------------------------------------------
# Avaliador determinístico de condições (ALL/ANY/NOT + folhas)
# ---------------------------------------------------------------------------
def _avaliar_folha(folha: dict, contexto: dict) -> dict:
    campo = folha.get("field")
    operador = folha.get("operator")
    esperado = folha.get("value")
    existe = campo in contexto
    observado = contexto.get(campo)
    if operador == "EXISTS":
        satisfeita = existe
    elif not existe:
        satisfeita = False  # conservador: sem dado, condição não vale
    elif operador == "EQ":
        satisfeita = observado == esperado
    elif operador == "NEQ":
        satisfeita = observado != esperado
    elif operador in ("GT", "GTE", "LT", "LTE"):
        try:
            a, b = float(observado), float(esperado)
            satisfeita = {"GT": a > b, "GTE": a >= b,
                          "LT": a < b, "LTE": a <= b}[operador]
        except (TypeError, ValueError):
            satisfeita = False
    elif operador == "IN":
        satisfeita = observado in (esperado or [])
    elif operador == "CONTAINS":
        satisfeita = str(esperado).lower() in str(observado or "").lower()
    else:
        satisfeita = False
    return {"field": campo, "operator": operador, "value": esperado,
            "valor_observado": observado if existe else None,
            "presente": existe, "satisfeita": satisfeita}


def avaliar_condicao(condicao: dict, contexto: dict) -> dict:
    """{'resultado': bool, 'folhas': [...], 'ausentes': [...]}."""
    if "op" in condicao:
        avaliacoes = [avaliar_condicao(filho, contexto)
                      for filho in condicao.get("children", [])]
        resultados = [a["resultado"] for a in avaliacoes]
        op = condicao["op"]
        resultado = (all(resultados) if op == "ALL"
                     else any(resultados) if op == "ANY"
                     else not resultados[0])
        return {
            "resultado": resultado,
            "folhas": [f for a in avaliacoes for f in a["folhas"]],
            "ausentes": sorted({c for a in avaliacoes
                                for c in a["ausentes"]}),
        }
    folha = _avaliar_folha(condicao, contexto)
    return {"resultado": folha["satisfeita"], "folhas": [folha],
            "ausentes": [] if folha["presente"]
            or condicao.get("operator") == "EXISTS"
            else [folha["field"]]}


# ---------------------------------------------------------------------------
# Elegibilidade de regras (status, vigência, fontes vigentes)
# ---------------------------------------------------------------------------
def _vigente(regra: dict, agora: datetime) -> bool:
    inicio, fim = regra.get("vigencia_inicio"), regra.get("vigencia_fim")

    def parse(valor):
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")) \
            if valor else None

    comeca, termina = parse(inicio), parse(fim)
    if comeca and agora < comeca:
        return False
    if termina and agora >= termina:
        return False
    return True


def regras_elegiveis(regras: list[dict],
                     fontes_revogadas: set[str] | None = None,
                     agora: datetime | None = None
                     ) -> tuple[list[dict], list[dict]]:
    """(elegíveis, ignoradas com motivo) — nada é descartado em silêncio."""
    agora = agora or datetime.now(timezone.utc)
    revogadas = fontes_revogadas or set()
    elegiveis, ignoradas = [], []
    for regra in regras:
        if regra.get("status") != "PUBLISHED":
            ignoradas.append({"chave": regra.get("chave_estavel"),
                              "motivo": f"status {regra.get('status')}"})
            continue
        if not _vigente(regra, agora):
            ignoradas.append({"chave": regra.get("chave_estavel"),
                              "motivo": "fora de vigência"})
            continue
        usadas = {str(f) for f in (regra.get("fontes") or [])}
        if usadas & revogadas:
            ignoradas.append({
                "chave": regra.get("chave_estavel"),
                "motivo": "fonte revogada: "
                          + ", ".join(sorted(usadas & revogadas))})
            continue
        elegiveis.append(regra)
    return elegiveis, ignoradas


# ---------------------------------------------------------------------------
# Resolução com precedência e detecção de conflito
# ---------------------------------------------------------------------------
def _peso(regra: dict) -> tuple[int, int]:
    return (_PESO_CAMADA.get(regra.get("camada"), 0),
            int(regra.get("prioridade", 0)))


def resolver(fatos: list[dict], regras: list[dict],
             fontes_revogadas: set[str] | None = None,
             processo_id: str | None = None, documento: str = "",
             agora: datetime | None = None) -> dict:
    """
    Decisão estruturada (governanca.nova_decisao) com resultado:
    clausulas_incluir/excluir, parametros/campos exigidos, familia,
    validacoes, alertas, bloqueios, pendencias (dados ausentes),
    conflitos e regras ignoradas. Determinística e reproduzível.
    """
    contexto = contexto_dos_fatos(fatos)
    elegiveis, ignoradas = regras_elegiveis(regras, fontes_revogadas, agora)

    satisfeitas: list[dict] = []
    trilha: list[dict] = []
    ausentes: set[str] = set()
    for regra in sorted(elegiveis, key=_peso, reverse=True):
        avaliacao = avaliar_condicao(regra["condicao"], contexto)
        trilha.append({
            "chave": regra["chave_estavel"], "versao": regra["versao"],
            "camada": regra["camada"], "prioridade": regra["prioridade"],
            "satisfeita": avaliacao["resultado"],
            "folhas": avaliacao["folhas"],
        })
        ausentes.update(avaliacao["ausentes"])
        if avaliacao["resultado"]:
            satisfeitas.append(regra)

    # ações por cláusula-alvo: camada/prioridade decidem; empate oposto
    # = conflito não determinístico (bloqueia — nunca resolve sozinho)
    votos: dict[str, list[tuple[tuple[int, int], str, dict]]] = {}
    resultado = {
        "clausulas_incluir": [], "clausulas_excluir": [],
        "parametros_exigidos": [], "campos_exigidos": [],
        "familia": None, "validacoes": [], "alertas": [],
        "bloqueios": [], "pendencias": sorted(ausentes),
        "conflitos": [], "regras_ignoradas": ignoradas,
    }
    for regra in satisfeitas:
        for acao in regra["acoes"]:
            tipo, alvo = acao.get("type"), acao.get("target")
            if tipo in ("INCLUIR_CLAUSULA", "EXCLUIR_CLAUSULA"):
                votos.setdefault(alvo, []).append(
                    (_peso(regra), tipo, regra))
            elif tipo == "EXIGIR_PARAMETRO":
                resultado["parametros_exigidos"].append(alvo)
            elif tipo == "EXIGIR_CAMPO":
                resultado["campos_exigidos"].append(alvo)
            elif tipo == "SELECIONAR_FAMILIA":
                resultado["familia"] = alvo
            elif tipo == "ATIVAR_VALIDACAO":
                resultado["validacoes"].append(alvo)
            elif tipo == "BLOQUEAR_EMISSAO":
                resultado["bloqueios"].append({
                    "regra": regra["chave_estavel"],
                    "motivo": acao.get("motivo")
                    or regra.get("justificativa") or "regra de bloqueio",
                })
            elif tipo == "ALERTA":
                resultado["alertas"].append(
                    acao.get("mensagem") or regra["chave_estavel"])

    for alvo, decisoes_alvo in votos.items():
        maior = max(peso for peso, _, _ in decisoes_alvo)
        vencedoras = [(tipo, regra) for peso, tipo, regra in decisoes_alvo
                      if peso == maior]
        tipos = {tipo for tipo, _ in vencedoras}
        if len(tipos) > 1:
            resultado["conflitos"].append({
                "clausula": alvo,
                "regras": sorted(r["chave_estavel"] for _, r in vencedoras),
                "motivo": "ações opostas com mesma camada e prioridade — "
                          "resolução exige decisão humana",
            })
            continue
        destino = ("clausulas_incluir" if tipos == {"INCLUIR_CLAUSULA"}
                   else "clausulas_excluir")
        resultado[destino].append(alvo)

    resultado["clausulas_incluir"].sort()
    resultado["clausulas_excluir"].sort()
    if resultado["conflitos"]:
        resultado["bloqueios"].append({
            "regra": "motor_conhecimento",
            "motivo": f"{len(resultado['conflitos'])} conflito(s) de regras "
                      "sem critério de desempate",
        })

    fontes_usadas = sorted({str(f) for r in satisfeitas
                            for f in (r.get("fontes") or [])})
    return governanca.nova_decisao(
        processo_id, "resolucao_conhecimento", resultado,
        satisfeitas, [f for f in fatos
                      if f.get("status") != "substituido"],
        fontes=fontes_usadas,
        explicacao={"regras_avaliadas": trilha,
                    "regras_ignoradas": ignoradas},
        documento=documento,
    )


# ---------------------------------------------------------------------------
# Fontes revogadas (governança de fontes — KQ-003)
# ---------------------------------------------------------------------------
def fontes_revogadas_do_banco() -> set[str]:
    if not db.disponivel():
        return set()
    try:
        registros = (
            db._cliente().table("fontes_conhecimento")  # noqa: SLF001
            .select("rotulo, vigente").eq("vigente", False).execute()
        ).data or []
        return {r["rotulo"] for r in registros}
    except Exception:  # noqa: BLE001 — sem migração/tabela: nenhum veto
        return set()


# ---------------------------------------------------------------------------
# Execução na tela (flags shadow/ativo)
# ---------------------------------------------------------------------------
def shadow_ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_MOTOR_SHADOW)


def motor_ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_MOTOR_ATIVO)


def executar_na_tela(dados: dict, processo_id: str | None) -> dict | None:
    """
    Resolve o conhecimento para o processo atual:
      - motor ATIVO: retorna a decisão (a tela exibe e respeita
        bloqueios);
      - só SHADOW: registra a decisão (log + banco best-effort) e
        retorna None — fluxo intacto;
      - ambos OFF: não faz nada.
    Cache por conteúdo na sessão (idempotência dentro da sessão).
    """
    if not (motor_ativo() or shadow_ativo()):
        return None
    lista_fatos = fatos_mod.extrair_do_formulario(dados, processo_id)
    if db.disponivel() and processo_id:
        try:
            lista_fatos = db.listar_fatos(processo_id) or lista_fatos
        except db.ErroBanco:
            pass
    try:
        regras = db.listar_regras() if db.disponivel() else []
    except db.ErroBanco:
        regras = []

    decisao = resolver(lista_fatos, regras, fontes_revogadas_do_banco(),
                       processo_id)
    chave = decisao["input_hash"]
    cache = st.session_state.get("_decisao_cache")
    if not cache or cache.get("chave") != chave:
        if db.disponivel():
            try:
                db.registrar_decisao(decisao)
            except db.ErroBanco as erro:
                _log.warning("decisão não persistida: %s", erro)
        st.session_state["_decisao_cache"] = {"chave": chave,
                                              "decisao": decisao}
    else:
        decisao = cache["decisao"]

    if not motor_ativo():
        resultado = decisao["resultado"]
        _log.info(
            "shadow: motor resolveu %d regra(s) satisfeita(s), %d "
            "bloqueio(s), %d conflito(s)",
            len(decisao["regras_versoes"]), len(resultado["bloqueios"]),
            len(resultado["conflitos"]))
        return None
    return decisao
