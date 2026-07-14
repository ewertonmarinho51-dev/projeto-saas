"""
Políticas de aplicação (Fase 3 do Centro de Governança V6).

Políticas são ARTEFATOS versionados do catálogo (tipo "politica") cujo
payload usa o MESMO formato de condições/ações do motor de conhecimento
V5 — o construtor visual só monta o que o motor já executa por código.

O que este módulo garante:
  - ponte catálogo → motor: `regras_publicadas()` converte as políticas
    PUBLICADAS (na vigência) para o formato de regra do V5, com a CAMADA
    derivada do escopo do artefato (tenant NULL = plataforma;
    secretaria_id = secretaria; senão município) — nunca escolhida à mão;
  - conflito detectado ANTES da publicação (T06): ação oposta sobre o
    mesmo alvo, na mesma camada e prioridade, sem condições provadamente
    disjuntas → `publicar` recusa e expõe as duas políticas;
  - simulação (T04/T05): a política candidata roda contra um contexto de
    teste no motor REAL (conhecimento.resolver) e o resultado é gravado
    em `simulacoes` — o administrador vê o efeito antes de publicar.

Flag `flag_visual_policy_builder`: liga o módulo na página Governança e
a entrada das políticas publicadas no motor. OFF = nada muda.
"""

from . import auth, catalogo, conhecimento, db, governanca


class ErroPolitica(Exception):
    """Operação de política recusada (conflito, papel ou contrato)."""


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_POLITICAS_VISUAL)


# ---------------------------------------------------------------------------
# Criação (payload validado pelo contrato de artefato "politica")
# ---------------------------------------------------------------------------
def criar_politica(chave_estavel: str, condicao: dict, acoes: list[dict],
                   prioridade: int = 100, justificativa: str = "",
                   fontes: list | None = None,
                   plataforma: bool = False) -> tuple[dict, dict]:
    payload = {
        "condicao": condicao,
        "acoes": acoes,
        "prioridade": int(prioridade),
        "justificativa": justificativa,
        "fontes": list(fontes or []),
    }
    return catalogo.criar_artefato("politica", chave_estavel, payload,
                                   plataforma)


# ---------------------------------------------------------------------------
# Ponte catálogo → motor de conhecimento (camada vem do ESCOPO)
# ---------------------------------------------------------------------------
def _camada_do_artefato(artefato: dict) -> str:
    if artefato.get("tenant_id") is None:
        return "plataforma"
    if artefato.get("secretaria_id"):
        return "secretaria"
    return "municipio"


def como_regra(artefato: dict, versao: dict) -> dict:
    payload = versao.get("payload") or {}
    return governanca.nova_regra(
        artefato["chave_estavel"],
        _camada_do_artefato(artefato),
        payload.get("condicao") or {},
        payload.get("acoes") or [],
        prioridade=payload.get("prioridade", 100),
        versao=versao.get("versao", 1),
        status="PUBLISHED" if versao.get("status") == "PUBLISHED"
        else "DRAFT",
        fontes=payload.get("fontes"),
        justificativa=payload.get("justificativa", ""),
        vigencia_inicio=versao.get("vigencia_inicio"),
        vigencia_fim=versao.get("vigencia_fim"),
    )


def regras_publicadas() -> list[dict]:
    """Políticas PUBLICADAS do catálogo no formato do motor V5."""
    regras = []
    for item in catalogo.listar_com_situacao("politica"):
        if item["publicada"]:
            regras.append(como_regra(item["artefato"], item["publicada"]))
    return regras


# ---------------------------------------------------------------------------
# Conflitos ANTES da publicação (T06)
# ---------------------------------------------------------------------------
def _restricoes_eq(condicao: dict) -> dict:
    """Campos com igualdade constante (para provar disjunção simples)."""
    restricoes: dict = {}
    if "op" in condicao:
        if condicao["op"] != "ALL":
            return {}  # ANY/NOT: sem prova simples de disjunção
        for filho in condicao.get("children", []):
            restricoes.update(_restricoes_eq(filho))
        return restricoes
    if condicao.get("operator") == "EQ":
        restricoes[condicao.get("field")] = condicao.get("value")
    return restricoes


def _disjuntas(cond_a: dict, cond_b: dict) -> bool:
    """True se as condições NUNCA valem juntas (EQ oposto no mesmo campo)."""
    a, b = _restricoes_eq(cond_a), _restricoes_eq(cond_b)
    return any(campo in b and b[campo] != valor
               for campo, valor in a.items())


def _alvos(payload: dict) -> dict[str, str]:
    """{alvo: INCLUIR|EXCLUIR} das ações de cláusula da política."""
    alvos = {}
    for acao in payload.get("acoes", []):
        if acao.get("type") in ("INCLUIR_CLAUSULA", "EXCLUIR_CLAUSULA"):
            alvos[acao.get("target")] = acao["type"]
    return alvos


def detectar_conflitos(artefato: dict, payload: dict) -> list[dict]:
    """
    Conflito NÃO determinístico com políticas já publicadas: mesmo alvo,
    ação oposta, mesma camada e prioridade, condições não disjuntas.
    """
    camada = _camada_do_artefato(artefato)
    prioridade = payload.get("prioridade", 100)
    meus_alvos = _alvos(payload)
    conflitos = []
    for item in catalogo.listar_com_situacao("politica"):
        outra, publicada = item["artefato"], item["publicada"]
        if not publicada or outra["id"] == artefato.get("id"):
            continue
        outro_payload = publicada.get("payload") or {}
        if _camada_do_artefato(outra) != camada or \
                outro_payload.get("prioridade", 100) != prioridade:
            continue  # camada/prioridade diferentes: precedência resolve
        for alvo, acao in _alvos(outro_payload).items():
            minha = meus_alvos.get(alvo)
            if minha and minha != acao and not _disjuntas(
                    payload.get("condicao") or {},
                    outro_payload.get("condicao") or {}):
                conflitos.append({
                    "clausula": alvo,
                    "politica": outra["chave_estavel"],
                    "versao": publicada["versao"],
                    "motivo": ("ação oposta na mesma camada e prioridade, "
                               "sem condição que as separe"),
                })
    return conflitos


def publicar(artefato: dict, versao: dict,
             vigencia_inicio: str | None = None) -> dict:
    """Publica SOMENTE sem conflitos não determinísticos (T06)."""
    conflitos = detectar_conflitos(artefato, versao.get("payload") or {})
    if conflitos:
        detalhes = "; ".join(
            f"{c['politica']} v{c['versao']} sobre {c['clausula']}"
            for c in conflitos)
        raise ErroPolitica(
            f"Publicação bloqueada por conflito com: {detalhes}. Ajuste a "
            "prioridade, a camada ou as condições — o sistema não escolhe "
            "sozinho.")
    return catalogo.transicionar(artefato, versao, "PUBLISHED",
                                 vigencia_inicio)


# ---------------------------------------------------------------------------
# Simulação (T04/T05) — o efeito ANTES de publicar
# ---------------------------------------------------------------------------
def _fatos_de_contexto(contexto: dict) -> list[dict]:
    fatos = []
    for path, valor in (contexto or {}).items():
        tipo = ("booleano" if isinstance(valor, bool)
                else "numero" if isinstance(valor, (int, float))
                else "lista" if isinstance(valor, list) else "texto")
        fatos.append(governanca.novo_fato(
            None, path, valor, tipo, "simulacao:contexto",
            status="confirmado", confianca=1.0))
    return fatos


def simular(artefato: dict, versao: dict, contexto: dict) -> dict:
    """
    Roda a política candidata (+ as publicadas) no motor real contra um
    contexto de teste. Persiste em `simulacoes` e retorna a decisão.
    """
    candidata = como_regra(artefato, versao)
    candidata["status"] = "PUBLISHED"  # só na simulação, em memória
    demais = [r for r in regras_publicadas()
              if r["chave_estavel"] != candidata["chave_estavel"]]
    decisao = conhecimento.resolver(
        _fatos_de_contexto(contexto), [candidata] + demais, set(), None,
        documento="simulacao")
    if db.disponivel():
        try:
            db._cliente().table("simulacoes").insert({  # noqa: SLF001
                "tenant_id": db.tenant_atual(),
                "alvo": {"chave": artefato["chave_estavel"],
                         "versao": versao.get("versao")},
                "contexto": contexto,
                "resultado": decisao["resultado"],
            }).execute()
        except Exception:  # noqa: BLE001 — simulação nunca é bloqueada
            pass
    return decisao
