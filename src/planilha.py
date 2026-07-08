"""
Planilha orçamentária da contratação.

Substitui o campo único de valor estimado por uma tabela de itens
(código, descrição, unidade, quantidade, valor unitário). O valor total
de cada item e o valor global (soma = estimativa da contratação) são
derivados automaticamente.
"""

# Chaves internas de cada item (estáveis para banco/prompt/exportação)
CAMPOS_ITEM = ["codigo", "descricao", "unidade", "quantidade", "valor_unitario"]

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
    try:
        return float(valor or 0)
    except (TypeError, ValueError):
        return 0.0


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
