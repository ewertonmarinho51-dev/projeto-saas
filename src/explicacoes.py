"""
Explicabilidade (Fase 4 do pacote V5).

Transforma REGISTROS DE DECISÃO já gravados (conhecimento.resolver /
tabela `decisoes`) em explicações legíveis, em três níveis:
  - usuário : linguagem clara, sem jargão técnico;
  - admin   : regras, camadas, fontes e condições observadas;
  - auditor : versões, hashes, trilha completa e reprodutibilidade.

Princípio inegociável (04_EXPLICABILIDADE do pacote): NADA é inventado.
Este módulo é 100% determinístico — só reordena e verbaliza campos que
existem no registro. Sem registro correspondente, a resposta é
"não há registro", nunca uma justificativa plausível. Nenhum modelo de
IA participa.

Feature flag `flag_explanations` (default OFF): controla apenas a
EXIBIÇÃO ("Por que isso está aqui?" na tela final); os registros de
decisão existem desde a Fase 3 independentemente da flag.
"""

from . import db, governanca

# Rótulos amigáveis para os paths de fatos mais comuns (fallback: path)
_ROTULOS_FATO = {
    "procedimento.srp": "uso do Sistema de Registro de Preços",
    "procedimento.execucao_continuada": "execução continuada do serviço",
    "objeto.natureza": "natureza do objeto",
    "objeto.descricao": "descrição do objeto",
    "valor.total": "valor global estimado",
    "prazo.descricao": "prazo pretendido",
    "orgao.nome": "órgão requisitante",
    "execucao.modelo": "modelo de execução",
}

_ROTULOS_OPERADOR = {
    "EQ": "é", "NEQ": "é diferente de", "GT": "é maior que",
    "GTE": "é pelo menos", "LT": "é menor que", "LTE": "é no máximo",
    "IN": "está entre", "CONTAINS": "contém", "EXISTS": "foi informado",
}


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_EXPLICACOES)


def _valor_legivel(valor) -> str:
    if valor is True:
        return "sim"
    if valor is False:
        return "não"
    if valor is None:
        return "—"
    if isinstance(valor, list):
        return ", ".join(str(v) for v in valor)
    return str(valor)


def _rotulo(path: str) -> str:
    return _ROTULOS_FATO.get(path, path)


# ---------------------------------------------------------------------------
# Cadeia fonte → fato → regra → decisão (somente do registro)
# ---------------------------------------------------------------------------
def _trilha(decisao: dict) -> list[dict]:
    return (decisao.get("explicacao") or {}).get("regras_avaliadas", [])


def _regras_da_clausula(decisao: dict, clausula: str,
                        tipos=("INCLUIR_CLAUSULA",
                               "EXCLUIR_CLAUSULA")) -> list[dict]:
    return [
        entrada for entrada in _trilha(decisao)
        if entrada.get("satisfeita")
        and any(a.get("type") in tipos and a.get("target") == clausula
                for a in entrada.get("acoes", []))
    ]


def explicar_clausula(decisao: dict, clausula: str) -> dict | None:
    """
    Por que a cláusula entrou (ou saiu)? SOMENTE a partir do registro:
    sem regra registrada para a cláusula, retorna None — o explicador
    jamais fabrica justificativa (KQ-008).
    """
    entradas = _regras_da_clausula(decisao, clausula)
    if not entradas:
        return None
    condicoes = [
        {
            "fato": folha["field"],
            "rotulo": _rotulo(folha["field"]),
            "operador": folha["operator"],
            "esperado": folha.get("value"),
            "observado": folha.get("valor_observado"),
        }
        for entrada in entradas
        for folha in entrada.get("folhas", [])
        if folha.get("satisfeita")
    ]
    return {
        "clausula": clausula,
        "regras": [{"chave": e["chave"], "versao": e["versao"],
                    "camada": e["camada"],
                    "justificativa": e.get("justificativa", "")}
                   for e in entradas],
        "condicoes": condicoes,
        "fontes": sorted({f for e in entradas
                          for f in e.get("fontes", [])}),
    }


# ---------------------------------------------------------------------------
# Nível usuário: linguagem clara
# ---------------------------------------------------------------------------
def texto_usuario(explicacao: dict) -> str:
    partes = []
    for condicao in explicacao["condicoes"]:
        alvo = ("" if condicao["operador"] == "EXISTS"
                else f" {_valor_legivel(condicao['esperado'])}")
        partes.append(
            f"{condicao['rotulo']} "
            f"{_ROTULOS_OPERADOR.get(condicao['operador'], condicao['operador'])}"
            f"{alvo} (informado no processo: "
            f"{_valor_legivel(condicao['observado'])})"
        )
    regras = ", ".join(
        f"{r['chave']} v{r['versao']} ({r['camada']})"
        for r in explicacao["regras"])
    frase = (f"A cláusula `{explicacao['clausula']}` se aplica porque "
             + "; ".join(partes) if partes else
             f"A cláusula `{explicacao['clausula']}` se aplica por regra "
             "institucional")
    frase += f". Regra: {regras}."
    if explicacao["fontes"]:
        frase += " Fontes: " + ", ".join(explicacao["fontes"]) + "."
    return frase


# ---------------------------------------------------------------------------
# Nível admin e nível auditor
# ---------------------------------------------------------------------------
def texto_admin(decisao: dict) -> list[str]:
    """Uma linha por regra avaliada: satisfeita ou não, e por quê."""
    linhas = []
    for entrada in _trilha(decisao):
        situacao = "SATISFEITA" if entrada.get("satisfeita") else "não se aplica"
        condicoes = "; ".join(
            f"{_rotulo(f['field'])}={_valor_legivel(f.get('valor_observado'))}"
            for f in entrada.get("folhas", []))
        linhas.append(
            f"{entrada['chave']} v{entrada['versao']} "
            f"[{entrada['camada']}/p{entrada['prioridade']}] — {situacao}"
            + (f" ({condicoes})" if condicoes else ""))
    for ignorada in (decisao.get("explicacao") or {}).get(
            "regras_ignoradas", []):
        linhas.append(f"{ignorada['chave']} — ignorada: {ignorada['motivo']}")
    return linhas


def registro_auditor(decisao: dict) -> dict:
    """Nível auditor: tudo que permite REPRODUZIR a decisão."""
    return {
        "tipo_decisao": decisao.get("tipo_decisao"),
        "input_hash": decisao.get("input_hash"),
        "output_hash": decisao.get("output_hash"),
        "regras_versoes": decisao.get("regras_versoes", []),
        "fatos_versoes": decisao.get("fatos_versoes", []),
        "fontes": decisao.get("fontes", []),
        "criado_em": decisao.get("criado_em"),
        "ator_tipo": decisao.get("ator_tipo"),
    }
