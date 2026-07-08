"""
Planilha orçamentária da contratação.

Substitui o campo único de valor estimado por uma tabela de itens
(código, descrição, unidade, quantidade, valor unitário). O valor total
de cada item e o valor global (soma = estimativa da contratação) são
derivados automaticamente. Os itens podem ser digitados na tabela ou
importados de um arquivo XLSX.
"""

import io
import re
import unicodedata

# Chaves numéricas/estruturais usadas no cálculo (código, descrição etc.)
CAMPOS_ITEM = ["codigo", "descricao", "unidade", "quantidade", "valor_unitario"]

# Coluna opcional fixa para a fonte do preço (geralmente um link/URL)
CAMPO_FONTE = "fonte"

# Colunas derivadas (não editáveis) — não entram no editor
CAMPOS_DERIVADOS = {"valor_total"}

# Sinônimos de cabeçalho aceitos na importação de XLSX (sem acento, minúsculo)
SINONIMOS = {
    "codigo": ["codigo", "cod", "item", "n", "no", "num", "numero"],
    "descricao": ["descricao", "especificacao", "discriminacao", "objeto",
                  "descricao do item", "especificacoes", "produto", "servico"],
    "unidade": ["unidade", "und", "un", "unid", "medida", "unidade de medida", "um"],
    "quantidade": ["quantidade", "qtd", "qtde", "quant", "qte", "qtd."],
    "valor_unitario": ["valor unitario", "vlr unitario", "vlr unit", "preco unitario",
                       "valor unit", "unitario", "vl unitario", "preco unit", "p unit"],
    "fonte": ["fonte", "link", "url", "referencia", "origem", "endereco",
              "fonte do preco", "fonte do valor", "site", "pesquisa"],
}

# Rótulos amigáveis para as colunas do editor
ROTULOS = {
    "codigo": "Código",
    "descricao": "Descrição",
    "unidade": "Unidade",
    "quantidade": "Quantidade",
    "valor_unitario": "Valor Unitário (R$)",
    "valor_total": "Valor Total (R$)",
    "fonte": "Fonte / Link",
}

_RE_URL = re.compile(r"^\s*(https?://|www\.)\S+\s*$", re.IGNORECASE)


def eh_url(valor) -> bool:
    return bool(_RE_URL.match(str(valor or "")))


def normalizar_url(valor) -> str:
    """Garante esquema http(s) para o link ficar clicável."""
    url = str(valor or "").strip()
    if url.lower().startswith("www."):
        return "https://" + url
    return url


def para_link_markdown(valor) -> str:
    """URL -> '[link](url)' (compacto e clicável); demais valores inalterados."""
    if eh_url(valor):
        return f"[link]({normalizar_url(valor)})"
    return str(valor or "")


# ---------------------------------------------------------------------------
# Limpeza de texto (descrições vindas de PDF costumam ter espaços espúrios
# no meio de palavras: "plás tica", "docu mentos", "d?água")
# ---------------------------------------------------------------------------
# Fragmentos que NÃO são palavras isoladas em português: quando aparecem
# soltos, quase sempre são o final de uma palavra quebrada por um espaço.
# Comparados SEM acento (via _core). Propositalmente omitidos os que colidem
# com palavras reais: "do/da/ha/ao/as" (palavras), "sao"→são, "ida", "cidade",
# "idade", "grafica"→gráfica, "menta" etc. — juntá-los corromperia texto.
_FRAGMENTOS = {
    "tica", "tico", "ticas", "ticos", "oplastica",
    "mento", "mentos",
    "ado", "ada", "ados", "adas",
    "avel", "aveis",
    "cao", "coes",          # capta ção/ções (risco de "cão" é desprezível aqui)
    "enio",
    "dade", "dades",
    "encia", "encias", "ancia", "ancias",
    "essidade", "bilidade", "tividade",
}

_RE_APOSTROFO = re.compile(r"(?<=[A-Za-zÀ-ÿ])\?(?=[A-Za-zÀ-ÿ])")
_RE_ESPACO_PONT = re.compile(r"\s+([,.;:!?)])")
_RE_ESPACOS = re.compile(r"\s{2,}")


def _core(token: str) -> str:
    """Token sem acentos, minúsculo e sem pontuação de borda (p/ comparar)."""
    t = token.strip(".,;:!?)(-–—\"'")
    t = unicodedata.normalize("NFKD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.lower()


def limpar_texto(valor) -> str:
    """
    Corrige artefatos comuns de texto copiado de PDF:
      - '?' entre letras vira apóstrofo (d?água -> d'água);
      - espaço antes de pontuação e espaços duplicados;
      - junta uma palavra quebrada quando o pedaço seguinte é claramente um
        fragmento de sufixo (plás tica -> plástica, docu mentos -> documentos).
    Conservador: só junta quando o 2º pedaço não é uma palavra real, para não
    colar texto legítimo (ex.: "de expediente" permanece intacto).
    """
    s = str(valor or "")
    if not s.strip():
        return s
    s = s.replace("\xa0", " ").replace("​", "")
    s = _RE_APOSTROFO.sub("'", s)
    s = _RE_ESPACO_PONT.sub(r"\1", s)
    s = _RE_ESPACOS.sub(" ", s).strip()

    tokens = s.split(" ")
    saida: list[str] = []
    i = 0
    while i < len(tokens):
        atual = tokens[i]
        proximo = tokens[i + 1] if i + 1 < len(tokens) else ""
        if (
            atual and atual.isalpha() and 2 <= len(atual) <= 12
            and proximo and _core(proximo) in _FRAGMENTOS
        ):
            saida.append(atual + proximo)  # mantém a pontuação do fragmento
            i += 2
            continue
        saida.append(atual)
        i += 1
    return " ".join(saida)


def linha_vazia() -> dict:
    return {"codigo": "", "descricao": "", "unidade": "", "quantidade": 0.0,
            "valor_unitario": 0.0}


def linhas_iniciais(n: int = 3) -> list[dict]:
    return [linha_vazia() for _ in range(n)]


def _num(valor) -> float:
    """Converte para float, aceitando moeda BR ('R$ 1.234,56') e strings."""
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    for lixo in ("r$", "R$", " ", "\xa0"):
        texto = texto.replace(lixo, "")
    # padrão BR: ponto de milhar, vírgula decimal
    if "," in texto and "." in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif "," in texto:
        texto = texto.replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0.0


def _normalizar(texto) -> str:
    """minúsculo, sem acento, sem pontuação de borda — para casar cabeçalhos."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.strip().lower().strip(".:")


class ErroPlanilha(Exception):
    """Erro amigável ao importar a planilha de um arquivo."""


# Raízes (substring, sem acento) para casar cabeçalhos escritos por extenso,
# ex.: "Descrição dos Serviços", "Especificação do Objeto", "Preço Unitário".
# 'valor_unitario' antes de qualquer coisa que contenha só 'valor'/'preco'
# para não confundir com "Valor Total".
_RAIZES = [
    ("valor_unitario", ("unitar", "vlr unit", "vl unit", "p unit", "preco unit",
                         "valor unit", "custo unit")),
    ("quantidade", ("quant", "qtd", "qtde", "qte")),
    ("descricao", ("descric", "especific", "discrimin", "objeto", "produto",
                   "servico", "item ", "material", "insumo")),
    ("codigo", ("codig", "cod ", "cod.", "sku", "referencia interna")),
    ("unidade", ("unidade", "und", "unid", "medida")),
    ("fonte", ("fonte", "link", "url", "origem", "endereco", "site",
               "pesquisa", "cotacao")),
]


def _campo_do_cabecalho(celula) -> str | None:
    """
    Mapeia um texto de cabeçalho para um campo do item. Tenta, nesta ordem:
    igualdade com um sinônimo, palavra inteira igual a um sinônimo e, por
    fim, raiz por substring — assim 'Descrição dos Serviços' vira 'descricao'.
    """
    norm = _normalizar(celula)
    if not norm:
        return None
    # 1) igualdade exata com um sinônimo
    for campo, syns in SINONIMOS.items():
        if norm in syns:
            return campo
    # 2) alguma palavra do cabeçalho é exatamente um sinônimo (>= 3 letras)
    palavras = norm.split()
    for campo, syns in SINONIMOS.items():
        for s in syns:
            if len(s) >= 3 and s in palavras:
                return campo
    # 3) raiz por substring (nomes escritos por extenso)
    for campo, raizes in _RAIZES:
        if any(r in norm for r in raizes):
            return campo
    return None


def _mapear_linha(linha) -> dict:
    """Devolve {coluna: campo} reconhecidos numa possível linha de cabeçalho."""
    mapa: dict[int, str] = {}
    for col, celula in enumerate(linha):
        campo = _campo_do_cabecalho(celula)
        if campo and campo not in mapa.values():
            mapa[col] = campo
    return mapa


def importar_de_xlsx(dados: bytes) -> list[dict]:
    """
    Lê um arquivo XLSX e devolve a lista de itens. Detecta a linha de
    cabeçalho pelos nomes das colunas (aceita acentos, nomes por extenso e
    variações); se não houver cabeçalho reconhecível, assume a ordem código,
    descrição, unidade, quantidade, valor unitário. Ignora linhas sem descrição.
    """
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(dados), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ErroPlanilha(
            f"Não foi possível ler o arquivo XLSX: {exc}. "
            "Envie um arquivo Excel (.xlsx) válido."
        ) from exc

    # varre TODAS as abas com dados (a 1ª aba pode ser capa/instruções)
    melhor = None  # (nº de campos, aba, idx_cabecalho, mapa, linhas)
    for ws in wb.worksheets:
        linhas = [list(r) for r in ws.iter_rows(values_only=True)]
        if not any(any(c not in (None, "") for c in ln) for ln in linhas):
            continue
        for i, linha in enumerate(linhas[:25]):
            mapa = _mapear_linha(linha)
            # cabeçalho válido: reconhece a DESCRIÇÃO (coluna essencial) e
            # pelo menos mais uma coluna (quantidade, valor, código...).
            if "descricao" in mapa.values() and len(set(mapa.values())) >= 2:
                pontos = len(set(mapa.values()))
                if melhor is None or pontos > melhor[0]:
                    melhor = (pontos, i, mapa, linhas)
                break

    itens: list[dict] = []
    cabecalho_visto = ""
    if melhor is not None:
        _, idx_cabecalho, mapa, linhas = melhor
        cabecalho = linhas[idx_cabecalho]
        cabecalho_visto = " | ".join(
            str(c).strip() for c in cabecalho if c not in (None, "")
        )
        # colunas não reconhecidas são preservadas com o rótulo original
        # (mas ignoramos "Valor Total"/"Total": esse valor é recalculado)
        extras = {
            col: str(cabecalho[col]).strip()
            for col in range(len(cabecalho))
            if col not in mapa and cabecalho[col] not in (None, "")
            and "total" not in _normalizar(cabecalho[col])
        }
        for linha in linhas[idx_cabecalho + 1:]:
            item = {c: "" for c in CAMPOS_ITEM}
            for col, campo in mapa.items():
                if col < len(linha):
                    item[campo] = linha[col]
            for col, rotulo in extras.items():
                if col < len(linha) and linha[col] not in (None, ""):
                    item[rotulo] = linha[col]
            _acrescentar(itens, item)
    else:
        # sem cabeçalho reconhecível: assume ordem posicional na 1ª aba com dados
        for ws in wb.worksheets:
            linhas = [list(r) for r in ws.iter_rows(values_only=True)]
            if not any(any(c not in (None, "") for c in ln) for ln in linhas):
                continue
            for linha in linhas:
                if not any(c not in (None, "") for c in linha):
                    continue
                item = dict(zip(CAMPOS_ITEM, list(linha) + [""] * len(CAMPOS_ITEM)))
                _acrescentar(itens, item)
            break

    if not itens:
        dica = (
            f' O cabeçalho lido foi: "{cabecalho_visto}".' if cabecalho_visto
            else " Não foi encontrada uma linha de cabeçalho."
        )
        raise ErroPlanilha(
            "Nenhum item reconhecido. A planilha precisa de uma coluna de "
            "descrição (ou especificação/objeto) e, de preferência, quantidade "
            "e valor unitário." + dica +
            " Dica: baixe o modelo abaixo e cole os seus dados nele."
        )
    return itens


def modelo_xlsx() -> bytes:
    """Gera um arquivo XLSX-modelo com o cabeçalho esperado e um exemplo."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Planilha Orçamentária"
    ws.append(["Código", "Descrição", "Unidade", "Quantidade",
               "Valor Unitário", "Fonte / Link"])
    ws.append(["001", "Notebook corporativo i5 16GB", "un", 100, 4500.00,
               "https://www.exemplo.com/notebook-i5"])
    ws.append(["002", "Monitor 24 polegadas", "un", 100, 900.00,
               "https://www.exemplo.com/monitor-24"])
    for col, larg in zip("ABCDEF", (10, 42, 12, 14, 16, 34)):
        ws.column_dimensions[col].width = larg
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _acrescentar(itens: list[dict], item: dict) -> None:
    """Normaliza os tipos e adiciona o item se tiver descrição."""
    descricao = str(item.get("descricao") or "").strip()
    if not descricao:
        return
    registro = {
        "codigo": str(item.get("codigo") or "").strip(),
        "descricao": limpar_texto(descricao),
        "unidade": str(item.get("unidade") or "").strip(),
        "quantidade": _num(item.get("quantidade")),
        "valor_unitario": _num(item.get("valor_unitario")),
    }
    # preserva a fonte e quaisquer colunas extras (texto)
    for chave, valor in item.items():
        if chave in registro or chave in CAMPOS_DERIVADOS:
            continue
        if valor not in (None, ""):
            texto = str(valor).strip()
            # não mexe em URLs (fonte/link); limpa demais textos
            registro[chave] = texto if eh_url(texto) else limpar_texto(texto)
    itens.append(registro)


def colunas_extra(itens: list[dict]) -> list[str]:
    """
    Colunas além das fixas (código..valor total) presentes em algum item,
    em ordem estável: 'fonte' primeiro, depois as demais na ordem de
    aparição. Usadas no editor, no prompt e na exportação.
    """
    fixas = set(CAMPOS_ITEM) | CAMPOS_DERIVADOS
    extras: list[str] = []
    for item in itens or []:
        for chave in item:
            if chave not in fixas and chave not in extras:
                extras.append(chave)
    if CAMPO_FONTE in extras:
        extras.remove(CAMPO_FONTE)
        extras.insert(0, CAMPO_FONTE)
    return extras


def item_valido(item: dict) -> bool:
    """Considera preenchido o item com descrição e algum valor/quantidade."""
    return bool((item.get("descricao") or "").strip()) and (
        _num(item.get("quantidade")) > 0 or _num(item.get("valor_unitario")) > 0
    )


def calcular(itens: list[dict]) -> tuple[list[dict], float]:
    """
    Filtra itens válidos, calcula valor_total de cada um (quantidade ×
    valor unitário) e o valor global (soma). Retorna (itens, valor_global).
    """
    resultado: list[dict] = []
    global_ = 0.0
    for item in itens or []:
        if not item_valido(item):
            continue
        qtd = _num(item.get("quantidade"))
        unit = _num(item.get("valor_unitario"))
        total = round(qtd * unit, 2)
        global_ += total
        registro = {
            "codigo": str(item.get("codigo") or "").strip(),
            "descricao": limpar_texto(str(item.get("descricao") or "").strip()),
            "unidade": str(item.get("unidade") or "").strip(),
            "quantidade": qtd,
            "valor_unitario": unit,
            "valor_total": total,
        }
        # preserva fonte e colunas extras (texto); limpa texto, mas não URLs
        for chave, valor in item.items():
            if chave in registro or chave in CAMPOS_DERIVADOS:
                continue
            texto = "" if valor is None else str(valor).strip()
            if texto:
                registro[chave] = texto if eh_url(texto) else limpar_texto(texto)
        resultado.append(registro)
    return resultado, round(global_, 2)


def formatar_moeda(valor) -> str:
    """R$ 1.234.567,89 (padrão brasileiro)."""
    v = _num(valor)
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _rotulo_coluna(chave: str) -> str:
    """Rótulo de exibição de uma coluna extra (usa ROTULOS ou o próprio nome)."""
    return ROTULOS.get(chave, chave)


def para_markdown(itens: list[dict], valor_global: float,
                  incluir_global: bool = True) -> str:
    """
    Tabela Markdown da planilha, com colunas extras (ex.: Fonte/Link) e o
    valor global na última linha. Links são compactados para '[link](url)'
    — clicáveis e enxutos nos documentos exportados. Com incluir_global=False
    omite a linha do VALOR GLOBAL (usado em amostras de contexto).
    """
    if not itens:
        return "(planilha não informada)"
    extras = colunas_extra(itens)
    cabecalho = ["Código", "Descrição", "Unidade", "Quantidade",
                 "Valor Unitário", "Valor Total"] + [_rotulo_coluna(e) for e in extras]
    linhas = [
        "| " + " | ".join(cabecalho) + " |",
        "|" + "---|" * len(cabecalho),
    ]
    for it in itens:
        qtd = f"{it['quantidade']:g}"
        celulas = [
            it.get("codigo") or "-", it.get("descricao") or "",
            it.get("unidade") or "-", qtd,
            formatar_moeda(it.get("valor_unitario")),
            formatar_moeda(it.get("valor_total")),
        ]
        for e in extras:
            celulas.append(para_link_markdown(it.get(e, "")) or "-")
        linhas.append("| " + " | ".join(str(c) for c in celulas) + " |")
    if incluir_global:
        fim = ["", "", "", "", "**VALOR GLOBAL**",
               f"**{formatar_moeda(valor_global)}**"] + [""] * len(extras)
        linhas.append("| " + " | ".join(fim) + " |")
    return "\n".join(linhas)


# Acima deste nº de itens, não pedimos à IA para redigitar a planilha: enviamos
# um resumo no prompt e injetamos a tabela real (exata) no documento gerado.
LIMITE_ITENS_INLINE = 12
MARCADOR_TABELA = "[[TABELA_ITENS]]"


def resumo_para_prompt(itens: list[dict], valor_global: float) -> str:
    """
    Resumo compacto da planilha para tabelas grandes: contagem, valor global
    e uma amostra dos primeiros itens. Instrui a IA a NÃO redigitar a lista
    (a tabela completa é injetada depois, sem erros e sem gastar tokens).
    """
    n = len(itens)
    amostra = para_markdown(itens[:6], valor_global, incluir_global=False)
    return (
        f"A planilha orçamentária possui {n} itens. VALOR GLOBAL (estimativa "
        f"total da contratação) = {formatar_moeda(valor_global)}.\n"
        f"IMPORTANTE: NÃO redija a lista de itens um a um. A TABELA COMPLETA já "
        f"formatada (com todas as colunas e o valor global) será inserida "
        f"AUTOMATICAMENTE no documento no lugar da marca {MARCADOR_TABELA}. "
        f"Escreva o texto da seção de estimativa de valor e coloque a marca "
        f"{MARCADOR_TABELA} sozinha, em uma linha, onde a tabela deve aparecer.\n"
        f"Amostra apenas ilustrativa dos primeiros itens (não a reproduza):\n"
        + amostra
    )


def injetar_tabela(texto: str, itens_brutos: list[dict] | None) -> str:
    """
    Substitui a marca [[TABELA_ITENS]] pela tabela real; se a planilha for
    grande e a marca não vier (a IA esqueceu), acrescenta a tabela ao final.
    Em tabelas pequenas (fluxo inline) não há marca e nada muda.
    """
    itens, glob = calcular(itens_brutos or [])
    if not itens:
        return texto.replace(MARCADOR_TABELA, "").strip()
    tabela = para_markdown(itens, glob)
    if MARCADOR_TABELA in texto:
        return texto.replace(MARCADOR_TABELA, tabela)
    if len(itens) > LIMITE_ITENS_INLINE:
        return texto.rstrip() + "\n\n" + tabela
    return texto
