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
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

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
    def __init__(self, abrir_url=None, arquivo_indice: str = ARQUIVO_INDICE,
                 agora=time.time) -> None:
        self._abrir = abrir_url or self._abrir_url
        self._arquivo = arquivo_indice
        self._agora = agora
        self._pdms: list[dict] | None = None

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
        try:
            with open(self._arquivo, encoding="utf-8") as arquivo:
                guardado = json.load(arquivo)
            if self._agora() - guardado["gerado_em"] < VALIDADE_INDICE_S:
                self._pdms = guardado["pdms"]
                return self._pdms
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
        try:
            with open(self._arquivo, "w", encoding="utf-8") as arquivo:
                json.dump({"gerado_em": self._agora(), "pdms": pdms}, arquivo)
        except OSError:
            pass   # sem disco gravável, o índice vale só para este processo
        self._pdms = pdms
        return pdms

    # ------------------------------------------------------------------
    # sugestão
    # ------------------------------------------------------------------
    def sugerir(self, descricao: str) -> list[Candidato]:
        """Até `MAX_CANDIDATOS` CATMAT para a descrição, do mais aderente."""
        termos = _termos(descricao)
        if not termos:
            return []
        primeira = _primeira_palavra(descricao)
        ranqueados = []
        for pdm in self.pdms():
            nome = _tokens(pdm["nome"])
            if not nome or not (nome & termos):
                continue
            # o nome do PDM é curto e específico: pesa quanto DELE está
            # na descrição, e o substantivo inicial decide empates
            # ("CANETA esferográfica…" contra "CARTUCHO caneta…")
            comuns = len(nome & termos)
            casa = comuns / len(nome)
            bonus = 0.5 if primeira and primeira == _primeira_palavra(pdm["nome"]) else 0
            # mais termos em comum vence; cobertura e substantivo desempatam
            ranqueados.append((comuns + casa + bonus, pdm))
        ranqueados.sort(key=lambda par: (-par[0], par[1]["nome"]))

        candidatos: list[Candidato] = []
        for _, pdm in ranqueados[:MAX_PDMS]:
            dados = self._obter("/4_consultarItemMaterial", {
                "pagina": 1, "tamanhoPagina": PAGINA_PDM,
                "codigoPdm": pdm["codigo"], "statusItem": "true"})
            for bruto in dados.get("resultado") or []:
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
    return _tokens(texto) | {c for c in curtos if c}


def _primeira_palavra(texto: str) -> str:
    palavras = _sem_acento(texto).replace(",", " ").split()
    return palavras[0].strip(".:") if palavras else ""
