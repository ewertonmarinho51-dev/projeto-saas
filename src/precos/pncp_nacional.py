"""
PNCP nacional sob demanda — a busca textual do portal como porta de entrada.

POR QUE EXISTE (11/11/2026)
---------------------------
O dono comparou a mesma cotação ("analisador bioquímico") no Banco de
Preços e aqui. Lá: dezenas de resultados homologados de CE, PE, GO, MT, MA,
MG, RS, SP e RJ, de até um ano atrás. Aqui: nenhum. Medido no mesmo dia:

* o índice do PNCP (`pncp_indice`) tinha 141 resultados, todos do Pará,
  nenhum "analisador";
* ampliar o índice para o Brasil inteiro não cabe: o PNCP publica ~32,5 mil
  pregões por mês (31.934 eletrônicos + 634 presenciais em out/2026, contra
  536 no Pará). Um ano nacional são ~390 mil contratações e uma chamada POR
  ITEM para ler o resultado — milhões de chamadas e de linhas;
* o módulo de dados abertos do Compras.gov (`3_consultarResultadoItens…`)
  devolve resultados em lote, mas só de órgão federal: o CNPJ de Santana do
  Araguaia voltou com zero registros.

O que resolve é a busca do próprio portal, `pncp.gov.br/api/search/`, que
o docstring de `pncp.py` (09/2026) não conhecia: texto livre, nacional,
filtrável por modalidade e por `tem_resultado`. "analisador bioquimico" com
pregão e resultado: 1.178 contratações de 18 UFs só na primeira página.

COMO FUNCIONA
-------------
1. busca textual com o NÚCLEO da descrição (as primeiras palavras
   significativas, na ordem) — e com o primeiro termo alternativo, se houver;
2. só pregão eletrônico e presencial (dispensa fora: dado pessoal, ver
   `pncp_indice.MODALIDADES_PADRAO`), com resultado, não cancelada, da UF
   pedida (sem UF: Brasil inteiro);
3. cada contratação passa por `pncp.PNCPContratacao`, com o cabeçalho que a
   busca já trouxe: lê os itens, escolhe os que têm o NOME do item
   (`aceitar_item`) e confere o resultado homologado (unitário × quantidade
   = total, maior desconto fora, cancelado fora). Equivalência e cesta
   continuam do motor;
4. referência fora da janela da pesquisa (`Consulta.data_inicial/final`)
   não entra. A janela é decisão da PESQUISA, não desta fonte.

A busca do portal NÃO é a API de consulta documentada: é a que o site usa.
Se mudar de contrato, a fonte falha alto (`falhar`) e a pesquisa segue nas
demais — nunca inventa preço.

O PNCP LIMITA A TAXA (medido em 11/11/2026): rajada de 4 chamadas em
paralelo levou HTTP 429 logo depois, inclusive na API de consulta. Por isso
uma chamada por vez no processo, com intervalo mínimo, `Retry-After`
respeitado, e nenhuma chamada à API de consulta.
"""

from __future__ import annotations

import json
import threading
import time
import unicodedata
import urllib.error
import urllib.parse
from datetime import timedelta

from . import pncp
from .fontes import Capacidade, Consulta, FontePesquisaPreco, ResultadoBusca

BUSCA = "https://pncp.gov.br/api/search/"
MODALIDADES = (6, 7)
# Contratações lidas por item: cada uma custa 1 chamada (itens) + até
# `ITENS_POR_CONTRATACAO` (resultados).
MAX_CONTRATACOES = 16
ITENS_POR_CONTRATACAO = 2
PAGINA_BUSCA = 50
ALVO_REFERENCIAS = 15
PALAVRAS_DA_BUSCA = 4
INTERVALO_S = 0.35
TENTATIVAS = 4
RECUO_S = 1.5
RETRY_AFTER_MAX_S = 10.0
# o resultado sai depois da publicação: o pregão publicado um pouco antes
# da janela ainda pode ter resultado dentro dela
FOLGA_PUBLICACAO_DIAS = 120

_RUIDO = {"especificacao", "especificacoes", "tipo", "material", "com", "sem",
          "para", "de", "da", "do", "das", "dos", "em", "ou", "e", "a", "o",
          "aplicacao", "caracteristicas", "adicionais", "cor", "unidade",
          "marca", "referencia", "modelo", "minimo", "aproximadamente",
          # embalagem e medida: estreitam a busca do portal sem dizer o que
          # o item É ("Cimento CP II 32, saco 50 kg" → "cimento")
          "saco", "sacos", "caixa", "pacote", "resma", "folhas", "litro",
          "litros", "metro", "metros", "frasco", "galao", "rolo", "fardo",
          "und", "pct", "gramas", "quilo", "quilos",
          # verbo da compra, que vem ANTES do objeto: "Contratação de empresa
          # para…", "Aquisição de cimento" — e, num serviço, antes de um
          # nome próprio (revisão de banco de 11/11/2026)
          "aquisicao", "contratacao", "empresa", "prestacao", "servico",
          "servicos", "fornecimento", "especializada", "eventual", "futura",
          "registro", "precos", "objeto"}
# formato com letra e número ("a4", "75g", "cr2032") é curto; maior que isso
# é código, documento ou identificação colada na descrição
FORMATO_MAX = 6
FORMATO_MAX_DIGITOS = 4


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode(
        "ascii", "ignore").decode().lower()


def nucleo(texto: str, maximo: int = PALAVRAS_DA_BUSCA) -> str:
    """As primeiras palavras significativas, NA ORDEM em que vieram.

    A descrição de planilha começa pelo que o item é ("Analisador bioquímico
    semiautomático, com…"); a especificação vem depois e só estreitaria a
    busca do portal. Número puro ("32", "500") fica de fora; formato com
    letra e número ("a4", "75g") fica — "papel" sozinho acha guardanapo."""
    palavras: list[str] = []
    for bruta in _sem_acento(texto).replace(",", " ").replace(";", " ").split():
        if "@" in bruta:
            continue                          # e-mail nunca vira termo
        palavra = "".join(c for c in bruta if c.isalnum())
        digitos = sum(c.isdigit() for c in palavra)
        formato = (0 < digitos <= FORMATO_MAX_DIGITOS
                   and any(c.isalpha() for c in palavra)
                   and 2 <= len(palavra) <= FORMATO_MAX)
        if ((len(palavra) > 2 and palavra.isalpha()) or formato) \
                and palavra not in _RUIDO and palavra not in palavras:
            palavras.append(palavra)
        if len(palavras) >= maximo:
            break
    return " ".join(palavras)


def _mesma_palavra(termo: str, palavra: str) -> bool:
    """Palavra longa casa pelo radical ("bioquímico" e "bioquímica",
    "analisador" e "analisadores"); curta, só inteira ("papel" não é
    "papeleira")."""
    if len(palavra) <= 6:
        return termo == palavra
    return termo.startswith(palavra[:6])


def aceitar_item(descricao_consulta: str):
    """
    Filtro do item DENTRO da contratação encontrada: o item tem de COMEÇAR
    pelo nome do item consultado (1ª palavra do núcleo) e conter a 2ª
    palavra do núcleo em qualquer lugar.

    Medido em 11/11/2026, na busca por "analisador bioquímico": sem isto
    entravam "Lâmpada halógena… para analisador" (Pedro Gomes/MS),
    "LAMPADA PARA ANALISADOR LABMAX" (Socorro/SP), kits de reagente
    (Uiraúna/PB) e o analisador de HEMATOLOGIA (Castanhal/PA); por "papel
    A4", envelope e guardanapo. Consulta sem núcleo não restringe.
    """
    palavras = nucleo(descricao_consulta).split()
    if not palavras:
        return None
    nome = palavras[0]
    qualificador = palavras[1] if len(palavras) > 1 else None

    def aceita(descricao_item: str) -> bool:
        termos = nucleo(descricao_item, maximo=60).split()
        if not termos or not _mesma_palavra(termos[0], nome):
            return False
        return qualificador is None or any(
            _mesma_palavra(t, qualificador) for t in termos)
    return aceita


def contratacao_do_resultado(hit: dict) -> dict:
    """O cabeçalho da contratação no formato da API de consulta (o que
    `pncp._referencia_do_resultado` e `pncp_indice.resumo_da_contratacao`
    leem), a partir do resultado da busca — sem chamar a API de consulta."""
    def _int(valor):
        try:
            return int(valor)
        except (TypeError, ValueError):
            return None
    return {
        "numeroControlePNCP": hit.get("numero_controle_pncp"),
        "usuarioNome": hit.get("usuario_nome"),
        "linkSistemaOrigem": hit.get("link_sistema_origem"),
        "modalidadeId": _int(hit.get("modalidade_licitacao_id")),
        "modalidadeNome": hit.get("modalidade_licitacao_nome"),
        "anoCompra": _int(hit.get("ano")),
        "sequencialCompra": _int(hit.get("numero_sequencial")),
        "numeroCompra": hit.get("numero"),
        "srp": hit.get("srp"),
        "dataAtualizacaoGlobal": hit.get("data_atualizacao_pncp"),
        "dataPublicacaoPncp": hit.get("data_publicacao_pncp"),
        "situacaoCompraNome": hit.get("situacao_nome"),
        "valorTotalHomologado": hit.get("valor_total_homologado"),
        "orgaoEntidade": {"cnpj": hit.get("orgao_cnpj"),
                          "razaoSocial": hit.get("orgao_nome"),
                          "esferaId": hit.get("esfera_id"),
                          "poderId": hit.get("poder_id")},
        "unidadeOrgao": {"ufSigla": hit.get("uf"),
                         "municipioNome": hit.get("municipio_nome"),
                         "nomeUnidade": hit.get("unidade_nome")},
    }


def parametros_da_busca(texto: str, *, uf: str | None = None,
                        modalidades=MODALIDADES,
                        tamanho: int = PAGINA_BUSCA) -> dict:
    """Pregões ENCERRADOS com resultado: com `status=todos` o portal ignora
    `tem_resultado` (medido: 25 de 30 sem resultado; com `encerradas`, 30/30)."""
    parametros = {
        "q": texto, "tipos_documento": "edital", "ordenacao": "-data",
        "pagina": 1, "tam_pagina": tamanho, "status": "encerradas",
        "modalidades": "|".join(str(m) for m in modalidades),
        "tem_resultado": "true"}
    if uf:
        parametros["ufs"] = uf.upper()
    return parametros


def controle_aceito(hit, *, modalidades=MODALIDADES, uf: str | None = None,
                    desde=None) -> str | None:
    """Número de controle do resultado da busca, se for pregão do piloto,
    com resultado, não cancelado, da UF e publicado a partir de `desde`."""
    if not isinstance(hit, dict) or hit.get("cancelado"):
        return None
    try:
        if int(hit.get("modalidade_licitacao_id")) not in modalidades:
            return None
    except (TypeError, ValueError):
        return None
    if not hit.get("tem_resultado"):
        return None
    if uf and str(hit.get("uf") or "").upper() != uf.upper():
        return None
    publicada = str(hit.get("data_publicacao_pncp") or "")[:10]
    if desde and publicada and publicada < desde.isoformat():
        return None
    controle = str(hit.get("numero_controle_pncp") or "")
    return controle if pncp.controle_da_entrada(controle) else None


class PNCPNacional(FontePesquisaPreco):
    """Resultados homologados de pregões do Brasil inteiro, por descrição."""

    fonte = pncp.FONTE_PNCP
    capacidades = frozenset({Capacidade.PRECO, Capacidade.EVIDENCIA})

    # o intervalo vale para o PROCESSO: duas instâncias da fonte não podem
    # somar rajadas
    _trava = threading.Lock()
    _ultima = 0.0

    def __init__(self, abrir_url=None, *, dormir=time.sleep,
                 relogio=time.monotonic,
                 max_contratacoes: int = MAX_CONTRATACOES,
                 itens_por_contratacao: int = ITENS_POR_CONTRATACAO,
                 intervalo_s: float = INTERVALO_S) -> None:
        self._abrir_cru = abrir_url or pncp.PNCPAdapter()._abrir_url
        self._dormir = dormir
        self._relogio = relogio
        self._max_contratacoes = max_contratacoes
        self._itens = itens_por_contratacao
        self._intervalo = intervalo_s

    def _esperar_vez(self) -> None:
        with PNCPNacional._trava:
            falta = PNCPNacional._ultima + self._intervalo - self._relogio()
            if falta > 0:
                self._dormir(falta)
            PNCPNacional._ultima = self._relogio()

    def _abrir(self, url: str) -> str:
        """Uma chamada por vez; nova tentativa em conexão recusada, 429
        (respeitando `Retry-After`) e 5xx; o resto sobe."""
        recuo = RECUO_S
        for tentativa in range(1, TENTATIVAS + 1):
            self._esperar_vez()
            espera = recuo
            try:
                return self._abrir_cru(url)
            except urllib.error.HTTPError as erro:
                if erro.code not in (429, 500, 502, 503, 504) or \
                        tentativa == TENTATIVAS:
                    raise
                pedido = erro.headers.get("Retry-After") \
                    if erro.code == 429 and erro.headers else None
                try:
                    espera = min(RETRY_AFTER_MAX_S, max(recuo, float(pedido)))
                except (TypeError, ValueError):
                    pass
            except (urllib.error.URLError, TimeoutError, OSError):
                if tentativa == TENTATIVAS:
                    raise
            self._dormir(espera)
            recuo *= 2
        raise urllib.error.URLError("PNCP não respondeu")  # inalcançável

    # -- busca do portal ------------------------------------------------------
    def _contratacoes(self, consulta: Consulta,
                      resultado: ResultadoBusca) -> list[dict] | None:
        textos = [nucleo(consulta.descricao)]
        if consulta.termos_alternativos:
            textos.append(nucleo(consulta.termos_alternativos[0]))
        desde = (consulta.data_inicial - timedelta(days=FOLGA_PUBLICACAO_DIAS)
                 if consulta.data_inicial else None)
        achadas: dict[str, dict] = {}
        for texto in dict.fromkeys(t for t in textos if t):
            parametros = parametros_da_busca(texto, uf=consulta.uf)
            resultado.chamadas += 1
            try:
                dados = json.loads(self._abrir(
                    f"{BUSCA}?{urllib.parse.urlencode(parametros)}"))
            except urllib.error.HTTPError as erro:
                resultado.falhar(f"a busca do PNCP respondeu HTTP {erro.code}; "
                                 "a pesquisa continua nas demais fontes")
                return None
            except (urllib.error.URLError, TimeoutError, OSError):
                resultado.falhar("a busca do PNCP não respondeu agora; a "
                                 "pesquisa continua nas demais fontes")
                return None
            except json.JSONDecodeError:
                resultado.falhar("a busca do PNCP devolveu resposta não-JSON")
                return None
            if not isinstance(dados, dict) or not isinstance(
                    dados.get("items"), list):
                resultado.falhar("a busca do PNCP mudou de formato; a "
                                 "pesquisa continua nas demais fontes")
                return None
            for hit in dados["items"]:
                controle = controle_aceito(hit, uf=consulta.uf, desde=desde)
                if controle and controle not in achadas:
                    achadas[controle] = hit
        return list(achadas.values())[:self._max_contratacoes]

    # -- fonte ----------------------------------------------------------------
    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        resultado = ResultadoBusca(fonte=self.fonte)
        if not nucleo(consulta.descricao):
            return resultado.registrar(
                "PNCP: descrição sem termo pesquisável")
        achadas = self._contratacoes(consulta, resultado)
        if achadas is None:
            return resultado
        if not achadas:
            return resultado.registrar(
                "PNCP: nenhum pregão homologado encontrado para a descrição")
        alvo = max(1, min(ALVO_REFERENCIAS, consulta.limite or ALVO_REFERENCIAS))
        filtro = aceitar_item(consulta.descricao)
        vistas: set[str] = set()
        falhas = 0
        for hit in achadas:
            parcial = pncp.PNCPContratacao(
                str(hit.get("numero_controle_pncp")), abrir_url=self._abrir,
                max_itens=self._itens, contratacao=contratacao_do_resultado(hit),
                aceitar_item=filtro).pesquisar(consulta)
            resultado.chamadas += parcial.chamadas
            if parcial.houve_falha:
                falhas += 1
            for referencia in parcial.referencias:
                if referencia.id_externo in vistas or \
                        not self._na_janela(referencia, consulta):
                    continue
                vistas.add(referencia.id_externo)
                resultado.referencias.append(referencia)
            if len(resultado.referencias) >= alvo:
                break
        if falhas:
            resultado.registrar(
                f"PNCP: {falhas} contratação(ões) não responderam; as demais "
                "foram lidas")
        if not resultado.referencias:
            resultado.registrar(
                "PNCP: as contratações encontradas não têm item homologado "
                "equivalente dentro da janela da pesquisa")
        return resultado

    @staticmethod
    def _na_janela(referencia, consulta: Consulta) -> bool:
        data = referencia.data_resultado
        if data is None:
            return False                 # sem data não se prova a janela
        if consulta.data_inicial and data < consulta.data_inicial:
            return False
        return not (consulta.data_final and data > consulta.data_final)

    def healthcheck(self) -> bool:
        try:
            dados = json.loads(self._abrir(f"{BUSCA}?" + urllib.parse.urlencode(
                {"q": "cimento", "tipos_documento": "edital", "pagina": 1,
                 "tam_pagina": 1})))
            return isinstance(dados, dict) and "items" in dados
        except Exception:  # noqa: BLE001
            return False
