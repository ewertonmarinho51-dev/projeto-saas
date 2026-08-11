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
# Base de regras da PLATAFORMA (P1)
#
# O motor já resolvia regras corretamente, mas a tabela `regras_conheci-
# mento` nasce VAZIA: sem regra publicada, nenhuma cláusula condicional
# jamais era ativada ou suprimida. Estas regras são o piso institucional
# — camada 'nacional', a MENOS específica de todas, de modo que qualquer
# regra do município, da secretaria ou do processo (banco/Centro de
# Governança) prevalece pela precedência já existente.
#
# São DADOS para o resolver existente: nenhuma lógica condicional nova
# foi criada, e cada regra aponta a fonte normativa que a sustenta.
# ---------------------------------------------------------------------------
def _regra(chave, condicao, acoes, justificativa, fontes,
           prioridade=10) -> dict:
    return {
        "chave_estavel": chave, "versao": 1, "status": "PUBLISHED",
        "camada": "nacional", "prioridade": prioridade,
        "condicao": condicao, "acoes": acoes,
        "vigencia_inicio": None, "vigencia_fim": None,
        "fontes": list(fontes), "justificativa": justificativa,
    }


def _eq(campo, valor) -> dict:
    return {"field": campo, "operator": "EQ", "value": valor}


def _nao(condicao: dict) -> dict:
    return {"op": "NOT", "children": [condicao]}


def _existe(campo: str) -> dict:
    return {"field": campo, "operator": "EXISTS", "value": None}


def _incluir(*alvos) -> list[dict]:
    return [{"type": "INCLUIR_CLAUSULA", "target": a} for a in alvos]


def _excluir(*alvos) -> list[dict]:
    return [{"type": "EXCLUIR_CLAUSULA", "target": a} for a in alvos]


_LEI = "Lei nº 14.133/2021"

def _alerta(mensagem: str) -> list[dict]:
    return [{"type": "ALERTA", "mensagem": mensagem}]


REGRAS_BASE: list[dict] = [
    # --- Sistema de Registro de Preços -------------------------------
    # A renovação do quantitativo registrado NÃO decorre da simples
    # adoção do SRP: depende da regulamentação do ente e dos
    # entendimentos aplicáveis. Fica de fora da base — uma regra
    # municipal publicada no Centro de Governança pode ativá-la com a
    # fundamentação própria (o alvo `srp.renovacao_quantitativo`
    # permanece disponível para isso).
    _regra(
        "base.srp.clausulas-proprias",
        _eq("procedimento.srp", True),
        _incluir("srp.vigencia_ata", "srp.gerenciamento", "srp.adesao",
                 "srp.cadastro_reserva"),
        "Contratação por Sistema de Registro de Preços exige as cláusulas "
        "próprias da Ata (vigência, gerenciamento, adesão, cadastro de "
        "reserva).",
        [f"{_LEI}, arts. 82 a 86"]),
    _regra(
        "base.srp.sem-srp-nao-ha-ata",
        _nao(_eq("procedimento.srp", True)),
        _excluir("srp.vigencia_ata", "srp.gerenciamento", "srp.adesao",
                 "srp.cadastro_reserva", "srp.renovacao_quantitativo"),
        "Sem Sistema de Registro de Preços não há Ata: as cláusulas "
        "próprias da ARP não podem constar do documento.",
        [f"{_LEI}, arts. 82 a 86"]),

    # --- Reajuste × repactuação --------------------------------------
    # Tri-state: só decide quem tem informação. Sem saber o regime de
    # pessoal, o motor ALERTA em vez de excluir ou impor o instituto.
    _regra(
        "base.repactuacao.sem-dedicacao-de-mao-de-obra",
        _eq("procedimento.dedicacao_mao_de_obra", False),
        _excluir("preco.repactuacao") + _incluir("preco.reajuste"),
        "Sem dedicação de mão de obra não cabe repactuação: a manutenção "
        "do equilíbrio se dá por reajuste por índice.",
        [f"{_LEI}, art. 92, §3º", f"{_LEI}, art. 135"]),
    _regra(
        "base.repactuacao.servico-com-mao-de-obra",
        _eq("procedimento.dedicacao_mao_de_obra", True),
        _incluir("preco.repactuacao"),
        "Serviço contínuo com dedicação exclusiva de mão de obra admite "
        "repactuação para manutenção do equilíbrio econômico-financeiro.",
        [f"{_LEI}, art. 135"], prioridade=20),
    _regra(
        "base.repactuacao.regime-nao-informado",
        {"op": "ALL", "children": [
            _eq("procedimento.execucao_continuada", True),
            _nao(_existe("procedimento.dedicacao_mao_de_obra"))]},
        _alerta("Serviço continuado sem informação sobre dedicação de mão "
                "de obra: a escolha entre REAJUSTE (art. 92, §3º) e "
                "REPACTUAÇÃO (art. 135) depende desse regime — registre-o "
                "no processo antes de fixar a cláusula."),
        "O instituto de atualização de preços depende do regime de "
        "pessoal, que não consta do processo.",
        [f"{_LEI}, art. 135", f"{_LEI}, art. 92, §3º"]),
    _regra(
        "base.reajuste.bens",
        _eq("objeto.natureza", "BENS"),
        _excluir("preco.repactuacao") + _incluir("preco.reajuste"),
        "Fornecimento de bens não comporta repactuação: aplica-se o "
        "reajuste por índice.",
        [f"{_LEI}, art. 92, §3º"]),

    # --- Garantia contratual -----------------------------------------
    _regra(
        "base.garantia.nao-presumida",
        _nao(_eq("contratacao.garantia_exigida", True)),
        _excluir("contrato.garantia"),
        "A garantia contratual é FACULDADE motivada da Administração: sem "
        "decisão registrada no processo, não se presume exigência nem "
        "percentual.",
        [f"{_LEI}, arts. 96 a 98"]),
    _regra(
        "base.garantia.exigida-no-processo",
        _eq("contratacao.garantia_exigida", True),
        _incluir("contrato.garantia"),
        "Havendo exigência de garantia no processo, a cláusula deve "
        "indicar modalidade, percentual e condições de liberação.",
        [f"{_LEI}, arts. 96 a 98"], prioridade=20),

    # --- Amostra / prova de conceito ---------------------------------
    _regra(
        "base.amostra.nao-presumida",
        _nao(_eq("contratacao.amostra_exigida", True)),
        _excluir("julgamento.amostra"),
        "Exigência de amostra ou prova de conceito restringe a competição "
        "e só cabe quando prevista no edital e justificada tecnicamente.",
        [f"{_LEI}, art. 41, II", f"{_LEI}, art. 42"]),
    _regra(
        "base.amostra.exigida-no-processo",
        _eq("contratacao.amostra_exigida", True),
        _incluir("julgamento.amostra"),
        "Amostra prevista no processo: definir momento, critérios "
        "objetivos de aceitação e consequência da reprovação.",
        [f"{_LEI}, art. 41, II", f"{_LEI}, art. 42"], prioridade=20),

    # --- Tratamento favorecido ME/EPP --------------------------------
    _regra(
        "base.me-epp.bens-e-servicos",
        {"op": "ANY", "children": [_eq("objeto.natureza", "BENS"),
                                   _eq("objeto.natureza", "SERVICOS")]},
        _incluir("participacao.me_epp"),
        "Aquisição de bens e contratação de serviços atraem o tratamento "
        "favorecido às microempresas e empresas de pequeno porte.",
        ["LC nº 123/2006, arts. 42 a 49"]),

    # --- Categorias do objeto (fato estruturado, nunca texto solto) ---
    # SOFTWARE/SaaS trata dados da Administração: daí LGPD, backup e
    # migração de saída. EQUIPAMENTO não recebe nada disso por padrão —
    # comprar monitores não gera cláusula de migração de dados. Quando o
    # hardware efetivamente armazenar dados, a regra própria é municipal.
    _regra(
        "base.ti.solucao-de-software",
        _eq("objeto.categoria", "TI_SOFTWARE"),
        _incluir("ti.nivel_servico", "ti.seguranca_backup",
                 "ti.interoperabilidade", "ti.protecao_dados",
                 "ti.migracao_saida"),
        "Software, SaaS e hospedagem tratam dados da Administração: "
        "exigem níveis de serviço, segurança e continuidade, "
        "interoperabilidade, proteção de dados pessoais e condições de "
        "migração/devolução ao término do contrato.",
        ["Lei nº 13.709/2018 (LGPD)", f"{_LEI}, art. 40"]),

    _regra(
        "base.epi.certificado-de-aprovacao",
        _eq("objeto.categoria", "EPI"),
        _incluir("epi.certificado_aprovacao"),
        "Equipamento de proteção individual exige Certificado de "
        "Aprovação (CA) válido, emitido pelo órgão competente.",
        # a fonte precisa estar INDEXADA na base para sustentar citação
        # de dispositivo no documento (ver rag.REGRA_DE_CITACAO)
        ["NR-6 — Portaria MTP nº 672/2021 (consolidação das NRs); "
         "confirmar vigência na base de conhecimento"]),

    # Veículos: garantia, manutenção e assistência dependem do que o
    # processo exigir. Exigência de rede autorizada, cobertura territorial
    # ou distância máxima restringe a competição e precisa de necessidade
    # técnica demonstrada — por isso a base apenas ALERTA.
    _regra(
        "base.veiculos.condicoes-a-justificar",
        _eq("objeto.categoria", "VEICULOS"),
        _alerta("Aquisição de veículos: defina garantia, manutenção e "
                "documentação de entrega conforme a necessidade do "
                "processo. Exigência de rede de assistência autorizada, "
                "cobertura territorial ou distância máxima só é admissível "
                "com justificativa técnica no processo — sem ela, não a "
                "inclua."),
        "Condições de garantia e assistência de veículos variam com a "
        "necessidade; restrições territoriais exigem motivação própria.",
        [f"{_LEI}, art. 40"]),
]


def regras_base() -> list[dict]:
    """Cópia da base de regras da plataforma (nunca mutável pelo chamador)."""
    import copy

    return copy.deepcopy(REGRAS_BASE)


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


# Uma INFERÊNCIA do sistema (fato cuja fonte é `inferencia:…`, ainda não
# confirmado por um humano) não pode, sozinha, incluir cláusula
# obrigatória, excluir matéria do documento, criar exigência técnica ou
# restringir a competição: a regra continua valendo, mas o efeito vira
# SUGESTÃO com alerta. Informação prestada no processo (qualquer fonte
# que não seja inferência) e fato confirmado seguem vinculando
# normalmente. Uma regra pode aceitar inferência explicitamente com
# `aceita_inferencia: True` — política declarada, não efeito colateral.
CONFIANCA_VINCULANTE = 0.75


def _perfil_dos_fatos(fatos: list[dict]) -> dict[str, dict]:
    """path → {'confianca', 'inferido'} da versão vigente do fato."""
    from .fatos import PREFIXO_INFERENCIA

    perfil: dict[str, dict] = {}
    versao: dict[str, int] = {}
    for fato in fatos:
        if fato.get("status") == "substituido":
            continue
        path = fato["path"]
        if versao.get(path, 0) >= int(fato.get("versao", 1)):
            continue
        versao[path] = int(fato.get("versao", 1))
        confirmado = fato.get("status") == "confirmado"
        perfil[path] = {
            "confianca": 1.0 if confirmado
            else float(fato.get("confianca") or 0.5),
            "inferido": (not confirmado) and str(fato.get("fonte") or "")
            .startswith(PREFIXO_INFERENCIA),
        }
    return perfil


def confiancas_dos_fatos(fatos: list[dict]) -> dict[str, float]:
    """path → confiança vigente (fato confirmado pelo humano vale 1.0)."""
    return {path: dados["confianca"]
            for path, dados in _perfil_dos_fatos(fatos).items()}


def _confianca_da_avaliacao(avaliacao: dict,
                            perfil: dict[str, dict]) -> tuple[float, str, bool]:
    """
    (confiança, fato mais fraco, é inferência?) da regra satisfeita.
    Vale o fato MENOS confiável entre os efetivamente usados. Condição
    satisfeita por AUSÊNCIA de fato (ex.: 'garantia não foi pedida no
    processo') não é inferência: é constatação sobre o processo.
    """
    usados = [f for f in avaliacao["folhas"] if f["satisfeita"] and f["presente"]]
    if not usados:
        return 1.0, "", False
    pior = min(usados,
               key=lambda f: perfil.get(f["field"], {}).get("confianca", 0.5))
    dados = perfil.get(pior["field"], {})
    return (dados.get("confianca", 0.5), pior["field"],
            bool(dados.get("inferido")))


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
    perfil = _perfil_dos_fatos(fatos)
    elegiveis, ignoradas = regras_elegiveis(regras, fontes_revogadas, agora)

    satisfeitas: list[dict] = []
    trilha: list[dict] = []
    ausentes: set[str] = set()
    sugeridas: list[tuple[dict, float, str]] = []
    for regra in sorted(elegiveis, key=_peso, reverse=True):
        avaliacao = avaliar_condicao(regra["condicao"], contexto)
        confianca, fato_fraco, inferido = _confianca_da_avaliacao(
            avaliacao, perfil)
        trilha.append({
            "chave": regra["chave_estavel"], "versao": regra["versao"],
            "camada": regra["camada"], "prioridade": regra["prioridade"],
            "satisfeita": avaliacao["resultado"],
            "folhas": avaliacao["folhas"],
            "acoes": regra["acoes"],
            "fontes": list(regra.get("fontes") or []),
            "justificativa": regra.get("justificativa", ""),
            "confianca": round(confianca, 2),
        })
        ausentes.update(avaliacao["ausentes"])
        if not avaliacao["resultado"]:
            continue
        if inferido and not regra.get("aceita_inferencia"):
            # a regra vale, mas quem a sustenta é uma inferência do
            # sistema: a ação é oferecida ao revisor, não imposta
            sugeridas.append((regra, confianca, fato_fraco))
            continue
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
        # regras satisfeitas por fato de baixa confiança: sugestão ao
        # revisor, nunca imposição ao documento
        "sugestoes": [],
    }
    for regra, confianca, fato_fraco in sugeridas:
        alvos = [a.get("target") for a in regra["acoes"] if a.get("target")]
        resultado["sugestoes"].append({
            "regra": regra["chave_estavel"],
            "acoes": [a.get("type") for a in regra["acoes"]],
            "alvos": alvos,
            "confianca": round(confianca, 2),
            "fato": fato_fraco,
            "motivo": (
                f"sustentada por inferência de baixa confiança "
                f"({fato_fraco} = {confianca:.2f}); confirme o fato para "
                "que a regra passe a valer"),
            "justificativa": regra.get("justificativa", ""),
        })
        resultado["alertas"].append(
            f"{regra.get('justificativa') or regra['chave_estavel']} "
            f"— avaliar: depende de confirmar '{fato_fraco}'.")
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
        do_banco = db.listar_regras() if db.disponivel() else []
    except db.ErroBanco:
        do_banco = []
    # a base da plataforma é o piso: qualquer regra do banco (município,
    # secretaria, processo) vence pela precedência já existente
    regras = regras_base() + do_banco
    # V6 Fase 3 (flag_visual_policy_builder): as políticas PUBLICADAS no
    # Centro de Governança entram no motor junto às regras do banco.
    if db.disponivel() and db.flag_ativa(governanca.FLAG_POLITICAS_VISUAL):
        from . import politicas

        try:
            regras = regras + politicas.regras_publicadas()
        except db.ErroBanco:
            pass

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


# ---------------------------------------------------------------------------
# Diretrizes de cláusulas condicionais para a GERAÇÃO (P1)
#
# Até aqui a decisão do motor só aparecia na tela final — depois do
# documento pronto. As cláusulas condicionais precisam chegar ao prompt,
# e por isso a MESMA decisão (mesmo resolver, mesmos fatos, mesma
# trilha) é traduzida em instruções objetivas para a redação.
# ---------------------------------------------------------------------------
ROTULOS_CLAUSULA = {
    "srp.vigencia_ata": "vigência da Ata de Registro de Preços (art. 84 da "
                        "Lei nº 14.133/2021: 1 ano, prorrogável por igual "
                        "período)",
    "srp.gerenciamento": "gerenciamento da Ata (órgão gerenciador, "
                         "participantes e controle dos quantitativos)",
    "srp.adesao": "adesão à Ata por órgãos não participantes, com os "
                  "limites do art. 86",
    "srp.cadastro_reserva": "cadastro de reserva dos licitantes que "
                            "aceitarem cotar nos preços do primeiro colocado",
    "srp.renovacao_quantitativo": "possibilidade de renovação do "
                                  "quantitativo registrado",
    "preco.reajuste": "reajuste de preços por índice oficial (art. 92, §3º)",
    "preco.repactuacao": "repactuação de preços (art. 135), restrita a "
                         "serviço contínuo com dedicação de mão de obra",
    "contrato.garantia": "garantia contratual, com modalidade, percentual e "
                         "condições (arts. 96 a 98)",
    "julgamento.amostra": "exigência de amostra/prova de conceito, com "
                          "critérios objetivos de aceitação",
    "participacao.me_epp": "tratamento favorecido a microempresas e "
                           "empresas de pequeno porte (LC nº 123/2006)",
    "ti.nivel_servico": "níveis mínimos de serviço (disponibilidade, "
                        "suporte e prazos de atendimento)",
    "ti.seguranca_backup": "segurança da informação, backup e continuidade",
    "ti.interoperabilidade": "interoperabilidade e formatos abertos de "
                             "intercâmbio de dados",
    "ti.protecao_dados": "proteção de dados pessoais (Lei nº 13.709/2018)",
    "ti.migracao_saida": "migração e devolução dos dados ao término do "
                         "contrato",
    "epi.certificado_aprovacao": "exigência de Certificado de Aprovação "
                                 "(CA) válido para cada equipamento",
}


def _rotulo(alvo: str) -> str:
    return ROTULOS_CLAUSULA.get(alvo, alvo.replace("_", " ").replace(".", ": "))


def bloco_de_diretrizes(resultado: dict) -> str:
    """Texto das cláusulas condicionais resolvidas (vazio se nada a dizer)."""
    incluir = resultado.get("clausulas_incluir") or []
    excluir = resultado.get("clausulas_excluir") or []
    alertas = resultado.get("alertas") or []
    if not (incluir or excluir or alertas):
        return ""
    linhas = [
        "\n=== CLÁUSULAS CONDICIONAIS DETERMINADAS PELAS REGRAS "
        "INSTITUCIONAIS (obrigatório) ===",
        "Estas determinações vêm das regras vigentes aplicadas aos dados "
        "do processo — não são sugestões e prevalecem sobre o padrão dos "
        "documentos anteriores.",
    ]
    if incluir:
        linhas.append("DEVE TRATAR (desenvolva a matéria na cláusula "
                      "adequada do documento):")
        linhas += [f"- {_rotulo(a)}" for a in incluir]
    if excluir:
        linhas.append("NÃO PODE CONSTAR (a matéria é inaplicável a esta "
                      "contratação; não escreva a cláusula nem mencione o "
                      "instituto como se aplicável):")
        linhas += [f"- {_rotulo(a)}" for a in excluir]
    if alertas:
        linhas.append("ATENÇÃO:")
        linhas += [f"- {a}" for a in alertas]
    return "\n".join(linhas)


def dados_consolidados(dados: dict, documentos: dict[str, str] | None) -> dict:
    """
    Dados do processo com as decisões JÁ CONSOLIDADAS pelos documentos
    aprovados sobrepondo a preferência do formulário.

    O formulário é hipótese de modelagem; o ETP é quem consolida o SRP.
    Sem esta sobreposição, gerar o TR depois de um ETP que afastou o
    registro de preços reintroduziria as cláusulas da Ata pela porta dos
    fundos. Usa o extrator de decisões da consistência — sem duplicar
    lógica de leitura de documento.
    """
    if not documentos:
        return dados
    from . import consistencia

    doc_ref, valor, _ = consistencia.documento_consolidador("srp", documentos)
    if not doc_ref or valor not in ("sim", "nao"):
        return dados
    srp_consolidado = valor == "sim"
    if srp_consolidado == str(dados.get("modelo_execucao") or "").startswith(
            "Sistema de Registro de Preços"):
        return dados
    ajustado = dict(dados)
    ajustado["modelo_execucao"] = (
        "Sistema de Registro de Preços (SRP)" if srp_consolidado
        else "Entrega parcelada")
    ajustado["_consolidado_por"] = doc_ref
    _log.info("modelagem consolidada pelo %s: srp=%s (formulário sobreposto)",
              doc_ref, srp_consolidado)
    return ajustado


def diretrizes_para_prompt(dados: dict, processo_id: str | None,
                           documentos: dict[str, str] | None = None,
                           doc_key: str = "") -> str:
    """
    Bloco de cláusulas condicionais para a geração. Só produz texto com o
    motor ATIVO (flag): shadow e OFF mantêm o prompt idêntico ao atual.
    As decisões consolidadas nos documentos anteriores prevalecem sobre a
    preferência registrada no formulário.
    Nunca levanta exceção — conhecimento é enriquecimento, não requisito.
    """
    try:
        if not motor_ativo():
            return ""
        # o documento em produção não consolida a si mesmo
        anteriores = {k: v for k, v in (documentos or {}).items()
                      if k != doc_key}
        decisao = executar_na_tela(
            dados_consolidados(dados, anteriores), processo_id)
        if not decisao:
            return ""
        return bloco_de_diretrizes(decisao["resultado"])
    except Exception as erro:  # noqa: BLE001
        _log.warning("diretrizes do motor indisponíveis: %s", erro)
        return ""
