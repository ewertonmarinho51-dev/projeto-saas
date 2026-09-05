"""
Filtros da tela de revisão (§20).

Operam sobre as LINHAS do banco — dicionários vindos de
`repositorio.listar_referencias` —, e não sobre `Referencia`. A razão é
que a revisão acontece depois, possivelmente noutro dia e noutra
máquina: o que ela tem em mãos é o que foi persistido, não os objetos da
coleta.

Duas regras que este módulo impõe e que valem para a interface inteira:

1. **filtro esconde, nunca apaga.** Toda função aqui devolve uma lista
   nova; nada é removido do banco. O §21 é explícito — "nunca esconder
   os resultados que foram descartados" —, e um filtro que apagasse
   tornaria a exigência impossível de cumprir;

2. **filtro vazio não filtra.** Campo em branco, lista vazia e `None`
   significam "não me importo com isto", nunca "nada passa". Uma tela
   que zera a lista porque o servidor não escolheu UF parece quebrada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from .modelo import StatusReferencia

# Piso do filtro "somente alta compatibilidade". Mais exigente que o
# piso da cesta automática (0,5): ali é o mínimo para entrar sozinha,
# aqui é o corte de quem quer olhar só o que é claramente comparável.
ALTA_COMPATIBILIDADE = Decimal("0.75")


def _decimal(valor) -> Decimal | None:
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _data(valor) -> date | None:
    if not valor:
        return None
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


@dataclass
class Filtros:
    """
    O que o revisor escolheu ver. Tudo opcional, por construção.

    `status` é conjunto e não valor único porque as três opções do §20
    — selecionados, rejeitados, e o resto — não são exclusivas: olhar
    "selecionados + em revisão manual" é o caso comum de quem está
    montando a cesta.
    """

    fontes: set[str] = field(default_factory=set)
    status: set[str] = field(default_factory=set)
    uf: str = ""
    unidade: str = ""
    tipo_catalogo: str = ""
    desde: date | None = None
    ate: date | None = None
    quantidade_minima: Decimal | None = None
    quantidade_maxima: Decimal | None = None
    somente_alta_compatibilidade: bool = False
    texto: str = ""

    @property
    def algum(self) -> bool:
        """Há algum critério ativo? A interface usa para dizer se filtra."""
        return bool(
            self.fontes or self.status or self.uf.strip()
            or self.unidade.strip() or self.tipo_catalogo.strip()
            or self.desde or self.ate
            or self.quantidade_minima is not None
            or self.quantidade_maxima is not None
            or self.somente_alta_compatibilidade or self.texto.strip())


def _data_da_linha(linha: dict) -> date | None:
    """
    A data que interessa é a do RESULTADO, com a da compra como reserva.

    Fontes diferentes preenchem campos diferentes; usar só uma delas
    faria metade da amostra sumir de qualquer filtro por período.
    """
    return _data(linha.get("data_resultado")) or _data(linha.get("data_compra"))


def _passa(linha: dict, f: Filtros) -> bool:
    if f.fontes and str(linha.get("fonte_id") or "") not in f.fontes:
        return False
    if f.status and str(linha.get("status") or "") not in f.status:
        return False
    if f.uf.strip() and str(linha.get("uf") or "").upper() != f.uf.strip().upper():
        return False
    if f.unidade.strip():
        alvo = f.unidade.strip().upper()
        # A unidade normalizada é a que interessa para comparar; a
        # original entra como reserva para a referência que não pôde ser
        # convertida — senão ela sumiria justamente do filtro em que o
        # revisor a procura.
        unidades_da_linha = {
            str(linha.get("unidade_normalizada") or "").upper(),
            str(linha.get("unidade_original") or "").upper(),
        }
        if alvo not in unidades_da_linha:
            return False
    if f.tipo_catalogo.strip():
        if (str(linha.get("tipo_catalogo") or "").upper()
                != f.tipo_catalogo.strip().upper()):
            return False

    if f.desde or f.ate:
        quando = _data_da_linha(linha)
        if quando is None:
            # Sem data, não dá para afirmar que está no período. Fica de
            # fora do filtro por período — e só dele.
            return False
        if f.desde and quando < f.desde:
            return False
        if f.ate and quando > f.ate:
            return False

    if f.quantidade_minima is not None or f.quantidade_maxima is not None:
        quantidade = _decimal(linha.get("quantidade_original"))
        if quantidade is None:
            return False
        if f.quantidade_minima is not None and quantidade < f.quantidade_minima:
            return False
        if f.quantidade_maxima is not None and quantidade > f.quantidade_maxima:
            return False

    if f.somente_alta_compatibilidade:
        score = _decimal(linha.get("score"))
        if score is None or score < ALTA_COMPATIBILIDADE:
            return False

    if f.texto.strip():
        alvo = f.texto.strip().lower()
        campos = (linha.get("descricao_original"), linha.get("orgao"),
                  linha.get("fornecedor"), linha.get("marca"),
                  linha.get("codigo_catalogo"), linha.get("municipio"))
        if not any(alvo in str(c or "").lower() for c in campos):
            return False

    return True


def aplicar(linhas: list[dict], f: Filtros | None = None) -> list[dict]:
    """Devolve uma lista NOVA com o que passa. Nada é apagado."""
    if f is None or not f.algum:
        return list(linhas)
    return [linha for linha in linhas if _passa(linha, f)]


def contar_por_status(linhas: list[dict]) -> dict[str, int]:
    """
    Quantas em cada status, para os contadores da tela.

    Conta sobre a lista COMPLETA, não sobre a filtrada: o revisor
    precisa saber que há 9 rejeitadas mesmo quando está olhando só as
    selecionadas — senão o filtro esconde a existência delas, que é o
    que o §21 proíbe.
    """
    contagem = {s.value: 0 for s in StatusReferencia}
    for linha in linhas:
        chave = str(linha.get("status") or "")
        if chave in contagem:
            contagem[chave] += 1
    return contagem


def fontes_presentes(linhas: list[dict]) -> list[tuple[str, str]]:
    """Pares (id, nome) das fontes que aparecem, para montar o seletor."""
    vistas: dict[str, str] = {}
    for linha in linhas:
        fonte_id = str(linha.get("fonte_id") or "")
        if fonte_id and fonte_id not in vistas:
            vistas[fonte_id] = str(linha.get("fonte_nome") or fonte_id)
    return sorted(vistas.items(), key=lambda par: par[1])


def unidades_presentes(linhas: list[dict]) -> list[str]:
    vistas = set()
    for linha in linhas:
        for chave in ("unidade_normalizada", "unidade_original"):
            valor = str(linha.get(chave) or "").strip().upper()
            if valor:
                vistas.add(valor)
    return sorted(vistas)


def ufs_presentes(linhas: list[dict]) -> list[str]:
    vistas = {str(linha.get("uf") or "").strip().upper() for linha in linhas}
    return sorted(u for u in vistas if u)
