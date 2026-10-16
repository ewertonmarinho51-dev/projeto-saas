"""
Importação de itens da cotação a partir de XLSX — com DIAGNÓSTICO.

O que o dossiê do Banco de Preços mostrou, e que aqui não se repete
(J05; temas 11a–11d da comparação):

* o concorrente avisava só o PRIMEIRO erro; o GovConnect descartava as
  linhas ruins EM SILÊNCIO e transformava quantidade "abc" em 0. Aqui
  TODAS as linhas são examinadas, e cada erro sai com linha, campo,
  valor e motivo — antes de qualquer gravação;
* o concorrente criava unidade nova a partir de texto livre ("Caixotes")
  e aceitava UF "ZZ". Aqui unidade só entra se o dicionário canônico a
  reconhece, e UF só se for uma das 27; nada vira cadastro;
* reimportar a planilha reordenada sobrescrevia itens diferentes sob o
  mesmo número. Aqui o casamento é pelo CÓDIGO (ou, sem código, pela
  descrição + unidade), e o número do item existente é preservado.

Leitura reaproveitada: `planilha.ler_tabela_xlsx` (mesma detecção de
cabeçalho do resto do app). Nada aqui grava sem `aplicar`, e `aplicar`
recebe o PLANO que o servidor viu na prévia.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from .. import planilha
from . import unidades

UFS = frozenset({
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
    "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
    "SP", "SE", "TO"})

# Limite da fixture do pacote (U02): 210 itens com folga. Planilha maior
# é recusada inteira, com a contagem — não truncada em silêncio.
MAXIMO_DE_LINHAS = 1000

# Cabeçalhos que `planilha` não mapeia e que a cotação lê.
_EXTRAS = {
    "uf": ("uf", "uf (estado)", "estado", "unidade da federacao"),
    "lote": ("lote", "grupo", "lote/grupo"),
    "nome": ("nome", "nome do item", "item nome"),
    "especificacao": ("especificacao", "especificacoes", "especificacao tecnica",
                      "detalhamento"),
}


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.strip().lower().strip(".:*").split())


@dataclass
class ErroDeLinha:
    linha: int
    campo: str
    valor: str
    motivo: str


@dataclass
class LinhaValida:
    linha: int
    codigo: str
    descricao: str
    unidade: str             # nome canônico
    unidade_original: str
    quantidade: Decimal
    uf: str = ""
    lote: str = ""

    def como_item(self) -> dict:
        return {"codigo": self.codigo or None, "descricao": self.descricao,
                "unidade": self.unidade, "quantidade": self.quantidade,
                "uf": self.uf or None, "lote": self.lote or None}


@dataclass
class Diagnostico:
    validos: list[LinhaValida] = field(default_factory=list)
    erros: list[ErroDeLinha] = field(default_factory=list)
    em_branco: int = 0
    cabecalho_visto: str = ""
    colunas: dict[str, str] = field(default_factory=dict)

    @property
    def pode_importar(self) -> bool:
        """Tudo ou nada: com erro, nada é gravado até a planilha ser corrigida."""
        return bool(self.validos) and not self.erros

    @property
    def linhas_com_erro(self) -> list[int]:
        return sorted({e.linha for e in self.erros})


def quantidade_de(valor) -> Decimal | None:
    """
    Quantidade estrita: número do Excel, ou texto no padrão brasileiro
    ("1.234,5") ou com ponto decimal ("12.5"). Qualquer outra coisa é
    erro — nunca zero.
    """
    if valor is None or valor == "":
        return None
    if isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float, Decimal)):
        try:
            return Decimal(str(valor))
        except InvalidOperation:
            return None
    texto = str(valor).strip().replace("\xa0", "").replace(" ", "")
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        numero = Decimal(texto)
    except InvalidOperation:
        return None
    return numero if numero.is_finite() else None


def _colunas_extras(cabecalho: list, mapa: dict) -> dict[str, int]:
    achadas: dict[str, int] = {}
    for coluna, rotulo in enumerate(cabecalho or []):
        if coluna in mapa or rotulo in (None, ""):
            continue
        normal = _norm(rotulo)
        for campo, sinonimos in _EXTRAS.items():
            if campo not in achadas and normal in sinonimos:
                achadas[campo] = coluna
    return achadas


def diagnosticar(dados: bytes) -> Diagnostico:
    """Examina TODAS as linhas. Não grava nada."""
    tabela = planilha.ler_tabela_xlsx(dados)
    mapa = tabela["mapa"]
    extras = _colunas_extras(tabela["cabecalho"], mapa)
    por_campo = {campo: col for col, campo in mapa.items()}
    por_campo.update(extras)
    diag = Diagnostico(cabecalho_visto=tabela["cabecalho_visto"],
                       colunas={campo: str(col) for campo, col
                                in por_campo.items()})

    def celula(linha, campo):
        col = por_campo.get(campo)
        if col is None or col >= len(linha):
            return None
        valor = linha[col]
        return None if valor in (None, "") else valor

    linhas = tabela["linhas"]
    preenchidas = [(n, l) for n, l in linhas
                   if any(c not in (None, "") for c in l)]
    diag.em_branco = len(linhas) - len(preenchidas)
    if len(preenchidas) > MAXIMO_DE_LINHAS:
        diag.erros.append(ErroDeLinha(
            0, "planilha", str(len(preenchidas)),
            f"a planilha tem {len(preenchidas)} linhas com dados; o limite é "
            f"{MAXIMO_DE_LINHAS}. Divida o arquivo."))
        return diag
    if "descricao" not in por_campo:
        diag.erros.append(ErroDeLinha(
            0, "cabeçalho", diag.cabecalho_visto or "(não encontrado)",
            "a planilha precisa de uma coluna de descrição"))
        return diag

    _validar_linhas(diag, [
        (numero, {campo: celula(linha, campo) for campo in
                  ("nome", "descricao", "especificacao", "quantidade",
                   "unidade", "uf", "codigo", "lote")})
        for numero, linha in preenchidas])
    return diag


def diagnosticar_itens(itens: list[dict]) -> Diagnostico:
    """
    O MESMO diagnóstico para itens que já são dicionários — a planilha do
    processo aberto (`dados["itens"]`). A linha informada é a posição.
    """
    diag = Diagnostico(cabecalho_visto="planilha do processo")
    _validar_linhas(diag, [
        (n, {campo: (None if item.get(campo) in (None, "") else item.get(campo))
             for campo in ("descricao", "quantidade", "unidade", "codigo",
                           "uf", "lote")})
        for n, item in enumerate(itens, start=1)
        if any(item.get(c) not in (None, "") for c in ("descricao", "codigo"))])
    return diag


def _validar_linhas(diag: Diagnostico, linhas: list[tuple[int, dict]]) -> None:
    codigos_vistos: dict[str, int] = {}
    for numero, valores in linhas:
        erros_da_linha: list[ErroDeLinha] = []

        def erro(campo, valor, motivo):
            erros_da_linha.append(ErroDeLinha(
                numero, campo, "" if valor is None else str(valor), motivo))

        nome = str(valores.get("nome") or "").strip()
        descricao = str(valores.get("descricao") or "").strip()
        especificacao = str(valores.get("especificacao") or "").strip()
        texto = " — ".join(p for p in (nome, descricao, especificacao) if p)
        if not descricao and not nome:
            erro("descrição", "", "descrição obrigatória")

        bruto_qtd = valores.get("quantidade")
        quantidade = quantidade_de(bruto_qtd)
        if bruto_qtd is None:
            erro("quantidade", "", "quantidade obrigatória")
        elif quantidade is None:
            erro("quantidade", bruto_qtd,
                 f"quantidade '{bruto_qtd}' não é número")
        elif quantidade <= 0:
            erro("quantidade", bruto_qtd, "quantidade deve ser maior que zero")

        unidade_original = str(valores.get("unidade") or "").strip()
        canonica = unidades.canonizar(unidade_original)
        if not unidade_original:
            erro("unidade", "", "unidade obrigatória")
        elif canonica is None:
            erro("unidade", unidade_original,
                 f"unidade '{unidade_original}' não reconhecida — use uma das "
                 "unidades do dicionário (ex.: UNIDADE, CAIXA, PACOTE, RESMA); "
                 "nenhuma unidade nova é criada")

        uf = str(valores.get("uf") or "").strip().upper()
        if uf and uf not in UFS:
            erro("UF", uf, f"UF '{uf}' inválida")

        codigo = str(valores.get("codigo") or "").strip()
        if codigo:
            if codigo in codigos_vistos:
                erro("código", codigo,
                     f"código '{codigo}' repetido (também na linha "
                     f"{codigos_vistos[codigo]})")
            else:
                codigos_vistos[codigo] = numero

        if erros_da_linha:
            diag.erros.extend(erros_da_linha)
            continue
        diag.validos.append(LinhaValida(
            linha=numero, codigo=codigo, descricao=planilha.limpar_texto(texto),
            unidade=canonica, unidade_original=unidade_original,
            quantidade=quantidade, uf=uf,
            lote=str(valores.get("lote") or "").strip()))


# ---------------------------------------------------------------------------
# Plano idempotente sobre os itens que a cotação JÁ tem
# ---------------------------------------------------------------------------
@dataclass
class Acao:
    tipo: str                 # 'novo' | 'atualizar' | 'igual'
    linha: LinhaValida
    numero: int
    item_id: str | None = None
    mudancas: list[str] = field(default_factory=list)
    refaz_busca: bool = False  # descrição/unidade mudou em item pesquisado


ESTADOS_PESQUISADOS = frozenset({"review", "complete", "incomplete", "error"})


def _chave_texto(descricao: str, unidade: str) -> tuple[str, str]:
    return _norm(descricao), str(unidades.canonizar(unidade) or _norm(unidade))


def planejar(diag: Diagnostico, existentes: list[dict]) -> list[Acao]:
    """
    Casa cada linha válida com um item existente — pelo código, ou pela
    descrição + unidade — e diz o que muda. Reimportar a mesma planilha
    (mesmo reordenada) dá só 'igual': não duplica nem perde seleção.
    """
    por_codigo = {str(i.get("codigo")).strip(): i for i in existentes
                  if str(i.get("codigo") or "").strip()}
    por_texto = {_chave_texto(str(i.get("descricao") or ""),
                              str(i.get("unidade") or "")): i
                 for i in existentes}
    proximo = max([int(i.get("numero") or 0) for i in existentes] or [0]) + 1
    usados: set[str] = set()
    plano: list[Acao] = []
    for linha in diag.validos:
        alvo = (por_codigo.get(linha.codigo) if linha.codigo else None) or \
            por_texto.get(_chave_texto(linha.descricao, linha.unidade))
        if alvo is not None and str(alvo.get("id")) in usados:
            alvo = None
        if alvo is None:
            plano.append(Acao("novo", linha, proximo))
            proximo += 1
            continue
        usados.add(str(alvo.get("id")))
        mudancas = []
        if _norm(alvo.get("descricao")) != _norm(linha.descricao):
            mudancas.append("descrição")
        if unidades.canonizar(alvo.get("unidade")) != linha.unidade:
            mudancas.append("unidade")
        if quantidade_de(alvo.get("quantidade")) != linha.quantidade:
            mudancas.append("quantidade")
        if str(alvo.get("codigo") or "").strip() != linha.codigo:
            mudancas.append("código")
        pesquisado = str(alvo.get("estado")) in ESTADOS_PESQUISADOS
        plano.append(Acao(
            "atualizar" if mudancas else "igual", linha,
            int(alvo.get("numero") or 0), str(alvo.get("id")), mudancas,
            refaz_busca=pesquisado and bool({"descrição", "unidade"}
                                            & set(mudancas))))
    return plano


def resumo_do_plano(plano: list[Acao]) -> dict[str, int]:
    saida = {"novo": 0, "atualizar": 0, "igual": 0, "refaz_busca": 0}
    for acao in plano:
        saida[acao.tipo] += 1
        saida["refaz_busca"] += int(acao.refaz_busca)
    return saida


def aplicar(pesquisa_id: str, plano: list[Acao], repositorio, *,
            colunas_0029: bool = True) -> dict[str, int]:
    """
    Grava o plano. Item novo nasce PENDENTE; item existente mantém o
    estado — exceto quando descrição ou unidade mudaram depois da busca:
    aí ele volta a BUSCANDO (a cesta valia para o item antigo) pela
    máquina de estados, e a busca seguinte o refaz.

    `colunas_0029=False` descarta UF e lote (banco sem a migração 0029):
    eles foram VALIDADOS, mas não há onde gravá-los ainda.
    """
    from .estados import EstadoItem

    gravar = []
    for acao in plano:
        if acao.tipo == "igual":
            continue
        item = {"numero": acao.numero, **acao.linha.como_item()}
        if not colunas_0029:
            item.pop("uf", None)
            item.pop("lote", None)
        gravar.append(item)
    if gravar:
        repositorio.salvar_itens(pesquisa_id, gravar)
    for acao in plano:
        if acao.refaz_busca and acao.item_id:
            atual = repositorio.obter_item(acao.item_id) or {}
            repositorio.mover_item(
                acao.item_id, EstadoItem.BUSCANDO,
                atual.get("estado") or EstadoItem.EM_REVISAO.value,
                erro="")
    return resumo_do_plano(plano)
