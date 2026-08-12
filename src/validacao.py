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

# Marcador de dado pendente. Fica FORA de _BLOQUEANTES porque é o único
# padrão cuja ocorrência vira uma PERGUNTA ao servidor (ver
# `campos_pendentes`): cada marcador é um achado próprio, com o nome do
# campo que falta — não um contador agregado.
RE_PREENCHER = re.compile(r"\[PREENCHER[^\]\n]*\]?", re.IGNORECASE)

# Padrões que NUNCA podem aparecer no documento final (bloqueiam)
_BLOQUEANTES = [
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

# ---------------------------------------------------------------------------
# Dados improvisados / vazamento da planilha (defeitos observados em
# documentos reais gerados)
# ---------------------------------------------------------------------------
# Link Markdown compacto [texto](https://...) — forma LEGÍTIMA de link
_RE_LINK_MD = re.compile(r"\[[^\]]+\]\(https?://[^\s)]+\)")
# URL crua (fora do formato compacto e fora de linha de tabela)
_RE_URL_CRUA = re.compile(r"(?:https?://|www\.)\S{4,}", re.IGNORECASE)
# Domínios institucionais que PODEM aparecer na prosa de um ato (portais
# oficiais e plataformas de licitação citadas em editais)
_RE_URL_INSTITUCIONAL = re.compile(
    r"gov\.br|pncp\.|comprasnet|portaldecompraspublicas|licitanet|"
    r"bll\.org|bnc\.org|licitacoes-e", re.IGNORECASE)

# Função/cargo cujo "valor" não é um nome: número solto ou palavra de
# escala (alto/baixa/médio...) — improviso da IA a partir do contexto
# (ex.: "Representante da área de almoxarifado: 15." / "…: alto.")
_RE_CARGO_INVALIDO = re.compile(
    r"^[^:\n]{0,120}\b(?:respons[áa]vel|representante|gestor(?:a)?|"
    r"fiscal|assessor(?:a)?)\b[^:\n]{0,80}:\s*"
    r"(?:alt[oa]|baix[oa]|m[ée]di[oa]|sim|n[ãa]o|\d{1,6})\s*[.;,]?\s*$",
    re.IGNORECASE | re.MULTILINE)

# Matrícula com aparência de improviso/provisória: todos os dígitos
# iguais (999999, 000000) ou curtíssima (1–2 dígitos)
_RE_MATRICULA = re.compile(
    r"matr[íi]cula\s*(?:n?[ºo°]?\.?\s*)?[:\-]?\s*(\d{1,8})", re.IGNORECASE)

# Cabeçalho da tabela de itens gerada pelo sistema (planilha.para_markdown)
_RE_CABECALHO_ITENS = re.compile(
    r"^\|\s*C[óo]digo\s*\|\s*Descri[çc][ãa]o\s*\|", re.IGNORECASE | re.MULTILINE)

# Cláusula de garantia "seca" (só o percentual, sem modalidade/condições)
_RE_GARANTIA_SECA = re.compile(
    r"^[^:\n]{0,60}garantia[^:\n]{0,40}:\s*(?:de\s*)?\d{1,2}\s*%?\s*[%.;]?\s*$",
    re.IGNORECASE | re.MULTILINE)

# CNPJ no formato brasileiro (com ou sem pontuação)
_RE_CNPJ = re.compile(r"\b(\d{2})\.?(\d{3})\.?(\d{3})/(\d{4})-?(\d{2})\b")

# ---------------------------------------------------------------------------
# Fundamentos legais — confusões recorrentes com a Lei nº 14.133/2021.
# Verificação DETERMINÍSTICA por parágrafo: (tema presente, artigo citado
# incompatível, artigo que sanaria). Não substitui revisão jurídica; mira
# os erros observados em documentos reais.
# ---------------------------------------------------------------------------
_FUNDAMENTOS_LEGAIS = [
    # pregão fundamentado no art. 109 (o rito está nos arts. 28, I, e 29)
    (re.compile(r"preg[ãa]o", re.IGNORECASE),
     re.compile(r"art(?:igo)?s?\.?\s*109\b", re.IGNORECASE),
     None, "bloqueia",
     "fundamento legal incorreto: pregão fundamentado no art. 109 "
     "(a modalidade pregão está nos arts. 28, I, e 29 da Lei nº "
     "14.133/2021)"),
    # vigência da ata fundamentada no art. 82 sem menção ao art. 84
    (re.compile(r"vig[êe]ncia\s+(?:da|de)\s+ata", re.IGNORECASE),
     re.compile(r"art(?:igo)?s?\.?\s*82\b", re.IGNORECASE),
     re.compile(r"art(?:igo)?s?\.?\s*84\b", re.IGNORECASE), "aviso",
     "fundamento legal impreciso: vigência da Ata de Registro de Preços "
     "fundada no art. 82 (a vigência da ata é regida pelo art. 84 da "
     "Lei nº 14.133/2021)"),
    # pagamento fundamentado no art. 98 (art. 98 = limite da garantia)
    (re.compile(r"pagamento", re.IGNORECASE),
     re.compile(r"art(?:igo)?s?\.?\s*98\b", re.IGNORECASE),
     None, "aviso",
     "fundamento legal impreciso: pagamento fundado no art. 98 (o art. "
     "98 trata do limite da garantia contratual; pagamentos são regidos "
     "pelos arts. 141 a 146 da Lei nº 14.133/2021)"),
]

# Repactuação pressupõe serviço contínuo com dedicação de mão de obra
# (art. 135); para bens/materiais o instituto é o reajuste (art. 92, §3º)
_RE_REPACTUACAO = re.compile(r"repactua[çc]", re.IGNORECASE)
_RE_MAO_DE_OBRA = re.compile(
    r"m[ãa]o\s+de\s+obra|dedica[çc][ãa]o\s+exclusiva", re.IGNORECASE)

# Aberturas meta-descritivas: a cláusula descreve o que deveria conter em
# vez de trazer o conteúdo real (ex.: "Descrição da necessidade…",
# "Indicação da solução proposta…"). Sinalizam cláusula não desenvolvida.
_RE_META_DESCRITIVA = re.compile(
    r"^\s*(descri[çc][ãa]o|indica[çc][ãa]o|especifica[çc][ãa]o|"
    r"identifica[çc][ãa]o|apresenta[çc][ãa]o)\s+d[aeo]s?\b"
    r"[^.]*\b(conforme|segundo|com base n)[^.]*\bformul[áa]rio\b",
    re.IGNORECASE)

_RE_CLAUSULA = re.compile(r"(?m)^#{1,3}\s*(\d{1,2})\s*[\.\-–]?\s+(.+?)\s*$")

# ---------------------------------------------------------------------------
# Raciocínio do ETP (P1): o estudo CONCLUI a solução — não a pressupõe.
# ---------------------------------------------------------------------------
# A cláusula da necessidade descreve o problema; anunciar nela a solução,
# a modalidade ou o modelo de execução como decisão tomada inverte o
# raciocínio do art. 18 (o levantamento vira formalidade).
_RE_SOLUCAO_ANTECIPADA = re.compile(
    r"\b(adota(?:-se|remos)?|opta(?:-se|remos)?|escolhe(?:-se)?|"
    r"conclui-se\s+(?:pel[ao]|que)|define-se|fica\s+definid[ao]|"
    r"a\s+solu[çc][ãa]o\s+(?:ser[áa]|escolhida\s+[ée]|adotada\s+[ée]))\b",
    re.IGNORECASE)
_RE_DECISAO_MODELAGEM = re.compile(
    r"\b(sistema\s+de\s+registro\s+de\s+pre[çc]os|\bSRP\b|preg[ãa]o|"
    r"concorr[êe]ncia|ades[ãa]o\s+[àa]\s+ata|loca[çc][ãa]o|aquisi[çc][ãa]o)\b",
    re.IGNORECASE)
_TITULO_NECESSIDADE = ("NECESSIDADE",)
_TITULO_LEVANTAMENTO = ("LEVANTAMENTO",)
_TITULO_SOLUCAO = ("DESCRIÇÃO DA SOLUÇÃO", "DESCRICAO DA SOLUCAO")

# Absolutismo sem evidência: a conclusão do estudo deve ter a firmeza que
# a análise sustenta — nem mais, nem menos.
_RE_ABSOLUTISMO = re.compile(
    r"\b(única\s+(?:solu[çc][ãa]o|alternativa|op[çc][ãa]o)\s+"
    r"(?:poss[íi]vel|viável|existente)|incontest[áa]vel|inquestion[áa]vel|"
    r"juridicamente\s+irrepreens[íi]vel|absolutamente\s+seguro)\b",
    re.IGNORECASE)


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


# ---------------------------------------------------------------------------
# Pendências de preenchimento — QUAL campo o sistema está pedindo
#
# O marcador é o contrato entre a geração e a revisão humana. Quando ele
# traz a descrição ([PREENCHER: prazo de vigência]), o campo é o que o
# próprio marcador declara. Quando vem "seco" ([PREENCHER] — forma que os
# prompts e as minutas de demonstração ainda produzem), o nome do campo é
# deduzido DETERMINISTICAMENTE do documento, nesta ordem: rótulo que
# antecede o marcador na linha → coluna da tabela → título da cláusula.
#
# Regra de UX: nunca se pergunta ao servidor "informação pendente". Sem
# rótulo, sem coluna e sem título, a pergunta cita o trecho onde a lacuna
# está — o usuário jamais precisa adivinhar o que o sistema quer saber.
# ---------------------------------------------------------------------------
_RE_DESCRICAO_PREENCHER = re.compile(
    r"\[PREENCHER\s*[:\-–—]?\s*([^\]\n]*)", re.IGNORECASE)

# numeração/marcação no início do rótulo: "3.2.", "1 -", "III -", "- ", "**"
_RE_NUMERACAO = re.compile(
    r"^\s*(?:[-*•>]\s+)*(?:\d+(?:\.\d+)*|[IVXLCDM]+)\s*[.)\-–—]\s*")
_RE_MARCACAO = re.compile(r"[*_`#]+")
_RE_SEPARADOR_TABELA = re.compile(r"^\s*\|?[\s:|-]*-[\s:|-]*\|?\s*$")

# rótulo que não identifica nada (conectivo, artigo, preposição solta)
_PALAVRAS_VAZIAS = {
    "e", "ou", "de", "do", "da", "dos", "das", "em", "no", "na", "nos",
    "nas", "o", "a", "os", "as", "um", "uma", "por", "para", "com", "ao",
    "aos", "à", "às", "que", "se", "ser", "sao", "é",
}

# Rótulo mínimo para valer como nome de campo: precisa ter substância.
_TAMANHO_MINIMO_ROTULO = 3
_TAMANHO_MAXIMO_ROTULO = 80


def _limpar_rotulo(bruto: str, limite: int = _TAMANHO_MAXIMO_ROTULO) -> str:
    """Rótulo legível: sem numeração de cláusula, marcação Markdown ou
    pontuação de arremate. Devolve '' quando não sobra substância."""
    rotulo = bruto or ""
    # resto de outra célula ou de outro marcador não nomeia campo algum
    if "|" in rotulo or "[" in rotulo or "]" in rotulo:
        return ""
    rotulo = _RE_MARCACAO.sub("", rotulo).strip()
    rotulo = _RE_NUMERACAO.sub("", rotulo).strip()
    rotulo = rotulo.strip(" \t-–—:;.,()[]")
    rotulo = re.sub(r"\s+", " ", rotulo)
    if len(rotulo) < _TAMANHO_MINIMO_ROTULO:
        return ""
    if len(rotulo) > limite:
        return ""
    palavras = [p for p in rotulo.lower().split() if p not in _PALAVRAS_VAZIAS]
    if not palavras:
        return ""
    # rótulo puramente numérico não nomeia campo algum
    if not re.search(r"[A-Za-zÀ-ÿ]", rotulo):
        return ""
    # Títulos vêm em CAIXA ALTA nos documentos e a pergunta é em prosa —
    # mas siglas (PCA, CNPJ, DFD) são palavra única e devem permanecer
    # como são: "Pca" seria uma pergunta pior que "PCA".
    if rotulo.isupper() and " " in rotulo:
        return rotulo.capitalize()
    return rotulo


def _rotulo_antes_do_marcador(antes: str) -> str:
    """
    Nome do campo a partir do texto que antecede o marcador NA MESMA
    linha: "3.2. Prazo de vigência: [PREENCHER]" → "prazo de vigência";
    "…, número do processo [PREENCHER], modalidade…" → "número do
    processo".
    """
    trecho = antes.rstrip()
    if not trecho:
        return ""
    if trecho.endswith(":"):
        # rótulo declarado: o que vem antes dos dois-pontos
        trecho = trecho[:-1]
        # corta o que pertence à frase anterior (ponto-e-vírgula, ponto
        # final seguido de espaço) preservando a numeração "3.2."
        pedaco = re.split(r";|(?<=[a-zà-ÿ])\.\s", trecho)[-1]
        return _limpar_rotulo(pedaco)
    # sem dois-pontos: última expressão da enumeração ("a, b, campo X ")
    pedaco = re.split(r"[;,:]|—|–|\.\s", trecho)[-1]
    return _limpar_rotulo(pedaco)


def _coluna_da_tabela(linhas: list[str], indice: int, linha: str,
                      posicao: int) -> str:
    """
    Marcador dentro de linha de tabela Markdown: o nome do campo é o
    CABEÇALHO da coluna em que ele está (a matriz de riscos gera linhas
    inteiras de marcadores secos, indistinguíveis sem isso).
    """
    if "|" not in linha:
        return ""
    coluna = linha.count("|", 0, posicao)
    if coluna == 0:
        return ""
    for i in range(indice - 1, -1, -1):
        anterior = linhas[i]
        if not anterior.strip() or "|" not in anterior:
            break
        if not _RE_SEPARADOR_TABELA.match(anterior):
            continue  # outra linha de dados: o cabeçalho está mais acima
        # o cabeçalho é a linha imediatamente acima do separador
        if i == 0 or "|" not in linhas[i - 1]:
            break
        celulas = linhas[i - 1].split("|")
        return _limpar_rotulo(celulas[coluna]) if coluna < len(celulas) else ""
    return ""


def _identificador_da_linha(linha: str) -> str:
    """
    Primeira célula preenchida da linha de tabela — é ela que distingue
    "Probabilidade" da linha do atraso da "Probabilidade" da linha da
    falha de qualidade. Sem isso, duas perguntas idênticas na tela.
    """
    for celula in linha.split("|"):
        rotulo = _limpar_rotulo(celula)
        if rotulo:
            return rotulo
    return ""


def _titulo_da_clausula(linhas: list[str], indice: int) -> str:
    """Título da cláusula/seção mais próxima acima do marcador."""
    for i in range(indice, -1, -1):
        m = _RE_CLAUSULA.match(linhas[i])
        if m:
            return f"{m.group(1)}. {m.group(2).strip()}"
        if linhas[i].startswith("#"):
            titulo = _RE_MARCACAO.sub("", linhas[i]).strip()
            if titulo:
                return titulo
    return ""


def _contexto_do_marcador(texto: str, inicio: int, fim: int) -> str:
    """Frase ao redor do marcador — o que a tela mostra sob o campo."""
    ini = texto.rfind("\n", 0, inicio) + 1
    termino = texto.find("\n", fim)
    linha = texto[ini:termino if termino != -1 else len(texto)]
    return re.sub(r"\s+", " ", linha).strip()


def _indice_da_linha(texto: str, posicao: int) -> int:
    return texto.count("\n", 0, posicao)


def pendencia_de_valor(texto: str, inicio: int, fim: int,
                       valor_improvisado: str, campo: str) -> dict:
    """
    Pendência de dado IMPROVISADO (matrícula provisória, CNPJ inválido):
    não há marcador a substituir — o alvo é o próprio valor errado, no
    lugar exato onde ele está. O `molde` preserva o rótulo em volta
    ("matrícula: {valor}") para que a resposta do servidor entre no
    documento sem arrastar o texto vizinho junto.
    """
    linhas = texto.splitlines()
    indice = _indice_da_linha(texto, inicio)
    alvo = texto[inicio:fim]
    corte = alvo.rfind(valor_improvisado)
    molde = ("{valor}" if corte < 0 else
             alvo[:corte] + "{valor}" + alvo[corte + len(valor_improvisado):])
    return {
        "campo": campo,
        "qualificador": "",
        "marcador": alvo,
        "molde": molde,
        "ocorrencia": texto.count(alvo, 0, inicio) + 1,
        "inicio": inicio,
        "fim": fim,
        "linha": indice + 1,
        "clausula": _titulo_da_clausula(linhas, indice),
        "contexto": _contexto_do_marcador(texto, inicio, fim),
        "origem": "valor_improvisado",
    }


def campos_pendentes(texto: str) -> list[dict]:
    """
    Uma entrada por marcador [PREENCHER] do documento, com o NOME do
    campo que falta, o marcador exato (para substituição sem ambiguidade)
    e a ocorrência daquele marcador idêntico no texto.

    `origem` registra como o nome foi obtido — 'marcador' (o próprio
    marcador descrevia o campo), 'rotulo', 'tabela', 'clausula' ou
    'trecho' (último recurso). Só 'trecho' significa que o documento não
    permitia nomear o campo com segurança.
    """
    texto = texto or ""
    linhas = texto.splitlines()

    vistos: dict[str, int] = {}
    pendencias: list[dict] = []
    for m in RE_PREENCHER.finditer(texto):
        marcador = m.group(0)
        chave = marcador.lower()
        vistos[chave] = vistos.get(chave, 0) + 1

        indice = _indice_da_linha(texto, m.start())
        linha = linhas[indice] if indice < len(linhas) else ""
        inicio_linha = texto.rfind("\n", 0, m.start()) + 1
        posicao = m.start() - inicio_linha

        # a descrição do próprio marcador é o campo declarado pela
        # geração: vale integralmente, sem o teto dos rótulos inferidos
        declarada = _RE_DESCRICAO_PREENCHER.match(marcador)
        descricao = _limpar_rotulo(
            declarada.group(1) if declarada else "", limite=240)
        clausula = _titulo_da_clausula(linhas, indice)
        contexto = _contexto_do_marcador(texto, m.start(), m.end())

        qualificador = ""
        if descricao:
            campo, origem = descricao, "marcador"
        else:
            # em linha de tabela o rótulo é o CABEÇALHO da coluna: o texto
            # à esquerda pertence a outra célula, não nomeia esta lacuna
            campo = _coluna_da_tabela(linhas, indice, linha, posicao)
            origem = "tabela"
            if campo:
                qualificador = _identificador_da_linha(linha)
            if not campo:
                campo = _rotulo_antes_do_marcador(linha[:posicao])
                origem = "rotulo"
            if not campo and clausula:
                campo = f"conteúdo de «{clausula}»"
                origem = "clausula"
            if not campo:
                # último recurso: nunca "informação pendente" seca — a
                # pergunta carrega o trecho em que a lacuna aparece
                resumo = contexto.replace(marcador, "___")[:80].strip()
                campo = (f"informação pendente em “{resumo}”" if resumo
                         else "informação pendente (marcador sem contexto)")
                origem = "trecho"

        pendencias.append({
            "campo": campo,
            "qualificador": qualificador,
            "marcador": marcador,
            "molde": "",           # o marcador é substituído por inteiro
            "ocorrencia": vistos[chave],
            "inicio": m.start(),
            "fim": m.end(),
            "linha": indice + 1,
            "clausula": clausula,
            "contexto": contexto,
            "origem": origem,
        })
    return pendencias


def _validar_pendencias(doc_key: str, texto: str) -> list[dict]:
    """
    Um achado POR MARCADOR: cada pendência precisa ser endereçável
    individualmente (a tela pergunta campo a campo). O achado carrega a
    pendência estruturada para que achados.py não tenha de reanalisar o
    documento inteiro para descobrir o que pedir.
    """
    achados = []
    for pendencia in campos_pendentes(texto):
        achado = _achado(
            doc_key, "bloqueia",
            f"campo pendente [PREENCHER]: {pendencia['campo']}",
            pendencia["contexto"],
        )
        achado["pendencia"] = pendencia
        achados.append(achado)
    return achados


def _validar_bloqueantes(doc_key: str, texto: str) -> list[dict]:
    achados = _validar_pendencias(doc_key, texto)
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


def _cnpj_valido(digitos: str) -> bool:
    """Valida os dígitos verificadores de um CNPJ (14 dígitos)."""
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    nums = [int(d) for d in digitos]
    for tamanho in (12, 13):
        pesos = ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2] if tamanho == 12
                 else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
        soma = sum(n * p for n, p in zip(nums[:tamanho], pesos))
        dv = 0 if soma % 11 < 2 else 11 - (soma % 11)
        if nums[tamanho] != dv:
            return False
    return True


def _validar_dados_improvisados(doc_key: str, texto: str) -> list[dict]:
    """
    Dados determinísticos que a IA jamais poderia ter 'inventado':
      - URL crua na prosa (links pertencem à coluna Fonte da planilha);
      - função/cargo preenchido com número solto ou palavra de escala;
      - matrícula com aparência de provisória (999999, 15…) — aviso;
      - CNPJ com dígitos verificadores inválidos.
    """
    achados: list[dict] = []

    # URLs cruas fora de linhas de tabela e fora de [link](url)
    urls = []
    for ln in texto.splitlines():
        s = ln.strip()
        if s.startswith("|"):
            continue  # linha de tabela: coluna Fonte pode ter link
        resto = _RE_LINK_MD.sub("", s)
        m = _RE_URL_CRUA.search(resto)
        if m and not _RE_URL_INSTITUCIONAL.search(m.group(0)):
            urls.append((s, m.group(0)))
    if urls:
        achados.append(_achado(
            doc_key, "bloqueia",
            f"URL crua na prosa ({len(urls)} ocorrência(s)) — links de "
            "pesquisa de preço pertencem à coluna Fonte da planilha, no "
            "formato [link](https://…)", urls[0][0]))

    cargos = _RE_CARGO_INVALIDO.findall(texto)
    if cargos:
        m = _RE_CARGO_INVALIDO.search(texto)
        achados.append(_achado(
            doc_key, "bloqueia",
            f"função/cargo preenchido com valor inválido "
            f"({len(cargos)} ocorrência(s)) — nome/identificação do agente "
            "não informado deve virar [PREENCHER: …], nunca um número ou "
            "palavra solta", m.group(0)))

    # Dado improvisado é PERGUNTA ao servidor (como o [PREENCHER]): um
    # achado por ocorrência, cada um sabendo qual valor errado substituir
    # — senão a tela pede "a matrícula" sem poder aplicar a resposta.
    suspeitas = [m for m in _RE_MATRICULA.finditer(texto)
                 if len(set(m.group(1))) == 1 or len(m.group(1)) <= 2]
    for m in suspeitas:
        ini = max(0, m.start() - 40)
        achado = _achado(
            doc_key, "aviso",
            f"matrícula com aparência de improviso/provisória "
            f"({m.group(1)}) — confirme o dado real ou use "
            "[PREENCHER: matrícula]",
            texto[ini:m.end() + 20].replace("\n", " "))
        achado["pendencia"] = pendencia_de_valor(
            texto, m.start(), m.end(), m.group(1),
            "matrícula do agente responsável")
        achados.append(achado)

    cnpjs_invalidos = [
        m for m in _RE_CNPJ.finditer(texto)
        if not _cnpj_valido("".join(m.groups()))
    ]
    for m in cnpjs_invalidos:
        achado = _achado(
            doc_key, "bloqueia",
            f"CNPJ inválido ({m.group(0)}) — dígitos verificadores não "
            "conferem; use o CNPJ real ou [PREENCHER: CNPJ]", m.group(0))
        achado["pendencia"] = pendencia_de_valor(
            texto, m.start(), m.end(), m.group(0),
            "CNPJ correto (com dígitos verificadores válidos)")
        achados.append(achado)

    if len(_RE_CABECALHO_ITENS.findall(texto)) >= 2:
        achados.append(_achado(
            doc_key, "bloqueia",
            "tabela de itens duplicada — a planilha orçamentária deve "
            "aparecer uma única vez no documento"))
    return achados


def _validar_fundamentos_legais(doc_key: str, texto: str) -> list[dict]:
    """
    Confusões recorrentes de fundamentação na Lei nº 14.133/2021,
    verificadas POR PARÁGRAFO (tema + artigo incompatível no mesmo
    trecho). Além delas, 'repactuação' sem regime de mão de obra no
    documento sugere instituto errado para bens/materiais (reajuste).
    """
    achados: list[dict] = []
    paragrafos = [p for p in texto.split("\n") if p.strip()]
    for tema, artigo_errado, artigo_sana, gravidade, mensagem in _FUNDAMENTOS_LEGAIS:
        for par in paragrafos:
            if not (tema.search(par) and artigo_errado.search(par)):
                continue
            if artigo_sana and artigo_sana.search(par):
                continue
            achados.append(_achado(doc_key, gravidade, mensagem, par))
            break  # um achado por regra é suficiente para a revisão

    if _RE_REPACTUACAO.search(texto) and not _RE_MAO_DE_OBRA.search(texto):
        m = _RE_REPACTUACAO.search(texto)
        ini = max(0, m.start() - 60)
        achados.append(_achado(
            doc_key, "aviso",
            "instituto possivelmente inadequado: 'repactuação' prevista sem "
            "regime de dedicação de mão de obra — para bens/materiais o "
            "instituto é o reajuste (art. 92, §3º); repactuação restringe-se "
            "a serviços contínuos com dedicação de mão de obra (art. 135 da "
            "Lei nº 14.133/2021)",
            texto[ini:m.end() + 60].replace("\n", " ")))

    if _RE_GARANTIA_SECA.search(texto):
        m = _RE_GARANTIA_SECA.search(texto)
        achados.append(_achado(
            doc_key, "aviso",
            "cláusula de garantia sem fundamentação/condições — indique a "
            "modalidade, as condições e a base legal (arts. 96 a 98 da Lei "
            "nº 14.133/2021), ou remova se inaplicável", m.group(0)))
    return achados


def _corpo_da_clausula(texto: str, titulos: tuple[str, ...]) -> tuple[int, str]:
    """(posição da cláusula, corpo até a próxima) — (-1, "") se ausente."""
    clausulas = list(_RE_CLAUSULA.finditer(texto))
    for i, m in enumerate(clausulas):
        alvo = _norm(m.group(2))
        if any(_norm(t) in alvo for t in titulos):
            fim = clausulas[i + 1].start() if i + 1 < len(clausulas) else len(texto)
            return i, texto[m.end():fim]
    return -1, ""


def _validar_raciocinio_etp(doc_key: str, texto: str) -> list[dict]:
    """
    O ETP deve CONCLUIR a solução: necessidade → requisitos →
    alternativas → análise → solução. Verificações determinísticas da
    inversão desse encadeamento (avisos: a redação é discricionária).
    """
    if doc_key != "etp":
        return []
    achados: list[dict] = []

    pos_necessidade, corpo_necessidade = _corpo_da_clausula(
        texto, _TITULO_NECESSIDADE)
    if corpo_necessidade:
        for frase in re.split(r"(?<=[.;])\s+", corpo_necessidade):
            if _RE_SOLUCAO_ANTECIPADA.search(frase) and \
                    _RE_DECISAO_MODELAGEM.search(frase):
                achados.append(_achado(
                    doc_key, "aviso",
                    "cláusula de necessidade antecipa a solução/modelagem "
                    "como decidida — a necessidade descreve o problema; a "
                    "escolha decorre do levantamento e da análise",
                    frase.strip()))
                break

    pos_levantamento, _ = _corpo_da_clausula(texto, _TITULO_LEVANTAMENTO)
    pos_solucao, _ = _corpo_da_clausula(texto, _TITULO_SOLUCAO)
    if pos_levantamento >= 0 and pos_solucao >= 0 and \
            pos_levantamento > pos_solucao:
        achados.append(_achado(
            doc_key, "aviso",
            "ordem do raciocínio invertida: a descrição da solução "
            "escolhida aparece ANTES do levantamento de soluções"))
    elif pos_solucao >= 0 and pos_levantamento < 0:
        achados.append(_achado(
            doc_key, "aviso",
            "solução descrita sem cláusula de levantamento de soluções — "
            "a escolha precisa decorrer da análise de alternativas"))
    return achados


def _validar_absolutismo(doc_key: str, texto: str) -> list[dict]:
    """Afirmação absoluta sem evidência que a sustente (aviso)."""
    m = _RE_ABSOLUTISMO.search(texto)
    if not m:
        return []
    ini = max(0, m.start() - 60)
    return [_achado(
        doc_key, "aviso",
        "afirmação absoluta sem evidência ('" + m.group(0).lower() + "') — "
        "conclua com a firmeza que a análise sustenta",
        texto[ini:m.end() + 60].replace("\n", " "))]


# ---------------------------------------------------------------------------
# Lastro das citações (P1): fecha o circuito da regra de citação.
#
# A instrução no prompt depende da obediência do modelo. Aqui a
# verificação é determinística: todo número de artigo citado precisa
# estar (a) no mapa canônico validado do sistema ou (b) em um trecho que
# o RAG efetivamente recuperou para AQUELA geração. Sem lastro, vira
# finding — e a correção preferida REMOVE o número, mantendo a norma;
# jamais troca por outro artigo inventado.
# ---------------------------------------------------------------------------
_RE_ARTIGO = re.compile(r"\bart(?:igo|s?)?\.?\s*(\d{1,3})\s*[º°]?", re.IGNORECASE)
# janela após a citação onde a norma costuma aparecer ("art. 84 da Lei
# nº 14.133/2021", "arts. 141 a 146 da Lei nº 14.133/2021")
_JANELA_NORMA = 90


def dispositivos_citados(texto: str) -> set[str]:
    """
    Dispositivos citados no documento, como `norma:artigo`.

    A norma é lida logo após a citação; sem norma declarada, vale a norma
    de referência da fase preparatória (`normas.NORMA_PADRAO`) — que é
    como o próprio documento se lê ("na forma do art. 33" significa a Lei
    nº 14.133/2021). Isso impede que o art. 84 de uma norma qualquer
    valide o art. 84 da Lei nº 14.133/2021.
    """
    from .normas import NORMA_PADRAO, dispositivo, identificar_norma

    texto = texto or ""
    citados: set[str] = set()
    for m in _RE_ARTIGO.finditer(texto):
        janela = texto[m.end():m.end() + _JANELA_NORMA]
        # a norma vale até o fim da frase: "art. 5º da CF. O art. 40…"
        janela = re.split(r"(?<=[.;:])\s", janela)[0]
        citados.add(dispositivo(identificar_norma(janela) or NORMA_PADRAO,
                                m.group(1)))
    return citados


def _validar_lastro_das_citacoes(doc_key: str, texto: str,
                                 lastro: set[str] | None) -> list[dict]:
    if lastro is None:
        return []          # sem rastro do RAG: nada a afirmar (conservador)
    from . import prompts

    sem_lastro = sorted(
        dispositivos_citados(texto) - prompts.DISPOSITIVOS_CANONICOS - lastro)
    if not sem_lastro:
        return []
    exemplo = _RE_ARTIGO.search(texto)
    legivel = ", ".join(f"art. {d.split(':')[1]} ({d.split(':')[0]})"
                        for d in sem_lastro)
    return [_achado(
        doc_key, "aviso",
        f"fundamento sem lastro: {legivel} — o dispositivo, NA NORMA "
        "citada, não consta do mapa canônico do sistema nem de qualquer "
        "trecho de legislação recuperado nesta geração. Remova o número e "
        "mantenha a referência à norma (ex.: 'nos termos da Lei nº "
        "14.133/2021'); não substitua por outro artigo sem fonte",
        (exemplo.group(0) if exemplo else ""))]


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


def validar_documento(doc_key: str, texto: str,
                      lastro: set[str] | None = None) -> list[dict]:
    """
    Valida um documento; retorna a lista de achados (pode ser vazia).

    `lastro`: números de artigo recuperados pelo RAG na geração deste
    documento. Quando informado, habilita a checagem de fundamento sem
    lastro; quando None (sem rastro disponível), a checagem é omitida.
    """
    texto = texto or ""
    return (
        _validar_bloqueantes(doc_key, texto)
        + _validar_dados_improvisados(doc_key, texto)
        + _validar_fundamentos_legais(doc_key, texto)
        + _validar_lastro_das_citacoes(doc_key, texto, lastro)
        + _validar_raciocinio_etp(doc_key, texto)
        + _validar_absolutismo(doc_key, texto)
        + _validar_estrutura(doc_key, texto)
        + _validar_tabelas(doc_key, texto)
    )


def validar_todos(documentos: dict[str, str],
                  lastro_por_doc: dict[str, set[str]] | None = None) -> list[dict]:
    achados: list[dict] = []
    for doc_key, texto in documentos.items():
        achados.extend(validar_documento(
            doc_key, texto, (lastro_por_doc or {}).get(doc_key)))
    return achados


def bloqueios(achados: list[dict]) -> list[dict]:
    return [a for a in achados if a["gravidade"] == "bloqueia"]


def avisos(achados: list[dict]) -> list[dict]:
    return [a for a in achados if a["gravidade"] == "aviso"]
