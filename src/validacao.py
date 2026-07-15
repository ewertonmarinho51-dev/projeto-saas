"""
Validação automática dos documentos ANTES da emissão (download).

Duas gravidades:
  - "bloqueia": impede o download do documento final (pendências de
    preenchimento, placeholders, vazamento de mecânica interna);
  - "aviso":   não impede, mas é exibido na revisão (profundidade abaixo
    do perfil, cláusula obrigatória ausente, numeração fora de ordem).

O objetivo é garantir que campos pendentes fiquem na etapa de REVISÃO do
sistema — nunca no PDF/DOCX definitivo — e que o documento final siga o
padrão dos documentos aprovados (perfis.py).
"""

import re
import unicodedata

from . import perfis
from .config import DOCUMENTOS

# Padrões que NUNCA podem aparecer no documento final (bloqueiam)
_BLOQUEANTES = [
    (re.compile(r"\[PREENCHER[^\]]*\]?", re.IGNORECASE), "campo pendente [PREENCHER]"),
    (re.compile(r"\[\[TABELA_ITENS\]\]"), "marcador interno de tabela não substituído"),
    (re.compile(r"\bplaceholder\b", re.IGNORECASE), "texto 'placeholder'"),
    (re.compile(r"formul[áa]rio[- ]matriz", re.IGNORECASE),
     "menção ao formulário interno do sistema"),
    (re.compile(r"\bcomo (modelo de linguagem|intelig[êe]ncia artificial|IA generativa)\b",
                re.IGNORECASE), "menção à IA/modelo de linguagem"),
    (re.compile(r"\b(system prompt|prompt do sistema|prompt recebido)\b", re.IGNORECASE),
     "menção a prompt do sistema"),
    (re.compile(r"base de conhecimento do sistema", re.IGNORECASE),
     "menção à base interna do sistema"),
    # Etiqueta de procedência INTERNA vazada no corpo (ex.: "(fonte:
    # formulário)") — a origem do dado não pode aparecer no ato. Mira só
    # o formulário/matriz (mecânica interna); referências legítimas a
    # documentos reais do processo (planilha orçamentária, memorando,
    # anexos) NÃO são vazamento e não entram aqui.
    (re.compile(r"\(\s*fonte:\s*(o\s+)?(formul[áa]rio|matriz|"
                r"dados do formul)\b[^)]*\)", re.IGNORECASE),
     "etiqueta de origem interna ('(fonte: formulário)') no texto"),
    (re.compile(r"\bconforme\s+(o\s+)?formul[áa]rio\b", re.IGNORECASE),
     "referência à mecânica interna ('conforme o formulário')"),
]

# Aberturas meta-descritivas: a cláusula descreve o que deveria conter em
# vez de trazer o conteúdo real (ex.: "Descrição da necessidade…",
# "Indicação da solução proposta…"). Sinalizam cláusula não desenvolvida.
_RE_META_DESCRITIVA = re.compile(
    r"^\s*(descri[çc][ãa]o|indica[çc][ãa]o|especifica[çc][ãa]o|"
    r"identifica[çc][ãa]o|apresenta[çc][ãa]o)\s+d[aeo]s?\b"
    r"[^.]*\b(conforme|segundo|com base n)[^.]*\bformul[áa]rio\b",
    re.IGNORECASE)

_RE_CLAUSULA = re.compile(r"(?m)^#{1,3}\s*(\d{1,2})\s*[\.\-–]?\s+(.+?)\s*$")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9 ]", " ", t.upper()).strip()


def _achado(doc_key: str, gravidade: str, mensagem: str, trecho: str = "") -> dict:
    return {
        "doc": doc_key,
        "documento": DOCUMENTOS.get(doc_key, {}).get("sigla", doc_key.upper()),
        "gravidade": gravidade,
        "mensagem": mensagem,
        "trecho": (trecho or "").strip()[:160],
    }


def _validar_bloqueantes(doc_key: str, texto: str) -> list[dict]:
    achados = []
    for padrao, rotulo in _BLOQUEANTES:
        ocorrencias = list(padrao.finditer(texto))
        if ocorrencias:
            m = ocorrencias[0]
            ini = max(0, m.start() - 40)
            achados.append(_achado(
                doc_key, "bloqueia",
                f"{rotulo} ({len(ocorrencias)} ocorrência(s))",
                texto[ini:m.end() + 40].replace("\n", " "),
            ))
    return achados


def _clausulas_do_texto(texto: str) -> list[tuple[int, str]]:
    return [(int(n), t) for n, t in _RE_CLAUSULA.findall(texto)]


def _validar_estrutura(doc_key: str, texto: str) -> list[dict]:
    """Numeração, cláusulas obrigatórias, títulos vazios e profundidade."""
    achados: list[dict] = []
    clausulas = _clausulas_do_texto(texto)

    if clausulas:
        numeros = [n for n, _ in clausulas]
        duplicados = sorted({n for n in numeros if numeros.count(n) > 1})
        if duplicados:
            achados.append(_achado(
                doc_key, "aviso",
                f"numeração de cláusula duplicada: {duplicados}"))
        ordenados = sorted(set(numeros))
        saltos = [f"{a}→{b}" for a, b in zip(ordenados, ordenados[1:]) if b - a > 1]
        if saltos:
            achados.append(_achado(
                doc_key, "aviso", f"salto na numeração das cláusulas: {', '.join(saltos)}"))

    # título de cláusula sem conteúdo (próxima linha não vazia já é outro
    # título) OU corpo meta-descritivo (descreve o que deveria conter em
    # vez de trazer o conteúdo real — cláusula não desenvolvida)
    linhas = texto.splitlines()
    for i, ln in enumerate(linhas):
        if not _RE_CLAUSULA.match(ln):
            continue
        corpo = next((l for l in linhas[i + 1:] if l.strip()), "")
        if corpo.startswith("#"):
            achados.append(_achado(
                doc_key, "aviso", "título de cláusula sem conteúdo", ln))
        elif _RE_META_DESCRITIVA.match(corpo):
            achados.append(_achado(
                doc_key, "aviso",
                "cláusula meta-descritiva (descreve o conteúdo em vez de "
                "desenvolvê-lo)", corpo))

    # cláusulas obrigatórias do perfil presentes?
    perfil = perfis.perfil(doc_key)
    if perfil and clausulas:
        titulos_norm = [_norm(t) for _, t in clausulas]
        for c in perfis.clausulas_obrigatorias(doc_key):
            alvo = _norm(c["titulo"])
            radical = " ".join(alvo.split()[:3])
            if not any(radical in t or alvo in t for t in titulos_norm):
                achados.append(_achado(
                    doc_key, "aviso",
                    f"cláusula obrigatória possivelmente ausente: "
                    f"{c['n']}. {c['titulo']}"))

    # profundidade mínima do documento (vs. documentos aprovados)
    minimo = perfis.palavras_minimas(doc_key)
    palavras = len(texto.split())
    if minimo and palavras < minimo:
        achados.append(_achado(
            doc_key, "aviso",
            f"documento raso: {palavras} palavras (referência mínima "
            f"{minimo}, extraída dos documentos aprovados). Considere "
            "regenerar ou complementar na revisão."))
    return achados


def _validar_tabelas(doc_key: str, texto: str) -> list[dict]:
    """Tabela Markdown sem linha separadora (---) = sem cabeçalho definido."""
    achados = []
    linhas = texto.splitlines()
    for i, ln in enumerate(linhas):
        if ln.strip().startswith("|") and (i == 0 or not linhas[i - 1].strip().startswith("|")):
            proxima = linhas[i + 1].strip() if i + 1 < len(linhas) else ""
            if not re.match(r"^\|?[\s:|-]+\|?$", proxima):
                achados.append(_achado(
                    doc_key, "aviso", "tabela sem linha de cabeçalho", ln))
    return achados


def validar_documento(doc_key: str, texto: str) -> list[dict]:
    """Valida um documento; retorna a lista de achados (pode ser vazia)."""
    texto = texto or ""
    return (
        _validar_bloqueantes(doc_key, texto)
        + _validar_estrutura(doc_key, texto)
        + _validar_tabelas(doc_key, texto)
    )


def validar_todos(documentos: dict[str, str]) -> list[dict]:
    achados: list[dict] = []
    for doc_key, texto in documentos.items():
        achados.extend(validar_documento(doc_key, texto))
    return achados


def bloqueios(achados: list[dict]) -> list[dict]:
    return [a for a in achados if a["gravidade"] == "bloqueia"]


def avisos(achados: list[dict]) -> list[dict]:
    return [a for a in achados if a["gravidade"] == "aviso"]
