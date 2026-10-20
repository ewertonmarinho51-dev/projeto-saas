"""
Serviço ÚNICO de busca de preços — Banco de Preços (manual) e Pesquisa
Automática usam exatamente este caminho.

    fontes oficiais → coleta → procedência → deduplicação → normalização de
    unidade → comparabilidade (score explicável)

Saem daqui candidatos ranqueados e as contagens que a tela e o relatório
precisam distinguir: o que a fonte devolveu (brutas), o que sobrou depois
de tirar o mesmo registro visto duas vezes (únicas), o que é comparável o
bastante para entrar numa cesta (elegíveis). Cesta, método e estimativa
NÃO moram aqui — moram em `estatistica` e `cesta`, iguais para as duas
modalidades.

Nada aqui chama IA nem grava em banco. Os termos da camada semântica,
quando existem, chegam prontos de quem chama.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from . import matching, unidades
from . import fontes as fontes_mod
from .fontes import Desfecho, FontePesquisaPreco
from .modelo import (NATUREZAS_COMPARAVEIS, Referencia,
                     conferir_procedencia, deduplicar)


@dataclass
class Coleta:
    """O que a busca encontrou para UM item, antes de qualquer cesta."""

    referencias: list[tuple[Referencia, matching.Comparabilidade]] = field(
        default_factory=list)
    ocorrencias: list[str] = field(default_factory=list)
    desfechos: dict[str, str] = field(default_factory=dict)
    de_preco: frozenset = frozenset()
    brutas: int = 0
    unicas: int = 0
    erro: str = ""
    duracao_s: float = 0.0
    codigo_confirmado: bool = False
    # fontes que a política automática deixou de consultar (amostra já
    # suficiente) — vão para a trilha, nunca somem
    fontes_nao_consultadas: list[str] = field(default_factory=list)
    _ocorrencias_da_fusao: list[str] = field(default_factory=list, repr=False)

    @property
    def duplicadas(self) -> int:
        return self.brutas - self.unicas

    def elegiveis(self, piso: Decimal) -> int:
        """Quantas a cesta automática aceitaria (ver `pre_selecao`)."""
        return len(self.pre_selecao(piso))

    def pre_selecao(self, piso: Decimal) -> set[str]:
        """
        As chaves que `estatistica.selecionar_cesta` poria na cesta: preço
        normalizado, natureza de preço (não estimativa de outro órgão) e
        comparabilidade ≥ piso. A consulta manual parte da MESMA regra da
        automática; o servidor ajusta a partir daí.
        """
        return {ref.chave_dedupe for ref, comp in self.referencias
                if ref.valor_unitario_normalizado is not None
                and ref.natureza_valor in NATUREZAS_COMPARAVEIS
                and comp.score >= piso}


def _mesma_compra(ref: Referencia) -> tuple | None:
    """
    Identidade MATERIAL da observação: a compra (idCompra do Compras.gov),
    o fornecedor e o preço. O PNCP publica a mesma compra com outro id;
    o `idCompra` vem no link do sistema de origem (`pncp._id_compra_de_origem`).
    """
    bruto = ref.bruto or {}
    compra = (bruto.get("idCompraOrigem") if ref.fonte.id == "pncp"
              else bruto.get("idCompra"))
    if not compra or not ref.ni_fornecedor or ref.valor_unitario_original is None:
        return None
    return (str(compra), str(ref.ni_fornecedor), ref.valor_unitario_original)


def fundir_entre_portais(referencias: list[Referencia],
                         ocorrencias: list[str]) -> list[Referencia]:
    """
    A mesma compra vista no Compras.gov E no PNCP conta UMA vez (IDX-02):
    fica a primeira (a ordem das fontes é a da prioridade), e a outra
    vira evidência registrada no motivo — não segundo preço na cesta.
    """
    vistas: dict[tuple, Referencia] = {}
    saida: list[Referencia] = []
    fundidas = 0
    for ref in referencias:
        chave = _mesma_compra(ref)
        if chave is not None and chave in vistas:
            if vistas[chave].fonte.id != ref.fonte.id:
                vistas[chave].com_motivo(
                    f"mesma compra também publicada em {ref.fonte.nome} "
                    f"({ref.referencia_externa or ref.id_externo})")
                fundidas += 1
                continue
        if chave is not None:
            vistas.setdefault(chave, ref)
        saida.append(ref)
    if fundidas:
        ocorrencias.append(
            f"{fundidas} referência(s) era(m) a mesma compra em dois portais "
            "— contada(s) uma vez")
    return saida


def _decimal(valor) -> Decimal | None:
    if valor in (None, ""):
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _ranquear(coletadas: list[Referencia], item: dict, filtros: dict,
              coleta: Coleta, pdms_inferidos: set[str]
              ) -> list[tuple[Referencia, matching.Comparabilidade]]:
    """
    Procedência → deduplicação (inclusive entre portais) → unidade →
    comparabilidade. Atualiza `brutas`/`unicas` da coleta; as ocorrências
    da fusão entre portais são registradas por quem chama.
    """
    from .execucao import codigo_de_catalogo

    coleta.brutas = len(coletadas)
    ocorrencias: list[str] = []
    unicas = conferir_procedencia(
        fundir_entre_portais(deduplicar(coletadas), ocorrencias))
    coleta.unicas = len(unicas)
    coleta._ocorrencias_da_fusao = ocorrencias

    unidade = str(item.get("unidade") or "")
    conteudo = unidades.conteudo_declarado(item.get("descricao"))
    normalizadas = [unidades.normalizar(r, unidade, conteudo) for r in unicas]

    data_base = filtros.get("data_base")
    if isinstance(data_base, str):
        data_base = date.fromisoformat(data_base[:10])

    # O código do item só serve de prova de identidade quando é MESMO de
    # catálogo: tipo declarado, ou a própria fonte confirmou que ele traz
    # preços. Código interno do município (6 dígitos na planilha real de
    # 210 itens) zerava a identidade de TODAS as referências — medido em
    # 15/10/2026: 0 de 10 itens concluídos.
    codigo = codigo_de_catalogo(item)
    if codigo and not (item.get("tipo_catalogo") or coleta.codigo_confirmado):
        codigo = None

    return matching.ordenar_por_comparabilidade(
        normalizadas,
        descricao=str(item.get("descricao") or ""),
        codigo_catalogo=codigo,
        quantidade=_decimal(item.get("quantidade")),
        uf=filtros.get("uf") or None,
        data_base=data_base,
        pdms_item=frozenset(pdms_inferidos),
    )


def coletar(item: dict, fontes: list[FontePesquisaPreco], *,
            filtros: dict | None = None,
            termos: tuple[str, ...] = (),
            politica=None) -> Coleta:
    """
    Coleta, depura e ranqueia as referências de um item.

    **Falha de fonte não derruba a busca** (§37): cada adapter roda no
    seu `try`. Se TODAS as fontes de preço falharem, `erro` diz que é
    falha técnica — não "o mercado não tem o item".

    `politica` (`estatistica.PoliticaAmostraAutomatica`, só na cotação
    automática): pede menos registros a cada fonte e PARA de consultar as
    fontes seguintes quando as elegíveis já bastam (`suficiente`). As
    fontes vêm em ordem de prioridade normativa, então a que fica de fora
    é a de menor prioridade — e a trilha diz qual foi e por quê.
    """
    from .estatistica import PISO_COMPARABILIDADE
    from .execucao import consulta_do_item

    filtros = dict(filtros or {})
    if politica is not None:
        filtros.setdefault("limite", politica.limite_por_fonte)
        filtros.setdefault("limite_grupo", politica.limite_por_grupo)
    inicio = time.monotonic()
    coleta = Coleta()
    consulta = consulta_do_item(item, filtros, termos)

    coletadas: list[Referencia] = []
    pdms_inferidos: set[str] = set()
    de_preco: set[str] = set()
    ranqueadas = None
    for posicao, fonte in enumerate(fontes):
        fid = getattr(getattr(fonte, "fonte", None), "id", "") or repr(fonte)
        nome = getattr(getattr(fonte, "fonte", None), "nome", "fonte")
        if politica is not None and ranqueadas is not None:
            elegiveis = sum(
                1 for ref, comp in ranqueadas
                if ref.valor_unitario_normalizado is not None
                and ref.natureza_valor in NATUREZAS_COMPARAVEIS
                and comp.score >= PISO_COMPARABILIDADE)
            if elegiveis >= politica.suficiente:
                puladas = [getattr(getattr(f, "fonte", None), "nome", "fonte")
                           for f in fontes[posicao:]]
                coleta.fontes_nao_consultadas = puladas
                coleta.ocorrencias.append(
                    f"busca encerrada com {elegiveis} preço(s) comparável(is) "
                    f"— suficiente pela política {politica.versao}; não "
                    f"consultada(s): {', '.join(puladas)}")
                break
        if fontes_mod.fornece_preco(fonte):
            de_preco.add(fid)
        try:
            busca = fonte.pesquisar(consulta)
        except Exception as exc:  # noqa: BLE001 — adapter nenhum derruba a busca
            coleta.desfechos[fid] = Desfecho.FALHA.value
            coleta.ocorrencias.append(
                f"{nome}: indisponível no momento ({type(exc).__name__})")
            continue
        coleta.desfechos[fid] = busca.desfecho.value
        coletadas.extend(busca.referencias)
        pdms_inferidos.update(getattr(busca, "pdms_inferidos", None) or ())
        coleta.codigo_confirmado |= bool(
            getattr(busca, "codigo_confirmado", False))
        coleta.ocorrencias.extend(busca.ocorrencias)
        if politica is not None and posicao < len(fontes) - 1:
            # só a automática paga o ranqueamento parcial: é ele que
            # decide se vale chamar a próxima fonte
            ranqueadas = _ranquear(coletadas, item, filtros, coleta,
                                   pdms_inferidos)
    coleta.de_preco = frozenset(de_preco)

    falharam = [fid for fid in de_preco
                if coleta.desfechos.get(fid) == Desfecho.FALHA.value]
    if de_preco and len(falharam) == len(de_preco):
        coleta.erro = (
            "as fontes de preço não responderam "
            f"({', '.join(sorted(falharam))}) — isto é falha técnica, não "
            "ausência de preço no mercado; o item volta para a fila")
    elif not de_preco:
        coleta.erro = ("nenhuma fonte capaz de fornecer preço foi "
                       "configurada para esta pesquisa")
    if coleta.erro:
        coleta.duracao_s = time.monotonic() - inicio
        return coleta

    # Procedência ANTES de tudo; depois o mesmo registro visto em dois
    # caminhos (ou duas fontes) vira um só (§55, "não somar espelhados").
    coleta.referencias = _ranquear(coletadas, item, filtros, coleta,
                                   pdms_inferidos)
    coleta.ocorrencias.extend(coleta._ocorrencias_da_fusao)
    coleta.duracao_s = time.monotonic() - inicio
    return coleta
