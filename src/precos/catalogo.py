"""
Sugestão de CATMAT a partir da descrição do item.

POR QUE EXISTE

A API oficial de preços praticados só consulta pelo código do catálogo
(`/modulo-pesquisa-preco/1_consultarMaterial`, `tipo=codigoItemCatalogo`):
com o código, 180 dias de preços voltam em ~1,5 s. Sem ele não há
consulta viável — o caminho por "itens de contratações" pede a janela
inteira e filtra o texto do lado de cá, e medido em 14/10/2026 passava de
100 s para 180 dias.

As planilhas reais chegam sem CATMAT (número sequencial ou código
interno do município). Este módulo propõe candidatos; QUEM ESCOLHE é o
servidor. Nada aqui grava código no item sozinho.

COMO

O catálogo também não tem busca textual (`descricaoItem` só casa com a
descrição exata). Mas lista os PDMs — o "padrão descritivo" que agrupa
itens (ex.: CANETA ESFEROGRÁFICA) — e lista os itens de cada PDM:

  1. índice local dos PDMs ativos (~15 mil, 31 páginas, ~50 s na
     primeira vez), guardado em disco por 7 dias;
  2. os PDMs cujo nome mais casa com a descrição do item;
  3. os itens desses PDMs, ranqueados pela sobreposição de termos.

Determinístico, sem IA: a mesma descrição dá os mesmos candidatos.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import lru_cache

from .compras_gov import _sem_acento, _tokens

BASE = "https://dadosabertos.compras.gov.br/modulo-material"
TIMEOUT_S = 30
PAGINA_PDM = 500
VALIDADE_INDICE_S = 7 * 24 * 3600
ARQUIVO_INDICE = os.path.join(tempfile.gettempdir(), "govdocs_catmat_pdms.json")
MAX_PDMS = 8
MAX_CANDIDATOS = 5
# abaixo disto a tela avisa que a sugestão é fraca e pede conferência
ADERENCIA_BAIXA = 0.5


@dataclass(frozen=True)
class Candidato:
    codigo: str
    descricao: str
    pdm: str
    classe: str
    aderencia: float     # 0..1: fração dos termos do item presentes no candidato


class ErroCatalogo(RuntimeError):
    """O catálogo não respondeu — sem candidato inventado no lugar."""


class Catalogo:
    def __init__(self, abrir_url=None,
                 arquivo_indice: str | None = ARQUIVO_INDICE,
                 agora=time.time) -> None:
        self._abrir = abrir_url or self._abrir_url
        # None = sem disco (testes): o índice vale só para esta instância
        self._arquivo = arquivo_indice
        self._agora = agora
        self._pdms: list[dict] | None = None
        # Itens por PDM e sugestões por descrição, em memória: a pesquisa
        # de uma planilha repete PDMs (dez canetas, vinte papéis) e a
        # mesma descrição volta a cada retomada.
        self._itens_do_pdm: dict[str, list[dict]] = {}
        self._sugestoes: dict[str, list[Candidato]] = {}
        self._trava = threading.Lock()

    @staticmethod
    def _abrir_url(url: str) -> str:
        requisicao = urllib.request.Request(
            url, headers={"Accept": "application/json",
                          "User-Agent": "GovDocs/pesquisa-precos"})
        with urllib.request.urlopen(requisicao, timeout=TIMEOUT_S) as resposta:
            return resposta.read().decode("utf-8")

    def _obter(self, caminho: str, parametros: dict) -> dict:
        url = f"{BASE}{caminho}?{urllib.parse.urlencode(parametros)}"
        try:
            return json.loads(self._abrir(url))
        except Exception as exc:  # noqa: BLE001 — vira mensagem, não stack
            raise ErroCatalogo(
                f"o catálogo de materiais não respondeu ({type(exc).__name__})"
            ) from None

    # ------------------------------------------------------------------
    # índice de PDMs
    # ------------------------------------------------------------------
    def pdms(self) -> list[dict]:
        if self._pdms is not None:
            return self._pdms
        with self._trava:
            if self._pdms is None:
                self._pdms = self._carregar_pdms()
        return self._pdms

    def _carregar_pdms(self) -> list[dict]:
        try:
            if not self._arquivo:
                raise OSError("sem índice em disco")
            with open(self._arquivo, encoding="utf-8") as arquivo:
                guardado = json.load(arquivo)
            if self._agora() - guardado["gerado_em"] < VALIDADE_INDICE_S:
                return guardado["pdms"]
        except (OSError, ValueError, KeyError):
            pass
        pdms: list[dict] = []
        pagina, total_paginas = 1, 1
        while pagina <= total_paginas:
            dados = self._obter("/3_consultarPdmMaterial", {
                "pagina": pagina, "tamanhoPagina": PAGINA_PDM,
                "statusPdm": "true"})
            total_paginas = int(dados.get("totalPaginas") or 0)
            for bruto in dados.get("resultado") or []:
                pdms.append({"codigo": str(bruto.get("codigoPdm")),
                             "nome": str(bruto.get("nomePdm") or ""),
                             "classe": str(bruto.get("nomeClasse") or "")})
            pagina += 1
        if not pdms:
            raise ErroCatalogo("o catálogo devolveu a lista de PDMs vazia")
        if self._arquivo:
            try:
                with open(self._arquivo, "w", encoding="utf-8") as arquivo:
                    json.dump({"gerado_em": self._agora(), "pdms": pdms},
                              arquivo)
            except OSError:
                pass   # sem disco gravável, o índice vale só neste processo
        return pdms

    def _itens(self, codigo_pdm: str) -> list[dict]:
        if codigo_pdm not in self._itens_do_pdm:
            dados = self._obter("/4_consultarItemMaterial", {
                "pagina": 1, "tamanhoPagina": PAGINA_PDM,
                "codigoPdm": codigo_pdm, "statusItem": "true"})
            self._itens_do_pdm[codigo_pdm] = dados.get("resultado") or []
        return self._itens_do_pdm[codigo_pdm]

    # ------------------------------------------------------------------
    # sugestão
    # ------------------------------------------------------------------
    def sugerir(self, descricao: str) -> list[Candidato]:
        """Até `MAX_CANDIDATOS` CATMAT para a descrição, do mais aderente."""
        chave = " ".join(sorted(_termos(descricao)))
        if chave not in self._sugestoes:
            self._sugestoes[chave] = self._sugerir(descricao)
        return list(self._sugestoes[chave])

    def _ranquear_pdms(self, descricao: str) -> list[tuple[float, bool, dict]]:
        """(pontuação, mesmo substantivo, pdm), do mais provável ao menos."""
        termos = _termos(descricao)
        if not termos:
            return []
        primeira = _primeira_palavra(descricao)
        radicais = {t[:6] for t in termos if len(t) >= 6}
        ranqueados = []
        for pdm in self.pdms():
            nome = _termos(pdm["nome"])
            if not nome or not (nome & termos):
                continue
            # o nome do PDM é curto e específico: pesa quanto DELE está
            # na descrição, e o substantivo inicial decide empates
            # ("CANETA esferográfica…" contra "CARTUCHO caneta…")
            # radical de 6 letras também conta: "formato" A4 é o PDM
            # "PAPEL PARA IMPRESSÃO FORMATADO", não "papel impressão livro"
            comuns = sum(1 for n in nome if n in termos or (
                len(n) >= 6 and n[:6] in radicais))
            casa = comuns / len(nome)
            mesmo = bool(primeira) and primeira == _primeira_palavra(pdm["nome"])
            # mais termos em comum vence; cobertura e substantivo desempatam
            ranqueados.append((comuns + casa + (0.5 if mesmo else 0), mesmo, pdm))
        ranqueados.sort(key=lambda t: (-t[0], t[2]["nome"]))
        return ranqueados

    def pdms_para(self, descricao: str, limite: int = 2) -> list[dict]:
        """
        Os grupos do catálogo (PDM) que a descrição descreve.

        Só entra PDM com o MESMO substantivo da descrição: "CLIPES… em
        arame de aço" é CLIPE, não ARAME — e preço de arame por quilo
        num item de clipes é o tipo de erro que a cesta não pode ter.
        """
        return [pdm for _, mesmo, pdm in self._ranquear_pdms(descricao)
                if mesmo][:limite]

    def _sugerir(self, descricao: str) -> list[Candidato]:
        termos = _termos(descricao)
        if not termos:
            return []
        candidatos: list[Candidato] = []
        for _, _, pdm in self._ranquear_pdms(descricao)[:MAX_PDMS]:
            for bruto in self._itens(pdm["codigo"]):
                texto = str(bruto.get("descricaoItem") or "")
                do_item = _termos(texto)
                if not do_item:
                    continue
                aderencia = len(termos & do_item) / len(termos)
                candidatos.append(Candidato(
                    codigo=str(bruto.get("codigoItem")), descricao=texto,
                    pdm=pdm["nome"], classe=pdm["classe"],
                    aderencia=round(aderencia, 3)))
        candidatos.sort(key=lambda c: (-c.aderencia, c.codigo))
        vistos, unicos = set(), []
        for candidato in candidatos:
            if candidato.codigo not in vistos:
                vistos.add(candidato.codigo)
                unicos.append(candidato)
        return unicos[:MAX_CANDIDATOS]


@lru_cache(maxsize=1)
def padrao() -> Catalogo:
    """O catálogo do processo: um índice compartilhado por todas as buscas."""
    return Catalogo()


def _termos(texto: str) -> set[str]:
    """
    Os termos de `_tokens` e mais os curtos COM dígito (A4, 75, 2B).

    `_tokens` descarta palavras de até 2 letras para não casar com
    qualquer coisa — e com isso "A4" sumia, e o papel A4 virava papel
    almaço. Tamanho e formato são justamente o que separa um CATMAT do
    vizinho.
    """
    curtos = {p.strip(".:,;") for p in _sem_acento(texto).split()
              if len(p.strip(".:,;")) <= 2
              and any(ch.isdigit() for ch in p)}
    return {_singular(t) for t in _tokens(texto)} | {c for c in curtos if c}


def _singular(palavra: str) -> str:
    """
    Plural regular em -S, dos dois lados da comparação.

    O catálogo nomeia no singular (CLIPE, PASTA); a planilha escreve no
    plural ("CLIPES METÁLICOS"). Grosseiro de propósito — e aplicado
    igual à descrição e ao catálogo, então "LÁPIS"→"LAPI" casa com
    "LAPI" do outro lado.
    """
    if len(palavra) > 4 and palavra.endswith(("OES", "AES")):
        return palavra[:-3] + "AO"          # BALÕES → BALAO (sem acento)
    return palavra[:-1] if len(palavra) > 4 and palavra.endswith("S") else palavra


def _primeira_palavra(texto: str) -> str:
    palavras = _sem_acento(texto).replace(",", " ").split()
    return _singular(palavras[0].strip(".:")) if palavras else ""
