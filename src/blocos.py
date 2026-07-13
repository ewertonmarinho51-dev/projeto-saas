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
from .config import DOCUMENTOS

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
            k: snapshot_documento(k, v)
            for k, v in documentos.items() if k in DOCUMENTOS
        },
    }
