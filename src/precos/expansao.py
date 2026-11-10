"""
Estratégia de expansão da busca — UMA, para o item avulso e para o lote.

Antes, cada caminho escolhia os termos à sua maneira: o worker forçava
`literal=True` na busca de um item (sem motor de IA, sem ampliação nenhuma)
e o lote chegava sem motor semântico. Este módulo é o ponto único:

1. **fase inicial** — a descrição do item (o código de catálogo validado vai
   no próprio adapter) e o termo que o servidor digitou, se houver. O termo
   manual é preservado SEMPRE, na frente (#182);
2. **variantes locais** — só quando a amostra elegível ficou curta:
   sinônimos e descrições de catálogo da mesma família, siglas, variantes
   de unidade ("75 g/m²" → "75 g"; "20 L" → "20 litros") e uma consulta
   CURTA com o nome do produto e os atributos essenciais. Determinístico;
3. **IA** — só quando as variantes locais também não bastaram, se houver
   motor e a política deixar. Um pedido por item, com cache pela versão da
   descrição e da política. A IA devolve PALAVRAS; preço, código,
   equivalência e cesta continuam determinísticos.

Com `literal` (o servidor marcou "apenas o meu termo"), só a fase inicial.

Cada fase é uma rodada completa de `busca.coletar` com TODOS os termos até
ali (as fontes recebem as variantes separadas, em `termos_alternativos`).
O orçamento é de no máximo `FASES_MAXIMAS` rodadas por item.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import OrderedDict
from dataclasses import dataclass, field

VERSAO = "2026-11-10.expansao.1"
MAX_VARIANTES_LOCAIS = 4
MAX_TERMOS_IA = 4
FASES_MAXIMAS = 3          # inicial + locais + IA
# Orçamento de IA: pedidos NOVOS ao motor (cache não conta). Por item, um;
# por execução do lote, este teto — o piloto liga a IA só com a flag
# `precos_ia_termos` e mede o ganho (`ganho_ia` na trilha) antes de subir.
ORCAMENTO_IA_POR_LOTE = 20


class Orcamento:
    """Quantos pedidos novos à IA ainda cabem nesta execução."""

    def __init__(self, limite: int) -> None:
        self.limite = max(0, int(limite))
        self.usados = 0

    def consumir(self) -> bool:
        if self.usados >= self.limite:
            return False
        self.usados += 1
        return True

DESCRICAO = "descricao"
MANUAL = "manual"
SINONIMO = "sinonimo"
UNIDADE = "unidade"
CURTA = "curta"
IA = "ia"

# Famílias de nomes do MESMO produto, como aparecem nos catálogos e nas
# descrições de compras públicas. Conservador de propósito: entra aqui só o
# que é o mesmo bem com outra redação — a elegibilidade continua sendo
# provada pelos atributos (`equivalencia`), não pelo sinônimo.
FAMILIAS: tuple[tuple[str, ...], ...] = (
    ("PAPEL SULFITE", "PAPEL PARA IMPRESSAO", "PAPEL OFFSET", "PAPEL A4"),
    ("AGUA MINERAL", "AGUA MINERAL NATURAL", "AGUA MINERAL SEM GAS"),
    ("GARRAFAO", "GALAO", "VASILHAME"),
    ("GASOLINA COMUM", "GASOLINA C", "GASOLINA TIPO C"),
    ("OLEO DIESEL S10", "DIESEL S10", "OLEO DIESEL S 10"),
    ("OLEO DIESEL S500", "DIESEL S500", "OLEO DIESEL S 500"),
    ("GAS LIQUEFEITO DE PETROLEO", "GLP", "GAS DE COZINHA", "BOTIJAO DE GAS"),
    ("CANETA ESFEROGRAFICA", "CANETA ESFERICA"),
    ("ACUCAR CRISTAL", "ACUCAR CRISTALIZADO"),
    ("FEIJAO CARIOCA", "FEIJAO CARIOQUINHA"),
    ("ARROZ TIPO 1", "ARROZ AGULHINHA TIPO 1", "ARROZ BRANCO TIPO 1"),
    ("CAFE TORRADO E MOIDO", "CAFE EM PO", "CAFE MOIDO"),
    ("COPO DESCARTAVEL", "COPO PLASTICO DESCARTAVEL"),
    ("SACO PARA LIXO", "SACO DE LIXO", "SACO PLASTICO PARA LIXO"),
    ("PAPEL HIGIENICO", "PAPEL HIGIENICO ROLO"),
    ("PAPEL TOALHA", "TOALHA DE PAPEL", "PAPEL TOALHA INTERFOLHADO"),
    ("DETERGENTE LIQUIDO", "DETERGENTE NEUTRO", "LAVA LOUCAS"),
    ("AGUA SANITARIA", "HIPOCLORITO DE SODIO"),
    ("ALCOOL ETILICO 70", "ALCOOL 70", "ALCOOL ETILICO HIDRATADO 70"),
)

# Variantes de unidade: a mesma medida escrita de outra forma
_VARIANTES_DE_UNIDADE = (
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*G/M2\b"), r"\1 G"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:L|LT|LTS)\b"), r"\1 LITROS"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*LITROS?\b"), r"\1 L"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*KG\b"), r"\1 QUILOS"),
    (re.compile(r"(\d+(?:[.,]\d+)?)\s*(?:FLS|FL)\b"), r"\1 FOLHAS"),
)


_FORA_DA_CURTA = frozenset({"ESPECIFICACAO", "ESPECIFICACOES", "DESCRICAO",
                            "ITEM", "CONFORME", "MINIMO", "APROXIMADAMENTE"})


def _norm(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    base = "".join(c for c in base if not unicodedata.combining(c))
    base = base.replace("²", "2").replace("³", "3")
    return " ".join(base.split())


def _com_palavra(texto: str, trecho: str) -> bool:
    return f" {trecho} " in f" {re.sub(r'[^A-Z0-9/ ]', ' ', texto)} "


def descricao_curta(descricao: str, limite_palavras: int = 8) -> str:
    """O nome do produto e os atributos essenciais, sem o texto de edital
    ("ESPECIFICAÇÃO: … deverá ser fornecido…") que afoga a busca."""
    from . import equivalencia

    limpo = _norm(descricao)
    # a parte antes do primeiro ponto/dois-pontos costuma ser o nome do item
    cabeca = re.split(r"[.:;]", limpo, maxsplit=1)[0]
    palavras = [p for p in re.sub(r"[^A-Z0-9/ ]", " ", cabeca).split()
                if len(p) > 1 and not p.isdigit() and p not in _FORA_DA_CURTA
                and p not in equivalencia._UNIDADES][:limite_palavras]  # noqa: SLF001
    medidas = [f"{n} {s}" for n, s in
               equivalencia._QUANTIFICADO.findall(limpo)[:3]]  # noqa: SLF001
    saida: list[str] = []
    for termo in [*palavras, *medidas]:
        if termo not in saida:
            saida.append(termo)
    return " ".join(saida)


def variantes_locais(descricao: str) -> list[str]:
    """Sinônimos da família, variantes de unidade e a consulta curta."""
    limpo = _norm(descricao)
    curta = descricao_curta(descricao)
    saida: list[str] = []

    def somar(texto: str) -> None:
        palavras: list[str] = []
        for p in texto.split():
            if not palavras or palavras[-1] != p:
                palavras.append(p)
        texto = " ".join(palavras)
        if texto and texto != limpo and texto not in saida:
            saida.append(texto)

    for familia in FAMILIAS:
        presentes = [nome for nome in familia if _com_palavra(curta, nome)]
        presente = max(presentes, key=len) if presentes else None
        if presente is None:
            continue
        for outro in familia:
            if outro != presente:
                somar(re.sub(rf"\b{re.escape(presente)}\b", outro, curta))
    for padrao, troca in _VARIANTES_DE_UNIDADE:
        if padrao.search(curta):
            somar(padrao.sub(troca, curta))
    if curta != limpo:
        somar(curta)
    return saida[:MAX_VARIANTES_LOCAIS]


def chave_de_cache(item: dict) -> str:
    """Versão da descrição + da política: muda um, muda a chave."""
    from . import semantica

    base = "|".join((_norm(item.get("descricao")), _norm(item.get("unidade")),
                     VERSAO, getattr(semantica, "VERSAO_DO_PROMPT", "")))
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


class CacheDeTermos:
    """Termos da IA por chave — em memória, com teto; a trilha guarda a
    mesma coisa (`para_registro`), que alimenta o cache do lote seguinte."""

    def __init__(self, maximo: int = 2048) -> None:
        self._dados: OrderedDict[str, tuple[str, ...]] = OrderedDict()
        self._maximo = maximo

    def obter(self, chave: str):
        if chave in self._dados:
            self._dados.move_to_end(chave)
            return self._dados[chave]
        return None

    def guardar(self, chave: str, termos) -> None:
        self._dados[chave] = tuple(termos)
        self._dados.move_to_end(chave)
        while len(self._dados) > self._maximo:
            self._dados.popitem(last=False)

    def carregar_da_trilha(self, eventos: list[dict]) -> None:
        for evento in eventos or []:
            expansao = (evento.get("payload") or {}).get("expansao") or \
                evento.get("expansao") or {}
            chave, termos = expansao.get("chave_ia"), expansao.get("termos_ia")
            if chave and isinstance(termos, list) and chave not in self._dados:
                self.guardar(chave, [str(t) for t in termos][:MAX_TERMOS_IA])


CACHE = CacheDeTermos()


@dataclass
class Plano:
    """As fases de busca de UM item e o que cada uma rendeu."""

    item: dict
    termo: str = ""
    literal: bool = False
    motor: object | None = None
    cache: CacheDeTermos = field(default_factory=lambda: CACHE)
    fases: list[dict] = field(default_factory=list)
    _termos: list[tuple[str, str]] = field(default_factory=list)
    _proxima: int = 0
    chave_ia: str = ""
    termos_ia: tuple[str, ...] = ()
    ia_do_cache: bool = False
    orcamento: Orcamento = field(default_factory=lambda: Orcamento(1))
    ia_sem_orcamento: bool = False

    def __post_init__(self) -> None:
        termo = (self.termo or "").strip()
        if termo and _norm(termo) != _norm(self.item.get("descricao")):
            self._termos.append((termo, MANUAL))

    @property
    def termos(self) -> tuple[str, ...]:
        return tuple(t for t, _ in self._termos)

    def fase_inicial(self) -> tuple[str, ...]:
        self._proxima = 1
        self.fases.append({"fase": DESCRICAO, "termos": list(self.termos)})
        return self.termos

    def proxima_fase(self) -> tuple[str, ...] | None:
        """Os termos da próxima fase (cumulativos), ou None se acabou."""
        if self.literal:
            return None
        while self._proxima < FASES_MAXIMAS:
            fase = self._proxima
            self._proxima += 1
            if fase == 1:
                novos = [(v, SINONIMO) for v in
                         variantes_locais(str(self.item.get("descricao") or ""))
                         if v not in self.termos]
                nome = "variantes_locais"
            else:
                novos = [(t, IA) for t in self._termos_da_ia()
                         if t not in self.termos]
                nome = IA
            if novos:
                self._termos.extend(novos)
                self.fases.append({"fase": nome,
                                   "termos": [t for t, _ in novos]})
                return self.termos
        return None

    def _termos_da_ia(self) -> tuple[str, ...]:
        if self.motor is None:
            return ()
        from . import semantica

        self.chave_ia = chave_de_cache(self.item)
        guardados = self.cache.obter(self.chave_ia)
        if guardados is not None:
            self.ia_do_cache = True
            self.termos_ia = tuple(guardados)
            return self.termos_ia
        if not self.orcamento.consumir():
            self.ia_sem_orcamento = True
            return ()
        termos = [" ".join(str(t).split())[:80] for t in
                  semantica.sugerir_termos(self.motor, self.item,
                                           limite=MAX_TERMOS_IA)
                  if str(t).strip()]
        self.termos_ia = tuple(termos[:MAX_TERMOS_IA])
        self.cache.guardar(self.chave_ia, self.termos_ia)
        return self.termos_ia

    def registrar_rendimento(self, elegiveis: int, unicas: int) -> None:
        if self.fases:
            self.fases[-1].update(elegiveis=elegiveis, unicas=unicas)

    @property
    def ganho_ia(self) -> int | None:
        """Elegíveis que a fase de IA acrescentou (None: não houve fase)."""
        fases = {f["fase"]: f for f in self.fases}
        if IA not in fases or "elegiveis" not in fases[IA]:
            return None
        anterior = [f for f in self.fases if f["fase"] != IA and "elegiveis" in f]
        base = max((f["elegiveis"] for f in anterior), default=0)
        return int(fases[IA]["elegiveis"]) - int(base)

    def para_registro(self) -> dict:
        return {"versao": VERSAO, "literal": self.literal,
                "ganho_ia": self.ganho_ia, "ia_sem_orcamento": self.ia_sem_orcamento,
                "termos": [{"texto": t, "origem": o} for t, o in self._termos],
                "fases": self.fases,
                "ia": bool(self.termos_ia), "ia_do_cache": self.ia_do_cache,
                "chave_ia": self.chave_ia, "termos_ia": list(self.termos_ia)}
