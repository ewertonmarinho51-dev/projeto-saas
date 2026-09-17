"""
A tabela consolidada vira a lista canônica do processo.

§14: alimenta o mecanismo de itens que JÁ existe — `dados["itens"]`, no
esquema de `planilha.CAMPOS_ITEM`. Não cria segunda lista, porque duas
listas de itens no mesmo processo divergem na primeira edição manual e
ninguém sabe qual vale.

Onde mora a alocação por secretaria, e por quê
----------------------------------------------
Na PROVENIÊNCIA, não no item. A tentação é gravar uma coluna por
secretaria em cada linha da planilha — é como a tabela é lida na tela,
afinal. Mas `planilha.colunas_extra` promove qualquer campo novo de item
a coluna de todo documento exportado: doze secretarias virariam doze
colunas dentro do edital e da ata.

O módulo de pesquisa de preços já tropeçou nisso e deixou o aviso
escrito em `precos/aplicacao.py`. Aqui a lição chega de graça.

O que NÃO entra
---------------
Valor. §15: o que veio na Solicitação de Despesa é dado de origem, não
preço praticado — nos arquivos reais ele vem zerado de qualquer forma.
Preço é assunto do módulo de pesquisa, com as regras dele.
"""

from __future__ import annotations

from decimal import Decimal

from .consolidacao import Consolidado, conferir

# Onde mora o objeto estruturado dentro de `dados`. NÃO é campo de item,
# pelo motivo explicado acima.
CHAVE_PROVENIENCIA = "consolidacao_demanda"


class ErroAplicacao(Exception):
    """Recusa deliberada antes de gravar no processo."""


def _texto(valor: Decimal) -> str:
    """
    Decimal para texto sem notação científica e sem zeros à toa.

    `str(Decimal("50.0000"))` guardaria "50.0000" e a planilha mostraria
    uma quantidade com quatro casas onde o servidor digitou cinquenta.
    """
    normalizado = valor.normalize()
    if normalizado == normalizado.to_integral_value():
        normalizado = normalizado.quantize(Decimal(1))
    return format(normalizado, "f")


def chave_do_item(codigo: str, unidade: str) -> str:
    """A mesma chave da consolidação, em forma serializável."""
    return f"{codigo}|{unidade}"


def aplicar(dados: dict, consolidado: Consolidado, *,
            conflitos_aceitos: tuple[str, ...] = ()) -> tuple[dict, dict]:
    """
    Devolve `(novos_dados, resumo)`. Não altera o dicionário recebido.

    Recusa em três casos, e os três são deliberados:

    - **conflito de unidade pendente**: gravaria uma quantidade que
      ninguém decidiu. Aceitar o conflito é ato do servidor — ele diz
      que viu e mantém as linhas separadas, e isso fica registrado;
    - **conta que não fecha**: transformaria erro de soma em número
      oficial do processo;
    - **consolidado vazio**: aplicar nada não é aplicar zero. Sem esta
      recusa, um upload que falhou apagaria a planilha que o servidor
      já tinha montado à mão.
    """
    pendentes = [c.codigo for c in consolidado.conflitos
                 if c.codigo not in conflitos_aceitos]
    if pendentes:
        raise ErroAplicacao(
            "Há conflito de unidade sem decisão nos itens "
            f"{', '.join(pendentes[:5])}. Resolva ou confirme cada um "
            "antes de aplicar ao processo.")

    if not consolidado.linhas:
        raise ErroAplicacao(
            "Nenhum item consolidado. Aplicar agora apagaria a planilha "
            "atual do processo sem colocar nada no lugar.")

    laudo = conferir(consolidado)
    if not laudo.fecha:
        raise ErroAplicacao(
            "A conferência da soma não fechou: "
            f"{laudo.divergencias[0]}. Nada foi gravado.")

    itens = []
    por_item = {}
    for linha in consolidado.linhas:
        itens.append({
            "codigo": linha.codigo,
            "descricao": linha.descricao,
            "unidade": linha.unidade,
            "quantidade": _texto(linha.total),
            # §15: o preço não vem daqui.
            "valor_unitario": "",
        })
        por_item[chave_do_item(linha.codigo, linha.unidade)] = {
            "total": _texto(linha.total),
            "por_secretaria": {s: _texto(q)
                               for s, q in sorted(linha.por_secretaria.items())},
            "origens": [
                {"secretaria": o.secretaria, "arquivo": o.arquivo,
                 "dfd": o.dfd, "quantidade": _texto(o.quantidade)}
                for o in linha.origens
            ],
            "variacoes_descricao": list(linha.variacoes_descricao),
        }

    novos = dict(dados)
    novos["itens"] = itens
    novos[CHAVE_PROVENIENCIA] = {
        "secretarias": list(consolidado.secretarias),
        "nao_lidos": list(consolidado.nao_lidos),
        "duplicatas": list(consolidado.duplicatas),
        "conflitos_aceitos": list(conflitos_aceitos),
        "ocorrencias": laudo.total_de_ocorrencias,
        "por_item": por_item,
    }

    resumo = {
        "itens": len(itens),
        "secretarias": len(consolidado.secretarias),
        "ocorrencias": laudo.total_de_ocorrencias,
        "nao_lidos": list(consolidado.nao_lidos),
        "duplicatas": list(consolidado.duplicatas),
        "conflitos_aceitos": list(conflitos_aceitos),
    }
    return novos, resumo


def alocacao_do_item(dados: dict, codigo: str, unidade: str) -> dict:
    """
    Quanto cada secretaria pediu deste item, depois de aplicado.

    Existe para a tela de conferência e para o "ver origem": quem
    audita precisa refazer a conta sem reabrir doze PDFs.
    """
    prov = (dados or {}).get(CHAVE_PROVENIENCIA) or {}
    item = (prov.get("por_item") or {}).get(chave_do_item(codigo, unidade)) or {}
    return item.get("por_secretaria") or {}


__all__ = ["CHAVE_PROVENIENCIA", "ErroAplicacao", "alocacao_do_item",
           "aplicar", "chave_do_item"]
