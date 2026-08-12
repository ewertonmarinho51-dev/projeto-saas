"""
Identidade das normas citadas — `norma:dispositivo`.

Um número de artigo, sozinho, não identifica nada: o art. 84 da Lei nº
14.133/2021 (vigência da ata) nada tem a ver com o art. 84 de outra lei.
Toda verificação de fundamentação do sistema — o mapa canônico
(prompts.py), o lastro recuperado pelo RAG (rag.py) e a checagem de
citações (validacao.py) — usa a MESMA identidade produzida aqui:

    lei_14133_2021:84    lc_123_2006:42    lei_13709_2018:7

Este módulo só normaliza referências; não interpreta direito nem decide
aplicabilidade.
"""

import re

# Norma de referência dos documentos da fase preparatória: quando o texto
# cita "art. 84" sem dizer de qual lei, é dela que se está falando (todos
# os perfis e instruções do sistema são construídos sobre ela). A
# suposição é explícita — e só vale para a citação sem norma declarada.
NORMA_PADRAO = "lei_14133_2021"

# Apelidos frequentes → identidade canônica
_APELIDOS = (
    (re.compile(r"lei\s+de\s+licita[çc][õo]es|nova\s+lei\s+de\s+licita",
                re.IGNORECASE), "lei_14133_2021"),
    (re.compile(r"\bLGPD\b|lei\s+geral\s+de\s+prote[çc][ãa]o\s+de\s+dados",
                re.IGNORECASE), "lei_13709_2018"),
    (re.compile(r"estatuto\s+d[ao]s?\s+microempresas?", re.IGNORECASE),
     "lc_123_2006"),
)

# Número da norma ("14.133") e o ano, com a data por extenso no meio:
# "Lei nº 14.133, de 1º de abril de 2021" e "Lei 14.133/2021".
_NUMERO = r"(\d{1,5}(?:\.\d{3})*)"
_ATE_O_ANO = (r"\s*(?:[/,]\s*|\s+de\s+)"
              r"(?:(?:de\s+)?\d{1,2}[º°]?\s+de\s+[^\s]+\s+de\s+)?(\d{4})")
_NUM = r"(?:n?[º°o]?\.?\s*)?"

# "Lei Complementar nº 123, de 2006" / "LC nº 123/2006"
_RE_COMPLEMENTAR = re.compile(
    rf"\b(?:lei\s+complementar|LC)\s*{_NUM}{_NUMERO}{_ATE_O_ANO}",
    re.IGNORECASE)
_RE_LEI = re.compile(
    rf"\blei\s*(?:federal\s*)?{_NUM}{_NUMERO}{_ATE_O_ANO}", re.IGNORECASE)
# "Decreto nº 11.462/2023", "Decreto Municipal nº 123/2024"
_RE_DECRETO = re.compile(
    rf"\bdecreto\s*(?:federal\s*|estadual\s*|municipal\s*)?{_NUM}"
    rf"{_NUMERO}{_ATE_O_ANO}", re.IGNORECASE)
# "Instrução Normativa SEGES nº 65/2021"
_RE_IN = re.compile(
    r"\b(?:instru[çc][ãa]o\s+normativa|IN)\s+([A-Z]{2,10})?\s*"
    r"(?:n?[º°o]?\.?\s*)?(\d{1,4})\s*[/]\s*(\d{4})", re.IGNORECASE)
# Normas técnicas e regulamentadoras: "NR-6", "ABNT NBR 15575"
_RE_NR = re.compile(r"\bNR\s*-?\s*(\d{1,2})\b", re.IGNORECASE)
_RE_NBR = re.compile(r"\bNBR\s*(\d{3,5})\b", re.IGNORECASE)


def _numero(bruto: str) -> str:
    return bruto.replace(".", "")


def identificar_norma(texto: str) -> str:
    """
    Identidade da PRIMEIRA norma reconhecida no texto ("" se nenhuma).
    A ordem importa: lei complementar antes de lei comum, para que
    "Lei Complementar nº 123/2006" não vire `lei_123_2006`.
    """
    texto = texto or ""
    m = _RE_COMPLEMENTAR.search(texto)
    if m:
        return f"lc_{_numero(m.group(1))}_{m.group(2)}"
    m = _RE_LEI.search(texto)
    if m:
        return f"lei_{_numero(m.group(1))}_{m.group(2)}"
    m = _RE_DECRETO.search(texto)
    if m:
        return f"decreto_{_numero(m.group(1))}_{m.group(2)}"
    m = _RE_IN.search(texto)
    if m:
        orgao = (m.group(1) or "").lower()
        return f"in_{orgao + '_' if orgao else ''}{m.group(2)}_{m.group(3)}"
    m = _RE_NR.search(texto)
    if m:
        return f"nr_{m.group(1)}"
    m = _RE_NBR.search(texto)
    if m:
        return f"nbr_{m.group(1)}"
    for padrao, identidade in _APELIDOS:
        if padrao.search(texto):
            return identidade
    return ""


def dispositivo(norma: str, artigo: str) -> str:
    """Identidade completa de um dispositivo: `norma:artigo`."""
    return f"{norma}:{artigo}"
