"""
Contratos de domínio da governança e qualidade documental (Fase 1 do
pacote_governanca_qualidade_documental_v1 / prompt V5).

Este módulo é a FUNDAÇÃO OBSERVÁVEL: define os formatos, validações e
hashes dos registros que as fases seguintes produzem — fatos canônicos
(F2), regras e decisões do motor de conhecimento (F3), explicações
(F4), consistência (F5), score (F6) e aprendizado (F7). Nenhuma tela
ou fluxo muda nesta fase.

Princípios do pacote aplicados aqui:
  - decisão DETERMINÍSTICA e REPRODUZÍVEL: input_hash/output_hash sobre
    JSON canônico (mesmas entradas ⇒ mesmo hash, sempre — KQ-014);
  - regra publicada é IMUTÁVEL: editar = derivar nova versão;
  - a IA nunca resolve conflito jurídico em silêncio: condições são
    estruturadas (ALL/ANY/NOT) e avaliadas por código (F3);
  - feedback SEMPRE anonimizado antes da curadoria (KQ-009);
  - todas as flags nascem DESLIGADAS (comportamento v4 idêntico).
"""

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Feature flags do pacote V5 (config_app: flag_<nome>; default OFF)
# ---------------------------------------------------------------------------
FLAG_FATOS = "canonical_facts"
FLAG_MOTOR_SHADOW = "knowledge_engine_shadow"
FLAG_MOTOR_ATIVO = "knowledge_engine_active"
FLAG_EXPLICACOES = "explanations"
FLAG_CONSISTENCIA = "process_consistency"
FLAG_SCORE_SHADOW = "confidence_score_shadow"
FLAG_SCORE_GATE = "confidence_emission_gate"
FLAG_APRENDIZADO_CAPTURA = "institutional_learning_capture"
FLAG_APRENDIZADO_PUBLICACAO = "institutional_learning_publish"

FLAGS_V5 = (
    FLAG_FATOS, FLAG_MOTOR_SHADOW, FLAG_MOTOR_ATIVO, FLAG_EXPLICACOES,
    FLAG_CONSISTENCIA, FLAG_SCORE_SHADOW, FLAG_SCORE_GATE,
    FLAG_APRENDIZADO_CAPTURA, FLAG_APRENDIZADO_PUBLICACAO,
)

# ---------------------------------------------------------------------------
# Vocabulários fechados
# ---------------------------------------------------------------------------
TIPOS_FATO = ("texto", "numero", "booleano", "lista", "objeto")
STATUS_FATO = ("extraido", "confirmado", "disputado", "substituido")

CAMADAS = ("nacional", "controle", "plataforma", "municipio",
           "secretaria", "processo")
# precedência: índice MAIOR vence (processo > … > nacional)

STATUS_REGRA = ("DRAFT", "UNDER_REVIEW", "PUBLISHED", "REVOKED",
                "SUPERSEDED")

OPERADORES_LOGICOS = ("ALL", "ANY", "NOT")
OPERADORES_FOLHA = ("EQ", "NEQ", "GT", "GTE", "LT", "LTE", "IN",
                    "CONTAINS", "EXISTS")

TIPOS_ACAO = (
    "INCLUIR_CLAUSULA", "EXCLUIR_CLAUSULA", "EXIGIR_PARAMETRO",
    "EXIGIR_CAMPO", "SELECIONAR_FAMILIA", "ATIVAR_VALIDACAO",
    "BLOQUEAR_EMISSAO", "ALERTA",
)

ESTADOS_FEEDBACK = (
    "CAPTURED", "NORMALIZED", "UNDER_REVIEW", "APPROVED_FOR_SHADOW",
    "SHADOW_VALIDATED", "PUBLISHED", "DEPRECATED", "REJECTED",
)
_TRANSICOES_FEEDBACK = {
    "CAPTURED": {"NORMALIZED", "REJECTED"},
    "NORMALIZED": {"UNDER_REVIEW", "REJECTED"},
    "UNDER_REVIEW": {"APPROVED_FOR_SHADOW", "REJECTED"},
    "APPROVED_FOR_SHADOW": {"SHADOW_VALIDATED", "REJECTED"},
    "SHADOW_VALIDATED": {"PUBLISHED", "REJECTED"},
    "PUBLISHED": {"DEPRECATED"},
    "DEPRECATED": set(),
    "REJECTED": set(),
}


class ErroContrato(Exception):
    """Registro fora do contrato de domínio — nunca persiste."""


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Hash canônico (reprodutibilidade — KQ-014)
# ---------------------------------------------------------------------------
def hash_canonico(dados) -> str:
    """
    SHA-256 do JSON canônico (chaves ordenadas, sem espaços): a MESMA
    entrada produz o MESMO hash em qualquer execução ou máquina.
    """
    canonico = json.dumps(dados, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), default=str)
    return hashlib.sha256(canonico.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Fato canônico (F2 consome)
# ---------------------------------------------------------------------------
def novo_fato(processo_id: str | None, path: str, valor, tipo: str,
              fonte: str, status: str = "extraido",
              confianca: float = 0.5, versao: int = 1,
              substitui: str | None = None) -> dict:
    if tipo not in TIPOS_FATO:
        raise ErroContrato(f"tipo de fato inválido: {tipo!r}")
    if status not in STATUS_FATO:
        raise ErroContrato(f"status de fato inválido: {status!r}")
    if not path.strip():
        raise ErroContrato("fato sem path estruturado")
    if not fonte.strip():
        raise ErroContrato(f"fato {path!r} sem fonte — fato material "
                           "não pode nascer sem origem")
    fato = {
        "processo_id": processo_id,
        "path": path.strip(),
        "tipo": tipo,
        "valor": valor,
        "fonte": fonte,
        "status": status,
        "confianca": max(0.0, min(1.0, float(confianca))),
        "versao": versao,
        "substitui": substitui,
    }
    fato["hash"] = hash_canonico(
        {k: fato[k] for k in ("path", "tipo", "valor", "versao")})
    return fato


# ---------------------------------------------------------------------------
# Condições estruturadas (ALL/ANY/NOT) — validação de forma; o
# AVALIADOR entra na F3 e o construtor visual do V6 reutiliza o formato
# ---------------------------------------------------------------------------
def validar_condicao(condicao: dict, _caminho: str = "condicao") -> list[str]:
    """Lista de violações de forma (vazia = bem-formada)."""
    if not isinstance(condicao, dict) or not condicao:
        return [f"{_caminho}: deve ser um objeto não vazio"]
    if "op" in condicao:
        op = condicao.get("op")
        if op not in OPERADORES_LOGICOS:
            return [f"{_caminho}: operador lógico inválido {op!r}"]
        filhos = condicao.get("children")
        if not isinstance(filhos, list) or not filhos:
            return [f"{_caminho}: {op} exige lista children não vazia"]
        if op == "NOT" and len(filhos) != 1:
            return [f"{_caminho}: NOT exige exatamente 1 filho"]
        erros = []
        for i, filho in enumerate(filhos):
            erros += validar_condicao(filho, f"{_caminho}.children[{i}]")
        return erros
    # folha: field/operator/value
    erros = []
    if not str(condicao.get("field") or "").strip():
        erros.append(f"{_caminho}: folha sem field")
    operador = condicao.get("operator")
    if operador not in OPERADORES_FOLHA:
        erros.append(f"{_caminho}: operador de folha inválido {operador!r}")
    if operador != "EXISTS" and "value" not in condicao:
        erros.append(f"{_caminho}: folha sem value")
    return erros


def nova_regra(chave_estavel: str, camada: str, condicao: dict,
               acoes: list[dict], prioridade: int = 100,
               versao: int = 1, status: str = "DRAFT",
               fontes: list | None = None, justificativa: str = "",
               vigencia_inicio: str | None = None,
               vigencia_fim: str | None = None) -> dict:
    if camada not in CAMADAS:
        raise ErroContrato(f"camada inválida: {camada!r}")
    if status not in STATUS_REGRA:
        raise ErroContrato(f"status de regra inválido: {status!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,}", chave_estavel or ""):
        raise ErroContrato(
            "chave_estavel inválida (minúsculas, dígitos, ., _, -)")
    if erros := validar_condicao(condicao):
        raise ErroContrato("condição malformada: " + "; ".join(erros))
    if not acoes:
        raise ErroContrato("regra sem ações")
    for i, acao in enumerate(acoes):
        if acao.get("type") not in TIPOS_ACAO:
            raise ErroContrato(
                f"ações[{i}]: tipo inválido {acao.get('type')!r}")
    regra = {
        "chave_estavel": chave_estavel,
        "versao": versao,
        "status": status,
        "camada": camada,
        "prioridade": int(prioridade),
        "condicao": condicao,
        "acoes": acoes,
        "vigencia_inicio": vigencia_inicio,
        "vigencia_fim": vigencia_fim,
        "fontes": list(fontes or []),
        "justificativa": justificativa,
    }
    regra["hash"] = hash_canonico(
        {k: regra[k] for k in ("chave_estavel", "versao", "camada",
                               "prioridade", "condicao", "acoes")})
    return regra


def regra_editavel(regra: dict) -> bool:
    """Publicada/revogada é IMUTÁVEL — editar = derivar nova versão."""
    return regra.get("status") in ("DRAFT", "UNDER_REVIEW")


def derivar_nova_versao(regra: dict) -> dict:
    """Cópia editável (DRAFT) com versão incrementada — jamais in-place."""
    nova = {k: v for k, v in regra.items() if k not in ("id", "hash")}
    nova["versao"] = int(regra.get("versao", 1)) + 1
    nova["status"] = "DRAFT"
    nova["hash"] = hash_canonico(
        {k: nova[k] for k in ("chave_estavel", "versao", "camada",
                              "prioridade", "condicao", "acoes")})
    return nova


# ---------------------------------------------------------------------------
# Decisão (append-only, reproduzível) — trilha da explicabilidade
# ---------------------------------------------------------------------------
def nova_decisao(processo_id: str | None, tipo_decisao: str,
                 resultado: dict, regras: list[dict],
                 fatos: list[dict], fontes: list | None = None,
                 explicacao: dict | None = None, documento: str = "",
                 ator_tipo: str = "sistema") -> dict:
    """
    Registro de decisão: aponta as VERSÕES de regras e fatos usadas e
    sela entrada/saída com hash canônico. Reexecutar com as mesmas
    versões produz o mesmo input_hash — e deve produzir o mesmo
    output_hash (reprodutibilidade auditável, KQ-014).
    """
    regras_versoes = sorted(
        ({"chave": r["chave_estavel"], "versao": r["versao"],
          "hash": r.get("hash", "")} for r in (regras or [])),
        key=lambda item: (item["chave"], item["versao"]))
    fatos_versoes = sorted(
        ({"path": f["path"], "versao": f["versao"],
          "hash": f.get("hash", "")} for f in (fatos or [])),
        key=lambda item: (item["path"], item["versao"]))
    entrada = {"tipo": tipo_decisao, "documento": documento,
               "regras": regras_versoes, "fatos": fatos_versoes,
               "fontes": sorted(fontes or [], key=str)}
    return {
        "processo_id": processo_id,
        "documento": documento,
        "tipo_decisao": tipo_decisao,
        "resultado": resultado,
        "regras_versoes": regras_versoes,
        "fatos_versoes": fatos_versoes,
        "fontes": entrada["fontes"],
        "explicacao": explicacao or {},
        "input_hash": hash_canonico(entrada),
        "output_hash": hash_canonico(resultado),
        "ator_tipo": ator_tipo,
        "criado_em": _agora(),
    }


# ---------------------------------------------------------------------------
# Aprendizado institucional — anonimização e transições (KQ-009/KQ-010)
# ---------------------------------------------------------------------------
_PADROES_SENSIVEIS = [
    (re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b"), "[CPF]"),
    (re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"), "[CNPJ]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    (re.compile(r"(?<!\d)(?:\+?55\s?)?(?:\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}(?!\d)"),
     "[TELEFONE]"),
    (re.compile(r"\bmatr[íi]cula\s*(?:n[ºo°.]?\s*)?\d+\b", re.IGNORECASE),
     "[MATRICULA]"),
]


def anonimizar_texto(texto: str) -> str:
    """Remove identificadores pessoais antes da curadoria (KQ-009)."""
    resultado = texto or ""
    for padrao, marcador in _PADROES_SENSIVEIS:
        resultado = padrao.sub(marcador, resultado)
    return resultado


def novo_feedback(processo_id: str | None, origem: str,
                  conteudo: dict) -> dict:
    """Feedback capturado — todo texto é anonimizado ANTES de gravar."""
    limpo = {
        chave: (anonimizar_texto(valor) if isinstance(valor, str)
                else valor)
        for chave, valor in (conteudo or {}).items()
    }
    return {
        "processo_id": processo_id,
        "origem": origem,
        "status": "CAPTURED",
        "conteudo": limpo,
        "evidencias": [],
    }


def transicao_feedback_valida(de: str, para: str) -> bool:
    return para in _TRANSICOES_FEEDBACK.get(de, set())


# ===========================================================================
# CENTRO DE GOVERNANÇA (pacote V6) — artefatos versionados do catálogo
# ===========================================================================
FLAG_CENTRO = "governance_center"
FLAG_CATALOGO = "clause_catalog_admin"
FLAG_POLITICAS_VISUAL = "visual_policy_builder"
FLAG_FAMILIAS_SHADOW = "model_family_resolution_shadow"
FLAG_FAMILIAS_ATIVA = "model_family_resolution_active"
FLAG_TEMPLATES = "template_builder"
FLAG_HERANCA = "tenant_inheritance_admin"
FLAG_IMPLANTACAO = "onboarding_assistant"
FLAG_PARECERES = "legal_opinion_ingestion"
FLAG_PARECERES_LOTE = "legal_opinion_batch_processing"
FLAG_LABORATORIO = "improvement_laboratory"
FLAG_PUBLICACAO_GATE = "governance_publication_gate"

FLAGS_V6 = (
    FLAG_CENTRO, FLAG_CATALOGO, FLAG_POLITICAS_VISUAL,
    FLAG_FAMILIAS_SHADOW, FLAG_FAMILIAS_ATIVA, FLAG_TEMPLATES,
    FLAG_HERANCA, FLAG_IMPLANTACAO, FLAG_PARECERES, FLAG_PARECERES_LOTE,
    FLAG_LABORATORIO, FLAG_PUBLICACAO_GATE,
)

TIPOS_ARTEFATO = ("clausula", "politica", "familia", "template")

COMPORTAMENTOS_CLAUSULA = ("FIXED_LOCKED", "FIXED_PARAMETERIZED",
                           "CONDITIONAL_LOCKED", "HYBRID", "AI_GENERATED")

# papéis do Centro (usuarios.papel_governanca; NULL = servidor comum)
PAPEIS_GOVERNANCA = ("proprietario", "admin_global", "admin_municipal",
                     "revisor_juridico", "publicador", "auditor")

ESTADOS_ARTEFATO = (
    "DRAFT", "UNDER_REVIEW", "APPROVED_FOR_SIMULATION", "SHADOW",
    "SCHEDULED", "PUBLISHED", "SUPERSEDED", "REVOKED",
)
_TRANSICOES_ARTEFATO = {
    "DRAFT": {"UNDER_REVIEW"},
    "UNDER_REVIEW": {"APPROVED_FOR_SIMULATION", "DRAFT"},
    "APPROVED_FOR_SIMULATION": {"SHADOW", "UNDER_REVIEW"},
    "SHADOW": {"SCHEDULED", "PUBLISHED", "UNDER_REVIEW"},
    "SCHEDULED": {"PUBLISHED", "UNDER_REVIEW"},
    "PUBLISHED": {"SUPERSEDED", "REVOKED"},
    "SUPERSEDED": set(),
    "REVOKED": set(),
}
ESTADOS_ARTEFATO_EDITAVEIS = ("DRAFT", "UNDER_REVIEW")


def transicao_artefato_valida(de: str, para: str) -> bool:
    return para in _TRANSICOES_ARTEFATO.get(de, set())


def versao_artefato_editavel(versao: dict) -> bool:
    """Publicada (ou além) é IMUTÁVEL — editar = derivar nova versão."""
    return versao.get("status") in ESTADOS_ARTEFATO_EDITAVEIS


# ---------------------------------------------------------------------------
# Validação de payload por tipo de artefato
# ---------------------------------------------------------------------------
def _validar_payload_clausula(payload: dict) -> list[str]:
    erros = []
    if not str(payload.get("titulo") or "").strip():
        erros.append("cláusula sem título")
    comportamento = payload.get("comportamento")
    if comportamento not in COMPORTAMENTOS_CLAUSULA:
        erros.append(f"comportamento inválido: {comportamento!r}")
    blocos_texto = payload.get("blocos")
    if not isinstance(blocos_texto, list) or not blocos_texto:
        erros.append("cláusula sem blocos de texto")
    if comportamento == "FIXED_PARAMETERIZED" and not payload.get(
            "parametros_permitidos"):
        erros.append("FIXED_PARAMETERIZED exige parametros_permitidos")
    for parametro in payload.get("parametros_obrigatorios") or []:
        if parametro not in (payload.get("parametros_permitidos") or []):
            erros.append(
                f"parâmetro obrigatório fora dos permitidos: {parametro}")
    return erros


def _validar_payload_politica(payload: dict) -> list[str]:
    erros = validar_condicao(payload.get("condicao") or {})
    acoes = payload.get("acoes")
    if not isinstance(acoes, list) or not acoes:
        erros.append("política sem ações")
    else:
        for i, acao in enumerate(acoes):
            if acao.get("type") not in TIPOS_ACAO:
                erros.append(f"ações[{i}]: tipo inválido {acao.get('type')!r}")
    if not isinstance(payload.get("prioridade", 100), int):
        erros.append("prioridade deve ser inteira")
    return erros


def _validar_payload_familia(payload: dict) -> list[str]:
    erros = []
    if not str(payload.get("nome") or "").strip():
        erros.append("família sem nome")
    if not payload.get("documentos_suportados"):
        erros.append("família sem documentos suportados")
    criterios = payload.get("criterios")
    if criterios:
        erros += validar_condicao(criterios)
    else:
        erros.append("família sem critérios de seleção")
    return erros


def _validar_payload_template(payload: dict) -> list[str]:
    erros = []
    blocos_template = payload.get("blocos")
    if not isinstance(blocos_template, list) or not blocos_template:
        return ["template sem blocos"]
    tipos_validos = ("cabecalho", "titulo", "metadados",
                     "clausula_catalogo", "secao_gerada", "tabela",
                     "lista_itens", "matriz_riscos", "assinatura",
                     "anexo", "quebra", "rodape")
    ids = set()
    for i, bloco in enumerate(blocos_template):
        if bloco.get("tipo") not in tipos_validos:
            erros.append(f"blocos[{i}]: tipo inválido {bloco.get('tipo')!r}")
        bloco_id = bloco.get("id")
        if not bloco_id or bloco_id in ids:
            erros.append(f"blocos[{i}]: id ausente ou duplicado")
        ids.add(bloco_id)
        if bloco.get("tipo") == "clausula_catalogo" and \
                not bloco.get("clausula"):
            erros.append(f"blocos[{i}]: bloco de catálogo sem cláusula")
        if bloco.get("condicao"):
            erros += validar_condicao(bloco["condicao"],
                                      f"blocos[{i}].condicao")
    return erros


_VALIDADORES_PAYLOAD = {
    "clausula": _validar_payload_clausula,
    "politica": _validar_payload_politica,
    "familia": _validar_payload_familia,
    "template": _validar_payload_template,
}


def nova_versao_artefato(tipo_artefato: str, chave_estavel: str,
                         payload: dict, versao: int = 1,
                         status: str = "DRAFT",
                         vigencia_inicio: str | None = None,
                         vigencia_fim: str | None = None) -> dict:
    """Versão de artefato validada por tipo, com hash canônico."""
    if tipo_artefato not in TIPOS_ARTEFATO:
        raise ErroContrato(f"tipo de artefato inválido: {tipo_artefato!r}")
    if status not in ESTADOS_ARTEFATO:
        raise ErroContrato(f"status de artefato inválido: {status!r}")
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,}", chave_estavel or ""):
        raise ErroContrato(
            "chave_estavel inválida (minúsculas, dígitos, ., _, -)")
    if erros := _VALIDADORES_PAYLOAD[tipo_artefato](payload or {}):
        raise ErroContrato(
            f"{tipo_artefato} inválido(a): " + "; ".join(erros))
    return {
        "tipo_artefato": tipo_artefato,
        "chave_estavel": chave_estavel,
        "versao": versao,
        "status": status,
        "vigencia_inicio": vigencia_inicio,
        "vigencia_fim": vigencia_fim,
        "payload": payload,
        "hash": hash_canonico({"tipo": tipo_artefato,
                               "chave": chave_estavel,
                               "versao": versao, "payload": payload}),
    }


def derivar_versao_artefato(versao: dict) -> dict:
    """Nova versão DRAFT derivada (a publicada permanece intocada)."""
    return nova_versao_artefato(
        versao["tipo_artefato"], versao["chave_estavel"],
        versao["payload"], versao=int(versao.get("versao", 1)) + 1,
        status="DRAFT")
