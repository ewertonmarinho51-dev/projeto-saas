"""
Equivalência entre o item pesquisado e o candidato que a fonte devolveu —
separar RECUPERAÇÃO de ELEGIBILIDADE.

A busca ampliada (sinônimos, siglas, variantes de unidade) existe para
trazer "papel para impressão A4 75 g, resma 500 folhas" quando o item diz
"papel sulfite A4 75 g/m², 500 folhas". Trazer não é aceitar: o candidato
só vira preço automático quando a descrição da fonte CONFIRMA os atributos
essenciais do item. Quatro classes, nesta ordem de força:

* **mesmo item** — mesmo código oficial, ou descrição fortemente semelhante
  com os atributos essenciais conferidos;
* **equivalente comprovado** — redação diferente, atributos essenciais
  (gramatura, volume, massa, concentração, contagem, formato…) iguais. Entra
  na cesta proposta como o mesmo item;
* **similar para revisão** — falta prova de um atributo essencial (a fonte
  não diz a gramatura, a caixa não diz quantas unidades). Fica com o
  servidor, com o motivo e o comparativo; nunca entra sozinho;
* **incompatível** — divergência essencial (90 g/m² contra 75 g/m², 10 L
  contra 20 L). Sai da elegibilidade.

Nada aqui chama IA nem olha preço: os atributos vêm do texto da fonte e do
item, e a régua é determinística. Item sem atributo quantificável não é
classificado (`None`): o casamento por descrição segue como sempre foi.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

VERSAO = "2026-11-26.equivalencia.3"

MESMO_ITEM = "mesmo_item"
EQUIVALENTE = "equivalente"
SIMILAR = "similar"
INCOMPATIVEL = "incompativel"

ROTULO = {MESMO_ITEM: "mesmo item", EQUIVALENTE: "equivalente comprovado",
          SIMILAR: "similar para revisão", INCOMPATIVEL: "incompatível"}

# Identidade mínima de um equivalente comprovado: atributos essenciais
# iguais valem tanto quanto uma redação "fortemente semelhante" (0,6) do
# matching — e um pouco mais, para não depender do sinônimo.
IDENTIDADE_EQUIVALENTE = Decimal("0.75")
SEMELHANCA_MESMO_ITEM = Decimal("0.8")

# unidade lida → (dimensão, fator para a unidade base da dimensão)
_UNIDADES: dict[str, tuple[str, Decimal]] = {
    "G/M2": ("gramatura", Decimal(1)), "GM2": ("gramatura", Decimal(1)),
    "G/M": ("gramatura", Decimal(1)), "GRAMATURA": ("gramatura", Decimal(1)),
    "MG/ML": ("concentracao", Decimal(1)),
    "KG": ("massa", Decimal(1000)), "G": ("massa", Decimal(1)),
    "GR": ("massa", Decimal(1)), "GRAMAS": ("massa", Decimal(1)),
    "GRAMA": ("massa", Decimal(1)), "MG": ("massa", Decimal("0.001")),
    "MCG": ("massa", Decimal("0.000001")),
    "L": ("volume", Decimal(1000)), "LT": ("volume", Decimal(1000)),
    "LTS": ("volume", Decimal(1000)), "LITRO": ("volume", Decimal(1000)),
    "LITROS": ("volume", Decimal(1000)), "ML": ("volume", Decimal(1)),
    "W": ("potencia", Decimal(1)), "V": ("tensao", Decimal(1)),
    "VOLTS": ("tensao", Decimal(1)), "%": ("percentual", Decimal(1)),
    "FOLHAS": ("folhas", Decimal(1)), "FLS": ("folhas", Decimal(1)),
    "FL": ("folhas", Decimal(1)), "FOLHA": ("folhas", Decimal(1)),
    "MM2": ("secao", Decimal(1)),
    "COMPRIMIDOS": ("doses", Decimal(1)), "CPR": ("doses", Decimal(1)),
    "CAPSULAS": ("doses", Decimal(1)), "CAPS": ("doses", Decimal(1)),
}
_SIGLAS = sorted(_UNIDADES, key=len, reverse=True)
_QUANTIFICADO = re.compile(
    r"(?<![\w.])(\d+(?:[.,]\d+)?)\s*(" + "|".join(re.escape(s) for s in _SIGLAS)
    + r")(?![\w/])")
# Só A3–A6 pelo nome: "OFÍCIO" no catálogo é TIPO de papel
# ("SULFITE/APERGAMINHADO/OFÍCIO"), não formato. A dimensão em mm também
# prova o formato (297 x 210 = A4), pela tabela de `atributos`.
_FORMATO = re.compile(r"(?<![\w])(A[3-6])(?![\w])")
# resma sem contagem declarada é, por convenção do mercado, 500 folhas
_RESMA = re.compile(r"(?<![\w])RESMAS?(?![\w])")

# Designações que SÃO especificação (26/11/2026). Medido na cotação real de
# materiais de construção: "ARGAMASSA COLANTE AC 2" recebia AC-I e AC-III, e
# "BUCHA DE NYLON SEM ABA S6" recebia S4, S5, S8 e S10 — séries de produtos
# diferentes, CV acima de 30% e o item preso em revisão. A lista é curta e
# fechada de propósito: cada família tem sentido técnico conhecido.
#
# * classe da argamassa colante (NBR 14081): AC-I/AC-II/AC-III, AC1/AC 2…;
# * tamanho da bucha de fixação: S4, S6, S8, S10… (só em texto de BUCHA);
# * bitola em polegadas: 6", 1/2", 1.1/2", 3/4 POL (alicate, tubo, conexão);
# * seção do condutor elétrico: 2,5 mm², 4 mm².
_CLASSE_AC = re.compile(r"(?<![A-Z0-9])AC[\s-]?(III|II|I|[123])(?![IVX0-9])")
_ROMANO = {"I": "1", "II": "2", "III": "3"}
_TAMANHO_BUCHA = re.compile(r"(?<![A-Z0-9])S[\s-]?(\d{1,2})(?!\d)")
# Água: a recarga do garrafão não é o fornecimento com vasilhame novo.
_RECARGA = re.compile(r"(?<![A-Z])(RECARGA|RETORNAVE(?:L|IS))(?![A-Z])")
_VASILHAME = re.compile(r"(?<![A-Z])(COM VASILHAME|VASILHAME INCLUSO|INCLUINDO VASILHAME|"
                        r"GARRAFAO NOVO|VASILHAME NOVO)(?![A-Z])")
# Bucha vendida em CONJUNTO com o parafuso: outro objeto que a bucha sozinha.
_COM_PARAFUSO = re.compile(r"(?<![A-Z])(COM|C/|E|\+)\s*PARAFUSOS?(?![A-Z])")
# O PRODUTO personalizado (gravação, logotipo): "personalizada conforme
# modelo", "personalizada com brasão", ", personalizada,". Não confunde com
# "lacre personalizado pelo fabricante" (medido no lote A, 26/11/2026).
_PERSONALIZADO = re.compile(
    r"PERSONALIZAD[OA]S?\s+(?:CONFORME|MEDIANTE|COM\s+(?:A\s+|O\s+)?(?:LOGO|BRAS|NOME|IMPRESS|GRAVA|ARTE))"
    r"|[,:;]\s*PERSONALIZAD[OA]S?\s*(?:[,;.]|$)")
# Cimento: tipo (CP I…CP V), adição (E/F/Z) e classe de resistência (25/32/40).
_CIMENTO_CP = re.compile(r"(?<![A-Z])CP\s*-?\s*(III|II|IV|V|I)\s*-?\s*([EFZ])?"
                         r"\s*-?\s*(25|32|40)?(?![A-Z0-9])")
# Fita: largura e comprimento ("25 MM X 50 M", "48X50"), com folga de medida.
_FITA_MEDIDA = re.compile(r"(?<![\d,.])(\d{2})\s*(?:MM)?\s*X\s*(\d{2,3})(?:\s*M(?:TS|ETROS)?)?(?![\dX])")
# Cor declarada. Só DIVERGÊNCIA conta: a fonte que não diz a cor não perde
# a elegibilidade por isso (o catálogo omite a cor em muita descrição).
_CORES = {"BRANC": "branco", "PRET": "preto", "AZUL": "azul", "VERMELH": "vermelho",
          "VERDE": "verde", "AMAREL": "amarelo", "CINZ": "cinza", "MARRO": "marrom",
          "LARANJ": "laranja", "ROX": "roxo", "ROSA": "rosa", "INCOLOR": "incolor"}
_SORTIDAS = re.compile(r"(?<![A-Z])(SORTID|VARIAD|DIVERSAS CORES|CORES DIVERSAS|COLORID)")
# dimensões que NÃO exigem prova na fonte — só a divergência declarada vale
_SO_DIVERGENCIA = frozenset({"cor"})
# dimensões que valem também AO CONTRÁRIO: a fonte tem, o item não pediu
_REVERSAS = frozenset({"conjunto"})
# folga relativa na comparação (medida nominal: fita "24 X 50" é a de 25 mm)
_FOLGA = {"largura": Decimal("0.05"), "comprimento": Decimal("0.1")}
# Produto definido pelo QUALIFICADOR: "água sanitária" não é "água de coco".
_PRODUTO_PELO_QUALIFICADOR = {
    "AGUA": frozenset({"SANITARIA", "MINERAL", "COCO", "DESTILADA", "OXIGENADA",
                       "DEIONIZADA", "DESMINERALIZADA", "TONICA", "SANITARIO"}),
    "CANETA": frozenset({"ESFEROGRAFICA", "INDICADOR", "LASER", "MARCADORA",
                         "MARCA", "HIDROGRAFICA", "CORRETIVA", "NANQUIM",
                         "TINTEIRO", "MARCADOR", "TOUCH", "STYLUS"}),
}

_POLEGADA = re.compile(
    r"(?<![\d/.,])(?:(\d{1,2})(?:[.,\s-]+(\d{1,2})/(\d{1,2}))?|(\d{1,2})/(\d{1,2}))"
    r"\s*(?:\"|”|“|''|POLEGADAS?(?![A-Z])|POL(?![A-Z]))")


_RUIDO = {"DE", "DA", "DO", "DAS", "DOS", "PARA", "COM", "SEM", "EM", "E",
          "TIPO", "ESPECIFICACAO", "MATERIAL", "COR", "UNIDADE"}


def _palavras(texto) -> set[str]:
    limpo = "".join(c if c.isalnum() else " " for c in _norm(texto))
    return {p for p in limpo.split() if len(p) > 2 and not p.isdigit()
            and p not in _RUIDO}


def _nucleo(descricao: str) -> set[str]:
    """A primeira palavra significativa do item — o nome do produto
    ("PAPEL", "AGUA", "BLOCO"), que a fonte equivalente tem de repetir."""
    limpo = "".join(c if c.isalnum() else " " for c in _norm(descricao))
    for palavra in limpo.split():
        if len(palavra) > 2 and not any(ch.isdigit() for ch in palavra)                 and palavra not in _RUIDO:
            return {palavra}
    return set()


# dimensões de CONTEÚDO DA EMBALAGEM (ver `classificar`)
_EMBALAGEM = frozenset({"folhas", "doses"})


# ---------------------------------------------------------------------------
# Conflito de OBJETO (13/11/2026): vale mesmo quando o item não tem atributo
# quantificável. Medido na cesta do "analisador bioquímico": o automático
# trazia "Analisador Automatizado de Bioquímica — 12 MES" (locação) e o
# analisador de HEMATOLOGIA. Os dois saem da série, aqui e no "Pôr na cesta"
# (`cotacoes._impedimento_de_inclusao`), pela MESMA regra.
# ---------------------------------------------------------------------------
_PALAVRAS_DE_LOCACAO = ("LOCAC", "ALUGU", "COMODAT", "ARRENDAM")
_PALAVRAS_DE_SERVICO = ("MANUTENC", "PRESTAC", "SERVICO", "ASSISTENC",
                        "CALIBRAC", "CONSERTO", "REPARO")
# unidade que mede TEMPO, não coisa: "12 MES" é locação mensal
_UNIDADES_DE_PERIODO = frozenset({"MES", "MESES", "MENSAL", "MENSALIDADE",
                                  "DIA", "DIAS", "DIARIA", "DIARIAS", "HORA",
                                  "HORAS", "ANO", "ANUAL", "SEMANA"})
# adjetivos que não distinguem o produto: ficam de fora do "qualificador"
_GENERICOS = frozenset({
    "AUTOMATICO", "AUTOMATICA", "SEMIAUTOMATICO", "SEMIAUTOMATICA",
    "SEMI", "AUTOMATIZADO", "AUTOMATIZADA", "PORTATIL", "DIGITAL",
    "ELETRONICO", "ELETRONICA", "ELETRICO", "ELETRICA", "COMPLETO",
    "COMPLETA", "NOVO", "NOVA", "COMPACTO", "COMPACTA", "MULTIPARAMETRICO",
    "MULTIPARAMETRICA", "MODELO", "MARCA", "REFERENCIA", "PROFISSIONAL",
    "INDUSTRIAL", "SIMPLES", "PADRAO", "MANUAL", "UNIVERSAL"})
# terminação de qualificador de ÁREA/ESPECIALIDADE: hematológico,
# bioquímica, cirúrgica, endodôntico, higiênico, odontologia…
_SUFIXOS_DE_AREA = ("ICO", "ICA", "ICOS", "ICAS", "IA", "IAS")


def _sequencia(texto) -> list[str]:
    limpo = "".join(c if c.isalnum() else " " for c in _norm(texto))
    return [p for p in limpo.split() if len(p) > 2 and p.isalpha()
            and p not in _RUIDO]


def natureza_do_objeto(descricao, unidade="") -> str:
    """"compra", "locação" ou "serviço", pela CABEÇA da descrição (as três
    primeiras palavras: "Locação de analisador", "Manutenção do…") e pela
    unidade de tempo. "Ar condicionado … com instalação" continua compra."""
    cabeca = _sequencia(descricao)[:3]
    if any(p.startswith(_PALAVRAS_DE_LOCACAO) for p in cabeca):
        return "locação"
    if any(p.startswith(_PALAVRAS_DE_SERVICO) for p in cabeca):
        return "serviço"
    if _norm(unidade).strip(" .") in _UNIDADES_DE_PERIODO:
        return "locação"
    return "compra"


def _nome_e_qualificador(descricao) -> tuple[str | None, str | None]:
    palavras = [p for p in _sequencia(descricao) if p not in _GENERICOS]
    if not palavras:
        return None, None
    return palavras[0], (palavras[1] if len(palavras) > 1 else None)


def _mesma(a: str, b: str) -> bool:
    return a[:6] == b[:6] if min(len(a), len(b)) > 6 else a == b


def conflito_de_objeto(descricao_item, descricao_fonte, *, unidade_item="",
                       unidade_fonte="") -> str:
    """O motivo do conflito entre o objeto do item e o da fonte, ou "".

    * natureza: compra × locação × serviço;
    * especificação concorrente: a fonte é o mesmo produto ("ANALISADOR"),
      com outro qualificador de área ("HEMATOLÓGICO") e sem o do item
      ("BIOQUÍMICO"). Qualificador ausente na fonte não é conflito — fica
      para a equivalência por atributo ou para a revisão."""
    do_item = natureza_do_objeto(descricao_item, unidade_item)
    da_fonte = natureza_do_objeto(descricao_fonte, unidade_fonte)
    if do_item != da_fonte:
        return f"objeto diferente: {da_fonte} na fonte, {do_item} no item"
    nome_item, qual_item = _nome_e_qualificador(descricao_item)
    nome_fonte, qual_fonte = _nome_e_qualificador(descricao_fonte)
    exclusivos = _PRODUTO_PELO_QUALIFICADOR.get(nome_item or "")
    if exclusivos and nome_fonte == nome_item and qual_item in exclusivos:
        da_fonte = set(_sequencia(descricao_fonte)) & exclusivos
        if da_fonte and qual_item not in da_fonte:
            outro = sorted(da_fonte)[0].lower()
            return (f"produto diferente: {nome_item.lower()} {outro} na fonte, "
                    f"{nome_item.lower()} {qual_item.lower()} no item")
    if not (nome_item and nome_fonte and qual_item and qual_fonte):
        return ""
    if not _mesma(nome_item, nome_fonte) or _mesma(qual_item, qual_fonte):
        return ""
    if not qual_fonte.endswith(_SUFIXOS_DE_AREA):
        return ""
    if any(_mesma(qual_item, p) for p in _sequencia(descricao_fonte)):
        return ""                       # "… de bioquímica e hematologia"
    return (f"especificação diferente: {qual_fonte.lower()} na fonte, "
            f"{qual_item.lower()} no item")


def _norm(texto) -> str:
    base = unicodedata.normalize("NFKD", str(texto or "").upper())
    base = "".join(c for c in base if not unicodedata.combining(c))
    return base.replace("²", "2").replace("³", "3")


def _formato_da_dimensao(limpo: str) -> str | None:
    from . import atributos as attr

    medida = attr._DIMENSAO.search(limpo)  # noqa: SLF001
    if not medida:
        return None
    par = attr._par(int(medida.group(1)), int(medida.group(2)))  # noqa: SLF001
    for nome, dimensao in attr.FORMATOS.items():
        if attr._mesmo_formato(par, attr._par(*dimensao)):  # noqa: SLF001
            return nome
    return None


def _numero(texto: str) -> Decimal | None:
    try:
        return Decimal(texto.replace(",", "."))
    except InvalidOperation:
        return None


def atributos(*textos) -> dict[str, frozenset]:
    """Dimensão → valores na unidade base. "75 g/m²" → {"gramatura": {75}}."""
    saida: dict[str, set] = {}
    for texto in textos:
        limpo = _norm(texto)
        for numero, sigla in _QUANTIFICADO.findall(limpo):
            valor = _numero(numero)
            if valor is None or valor <= 0:
                continue
            dimensao, fator = _UNIDADES[sigla]
            saida.setdefault(dimensao, set()).add((valor * fator).normalize())
        for formato in _FORMATO.findall(limpo):
            saida.setdefault("formato", set()).add(formato)
        formato = _formato_da_dimensao(limpo)
        if formato:
            saida.setdefault("formato", set()).add(formato)
        if _RESMA.search(limpo) and "folhas" not in saida:
            saida.setdefault("folhas", set()).add(Decimal(500))
        for classe in _CLASSE_AC.findall(limpo):
            saida.setdefault("classe", set()).add("AC-" + _ROMANO.get(classe, classe))
        if "BUCHA" in limpo:
            for tamanho in _TAMANHO_BUCHA.findall(limpo):
                saida.setdefault("tamanho", set()).add(f"S{int(tamanho)}")
        if "AGUA" in limpo:
            if _VASILHAME.search(limpo):
                saida.setdefault("fornecimento", set()).add("com vasilhame")
            elif _RECARGA.search(limpo):
                saida.setdefault("fornecimento", set()).add("recarga")
        if _PERSONALIZADO.search(limpo):
            # personalização (gravação, logotipo) é serviço agregado ao produto
            saida.setdefault("conjunto", set()).add("personalizado")
        if "BUCHA" in limpo and _COM_PARAFUSO.search(limpo):
            saida.setdefault("conjunto", set()).add("com parafuso")
        if "CIMENTO" in limpo:
            for tipo, adicao, classe in _CIMENTO_CP.findall(limpo):
                saida.setdefault("cimento_tipo", set()).add(f"CP {tipo}")
                if adicao:
                    saida.setdefault("cimento_adicao", set()).add(adicao)
                if classe:
                    saida.setdefault("cimento_classe", set()).add(classe)
            if re.search(r"CIMENTO\s+(?:PORTLAND\s+)?BRANCO", limpo):
                saida.setdefault("cimento_tipo", set()).add("branco")
        if "FITA" in limpo:
            for largura, comprimento in _FITA_MEDIDA.findall(limpo):
                saida.setdefault("largura", set()).add(Decimal(largura))
                saida.setdefault("comprimento", set()).add(Decimal(comprimento))
        if not _SORTIDAS.search(limpo):
            for palavra in re.findall(r"[A-Z]+", limpo):
                for raiz, cor in _CORES.items():
                    if palavra.startswith(raiz) and len(palavra) <= len(raiz) + 2:
                        saida.setdefault("cor", set()).add(cor)
        for inteiro, num, den, num_so, den_so in _POLEGADA.findall(limpo):
            valor = _fracao(inteiro, num, den, num_so, den_so)
            if valor is not None:
                saida.setdefault("polegadas", set()).add(valor)
    return {k: frozenset(v) for k, v in saida.items()}


def _fracao(inteiro: str, num: str, den: str, num_so: str, den_so: str) -> Decimal | None:
    """6 → 6; 1.1/2 → 1,5; 3/4 → 0,75. Denominador zero não é medida."""
    try:
        if num_so:
            return (Decimal(num_so) / Decimal(den_so)).normalize()
        base = Decimal(inteiro)
        if num:
            base += Decimal(num) / Decimal(den)
        return base.normalize() if base > 0 else None
    except (InvalidOperation, ZeroDivisionError):
        return None


_NOME = {"gramatura": "gramatura", "massa": "massa", "volume": "volume",
         "concentracao": "concentração", "potencia": "potência",
         "tensao": "tensão", "percentual": "percentual", "folhas": "folhas",
         "doses": "doses", "formato": "formato", "classe": "classe",
         "tamanho": "tamanho", "polegadas": "bitola", "secao": "seção",
         "fornecimento": "fornecimento", "conjunto": "conjunto",
         "cimento_tipo": "tipo de cimento", "cimento_adicao": "adição do cimento",
         "cimento_classe": "classe do cimento", "largura": "largura",
         "comprimento": "comprimento", "cor": "cor"}


def _texto(valor: Decimal) -> str:
    return format(valor.normalize(), "f").replace(".", ",")


def _um(dimensao: str, valor) -> str:
    if not isinstance(valor, Decimal):
        return str(valor)
    if dimensao == "volume" and valor >= 1000:
        return f"{_texto(valor / 1000)} L"
    if dimensao == "massa" and valor >= 1000:
        return f"{_texto(valor / 1000)} kg"
    unidade = {"gramatura": " g/m²", "massa": " g", "volume": " ml",
               "concentracao": " mg/ml", "potencia": " W", "tensao": " V",
               "percentual": "%", "folhas": " folhas", "doses": " un",
               "polegadas": "\"", "secao": " mm²", "largura": " mm",
               "comprimento": " m"
               }.get(dimensao, "")
    return f"{_texto(valor)}{unidade}"


def _exibir(dimensao: str, valores) -> str:
    return "/".join(_um(dimensao, v) for v in sorted(valores, key=str))


@dataclass(frozen=True)
class Equivalencia:
    classe: str
    conferidos: tuple[str, ...] = ()
    faltam: tuple[str, ...] = ()
    divergem: tuple[str, ...] = ()
    versao: str = VERSAO

    @property
    def rotulo(self) -> str:
        return ROTULO[self.classe]

    @property
    def explicacao(self) -> str:
        partes = [self.rotulo]
        if self.divergem:
            partes.append("diverge: " + "; ".join(self.divergem))
        if self.faltam:
            partes.append("a fonte não comprova: " + "; ".join(self.faltam))
        if self.conferidos:
            partes.append("conferido: " + "; ".join(self.conferidos))
        return " — ".join(partes)

    @property
    def score(self) -> Decimal:
        return {MESMO_ITEM: Decimal(1), EQUIVALENTE: Decimal("0.9"),
                SIMILAR: Decimal("0.5"), INCOMPATIVEL: Decimal(0)}[self.classe]

    def para_registro(self) -> dict:
        return {"classe": self.classe, "rotulo": self.rotulo,
                "conferidos": list(self.conferidos), "faltam": list(self.faltam),
                "divergem": list(self.divergem), "versao": self.versao}


def _cruzar(dimensao: str, do_item: frozenset, da_fonte: dict) -> tuple:
    """Gramatura e massa se confundem na redação ("75 g" no papel): o
    número igual na outra dimensão conta como a mesma medida."""
    if dimensao in da_fonte:
        return da_fonte[dimensao], dimensao
    par = {"gramatura": "massa", "massa": "gramatura"}.get(dimensao)
    if par and par in da_fonte and do_item & da_fonte[par]:
        return da_fonte[par], par
    return None, None


def _perto(valores, achados, folga: Decimal) -> bool:
    """Algum valor do item a até `folga` (relativa) de algum da fonte."""
    return any(abs(a - b) <= folga * b for a in achados for b in valores if b)


def classificar(descricao_item: str, descricao_fonte: str, *,
                unidade_item: str = "", unidade_fonte: str = "",
                mesmo_codigo: bool = False,
                semelhanca: Decimal = Decimal(0),
                convertida: bool = False) -> Equivalencia | None:
    """
    A classe do candidato, ou `None` quando o item não traz atributo
    quantificável (nada a comprovar além da redação).

    `semelhanca` é o fator de descrição do matching (0..1); `mesmo_codigo`,
    o código oficial igual — prova documental que prevalece sobre a redação.

    Contagem (folhas, doses) é EMBALAGEM, não especificação: quem a prova é
    a conversão de unidade (`unidades.normalizar`, fator explícito da
    fonte). `convertida` = a referência tem preço na unidade do item; aí a
    contagem está conferida, ainda que o texto da fonte não a repita ou
    traga outra (resma de 500 contra pacote de 100 se converte, não
    diverge). Sem conversão, falta prova — e a seleção já a recusa.
    """
    if not mesmo_codigo:
        conflito = conflito_de_objeto(descricao_item, descricao_fonte,
                                      unidade_item=unidade_item,
                                      unidade_fonte=unidade_fonte)
        if conflito:
            return Equivalencia(INCOMPATIVEL, divergem=(conflito,))
    do_item = atributos(descricao_item, unidade_item)
    if not do_item:
        return None
    if mesmo_codigo:
        return Equivalencia(MESMO_ITEM, conferidos=("mesmo código oficial",))
    da_fonte = atributos(descricao_fonte, unidade_fonte)
    conferidos, faltam, divergem = [], [], []
    for dimensao, valores in sorted(do_item.items()):
        nome = _NOME[dimensao]
        achados, _ = _cruzar(dimensao, valores, da_fonte)
        if dimensao in _EMBALAGEM:
            if achados is not None and valores <= achados:
                conferidos.append(f"{nome} {_exibir(dimensao, valores)}")
            elif convertida:
                conferidos.append(f"{nome} {_exibir(dimensao, valores)} "
                                  "pela conversão de embalagem")
            else:
                faltam.append(f"{nome} {_exibir(dimensao, valores)}")
            continue
        if dimensao in _SO_DIVERGENCIA:
            if achados is None:
                continue                       # a fonte não diz: não pesa
            if valores & achados:
                conferidos.append(f"{nome} {_exibir(dimensao, valores & achados)}")
            else:
                divergem.append(f"{nome} {_exibir(dimensao, achados)} na fonte, "
                                f"{_exibir(dimensao, valores)} no item")
            continue
        if dimensao in _FOLGA and achados is not None:
            if _perto(valores, achados, _FOLGA[dimensao]):
                conferidos.append(f"{nome} {_exibir(dimensao, valores)}")
            else:
                divergem.append(f"{nome} {_exibir(dimensao, achados)} na fonte, "
                                f"{_exibir(dimensao, valores)} no item")
            continue
        if achados is None:
            faltam.append(f"{nome} {_exibir(dimensao, valores)}")
        elif valores <= achados:
            conferidos.append(f"{nome} {_exibir(dimensao, valores)}")
        elif valores & achados:
            # parte confere, parte não (dimensões com mais de um valor)
            faltam.append(f"{nome} {_exibir(dimensao, valores - achados)}")
        else:
            divergem.append(f"{nome} {_exibir(dimensao, achados)} na fonte, "
                            f"{_exibir(dimensao, valores)} no item")
    for dimensao in sorted(_REVERSAS & set(da_fonte) - set(do_item)):
        divergem.append(f"{_NOME[dimensao]} {_exibir(dimensao, da_fonte[dimensao])} "
                        "na fonte, não pedido no item")
    if not (conferidos or faltam or divergem):
        return None                    # só atributo brando, e a fonte calada
    # A medida só fala do PRODUTO que a descrição nomeia: "PRODUTO
    # DIFERENTE 76X76" não é o bloco autoadesivo do item por ter a mesma
    # medida. Sem o núcleo do item na fonte e com redação pouco semelhante,
    # não há o que classificar — o matching por descrição decide (e recusa).
    mesmo_produto = _nucleo(descricao_item) <= _palavras(descricao_fonte)         or semelhanca >= Decimal("0.3")
    if not mesmo_produto:
        return None
    if divergem:
        return Equivalencia(INCOMPATIVEL, tuple(conferidos), tuple(faltam),
                            tuple(divergem))
    if faltam:
        return Equivalencia(SIMILAR, tuple(conferidos), tuple(faltam))
    # "mesmo item" é redação quase igual; "sulfite" × "para impressão" com
    # os atributos conferidos é equivalente comprovado (a mesma força na
    # cesta, rótulo honesto na revisão)
    if semelhanca >= SEMELHANCA_MESMO_ITEM:
        return Equivalencia(MESMO_ITEM, tuple(conferidos))
    # equivalente só com especificação conferida NO TEXTO da fonte; contagem
    # provada pela conversão de embalagem sozinha não fala do produto
    no_texto = [c for c in conferidos if "pela conversão" not in c]
    if not no_texto:
        return Equivalencia(SIMILAR, tuple(conferidos),
                            ("especificação essencial no texto da fonte",))
    return Equivalencia(EQUIVALENTE, tuple(conferidos))


def elegivel_automatica(classe: str | None) -> bool:
    """Pode compor a cesta proposta sem decisão de pessoa?"""
    return classe not in (SIMILAR, INCOMPATIVEL)


@dataclass
class Contagem:
    """Quantos candidatos de cada classe — o "ganho de cobertura" contra o
    "simples aumento de candidatos" da trilha."""

    por_classe: dict = field(default_factory=dict)

    def somar(self, classe: str | None) -> None:
        chave = classe or "sem_atributos"
        self.por_classe[chave] = self.por_classe.get(chave, 0) + 1
