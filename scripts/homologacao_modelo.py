#!/usr/bin/env python3
"""
Homologa — ou reprova — um motor para GERAÇÃO DE DOCUMENTO OFICIAL.

O QUE ESTÁ EM JOGO

`PROCUREMENT_HIGH_ACCURACY` é o grupo de motores que podem gerar DFD,
ETP, TR, Mapa de Riscos, edital e ARP. O que sai dali é assinado por
agente público e publicado. Entrar nesse grupo não pode ser uma linha
acrescentada numa tabela porque alguém achou que o modelo é bom: precisa
ser o resultado de uma medição que qualquer pessoa consegue repetir.

Este script é essa medição. Ele gera documentos REAIS com o motor
candidato, a partir de um caso real do repositório — 210 itens, valores,
códigos, unidades —, e confere se o que entrou saiu LITERAL.

O CRITÉRIO É LITERALIDADE, NÃO SEMELHANÇA

Um documento pode estar bem escrito, bem estruturado, juridicamente
elegante — e ter trocado `R$ 8.024.834,67` por `R$ 8.024.834,00`. Para um
edital isso não é um erro de digitação: é outro valor licitado. Por isso
o veredito olha primeiro o que NÃO pode mudar:

  valor monetário · quantidade · unidade · código de item · data ·
  artigo de lei · identificador · link

Estrutura e completude entram depois, e não salvam um motor que perdeu um
número.

EXIGE CHAVE DE API — e a chave NÃO é lida, impressa nem registrada por
este script. Ele usa o caminho normal do aplicativo (`llm.gerar_documento`),
que já sabe onde ela mora.

USO

    # o motor candidato precisa estar configurado no ambiente do app
    .venv/bin/python scripts/homologacao_modelo.py --motor gemini
    .venv/bin/python scripts/homologacao_modelo.py --motor gemini --gravar

`--gravar` escreve `docs/homologacao/<motor>.json`. Esse arquivo é a
evidência; sem ele, `tests/test_homologacao.py` recusa o motor no grupo
crítico.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

RELATORIOS = RAIZ / "docs" / "homologacao"
FIXTURE = RAIZ / "tests" / "fixtures" / "caso_210_itens.json"

# Os documentos da cadeia. O edital é o mais exigente — ele herda o TR
# inteiro —, e por isso é o que mais importa aqui.
CADEIA = ("dfd", "etp", "tr", "edital")

# ---------------------------------------------------------------------------
# O QUE NÃO PODE MUDAR
#
# Mesma lista de `scripts/headroom_bench.py`, e de propósito: são duas
# camadas diferentes (compressão e roteamento) medindo a MESMA promessa.
# Duas definições de "literal" divergiriam na primeira correção feita só
# de um lado.
# ---------------------------------------------------------------------------
LITERAIS = {
    "valor monetário": re.compile(r"R\$\s?[\d.]+,\d{2}"),
    "quantidade": re.compile(r"\b\d+(?:\.\d{3})*,\d{4}\b"),
    "código de item": re.compile(r"\b\d{6}\b"),
    "data": re.compile(r"\b\d{2}/\d{2}/\d{4}\b"),
    "artigo de lei": re.compile(r"\bart\.?\s?\d+[ºo°]?", re.I),
    "lei": re.compile(r"\bLei\s+n[ºo°]?\s?[\d.]+/\d{4}"),
    "link": re.compile(r"https?://\S+"),
}


def literais(texto: str) -> dict[str, set[str]]:
    return {rotulo: set(p.findall(texto)) for rotulo, p in LITERAIS.items()}


def caso_real() -> dict:
    """
    O caso de avaliação: dados de um processo real deste repositório.

    Não é sintético de propósito. Um modelo que acerta "material de
    escritório, 3 itens" e erra numa planilha de 210 linhas com códigos de
    seis dígitos não está homologado — está sem ter sido testado.
    """
    bruto = json.loads(FIXTURE.read_text())
    itens = bruto["itens"]
    return {
        "orgao": "Prefeitura Municipal de Ensaio",
        "objeto": bruto["objeto"],
        "justificativa": (
            "Reposição do estoque de materiais de expediente das unidades "
            "administrativas, esgotado no exercício corrente."),
        "valor_estimado": bruto["valor_estimado"],
        "itens": itens,
        "modalidade": "Pregão Eletrônico",
        "criterio_julgamento": "Menor preço por item",
    }


def _entrada_literal(dados: dict) -> dict[str, set[str]]:
    """Os literais que ENTRARAM — contra os quais a saída é conferida."""
    return literais(json.dumps(dados, ensure_ascii=False))


def avaliar(motor: str, dados: dict, *, limite: int) -> list[dict]:
    """Gera a cadeia com o motor e mede cada documento."""
    from src import llm

    entrada = _entrada_literal(dados)
    resultados: list[dict] = []
    contexto: str | None = None

    for doc in CADEIA:
        inicio = time.perf_counter()
        try:
            texto = llm.gerar_documento(doc, dict(dados), contexto)
        except Exception as erro:  # noqa: BLE001
            resultados.append({
                "documento": doc, "status": "erro",
                "erro": f"{type(erro).__name__}: {erro}",
            })
            break
        segundos = round(time.perf_counter() - inicio, 1)
        contexto = texto

        saida = literais(texto)
        perdas = {r: sorted(v - saida[r])[:limite]
                  for r, v in entrada.items() if v - saida[r]}
        total = sum(len(v - saida[r]) for r, v in entrada.items())

        resultados.append({
            "documento": doc,
            "status": "ok" if total == 0 else "perdeu literalidade",
            "caracteres": len(texto),
            "segundos": segundos,
            "literais_perdidos": total,
            "amostra": perdas,
        })
    return resultados


def veredito(resultados: list[dict]) -> tuple[bool, str]:
    if any(r["status"] == "erro" for r in resultados):
        return False, "a geração falhou — não há o que homologar"
    if len(resultados) < len(CADEIA):
        return False, "a cadeia não foi concluída"
    perdidos = sum(r.get("literais_perdidos", 0) for r in resultados)
    if perdidos:
        return False, (f"{perdidos} literal(is) perdido(s): número, valor, "
                       "data ou referência saiu diferente do que entrou")
    return True, "nenhum literal perdido na cadeia completa"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--motor", required=True,
                   choices=("openai", "gemini", "openrouter"))
    p.add_argument("--gravar", action="store_true",
                   help="escreve docs/homologacao/<motor>.json")
    p.add_argument("--amostra", type=int, default=8,
                   help="quantos literais perdidos listar por categoria")
    args = p.parse_args()

    from src import llm

    # Força O MOTOR CANDIDATO, e só ele: homologar com fallback ligado
    # mediria a cascata, não o modelo.
    llm.motores_disponiveis = _apenas(args.motor, llm)

    print(f"homologando '{args.motor}' na cadeia {' → '.join(CADEIA)}\n")
    dados = caso_real()
    print(f"caso: {dados['objeto']} · {len(dados['itens'])} itens · "
          f"R$ {dados['valor_estimado']:,.2f}\n".replace(",", "X")
          .replace(".", ",").replace("X", "."))

    resultados = avaliar(args.motor, dados, limite=args.amostra)

    for r in resultados:
        if r["status"] == "erro":
            print(f"  {r['documento']:8} ERRO — {r['erro'][:160]}")
            continue
        print(f"  {r['documento']:8} {r['caracteres']:>7} car · "
              f"{r['segundos']:>5}s · perdidos: {r['literais_perdidos']}")
        for rotulo, valores in (r["amostra"] or {}).items():
            print(f"           {rotulo}: {', '.join(valores)}")

    aprovado, motivo = veredito(resultados)
    print(f"\nVEREDITO: {'APROVADO' if aprovado else 'REPROVADO'} — {motivo}")

    if args.gravar:
        RELATORIOS.mkdir(parents=True, exist_ok=True)
        alvo = RELATORIOS / f"{args.motor}.json"
        alvo.write_text(json.dumps({
            "motor": args.motor,
            "aprovado": aprovado,
            "motivo": motivo,
            "caso": FIXTURE.name,
            "itens": len(dados["itens"]),
            "cadeia": list(CADEIA),
            "resultados": resultados,
            "gerado_em": time.strftime("%Y-%m-%d"),
        }, ensure_ascii=False, indent=2))
        print(f"relatório: {alvo.relative_to(RAIZ)}")
        if aprovado:
            print(f"\nPara promover, acrescente '{args.motor}' a "
                  "roteamento.MOTORES_DO_GRUPO[PROCUREMENT_HIGH_ACCURACY] "
                  "no MESMO commit deste relatório.")

    return 0 if aprovado else 1


def _apenas(motor: str, llm):
    """Substitui `motores_disponiveis` para deixar só o candidato."""
    original = llm.motores_disponiveis

    def so_ele():
        return [(m, k) for m, k in original() if m == motor]
    return so_ele


if __name__ == "__main__":
    sys.exit(main())
