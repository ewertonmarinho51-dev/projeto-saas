"""
Serviço ÚNICO de cesta — recalcula o preço do item a partir da seleção
GRAVADA, igual para o Banco de Preços manual e a Pesquisa Automática.

Antes, incluir ou excluir uma referência na revisão mudava só o status
dela: o preço estimado do item continuava o calculado pela máquina, e a
memória de cálculo descrevia uma cesta que já não existia. Agora toda
mudança de seleção passa por aqui, e o número é refeito com o mesmo
`estatistica.estimar` do pipeline — não há segundo cálculo.

As linhas lidas são as de `pesquisa_preco_referencias` (o servidor é a
fonte da verdade, não o `session_state`): reabrir a pesquisa em outra
sessão mostra a mesma cesta e o mesmo preço.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from . import estatistica
from .estados import EstadoItem
from .modelo import Fonte, NaturezaValor, Referencia
from .perfil import PerfilNormativo

SELECIONADA = "selected"


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _data(valor) -> date | None:
    try:
        return date.fromisoformat(str(valor)[:10]) if valor else None
    except ValueError:
        return None


def referencia_da_linha(linha: dict) -> Referencia:
    """Linha gravada → `Referencia`, com o preço NORMALIZADO gravado."""
    try:
        natureza = NaturezaValor(str(linha.get("natureza_valor") or "outro"))
    except ValueError:
        natureza = NaturezaValor.OUTRO
    return Referencia(
        fonte=Fonte(id=str(linha.get("fonte_id") or ""),
                    nome=str(linha.get("fonte_nome") or ""),
                    tipo=str(linha.get("fonte_tipo") or "outro")),
        id_externo=str(linha.get("id_externo") or ""),
        bruto=dict(linha.get("bruto") or {}),
        descricao_original=str(linha.get("descricao_original") or ""),
        unidade_original=linha.get("unidade_original"),
        valor_unitario_original=_decimal(linha.get("valor_unitario_original")),
        natureza_valor=natureza,
        orgao=linha.get("orgao"),
        data_compra=_data(linha.get("data_compra")),
        unidade_normalizada=linha.get("unidade_normalizada"),
        valor_unitario_normalizado=_decimal(
            linha.get("valor_unitario_normalizado")),
    )


def _compoe_cesta(referencia: Referencia) -> bool:
    """Preço praticado/homologado/contratado/adjudicado, ou cotação direta
    registrada com a trilha do art. 23, § 1º, IV (`cotacao.admissivel`)."""
    from . import cotacao

    return referencia.serve_de_preco or cotacao.admissivel(referencia)


def recalcular(linhas: list[dict], *, perfil: PerfilNormativo,
               regras: str, justificativa: str | None = None
               ) -> estatistica.Estimativa:
    """
    Estimativa da cesta formada pelas linhas com status SELECIONADA.

    Só entra quem tem preço normalizado: referência sem conversão de
    unidade comprovada não compõe média nenhuma, mesmo marcada.
    """
    selecionadas = [referencia_da_linha(linha) for linha in linhas
                    if str(linha.get("status")) == SELECIONADA]
    com_preco = [r for r in selecionadas
                 if r.valor_unitario_normalizado is not None]
    de_preco = [r for r in com_preco if _compoe_cesta(r)]
    cesta = estatistica.Cesta(selecionadas=de_preco)
    if len(com_preco) < len(selecionadas):
        cesta.motivos.append(
            f"{len(selecionadas) - len(com_preco)} referência(s) marcada(s) "
            "sem preço normalizado (unidade não comprovada) ficaram fora "
            "do cálculo")
    if len(de_preco) < len(com_preco):
        cesta.motivos.append(
            f"{len(com_preco) - len(de_preco)} referência(s) marcada(s) com "
            "valor que não é preço praticado (ex.: estimativa de outro "
            "órgão) ficaram fora do cálculo")
    return estatistica.estimar(cesta, perfil=perfil, justificativa=justificativa,
                               regras=regras)


def recalcular_e_gravar(pesquisa: dict, item: dict, repositorio, *,
                        perfil: PerfilNormativo) -> estatistica.Estimativa:
    """
    Refaz a estimativa do item pela seleção gravada e persiste.

    O item fica em REVISÃO se a cesta fecha o perfil, INCOMPLETO se não
    fecha — a regra dos três vale igual depois da edição humana.
    """
    linhas = repositorio.listar_referencias(str(item["id"]))
    estimativa = recalcular(
        linhas, perfil=perfil,
        regras=str(pesquisa.get("versao_regras") or
                   estatistica.REGRAS_LEGADAS))
    repositorio.atualizar_estimativa(
        item, estimativa, quantidade=_decimal(item.get("quantidade")))
    return estimativa


def validas_na_cesta(linhas: list[dict]) -> int:
    """Quantas referências selecionadas têm preço normalizado — o N de "N/3"."""
    return sum(1 for linha in linhas
               if str(linha.get("status")) == SELECIONADA
               and _decimal(linha.get("valor_unitario_normalizado"))
               is not None
               and _compoe_cesta(referencia_da_linha(linha)))


def na_cesta_do_item(item: dict) -> int | None:
    """
    O N de "N/3" a partir do que o item JÁ gravou (`estatisticas`), sem
    reler referências: a tabela de 210 itens não pode fazer 210 consultas
    para desenhar um indicador. `None` = o item ainda não foi pesquisado.
    """
    gravado = item.get("estatisticas")
    if not isinstance(gravado, dict) or "selecionadas" not in gravado:
        return None
    try:
        return int(gravado["selecionadas"])
    except (TypeError, ValueError):
        return None


def indicador(item: dict, minimo: int = 3) -> str:
    """ "3/3 ✓", "2/3" ou "—" (não pesquisado)."""
    n = na_cesta_do_item(item)
    if n is None:
        return "—"
    return f"{n}/{minimo} ✓" if n >= minimo else f"{n}/{minimo}"


ESTADOS_RECALCULAVEIS = frozenset({EstadoItem.EM_REVISAO.value,
                                   EstadoItem.INCOMPLETO.value})


def salvar_consulta_como_pesquisa(
        *, repositorio, nome: str, item: dict, coleta, selecionados: set[str],
        perfil: PerfilNormativo, auth_user_id: str,
        secretaria_id: str | None = None, processo_id: str | None = None,
        filtros: dict | None = None, idempotency_key: str = "") -> dict:
    """
    A consulta do Banco de Preços vira uma pesquisa — a MESMA entidade da
    Pesquisa Automática, com o mesmo item, referências, cesta, relatórios
    e aplicação ao processo. Não há "pesquisa manual" paralela.

    `selecionados` são as chaves (`fonte:id_externo`) que o servidor
    marcou; as demais candidatas também são gravadas, para que a
    revisão mostre o que foi visto e não escolhido. O item percorre as
    mesmas transições do motor (pendente → buscando → classificando →
    revisão/incompleto): nada pula a máquina de estados.
    """
    from .estados import EstadoPesquisa
    from .modelo import StatusReferencia

    # Duplo clique / rerun não cria segunda pesquisa: a mesma chave
    # devolve a que já existe.
    if idempotency_key:
        existente = repositorio.obter_por_chave(idempotency_key)
        if existente:
            return {"pesquisa_id": str(existente["id"]), "item_id": None,
                    "estimativa": None, "reaproveitada": True}

    pesquisa = repositorio.criar_pesquisa(
        nome, auth_user_id=auth_user_id, secretaria_id=secretaria_id,
        processo_id=processo_id, perfil_normativo=perfil.id,
        filtros=dict(filtros or {}),
        versao_regras=estatistica.REGRAS_MEDIA_PADRAO,
        idempotency_key=idempotency_key)
    pesquisa_id = str(pesquisa["id"])
    [linha_item] = repositorio.salvar_itens(pesquisa_id, [{
        "numero": 1, "codigo": item.get("codigo") or None,
        "tipo_catalogo": item.get("tipo_catalogo") or None,
        "descricao": item["descricao"], "unidade": item.get("unidade") or "",
        "quantidade": item.get("quantidade")}])
    item_id = str(linha_item["id"])

    # A tela manda chaves; quem decide se a chave pode compor cesta é o
    # servidor. Natureza não comparável ou unidade não comprovada ficam
    # CANDIDATAS mesmo que venham marcadas.
    for referencia, _comp in coleta.referencias:
        apta = (referencia.chave_dedupe in selecionados
                and referencia.valor_unitario_normalizado is not None
                and referencia.serve_de_preco)
        referencia.status = (StatusReferencia.SELECIONADA if apta
                             else StatusReferencia.CANDIDATA)
    escolhidas = sum(1 for r, _ in coleta.referencias
                     if r.status is StatusReferencia.SELECIONADA)
    repositorio.mover_pesquisa(pesquisa_id, EstadoPesquisa.NA_FILA,
                               EstadoPesquisa.RASCUNHO)
    repositorio.mover_pesquisa(pesquisa_id, EstadoPesquisa.EXECUTANDO,
                               EstadoPesquisa.NA_FILA)
    repositorio.mover_item(item_id, EstadoItem.BUSCANDO, EstadoItem.PENDENTE)
    repositorio.registrar_referencias(item_id, coleta.referencias)
    repositorio.mover_item(item_id, EstadoItem.CLASSIFICANDO,
                           EstadoItem.BUSCANDO)

    linhas = repositorio.listar_referencias(item_id)
    estimativa = recalcular(linhas, perfil=perfil,
                            regras=estatistica.REGRAS_MEDIA_PADRAO)
    repositorio.registrar_estimativa(
        item_id, estimativa, atual=EstadoItem.CLASSIFICANDO,
        quantidade=_decimal(item.get("quantidade")))
    destino = (EstadoPesquisa.EM_REVISAO if estimativa.concluida
               else EstadoPesquisa.PARCIAL)
    repositorio.mover_pesquisa(pesquisa_id, destino, EstadoPesquisa.EXECUTANDO)
    repositorio.registrar_evento(
        pesquisa_id, "pesquisa_criada", ator=auth_user_id,
        descricao=f"Banco de Preços: consulta salva com "
                  f"{escolhidas} referência(s) escolhida(s) de "
                  f"{coleta.unicas} encontrada(s)",
        payload={"origem": "banco_de_precos", "brutas": coleta.brutas,
                 "unicas": coleta.unicas, "selecionadas": escolhidas,
                 "valor": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f")})
    return {"pesquisa_id": pesquisa_id, "item_id": item_id,
            "estimativa": estimativa}
