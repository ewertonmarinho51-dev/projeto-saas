"""
Modelo canônico de blocos dos documentos (Etapa 1 da correção automática
— ver pacote_correcao_automatica_documentos_v1, 01_ARQUITETURA).

Converte o Markdown de cada documento em BLOCOS endereçáveis com caminho
estável e hash — a fundação do ciclo auditoria → correção por patches →
aplicação determinística:
  - o auditor aponta findings por caminho (allowedPaths/blockedPaths);
  - o corretor propõe operações apenas nesses caminhos;
  - o aplicador valida hash e escopo antes de tocar em qualquer bloco.

Caminho estável:
  - `<doc>/preambulo/<i>`     blocos antes da primeira cláusula numerada;
  - `<doc>/clausula/<n>/<i>`  i-ésimo bloco da cláusula n (título = 0).
A âncora é o NÚMERO da cláusula no texto (mesma regex da validação),
então editar o conteúdo de um bloco não desloca o caminho dos demais.
Cláusula com número repetido ganha sufixo de ocorrência (`3.2`), para
nenhum caminho colidir mesmo em documento defeituoso.
"""

import hashlib
import re

from . import validacao

# Mesma noção de cláusula da validação — uma única fonte de verdade
_RE_CLAUSULA = validacao._RE_CLAUSULA  # noqa: SLF001

_RE_TABELA = re.compile(r"^\s*\|")


def hash_texto(texto: str) -> str:
    """SHA-256 do conteúdo (hex). Usado em blocos, documentos e bundle."""
    return hashlib.sha256((texto or "").encode()).hexdigest()


def _novo_bloco(doc_key: str, secao: str, indice: int, tipo: str,
                linhas: list[str], clausula: int | None) -> dict:
    conteudo = "\n".join(linhas).strip()
    return {
        "path": f"{doc_key}/{secao}/{indice}",
        "tipo": tipo,
        "clausula": clausula,
        "conteudo": conteudo,
        "hash": hash_texto(conteudo),
    }


def dividir_em_blocos(doc_key: str, texto: str) -> list[dict]:
    """
    Blocos do documento: títulos de cláusula, parágrafos (separados por
    linha em branco) e tabelas Markdown (linhas `|` consecutivas viram
    UM bloco, para o patch nunca cortar uma tabela ao meio).
    """
    blocos: list[dict] = []
    secao, indice, clausula = "preambulo", 0, None
    ocorrencias: dict[int, int] = {}
    atual: list[str] = []
    tipo_atual = "paragrafo"

    def fechar() -> None:
        nonlocal atual, indice
        if any(ln.strip() for ln in atual):
            blocos.append(_novo_bloco(
                doc_key, secao, indice, tipo_atual, atual, clausula))
            indice += 1
        atual = []

    for linha in (texto or "").splitlines():
        m = _RE_CLAUSULA.match(linha)
        if m:
            fechar()
            n = int(m.group(1))
            ocorrencias[n] = ocorrencias.get(n, 0) + 1
            clausula = n
            secao = (f"clausula/{n}" if ocorrencias[n] == 1
                     else f"clausula/{n}.{ocorrencias[n]}")
            indice = 0
            blocos.append(_novo_bloco(
                doc_key, secao, indice, "titulo", [linha], clausula))
            indice = 1
            tipo_atual = "paragrafo"
            continue
        eh_tabela = bool(_RE_TABELA.match(linha))
        if not linha.strip():
            fechar()
            tipo_atual = "paragrafo"
            continue
        if eh_tabela != (tipo_atual == "tabela"):
            fechar()  # transição parágrafo↔tabela fecha o bloco anterior
            tipo_atual = "tabela" if eh_tabela else "paragrafo"
        atual.append(linha)
    fechar()
    return blocos


def reconstruir(blocos: list[dict]) -> str:
    """
    Markdown do documento a partir dos blocos (forma normalizada: um
    bloco por parágrafo, separados por linha em branco). É a operação
    inversa de dividir_em_blocos — usada pelo aplicador de patches.
    """
    return "\n\n".join(b["conteudo"] for b in blocos if b["conteudo"].strip())


def localizar_bloco(blocos: list[dict], trecho: str) -> dict | None:
    """
    Bloco que contém o trecho (espaços normalizados). O trecho do
    validador carrega ±40 caracteres de contexto e pode atravessar a
    fronteira de blocos — nesse caso vale o bloco que contiver a MAIOR
    janela de palavras consecutivas do trecho (mínimo de 3, para nunca
    casar por acidente com uma palavra solta).
    """
    alvo = " ".join((trecho or "").split()).strip(" .…")
    if not alvo:
        return None
    conteudos = [(b, " ".join(b["conteudo"].split())) for b in blocos]
    for bloco, conteudo in conteudos:
        if alvo in conteudo:
            return bloco
    palavras = alvo.split()
    minimo = min(3, len(palavras))
    for tam in range(len(palavras) - 1, minimo - 1, -1):
        for i in range(len(palavras) - tam + 1):
            janela = " ".join(palavras[i:i + tam])
            for bloco, conteudo in conteudos:
                if janela in conteudo:
                    return bloco
    return None


def caminhos_de_titulos(blocos: list[dict]) -> list[str]:
    return [b["path"] for b in blocos if b["tipo"] == "titulo"]


def caminhos_da_clausula(blocos: list[dict], numero: int) -> list[str]:
    return [b["path"] for b in blocos if b.get("clausula") == numero]


# ---------------------------------------------------------------------------
# Diff estrutural entre versões (Etapa 2 — 01_ARQUITETURA/03)
# ---------------------------------------------------------------------------
def diff_estrutural(antes: list[dict], depois: list[dict]) -> dict:
    """
    Compara duas versões de um documento por caminho de bloco:
    alterados (mesmo path, hash diferente), adicionados e removidos.
    """
    h_antes = {b["path"]: b["hash"] for b in antes}
    h_depois = {b["path"]: b["hash"] for b in depois}
    return {
        "alterados": sorted(
            p for p in h_antes if p in h_depois and h_antes[p] != h_depois[p]),
        "adicionados": sorted(p for p in h_depois if p not in h_antes),
        "removidos": sorted(p for p in h_antes if p not in h_depois),
        "total_antes": len(antes),
    }


def diff_bundle(snap_antes: dict, snap_depois: dict) -> dict:
    """Diff estrutural documento a documento entre snapshots do bundle."""
    docs = set(snap_antes["documentos"]) | set(snap_depois["documentos"])
    por_doc = {}
    for doc in sorted(docs):
        por_doc[doc] = diff_estrutural(
            snap_antes["documentos"].get(doc, {}).get("blocos", []),
            snap_depois["documentos"].get(doc, {}).get("blocos", []),
        )
    return {
        "de_versao": snap_antes["versao"],
        "para_versao": snap_depois["versao"],
        "documentos": por_doc,
    }


def validar_diff(diff: dict, permitidos: list[str], bloqueados: list[str],
                 max_proporcao_blocos: float = 0.25) -> list[str]:
    """
    Regras de preservação (03_preservacao_e_diff.md) sobre o diff de UM
    documento. Retorna as violações — qualquer uma rejeita o patch
    INTEIRO (o aplicador da Etapa 4 é transacional):
      1. todo caminho alterado/adicionado/removido está em `permitidos`;
      2. nenhum caminho bloqueado foi tocado;
      3. a quantidade de alterações respeita o orçamento do ciclo.
    """
    violacoes = []
    tocados = diff["alterados"] + diff["adicionados"] + diff["removidos"]
    permitidos_set = set(permitidos)
    for path in tocados:
        if path not in permitidos_set:
            violacoes.append(f"alteração fora do escopo autorizado: {path}")
    for path in tocados:
        if path in set(bloqueados):
            violacoes.append(f"alteração em caminho bloqueado: {path}")
    total = max(diff.get("total_antes") or 0, 1)
    proporcao = len(tocados) / total
    if tocados and proporcao > max_proporcao_blocos:
        violacoes.append(
            f"orçamento de alterações excedido: {len(tocados)}/{total} "
            f"blocos ({proporcao:.0%} > {max_proporcao_blocos:.0%})")
    return violacoes


# ---------------------------------------------------------------------------
# Snapshot versionado do bundle (dossiê completo)
# ---------------------------------------------------------------------------
def snapshot_documento(doc_key: str, texto: str) -> dict:
    return {
        "documento": doc_key,
        "hash": hash_texto(texto or ""),
        "blocos": dividir_em_blocos(doc_key, texto or ""),
    }


def hash_bundle(documentos: dict[str, str]) -> str:
    """Hash do dossiê: estável para o mesmo conteúdo, em qualquer ordem."""
    partes = [f"{k}:{hash_texto(v or '')}" for k, v in sorted(documentos.items())]
    return hash_texto("\n".join(partes))


def snapshot_bundle(documentos: dict[str, str], versao: int = 1) -> dict:
    """
    Snapshot imutável de uma versão do bundle — base do diff estrutural
    e da validação de hash antes de aplicar patches (Etapas 2+).
    """
    return {
        "versao": versao,
        "hash": hash_bundle(documentos),
        "documentos": {
            k: snapshot_documento(k, v) for k, v in documentos.items()
        },
    }
