"""
Projeção do relatório de cotação — `CotacaoReportView`.

UM retrato, somente leitura, de tudo o que os documentos da cotação
imprimem: o relatório de cotação (PDF/DOCX compacto), o relatório
analítico integral e a memória analítica (XLSX) leem daqui, e por isso não
podem discordar entre si em preço, contagem, método ou pendência.

O que esta projeção NÃO faz, de propósito:

* não calcula preço. Unitário, total, método e memória são os GRAVADOS no
  item (`cesta.recalcular` → `repositorio.atualizar_estimativa`); a
  contagem N/3 é `cesta.consideradas`, a mesma do cálculo e da tela;
* não troca regra antiga por nova. Pesquisa criada sob a regra legada
  (mediana em série dispersa) continua mostrando mediana;
* não completa dado ausente. Onde a fonte não trouxe, fica "Não
  informado"; link só quando o adaptador da fonte o monta;
* não toca banco, sessão, rede nem IA.

A única soma é o subtotal dos itens CONCLUÍDOS — a mesma do relatório
legado (`completo`, seção 18) — e o "valor global" só existe quando
todos os itens estão concluídos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import MappingProxyType

from . import cesta as cesta_mod
from . import relatorio as rel
from .estados import ROTULO_PESQUISA, EstadoItem
from .estatistica import REGRAS_MEDIA_PADRAO, ROTULO_METODO
from .modelo import ROTULO_NATUREZA, NaturezaValor
from .perfil import inciso_da_fonte
from .perfil import obter as obter_perfil

NAO_INFORMADO = "Não informado"

# Quantas referências o relatório COMPACTO mostra por item. Revisão 02:
# TODAS as consideradas (a cesta automática tem no máximo 15), para o
# relatório bastar sozinho; o corte só vale para cesta antiga, formada
# antes do teto, e o documento diz quantas foram exibidas.
REFERENCIAS_EXIBIDAS = 30

# Brasil sem horário de verão desde 2019: UTC−3 fixo é o horário de
# Brasília, e não depende de base de fusos instalada no servidor.
BRASILIA = timezone(timedelta(hours=-3), "BRT")


@dataclass(frozen=True)
class ReferenciaView:
    id: str
    considerada: bool
    status: str
    situacao: str
    motivo: str
    sinalizada: bool
    fonte_id: str
    fonte: str
    inciso: str
    natureza: str
    orgao: str
    uf: str
    municipio: str
    fornecedor: str
    data: str
    quantidade: Decimal | None
    unidade: str
    unidade_original: str
    valor: Decimal | None
    valor_original: Decimal | None
    compatibilidade: Decimal | None
    id_externo: str
    evidencia: str
    link: str | None
    coletado_em: str
    descricao_fonte: str
    # Revisão 02 (06_FONTES_E_LINKS): página PÚBLICA da contratação, rótulo
    # do que ela é, identificação impressa e o endpoint técnico à parte.
    contratacao_url: str | None = None
    contratacao_rotulo: str = ""
    identificacao: str = ""
    dados_url: str | None = None
    fonte_url: str | None = None
    # dados da contratação, só quando a fonte os entrega (nunca inventados)
    objeto_contratacao: str = ""
    modalidade: str = ""
    fornecedor_cnpj: str = ""
    marca: str = ""
    item_da_compra: str = ""
    # como a referência saiu da cesta, dito com a autoria certa
    autoria_da_saida: str = ""


@dataclass(frozen=True)
class ItemView:
    id: str
    numero: int
    titulo: str
    descricao: str
    unidade: str
    quantidade: Decimal | None
    codigo: str
    tipo_catalogo: str
    estado: str
    situacao: str
    concluido: bool
    metodo: str
    metodo_rotulo: str
    preco_unitario: Decimal | None
    preco_total: Decimal | None
    consideradas: int
    minimo: int
    total_referencias: int
    estatisticas: MappingProxyType
    memoria: tuple[str, ...]
    excecao: MappingProxyType | None
    excecoes_invalidadas: tuple[str, ...]
    metodo_do_revisor: MappingProxyType | None
    deficiencias: tuple[str, ...]
    analise_critica: tuple[str, ...]
    anomalias: tuple[MappingProxyType, ...]
    marcas_percentuais: tuple[MappingProxyType, ...]
    referencias: tuple[ReferenciaView, ...]
    exibidas: tuple[ReferenciaView, ...]
    motivos_de_exclusao: tuple[tuple[str, int], ...]
    cotacoes_diretas: tuple[MappingProxyType, ...]
    # Revisão 02 — o que o relatório principal precisa, sem inventário:
    # as saídas que AFETARAM a série (analisadas e tiradas, com autoria
    # certa), os atípicos mantidos por decisão, o ajuste pelo teto da
    # mediana e as violações de integridade da leitura.
    saidas_da_serie: tuple[ReferenciaView, ...] = ()
    mantidas: tuple[tuple[ReferenciaView, MappingProxyType], ...] = ()
    ajuste_teto: tuple[Decimal, Decimal] | None = None
    integridade: tuple[str, ...] = ()
    nao_usadas: int = 0

    @property
    def considerada_lista(self) -> tuple[ReferenciaView, ...]:
        return tuple(r for r in self.referencias if r.considerada)

    @property
    def desconsideradas(self) -> tuple[ReferenciaView, ...]:
        return tuple(r for r in self.referencias if not r.considerada)

    @property
    def excluidas_pelo_revisor(self) -> tuple[ReferenciaView, ...]:
        return tuple(r for r in self.referencias if r.status == "rejected")

    @property
    def valor_provisorio(self) -> bool:
        """Há valor calculado, mas o item não está concluído."""
        return self.preco_unitario is not None and not self.concluido


@dataclass(frozen=True)
class FonteView:
    id: str
    nome: str
    enquadramento: str
    referencias: int
    consideradas: int
    primeira_coleta: str
    ultima_coleta: str
    desfechos: MappingProxyType


@dataclass(frozen=True)
class CotacaoReportView:
    pesquisa_id: str
    nome: str
    objeto: str
    revisao: int
    motivo_da_revisao: str
    situacao: str
    data_base: str
    criada_em: str
    coleta_inicio: str
    coleta_fim: str
    emitido_em: datetime
    perfil_nome: str
    perfil_base_legal: str
    minimo: int
    admite_menos: bool
    perfil_observacoes: tuple[str, ...]
    fundamento_desconsideracao: str
    versao_regras: str
    regra_rotulo: str
    criterios: tuple[tuple[str, str], ...]
    janela_dias: int | None
    recorte_uf: str
    processo_id: str
    processo_orgao: str
    processo_objeto: str
    responsavel: str
    local: str
    orgao_emissor: str
    branding: MappingProxyType | None
    itens: tuple[ItemView, ...]
    fontes: tuple[FonteView, ...]
    alertas: tuple[tuple[str, str], ...]
    hash_decisorio: str
    formato_hash: str
    subtotal_concluidos: Decimal
    concluidos: int
    nao_concluidos: int
    total_referencias: int
    total_consideradas: int
    metodos_aplicados: tuple[str, ...] = field(default=())
    # Ciência de alertas registrada antes desta emissão (pacote Jev):
    # impressa nos alertas, fora do identificador — a ciência não muda o
    # resultado, só registra que alguém o viu com os alertas.
    ciencia: MappingProxyType | None = None
    # Revisão 02 (D12): coleta e emissão no horário de Brasília no corpo;
    # UTC só na identificação técnica.
    coleta_inicio_local: str = ""
    coleta_fim_local: str = ""
    # versões da triagem automática que DE FATO agiram nesta pesquisa (lidas
    # dos motivos gravados): a metodologia só descreve triagem que ocorreu
    triagem_versoes: tuple[str, ...] = ()

    @property
    def emitido_local(self) -> str:
        return (self.emitido_em.astimezone(BRASILIA).strftime("%d/%m/%Y %H:%M")
                + " (horário de Brasília)")

    @property
    def coleta_local(self) -> str:
        if not self.coleta_inicio_local:
            return NAO_INFORMADO
        if self.coleta_inicio_local == self.coleta_fim_local:
            return f"{self.coleta_inicio_local} (horário de Brasília)"
        return (f"{self.coleta_inicio_local} a {self.coleta_fim_local} "
                "(horário de Brasília)")

    @property
    def valor_global(self) -> Decimal | None:
        """Só existe quando TODOS os itens estão concluídos."""
        if self.itens and self.nao_concluidos == 0:
            return self.subtotal_concluidos
        return None

    @property
    def emitido_em_texto(self) -> str:
        utc = self.emitido_em.astimezone(timezone.utc)
        local = self.emitido_em.astimezone(BRASILIA)
        return (f"{utc.strftime('%d/%m/%Y %H:%M')} UTC "
                f"({local.strftime('%d/%m/%Y %H:%M')} horário de Brasília)")


# ---------------------------------------------------------------------------
# Montagem
# ---------------------------------------------------------------------------
def _texto(valor) -> str:
    """Texto externo achatado (sem quebras), ou "Não informado"."""
    limpo = " ".join(str(valor or "").replace("\r", "\n").split())
    return limpo or NAO_INFORMADO


def titulo_curto(descricao: str, limite: int = 64) -> str:
    """
    O nome do item para o quadro e a faixa: o que vem antes de
    "ESPECIFICAÇÃO" (ou do primeiro ponto final), no máximo `limite`
    caracteres. A descrição integral vai no detalhamento.
    """
    texto = " ".join(str(descricao or "").split())
    if not texto:
        return NAO_INFORMADO
    corte = re.split(r"\.\s*ESPECIFICA|\s+ESPECIFICAÇÃO\s*:|\.\s", texto,
                     maxsplit=1, flags=re.IGNORECASE)[0].strip(" .:")
    corte = corte or texto
    if len(corte) <= limite:
        return corte
    return corte[:limite - 1].rsplit(" ", 1)[0].rstrip(" ,;:-") + "…"


def _natureza(linha: dict) -> str:
    rotulo = linha.get("rotulo_natureza")
    if rotulo:
        return str(rotulo)
    try:
        return ROTULO_NATUREZA.get(
            NaturezaValor(str(linha.get("natureza_valor") or "outro")),
            NAO_INFORMADO)
    except ValueError:
        return NAO_INFORMADO


def _situacao_da_referencia(linha: dict, considerada: bool) -> str:
    status = str(linha.get("status") or "")
    if considerada:
        return ("Considerada (sinalizada)" if status == "warning"
                else "Considerada")
    if status in cesta_mod.NA_CESTA:
        return "Marcada, fora do cálculo"
    if status == "rejected":
        autoria = autoria_da_saida(linha)
        return autoria[:1].upper() + autoria[1:] if autoria else "Fora da série"
    return {
        "candidate": "Não selecionada",
        "manual_review": "Abaixo do piso de comparabilidade",
    }.get(status, rel._ROTULO_STATUS.get(status, status or NAO_INFORMADO))  # noqa: SLF001


def _motivo(linha: dict, considerada: bool) -> str:
    motivos = "; ".join(" ".join(str(m).split())
                        for m in (linha.get("motivos") or []) if m)
    if motivos:
        return motivos
    status = str(linha.get("status") or "")
    if not considerada and status in cesta_mod.NA_CESTA:
        return ("sem preço normalizado na unidade do item, ou valor que "
                "não é preço praticado")
    return ""


# Códigos de modalidade do SIASG que a API de preços praticados devolve.
# Só os conferidos: 05 abriu "Pregão Eletrônico" na página pública da
# compra (links.py). Código fora da lista não é traduzido nem exibido.
MODALIDADE_COMPRAS = {"5": "Pregão", "05": "Pregão", "6": "Dispensa",
                      "06": "Dispensa", "7": "Inexigibilidade",
                      "07": "Inexigibilidade"}


def _cnpj(texto) -> str:
    digitos = re.sub(r"\D", "", str(texto or ""))
    if len(digitos) != 14:
        return ""
    return (f"{digitos[:2]}.{digitos[2:5]}.{digitos[5:8]}/"
            f"{digitos[8:12]}-{digitos[12:]}")


def autoria_da_saida(linha: dict) -> str:
    """
    Quem tirou a referência da série, com a autoria CERTA (Revisão 02,
    D07: o PDF dizia "excluída pelo revisor" para decisão automática).
    Vazio quando ela não saiu da série (nunca entrou, ou está nela).
    """
    from . import cotacoes, saneamento

    status = str(linha.get("status") or "")
    motivos = [str(m) for m in (linha.get("motivos") or [])]
    if status != "rejected":
        return ""
    if saneamento.desconsiderada_pelo_jev(linha):
        return "desconsiderada pela triagem automática"
    if any(m == cotacoes.MOTIVO_RETIRADA_AUTOMATICO for m in motivos):
        return "retirada da cesta pelo servidor"
    if any("critério" in m and "discrepante" in m for m in motivos):
        return "retirada pelo servidor (preço atípico)"
    if any(m.startswith("unidade") or "conversão" in m or "grandeza" in m
           for m in motivos):
        return "fora da série: unidade sem conversão comprovada"
    return "retirada pelo servidor"


def _referencia(linha: dict, considerada: bool) -> ReferenciaView:
    from . import links as links_mod

    resolvidos = links_mod.resolver(linha)
    bruto = linha.get("bruto") or {}
    objeto = " ".join(str(bruto.get("objetoCompra") or "").split())
    objeto = re.sub(r"^Objeto:\s*", "", objeto, flags=re.IGNORECASE)
    modalidade = MODALIDADE_COMPRAS.get(str(bruto.get("modalidade") or ""), "") \
        if str(linha.get("fonte_id")) == "compras_gov_precos" else \
        " ".join(str(bruto.get("modalidadeNome") or "").split())
    numero_item = bruto.get("numeroItemCompra") or bruto.get("numeroItemPncp")
    return ReferenciaView(
        id=str(linha.get("id") or ""),
        considerada=considerada,
        status=str(linha.get("status") or ""),
        situacao=_situacao_da_referencia(linha, considerada),
        motivo=_motivo(linha, considerada),
        sinalizada=str(linha.get("status")) == "warning",
        fonte_id=str(linha.get("fonte_id") or ""),
        fonte=_texto(linha.get("fonte_nome") or linha.get("fonte_id")),
        inciso=inciso_da_fonte(linha.get("fonte_id"),
                               linha.get("fonte_tipo")) or "",
        natureza=_natureza(linha),
        orgao=_texto(linha.get("orgao")),
        uf=" ".join(str(linha.get("uf") or "").split()),
        municipio=" ".join(str(linha.get("municipio") or "").split()),
        fornecedor=" ".join(str(linha.get("fornecedor") or "").split()),
        data=(rel._data(linha.get("data_resultado")  # noqa: SLF001
                        or linha.get("data_compra"))
              if (linha.get("data_resultado") or linha.get("data_compra"))
              else NAO_INFORMADO),
        quantidade=rel._decimal(linha.get("quantidade_original")),  # noqa: SLF001
        unidade=_texto(linha.get("unidade_normalizada")
                       or linha.get("unidade_original")),
        unidade_original=_texto(linha.get("unidade_original")),
        valor=rel._decimal(linha.get("valor_unitario_normalizado")),  # noqa: SLF001
        valor_original=rel._decimal(linha.get("valor_unitario_original")),  # noqa: SLF001
        compatibilidade=rel._decimal(linha.get("score")),  # noqa: SLF001
        id_externo=_texto(linha.get("id_externo")),
        evidencia=str(linha.get("raw_hash") or ""),
        link=rel.url_de_verificacao(linha),
        coletado_em=(rel._hora(rel._instante(linha.get("coletado_em")))  # noqa: SLF001
                     if linha.get("coletado_em") else NAO_INFORMADO),
        descricao_fonte=" ".join(
            str(linha.get("descricao_original") or "").split()),
        contratacao_url=resolvidos.contratacao_url,
        contratacao_rotulo=resolvidos.contratacao_rotulo,
        identificacao=resolvidos.identificacao,
        dados_url=resolvidos.dados_url,
        fonte_url=resolvidos.fonte_url,
        objeto_contratacao=objeto[:300],
        modalidade=modalidade,
        fornecedor_cnpj=_cnpj(linha.get("ni_fornecedor")
                              or bruto.get("niFornecedor")
                              or bruto.get("codFornecedor")),
        marca=" ".join(str(linha.get("marca") or bruto.get("marca")
                           or "").split()),
        item_da_compra=str(numero_item) if numero_item not in (None, "", 0)
        else "",
        autoria_da_saida=autoria_da_saida(linha),
    )


def representativas(consideradas: tuple[ReferenciaView, ...],
                    quantas: int = REFERENCIAS_EXIBIDAS
                    ) -> tuple[ReferenciaView, ...]:
    """
    As referências que o relatório COMPACTO mostra: a menor, os quartis, a
    mediana e a maior da série considerada — a dispersão inteira em cinco
    linhas, e não as cinco mais baratas. Com N ≤ `quantas`, todas.

    Critério só de EXIBIÇÃO: a cesta e o cálculo não mudam, e o documento
    diz "Exibidas X de N".
    """
    com_valor = sorted((r for r in consideradas if r.valor is not None),
                       key=lambda r: (r.valor, r.id))
    if len(com_valor) <= quantas:
        return tuple(com_valor)
    posicoes = sorted({round(k * (len(com_valor) - 1) / (quantas - 1))
                       for k in range(quantas)})
    return tuple(com_valor[p] for p in posicoes)


def _congelar(valor):
    if isinstance(valor, dict):
        return MappingProxyType({k: _congelar(v) for k, v in valor.items()})
    if isinstance(valor, list):
        return tuple(_congelar(v) for v in valor)
    return valor


def _estatisticas(gravado: dict) -> MappingProxyType:
    bruto = gravado.get("estatisticas") or {}
    return MappingProxyType({
        chave: (rel._decimal(bruto.get(chave)) if chave != "quantidade"  # noqa: SLF001
                else bruto.get(chave))
        for chave in ("quantidade", "menor", "media", "mediana", "maior",
                      "desvio_padrao", "coeficiente_variacao", "soma")
        if bruto.get(chave) not in (None, "")})


_TETO = re.compile(r"valor ajustado de R\$\s*([\d.]+,\d{2}) para R\$\s*([\d.]+,\d{2})")


def _brl_para_decimal(texto: str) -> Decimal:
    return Decimal(texto.replace(".", "").replace(",", "."))


def _ajuste_teto(gravado: dict, memoria: str) -> tuple[Decimal, Decimal] | None:
    """O par (pelo método, adotado) — estruturado, ou da memória antiga."""
    ajuste = gravado.get("ajuste_teto")
    if isinstance(ajuste, dict) and ajuste.get("adotado"):
        return (Decimal(str(ajuste["pelo_metodo"])),
                Decimal(str(ajuste["adotado"])))
    achado = _TETO.search(memoria or "")
    if achado:
        return (_brl_para_decimal(achado.group(1)),
                _brl_para_decimal(achado.group(2)))
    return None


def _item(item: dict, linhas: list[dict], perfil,
          deficiencias: tuple[str, ...]) -> ItemView:
    from . import saneamento
    from .estatistica import POLITICA_AUTOMATICA, chave_da_referencia

    consideradas = cesta_mod.consideradas(linhas)
    dentro = {id(linha) for linha in consideradas}
    refs = tuple(_referencia(linha, id(linha) in dentro) for linha in
                 sorted(linhas, key=lambda l: (id(l) not in dentro,
                                               str(l.get("status") or ""),
                                               str(l.get("id") or ""))))
    gravado = item.get("estatisticas") or {}
    decisoes = gravado.get("decisoes") or {}
    estado = str(item.get("estado") or EstadoItem.PENDENTE.value)
    metodo = str(item.get("metodo") or "")
    motivos: dict[str, int] = {}
    for r in refs:
        if not r.considerada and r.status == "rejected":
            chave = r.motivo or "sem motivo registrado"
            motivos[chave] = motivos.get(chave, 0) + 1
    por_id = {str(l.get("id")): l for l in linhas}
    # Saídas que AFETARAM a série: analisadas como preço e tiradas dela —
    # pela triagem com critério de análise (extremo corroborado, objeto
    # divergente) ou pela pessoa. Unidade sem conversão, duplicata e
    # valor inválido não são preço do item: ficam só contados.
    saidas = tuple(
        r for r in refs if not r.considerada and r.status == "rejected"
        and (saneamento.desconsiderada_por_analise(por_id.get(r.id) or {})
             or r.autoria_da_saida.startswith("retirada")))
    decisoes_mantidas = (decisoes.get("mantidas") or {})
    mantidas = tuple(
        (r, MappingProxyType(dict(decisoes_mantidas[chave])))
        for r in refs if r.considerada
        for chave in [chave_da_referencia(por_id.get(r.id) or {})]
        if chave in decisoes_mantidas)
    return ItemView(
        id=str(item.get("id") or ""),
        numero=int(item.get("numero") or 0),
        titulo=titulo_curto(item.get("descricao")),
        descricao=_texto(item.get("descricao")),
        unidade=_texto(item.get("unidade")),
        quantidade=rel._decimal(item.get("quantidade")),  # noqa: SLF001
        codigo=" ".join(str(item.get("codigo") or "").split()),
        tipo_catalogo=" ".join(str(item.get("tipo_catalogo") or "").split()),
        estado=estado,
        situacao=rel.ROTULO_ESTADO_ITEM.get(estado, estado),
        concluido=estado == EstadoItem.COMPLETO.value,
        metodo=metodo,
        metodo_rotulo=ROTULO_METODO.get(metodo, metodo) if metodo else "",
        preco_unitario=rel._decimal(item.get("preco_estimado")),  # noqa: SLF001
        preco_total=rel._decimal(item.get("preco_total")),  # noqa: SLF001
        consideradas=len(consideradas),
        minimo=perfil.minimo_referencias,
        total_referencias=len(linhas),
        estatisticas=_estatisticas(gravado),
        memoria=tuple(" ".join(l.split()) for l in
                      str(item.get("justificativa") or "").splitlines()
                      if l.strip()),
        excecao=_congelar(decisoes["excecao"]) if decisoes.get("excecao")
        else None,
        excecoes_invalidadas=tuple(
            str(a.get("motivo_invalidacao"))
            for a in decisoes.get("excecoes_anteriores") or []
            if a.get("motivo_invalidacao")),
        metodo_do_revisor=_congelar(decisoes["metodo"])
        if decisoes.get("metodo") else None,
        deficiencias=deficiencias,
        analise_critica=tuple(str(p) for p in gravado.get("pendencias") or []),
        anomalias=tuple(_congelar(a) for a in gravado.get("anomalias") or []),
        marcas_percentuais=tuple(
            _congelar(m) for m in gravado.get("marcas_percentuais") or []
            if m.get("marca") != "valido"),
        referencias=refs,
        exibidas=representativas(tuple(r for r in refs if r.considerada)),
        motivos_de_exclusao=tuple(sorted(motivos.items(),
                                         key=lambda par: (-par[1], par[0]))),
        cotacoes_diretas=tuple(
            _congelar({
                "fornecedor": linha.get("fornecedor"),
                "cnpj": linha.get("ni_fornecedor"),
                "data": linha.get("data_compra"),
                "valor": linha.get("valor_unitario_original"),
                "solicitacao": (linha.get("bruto") or {}).get(
                    "solicitacao_formal"),
                "justificativa": (linha.get("bruto") or {}).get(
                    "justificativa_escolha"),
                "comprovante": ((linha.get("bruto") or {}).get("comprovante")
                                or {}).get("sha256"),
            })
            for linha in linhas
            if str(linha.get("fonte_id")) == "cotacao_direta"),
        saidas_da_serie=saidas,
        mantidas=mantidas,
        ajuste_teto=_ajuste_teto(gravado, str(item.get("justificativa") or "")),
        integridade=tuple(cesta_mod.integridade_do_item(
            item, linhas, teto=POLITICA_AUTOMATICA.teto)),
        nao_usadas=len(linhas) - len(consideradas),
    )


def _criterios(pesquisa: dict) -> tuple[tuple[str, str], ...]:
    """As linhas de `_criterios_estatisticos` como (título, texto)."""
    saida = []
    for linha in rel._criterios_estatisticos(pesquisa):  # noqa: SLF001
        limpa = linha.removeprefix("- ").strip()
        achado = re.match(r"\*\*(.+?)\*\*\s*(.*)", limpa)
        if achado:
            saida.append((achado.group(1).rstrip(":"), achado.group(2)))
        else:
            saida.append(("", limpa))
    return tuple(saida)


def projetar(pesquisa: dict, itens: list[dict],
             referencias: dict[str, list[dict]], *,
             emitido_em: datetime | None = None,
             processo: dict | None = None,
             branding: dict | None = None,
             ciencia: dict | None = None) -> CotacaoReportView:
    """
    O retrato. Não altera nenhum dos dicionários recebidos (a prova
    compara antes e depois).
    """
    from .execucao import janela_efetiva

    momento = emitido_em or datetime.now(timezone.utc)
    perfil = obter_perfil(pesquisa.get("perfil_normativo"))
    ordenados = sorted(itens, key=lambda i: int(i.get("numero") or 0))
    pendencias = {p["item_id"]: tuple(p["deficiencias"]) for p in
                  rel.pendencias_nominais(ordenados, referencias, perfil)}
    vistos = tuple(
        _item(item, referencias.get(str(item.get("id")), []), perfil,
              pendencias.get(str(item.get("id")), ()))
        for item in ordenados)
    concluidos = [i for i in vistos if i.concluido]
    subtotal = sum((i.preco_total or Decimal("0")) for i in concluidos)
    inicio, fim = rel._janela_de_coleta(referencias)  # noqa: SLF001
    instantes = [m for lista in referencias.values() for linha in lista
                 if (m := rel._instante(linha.get("coletado_em")))]  # noqa: SLF001
    local = (lambda m: m.astimezone(BRASILIA).strftime("%d/%m/%Y %H:%M"))
    filtros = pesquisa.get("filtros") or {}
    regras = str(pesquisa.get("versao_regras") or "")
    processo = processo or {}
    branding = branding or None
    orgao = (str((branding or {}).get("orgao") or (branding or {}).get("nome")
                 or processo.get("orgao") or "").strip())
    return CotacaoReportView(
        pesquisa_id=str(pesquisa.get("id") or ""),
        nome=_texto(pesquisa.get("nome")),
        objeto=_texto(pesquisa.get("objeto")),
        revisao=int(pesquisa.get("versao") or 1),
        motivo_da_revisao=" ".join(
            str(pesquisa.get("motivo_da_revisao") or "").split()),
        situacao=ROTULO_PESQUISA.get(str(pesquisa.get("estado") or ""),
                                     str(pesquisa.get("estado") or "")),
        data_base=rel._data(pesquisa.get("data_base"))  # noqa: SLF001
        if pesquisa.get("data_base") else NAO_INFORMADO,
        criada_em=rel._data(pesquisa.get("criado_em"))  # noqa: SLF001
        if pesquisa.get("criado_em") else NAO_INFORMADO,
        coleta_inicio=inicio, coleta_fim=fim,
        emitido_em=momento,
        perfil_nome=perfil.nome, perfil_base_legal=perfil.base_legal,
        minimo=perfil.minimo_referencias,
        admite_menos=perfil.admite_menos_com_justificativa,
        perfil_observacoes=tuple(perfil.observacoes),
        fundamento_desconsideracao=perfil.fundamento_desconsideracao or "",
        versao_regras=regras,
        regra_rotulo=("média aritmética simples como padrão (regra de "
                      "15/10/2026)" if regras == REGRAS_MEDIA_PADRAO else
                      "regra anterior a 15/10/2026: mediana em série "
                      "dispersa, média em série homogênea"),
        criterios=_criterios(pesquisa),
        janela_dias=janela_efetiva(filtros) if filtros.get("janela_dias")
        else None,
        recorte_uf=" ".join(str(filtros.get("uf") or "").split()),
        processo_id=str(pesquisa.get("processo_id") or ""),
        processo_orgao=" ".join(str(processo.get("orgao") or "").split()),
        processo_objeto=" ".join(str(processo.get("objeto") or "").split()),
        responsavel=_texto(pesquisa.get("responsavel")),
        local=_texto(pesquisa.get("local_referencia")),
        orgao_emissor=orgao,
        branding=MappingProxyType(dict(branding)) if branding else None,
        itens=vistos,
        fontes=tuple(
            FonteView(id=f["id"], nome=f["nome"],
                      enquadramento=f["enquadramento"],
                      referencias=f["referencias"],
                      consideradas=f["consideradas"],
                      primeira_coleta=f["primeira_coleta"],
                      ultima_coleta=f["ultima_coleta"],
                      desfechos=MappingProxyType(f["desfechos"]))
            for f in rel.fontes_consultadas(ordenados, referencias, perfil)),
        alertas=tuple(rel.alertas_estruturados(ordenados, referencias, perfil)),
        hash_decisorio=rel.identificador_da_versao(pesquisa, ordenados,
                                                   referencias),
        formato_hash=rel.FORMATO,
        subtotal_concluidos=subtotal,
        concluidos=len(concluidos),
        nao_concluidos=len(vistos) - len(concluidos),
        total_referencias=sum(i.total_referencias for i in vistos),
        total_consideradas=sum(i.consideradas for i in vistos),
        metodos_aplicados=tuple(sorted({i.metodo_rotulo for i in vistos
                                        if i.metodo_rotulo})),
        ciencia=MappingProxyType(dict(ciencia)) if ciencia else None,
        triagem_versoes=tuple(sorted({
            achado for lista in referencias.values() for linha in lista
            for m in (linha.get("motivos") or [])
            for achado in re.findall(r"política (\d{4}-\d{2}-\d{2}\.saneamento-v\d+)",
                                     str(m))})),
        coleta_inicio_local=local(min(instantes)) if instantes else "",
        coleta_fim_local=local(max(instantes)) if instantes else "",
    )
