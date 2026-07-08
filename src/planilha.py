"""
Planilha orçamentária da contratação.

Substitui o campo único de valor estimado por uma tabela de itens
(código, descrição, unidade, quantidade, valor unitário). O valor total
de cada item e o valor global (soma = estimativa da contratação) são
derivados automaticamente. Os itens podem ser digitados na tabela ou
importados de um arquivo XLSX.
"""

import io
import unicodedata

# Chaves internas de cada item (estáveis para banco/prompt/exportação)
CAMPOS_ITEM = ["codigo", "descricao", "unidade", "quantidade", "valor_unitario"]

# Sinônimos de cabeçalho aceitos na importação de XLSX (sem acento, minúsculo)
SINONIMOS = {
    "codigo": ["codigo", "cod", "item", "n", "no", "num", "numero"],
    "descricao": ["descricao", "especificacao", "discriminacao", "objeto",
                  "descricao do item", "especificacoes", "produto", "servico"],
    "unidade": ["unidade", "und", "un", "unid", "medida", "unidade de medida", "um"],
    "quantidade": ["quantidade", "qtd", "qtde", "quant", "qte", "qtd."],
    "valor_unitario": ["valor unitario", "vlr unitario", "vlr unit", "preco unitario",
                       "valor unit", "unitario", "vl unitario", "preco unit", "p unit"],
}

# Rótulos amigáveis para as colunas do editor
ROTULOS = {
    "codigo": "Código",
    "descricao": "Descrição",
    "unidade": "Unidade",
    "quantidade": "Quantidade",
    "valor_unitario": "Valor Unitário (R$)",
    "valor_total": "Valor Total (R$)",
}


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


def importar_de_xlsx(dados: bytes) -> list[dict]:
    """
    Lê um arquivo XLSX e devolve a lista de itens. Detecta a linha de
    cabeçalho pelos nomes das colunas (aceita acentos e variações); se não
    houver cabeçalho reconhecível, assume a ordem código, descrição,
    unidade, quantidade, valor unitário. Ignora linhas sem descrição.
    """
    try:
        from openpyxl import load_workbook

        wb = load_workbook(io.BytesIO(dados), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise ErroPlanilha(
            f"Não foi possível ler o arquivo XLSX: {exc}. "
            "Envie um arquivo Excel (.xlsx) válido."
        ) from exc

    ws = wb.active
    linhas = [list(r) for r in ws.iter_rows(values_only=True)]
    if not linhas:
        raise ErroPlanilha("A planilha está vazia.")

    # localiza a linha de cabeçalho (a que mais casa com os sinônimos)
    lookup = {syn: campo for campo, syns in SINONIMOS.items() for syn in syns}
    idx_cabecalho, mapa = None, {}
    for i, linha in enumerate(linhas[:15]):
        atual = {}
        for col, celula in enumerate(linha):
            campo = lookup.get(_normalizar(celula))
            if campo and campo not in atual.values():
                atual[col] = campo
        if len(set(atual.values())) >= 2:  # ao menos 2 colunas reconhecidas
            idx_cabecalho, mapa = i, atual
            break

    itens: list[dict] = []
    if idx_cabecalho is not None:
        for linha in linhas[idx_cabecalho + 1:]:
            item = {c: "" for c in CAMPOS_ITEM}
            for col, campo in mapa.items():
                if col < len(linha):
                    item[campo] = linha[col]
            _acrescentar(itens, item)
    else:
        # sem cabeçalho: assume ordem posicional das colunas
        for linha in linhas:
            if not any(linha):
                continue
            item = dict(zip(CAMPOS_ITEM, list(linha) + [""] * len(CAMPOS_ITEM)))
            _acrescentar(itens, item)

    if not itens:
        raise ErroPlanilha(
            "Nenhum item reconhecido. A planilha deve ter colunas de "
            "descrição, quantidade e valor unitário (com ou sem código e unidade)."
        )
    return itens


def modelo_xlsx() -> bytes:
    """Gera um arquivo XLSX-modelo com o cabeçalho esperado e um exemplo."""
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Planilha Orçamentária"
    ws.append(["Código", "Descrição", "Unidade", "Quantidade", "Valor Unitário"])
    ws.append(["001", "Notebook corporativo i5 16GB", "un", 100, 4500.00])
    ws.append(["002", "Monitor 24 polegadas", "un", 100, 900.00])
    for col, larg in zip("ABCDE", (10, 42, 12, 14, 16)):
        ws.column_dimensions[col].width = larg
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def _acrescentar(itens: list[dict], item: dict) -> None:
    """Normaliza os tipos e adiciona o item se tiver descrição."""
    descricao = str(item.get("descricao") or "").strip()
    if not descricao:
        return
    itens.append({
        "codigo": str(item.get("codigo") or "").strip(),
        "descricao": descricao,
        "unidade": str(item.get("unidade") or "").strip(),
        "quantidade": _num(item.get("quantidade")),
        "valor_unitario": _num(item.get("valor_unitario")),
    })


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
        resultado.append({
            "codigo": (item.get("codigo") or "").strip(),
            "descricao": (item.get("descricao") or "").strip(),
            "unidade": (item.get("unidade") or "").strip(),
            "quantidade": qtd,
            "valor_unitario": unit,
            "valor_total": total,
        })
    return resultado, round(global_, 2)


def formatar_moeda(valor) -> str:
    """R$ 1.234.567,89 (padrão brasileiro)."""
    v = _num(valor)
    return "R$ " + f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def para_markdown(itens: list[dict], valor_global: float) -> str:
    """Tabela Markdown da planilha, com o valor global na última linha."""
    if not itens:
        return "(planilha não informada)"
    linhas = [
        "| Código | Descrição | Unidade | Quantidade | Valor Unitário | Valor Total |",
        "|---|---|---|---|---|---|",
    ]
    for it in itens:
        qtd = f"{it['quantidade']:g}"
        linhas.append(
            f"| {it['codigo'] or '-'} | {it['descricao']} | "
            f"{it['unidade'] or '-'} | {qtd} | "
            f"{formatar_moeda(it['valor_unitario'])} | "
            f"{formatar_moeda(it['valor_total'])} |"
        )
    linhas.append(
        f"| | | | | **VALOR GLOBAL** | **{formatar_moeda(valor_global)}** |"
    )
    return "\n".join(linhas)
