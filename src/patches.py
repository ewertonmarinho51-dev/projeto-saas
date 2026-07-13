"""
Aplicador determinístico de patches (Etapa 4 da correção automática —
pacote_correcao_automatica_documentos_v1, 01_ARQUITETURA).

A IA propõe (corretor.py); ESTE código valida e aplica. A aplicação é
TRANSACIONAL: primeiro todas as pré-condições, depois a aplicação em
cópia, depois todas as pós-condições — qualquer violação em qualquer
fase rejeita o plano INTEIRO e o bundle original permanece intocado.

Camadas de defesa (em ordem):
  1. hash/versão de origem: o plano só vale para o bundle exato que o
     originou (documento editado depois = plano descartado);
  2. revalidação do plano (corretor.validar_plano) — defesa em
     profundidade, não confia que o chamador validou;
  3. cláusulas fixas dos perfis: FIXED_LOCKED nunca muda;
     FIXED_PARAMETERIZED só aceita mudança de PARÂMETROS (números,
     valores, datas, percentuais) com a prosa preservada;
  4. diff estrutural pós-aplicação com granularidade de CLÁUSULA: as
     operações são exatas por bloco, mas o resultado é conferido por
     cláusula (um replace que vira dois parágrafos continua dentro da
     cláusula autorizada; qualquer efeito em cláusula não autorizada
     rejeita tudo);
  5. orçamento do ciclo: no máximo `max_proporcao_blocos` dos blocos do
     bundle alterados de uma vez.

Feature flag `flag_correcao_automatica` (default OFF): consultada pelo
ORQUESTRADOR do ciclo (Etapa 5) — este módulo é função pura e não lê
flag nem banco.
"""

import re

from . import blocos, corretor, perfis

FLAG_APLICACAO = "correcao_automatica"

MAX_PROPORCAO_BLOCOS = 0.25  # orçamento padrão de alterações por ciclo


class ErroAplicacao(Exception):
    """Plano rejeitado — nenhuma alteração foi aplicada."""


# ---------------------------------------------------------------------------
# FIXED_PARAMETERIZED: só parâmetros podem mudar
# ---------------------------------------------------------------------------
# classes de parâmetro autorizadas: moeda, data, número/percentual
_RE_PARAMETRO = re.compile(
    r"R\$\s?[\d.,]+|\d{2}/\d{2}/\d{4}|\d+(?:[.,]\d+)?\s*%?")


def _esqueleto(texto: str) -> str:
    """Texto com os parâmetros mascarados — o que NÃO pode mudar."""
    return _RE_PARAMETRO.sub("§", " ".join((texto or "").split()))


def parametros_compativeis(antigo: str, novo: str) -> bool:
    """True se apenas parâmetros autorizados diferem entre as versões."""
    return _esqueleto(antigo) == _esqueleto(novo)


# ---------------------------------------------------------------------------
# Utilidades de caminho (granularidade de cláusula)
# ---------------------------------------------------------------------------
def _prefixo_clausula(path: str) -> str:
    """'dfd/clausula/2/1' → 'dfd/clausula/2'; 'dfd/preambulo/0' → 'dfd/preambulo'."""
    partes = path.split("/")
    tamanho = 3 if len(partes) > 1 and partes[1] == "clausula" else 2
    return "/".join(partes[:tamanho])


def _numero_da_clausula(path: str) -> int | None:
    partes = path.split("/")
    if len(partes) < 3 or partes[1] != "clausula":
        return None
    return int(str(partes[2]).split(".")[0])


# ---------------------------------------------------------------------------
# Validações específicas da aplicação
# ---------------------------------------------------------------------------
def _validar_clausulas_fixas(plano: dict, snapshot: dict) -> list[str]:
    violacoes = []
    hashes_conteudo = {
        b["path"]: b["conteudo"]
        for doc in snapshot["documentos"].values() for b in doc["blocos"]
    }
    for i, op in enumerate(plano["operations"]):
        rotulo = f"operação {i + 1}"
        doc_key = (op.get("path") or "").split("/")[0]
        numero = _numero_da_clausula(op.get("path") or "")
        if numero is None:
            continue
        fixa = perfis.clausulas_fixas(doc_key).get(numero)
        if fixa == "LOCKED":
            violacoes.append(
                f"{rotulo}: cláusula {numero} do {doc_key} é FIXED_LOCKED "
                "— a IA não pode alterá-la")
        elif fixa == "PARAMETERIZED":
            if op.get("op") != "replace":
                violacoes.append(
                    f"{rotulo}: cláusula {numero} do {doc_key} é "
                    "FIXED_PARAMETERIZED — só aceita substituição de "
                    "parâmetros (sem adicionar/remover blocos)")
            elif not parametros_compativeis(
                hashes_conteudo.get(op["path"], ""),
                str(op.get("newValue") or ""),
            ):
                violacoes.append(
                    f"{rotulo}: cláusula {numero} do {doc_key} é "
                    "FIXED_PARAMETERIZED — apenas números, valores, datas "
                    "e percentuais podem mudar; a prosa foi alterada")
    return violacoes


def _validar_diff_por_clausula(diff_bundle: dict, permitidos: set[str],
                               bloqueados: set[str],
                               max_proporcao: float) -> list[str]:
    """Pós-condições sobre o diff (granularidade de cláusula) + orçamento."""
    violacoes = []
    prefixos_permitidos = {_prefixo_clausula(p) for p in permitidos}
    prefixos_bloqueados = {_prefixo_clausula(p) for p in bloqueados}
    tocados_total, blocos_total = 0, 0
    for doc, diff in diff_bundle["documentos"].items():
        tocados = diff["alterados"] + diff["adicionados"] + diff["removidos"]
        tocados_total += len(tocados)
        blocos_total += diff.get("total_antes") or 0
        for path in tocados:
            prefixo = _prefixo_clausula(path)
            if prefixo in prefixos_bloqueados:
                violacoes.append(
                    f"{doc}: alteração em cláusula bloqueada ({path})")
            elif prefixo not in prefixos_permitidos:
                violacoes.append(
                    f"{doc}: alteração fora do escopo autorizado ({path})")
    proporcao = tocados_total / max(blocos_total, 1)
    if tocados_total and proporcao > max_proporcao:
        violacoes.append(
            f"orçamento do ciclo excedido: {tocados_total}/{blocos_total} "
            f"blocos alterados ({proporcao:.0%} > {max_proporcao:.0%})")
    return violacoes


# ---------------------------------------------------------------------------
# Aplicação em memória (cópia) — nunca toca o bundle original
# ---------------------------------------------------------------------------
def _aplicar_no_documento(doc_key: str, texto: str,
                          operacoes: list[dict]) -> str:
    bloclist = blocos.dividir_em_blocos(doc_key, texto)
    indice = {b["path"]: i for i, b in enumerate(bloclist)}
    conteudos: list[str | None] = [b["conteudo"] for b in bloclist]

    insercoes: list[tuple[int, str]] = []
    for op in operacoes:
        path, novo = op["path"], str(op.get("newValue") or "").strip()
        if op["op"] == "replace":
            conteudos[indice[path]] = novo
        elif op["op"] == "remove":
            conteudos[indice[path]] = None
        elif op["op"] == "add":
            numero = _numero_da_clausula(path)
            posicao = len(bloclist)
            if numero is not None:
                existentes = [i for i, b in enumerate(bloclist)
                              if b.get("clausula") == numero]
                if existentes:
                    posicao = existentes[-1] + 1  # fim da própria cláusula
                else:
                    posteriores = [
                        i for i, b in enumerate(bloclist)
                        if (b.get("clausula") or 0) > numero
                    ]
                    if posteriores:
                        posicao = posteriores[0]  # antes da cláusula seguinte
            insercoes.append((posicao, novo))

    partes: list[str] = []
    for i, conteudo in enumerate(conteudos):
        partes.extend(txt for pos, txt in insercoes if pos == i)
        if conteudo:
            partes.append(conteudo)
    partes.extend(txt for pos, txt in insercoes if pos >= len(conteudos))
    return "\n\n".join(partes)


# ---------------------------------------------------------------------------
# Entrada única: aplicar o plano (transacional)
# ---------------------------------------------------------------------------
def aplicar_plano(plano: dict, documentos: dict[str, str], relatorio: dict,
                  max_proporcao_blocos: float = MAX_PROPORCAO_BLOCOS) -> dict:
    """
    Aplica o plano sobre o bundle e retorna
    {"documentos", "snapshot", "diff", "versao"} da NOVA versão.
    Levanta ErroAplicacao (sem efeito colateral) em qualquer violação.
    """
    versao_origem = plano["sourceBundleVersion"]
    snap_antes = blocos.snapshot_bundle(documentos, versao=versao_origem)

    # 1. o plano só vale para o bundle exato que o originou
    if plano["sourceBundleHash"] != snap_antes["hash"]:
        raise ErroAplicacao(
            "o conteúdo dos documentos mudou depois que o plano foi "
            "criado (hash de origem divergente) — gere um novo plano")

    # 2. revalidação completa do plano (defesa em profundidade)
    violacoes = corretor.validar_plano(plano, relatorio, snap_antes)
    # 3. cláusulas fixas de governança (perfis.py)
    violacoes += _validar_clausulas_fixas(plano, snap_antes)
    if violacoes:
        raise ErroAplicacao("; ".join(violacoes))

    # 4. aplicação em cópia
    por_doc: dict[str, list[dict]] = {}
    for op in plano["operations"]:
        por_doc.setdefault(op["path"].split("/")[0], []).append(op)
    novos = dict(documentos)
    for doc_key, operacoes in por_doc.items():
        novos[doc_key] = _aplicar_no_documento(
            doc_key, documentos.get(doc_key, ""), operacoes)

    # 5. pós-condições: diff estrutural, escopo por cláusula e orçamento
    snap_depois = blocos.snapshot_bundle(novos, versao=versao_origem + 1)
    diff = blocos.diff_bundle(snap_antes, snap_depois)
    findings_usados = {op["findingId"] for op in plano["operations"]}
    permitidos = {
        p for f in relatorio["findings"]
        if f["findingId"] in findings_usados for p in f["allowedPaths"]
    }
    bloqueados = {
        p for f in relatorio["findings"] for p in f["blockedPaths"]
    }
    violacoes = _validar_diff_por_clausula(
        diff, permitidos, bloqueados, max_proporcao_blocos)
    if violacoes:
        raise ErroAplicacao("; ".join(violacoes))

    return {
        "documentos": novos,
        "snapshot": snap_depois,
        "diff": diff,
        "versao": versao_origem + 1,
    }
