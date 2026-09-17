#!/usr/bin/env python3
"""
Shadow mode, fora do produto: mede o que o Headroom ECONOMIZARIA e, mais
importante, o que ele PERDERIA — sobre material real deste repositório.

POR QUE ELE MORA AQUI E NÃO EM `src/`

Shadow mode dentro do aplicativo exigiria a dependência em produção para
descobrir se vale a pena tê-la em produção. Pergunta circular. Este
script responde a mesma pergunta offline, sobre os mesmos dados, sem que
uma linha de `headroom` entre no caminho que gera documento de licitação.

O QUE ELE MEDE, E A ORDEM IMPORTA

1. **Literalidade** — números, valores, datas, quantidades, artigos de
   lei, códigos de item, identificadores e links do original ainda estão
   no comprimido? Esta é a PRIMEIRA coluna porque é a que reprova. Num
   sistema que gera edital sob a Lei 14.133, perder um dígito não é
   degradação graciosa: é documento errado assinado por agente público.
2. **Economia** — tokens antes e depois.
3. **Latência** — quanto custa comprimir.

Um corpus que economiza 60% e perde um valor monetário é REPROVADO. Um
que economiza 8% e não perde nada é aprovado com a observação de que 8%
talvez não pague a dependência.

USO

    .venv/bin/python scripts/headroom_bench.py
    .venv/bin/python scripts/headroom_bench.py --json   # para CI

Sem `headroom` instalado, ele diz isso e sai com 0 — é bancada, não
portão.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
FIXTURES = RAIZ / "tests" / "fixtures"

# ---------------------------------------------------------------------------
# O QUE NÃO PODE SUMIR
#
# Cada padrão corresponde a um item da lista que o operador declarou
# intocável: números, valores, quantidades, unidades, datas, referências
# legais, artigos, itens, subitens, identificadores e links.
#
# `_NUMERO` é deliberadamente amplo — qualquer número com 2+ dígitos.
# Amplo demais produz falso alarme; estreito demais deixa passar o que
# importa. Entre os dois erros, este script prefere o alarme: ele existe
# para decidir se uma camada de compressão entra perto de documento
# jurídico, e nessa decisão o custo de um susto é uma leitura a mais.
# ---------------------------------------------------------------------------
LITERAIS = {
    "valor monetário": re.compile(r"R\$\s?[\d.]+,\d{2}"),
    "número": re.compile(r"(?<![\w.,])\d{2,}(?:[.,]\d+)*(?![\w])"),
    "data": re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    "artigo de lei": re.compile(r"\bart\.?\s?\d+[ºo°]?(?:\s?-\s?[A-Z])?", re.I),
    "lei": re.compile(r"\bLei\s+n[ºo°]?\s?[\d.]+/\d{4}"),
    "código de item": re.compile(r"\b\d{6}\b"),
    "identificador": re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"),
    "link": re.compile(r"https?://\S+"),
}


def literais(texto: str) -> dict[str, set[str]]:
    return {rotulo: set(p.findall(texto)) for rotulo, p in LITERAIS.items()}


def perdas(original: str, comprimido: str) -> dict[str, list[str]]:
    """O que existia no original e não existe mais — por categoria."""
    antes, depois = literais(original), literais(comprimido)
    saida = {}
    for rotulo, valores in antes.items():
        sumiu = sorted(valores - depois[rotulo])
        if sumiu:
            saida[rotulo] = sumiu
    return saida


# ---------------------------------------------------------------------------
# O CORPUS — material REAL do repositório, não texto sintético
# ---------------------------------------------------------------------------
def _ler(caminho: pathlib.Path) -> str:
    return caminho.read_text(errors="replace")


def corpus() -> list[tuple[str, str, str]]:
    """`(nome, categoria, conteúdo)`. Categoria é a classificação do operador."""
    itens: list[tuple[str, str, str]] = []

    planilha = FIXTURES / "caso_210_itens.json"
    if planilha.exists():
        itens.append(("planilha de 210 itens (DFD/TR)",
                      "SEM COMPRESSÃO", _ler(planilha)))

    for nome in ("compras_itens_contratacoes.json", "compras_precos_praticados.json"):
        alvo = FIXTURES / "precos" / nome
        if alvo.exists():
            itens.append((f"API compras.gov.br — {nome}",
                          "RECOMENDADA", _ler(alvo)))

    for nome in ("multi_dfd_sems.txt", "layout_a_seplan.txt"):
        alvo = FIXTURES / "demanda" / nome
        if alvo.exists():
            itens.append((f"DFD extraído de PDF — {nome}",
                          "SEM COMPRESSÃO", _ler(alvo)))

    # Prosa jurídica de verdade: as instruções que vão em TODO prompt do
    # produto, com artigos de lei e referências normativas.
    prompts = RAIZ / "src" / "prompts.py"
    if prompts.exists():
        itens.append(("instruções normativas do gerador (prosa PT-BR)",
                      "CONDICIONAL", _ler(prompts)))

    # Código-fonte: o que o agente de desenvolvimento lê o dia inteiro.
    db = RAIZ / "src" / "db.py"
    if db.exists():
        itens.append(("código-fonte Python (src/db.py)",
                      "CONDICIONAL", _ler(db)))

    # JSON grande e repetitivo, o caso de uso que o Headroom anuncia.
    migracoes = sorted((RAIZ / "supabase" / "migrations").glob("*.sql"))
    if migracoes:
        itens.append(("SQL das migrações concatenado",
                      "CONDICIONAL",
                      "\n".join(_ler(m) for m in migracoes[-6:])))

    return itens


# ---------------------------------------------------------------------------
# A medição
# ---------------------------------------------------------------------------
def medir(nome: str, categoria: str, conteudo: str) -> dict:
    from headroom import compress

    # A FORMA DA MENSAGEM É PARTE DA MEDIÇÃO, e descobrir isso custou uma
    # tabela inteira de zeros.
    #
    # O Headroom PROTEGE a mensagem do usuário: com o conteúdo numa única
    # mensagem `user`, ele devolve `router:protected:user_message` e
    # economia zero — corretamente, porque o turno vivo do usuário não é
    # material de compressão. Medir assim daria "o Headroom não serve
    # para nada aqui", que é falso.
    #
    # Saída de ferramenta não vive em `user`: vive em `tool`/`assistant`,
    # cercada pelo diálogo. É essa forma que a camada de otimização vê, e
    # é nela que a medição faz sentido.
    mensagens = [
        {"role": "user", "content": "(pergunta do agente)"},
        {"role": "tool", "content": conteudo},
        {"role": "user", "content": "(pergunta seguinte)"},
    ]

    inicio = time.perf_counter()
    ligado = compress(mensagens, optimize=True)
    ms = (time.perf_counter() - inicio) * 1000

    # `optimize=False` é o passthrough que o próprio Headroom oferece
    # para A/B — o grupo de controle sai da mesma função, não de uma
    # contagem paralela minha.
    desligado = compress(mensagens, optimize=False)  # noqa: F841

    # Os nomes vêm da versão INSTALADA, conferidos em `dir(CompressResult)`:
    # tokens_before / tokens_after / tokens_saved / compression_ratio /
    # transforms_applied. A primeira versão deste script chutou
    # `original_tokens` e `compressed_tokens` a partir da documentação, e o
    # resultado foi uma tabela inteira de zeros que ainda assim imprimia
    # "nenhuma perda de literalidade" — verdade vazia, porque nada tinha
    # sido medido. Por isso `_numero` levanta em vez de cair para zero.
    # `tokens_before` sai do resultado LIGADO: no passthrough
    # (`optimize=False`) o Headroom não conta nada e devolve 0, o que
    # produziria uma economia de 0% sobre uma base de 0 — número que
    # parece medição e não é.
    antes = _numero(ligado, "tokens_before")
    depois = _numero(ligado, "tokens_after")
    texto_final = _texto(ligado)

    return {
        "corpus": nome,
        "categoria": categoria,
        "tokens_sem_headroom": antes,
        "tokens_com_headroom": depois,
        "economia_pct": round(100 * (1 - depois / antes), 1) if antes else 0.0,
        "latencia_ms": round(ms, 2),
        "transformacoes": list(getattr(ligado, "transforms_applied", []) or []),
        "perdas": perdas(conteudo, texto_final),
    }


def _numero(resultado, campo: str) -> int:
    """
    Lê o campo e RECUSA a ausência.

    Um `getattr(..., 0)` aqui transformaria uma renomeação de atributo
    numa medição de zero — e zero economia com zero perda parece um
    relatório tranquilo. Prefiro o erro: se o contrato do `CompressResult`
    mudar, este script para e alguém conserta.
    """
    valor = getattr(resultado, campo, None)
    if not isinstance(valor, int):
        raise SystemExit(
            f"CompressResult não expõe `{campo}` como int (veio {valor!r}). "
            "O contrato da versão instalada mudou — confira "
            "`dir(CompressResult)` antes de confiar em qualquer número.")
    return valor


def _texto(resultado) -> str:
    """O conteúdo que de fato iria ao modelo."""
    mensagens = getattr(resultado, "messages", None) or []
    partes = []
    for m in mensagens:
        c = m.get("content") if isinstance(m, dict) else None
        if isinstance(c, str):
            partes.append(c)
        elif isinstance(c, list):
            partes += [b.get("text", "") for b in c if isinstance(b, dict)]
    return "\n".join(partes)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--json", action="store_true", help="saída para máquina")
    args = p.parse_args()

    try:
        import headroom  # noqa: F401
    except ImportError:
        print("headroom não instalado — nada a medir.\n"
              '  .venv/bin/pip install "headroom-ai[mcp]"')
        return 0

    linhas = [medir(*caso) for caso in corpus()]

    if args.json:
        print(json.dumps(linhas, ensure_ascii=False, indent=2))
        return 0

    print(f"{'corpus':44} {'categoria':16} {'antes':>8} {'depois':>8} "
          f"{'econ.':>7} {'ms':>7}  literalidade")
    print("-" * 110)
    for linha in linhas:
        veredito = "OK" if not linha["perdas"] else \
            "PERDEU " + ", ".join(linha["perdas"])
        print(f"{linha['corpus'][:44]:44} {linha['categoria']:16} "
              f"{linha['tokens_sem_headroom']:>8} "
              f"{linha['tokens_com_headroom']:>8} "
              f"{linha['economia_pct']:>6}% {linha['latencia_ms']:>7}  {veredito}")

    reprovados = [linha for linha in linhas if linha["perdas"]]
    print()
    if reprovados:
        print(f"{len(reprovados)} corpus PERDERAM literalidade. Detalhe:")
        for linha in reprovados:
            for rotulo, valores in linha["perdas"].items():
                amostra = ", ".join(valores[:6])
                resto = f" (+{len(valores) - 6})" if len(valores) > 6 else ""
                print(f"  {linha['corpus'][:40]:40} {rotulo}: {amostra}{resto}")
    else:
        print("Nenhuma perda de literalidade nos corpora medidos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
