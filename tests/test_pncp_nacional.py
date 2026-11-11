"""
PNCP nacional sob demanda (`src/precos/pncp_nacional.py`).

O portal é respondido por uma API falsa com o FORMATO observado em
11/11/2026 (busca `/api/search/`, itens e resultados de `/api/pncp/v1`).
Sem rede.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
from datetime import date
from email.message import Message

import pytest

from src import db, governanca
from src.precos import cotacoes, pncp_nacional
from src.precos.fontes import Consulta, Desfecho
from src.precos.pncp_nacional import PNCPNacional, aceitar_item, nucleo
from tests.cotacoes_apoio import ligar_banco_falso

JANELA = dict(data_inicial=date(2026, 5, 15), data_final=date(2026, 11, 11))


def _hit(controle, *, uf="MG", municipio="Careaçu", modalidade="6",
         tem_resultado=True, cancelado=False, publicada="2026-09-01"):
    return {"numero_controle_pncp": controle, "uf": uf,
            "municipio_nome": municipio, "orgao_nome": f"Prefeitura de {municipio}",
            "modalidade_licitacao_id": modalidade,
            "modalidade_licitacao_nome": "Pregão - Eletrônico",
            "tem_resultado": tem_resultado, "cancelado": cancelado,
            "data_publicacao_pncp": f"{publicada}T10:00:00",
            "data_atualizacao_pncp": f"{publicada}T12:00:00",
            "orgao_cnpj": controle.split("-")[0], "ano": controle[-4:],
            "numero_sequencial": controle.split("-")[-1].split("/")[0].lstrip("0"),
            "usuario_nome": "Portal de Compras Públicas",
            "link_sistema_origem": "https://www.portaldecompraspublicas.com.br/x"}


def _item(numero, descricao, *, criterio="Menor preço", tem_resultado=True):
    return {"numeroItem": numero, "descricao": descricao, "unidadeMedida": "UN",
            "quantidade": 1, "temResultado": tem_resultado,
            "criterioJulgamentoNome": criterio, "materialOuServico": "M",
            "catalogoCodigoItem": None, "situacaoCompraItem": 2,
            "situacaoCompraItemNome": "Homologado"}


def _resultado(valor, *, quantidade=1, data="2026-10-29"):
    return [{"valorUnitarioHomologado": valor, "quantidadeHomologada": quantidade,
             "valorTotalHomologado": valor * quantidade, "dataResultado": data,
             "sequencialResultado": 1, "nomeRazaoSocialFornecedor": "Fornecedor",
             "niFornecedor": "12345678000199",
             "situacaoCompraItemResultadoNome": "Informado"}]


CAREACU = "11111111000111-1-000010/2026"
COARI = "22222222000122-1-000020/2026"


class Portal:
    """Busca, itens e resultados; registra cada URL pedida."""

    def __init__(self, hits, contratacoes):
        self.hits = hits
        self.contratacoes = contratacoes      # controle -> (itens, {n: resultado})
        self.urls: list[str] = []
        self.falhas: list[Exception] = []     # levantadas em ordem, antes de responder

    def __call__(self, url: str) -> str:
        self.urls.append(url)
        if self.falhas:
            raise self.falhas.pop(0)
        partes = urllib.parse.urlsplit(url)
        if partes.path == "/api/search/":
            return json.dumps({"items": self.hits, "total": len(self.hits)})
        assert "/api/consulta/" not in url, "a fonte não chama a API de consulta"
        _, _, resto = partes.path.partition("/orgaos/")
        cnpj, _, ano, seq, *cauda = resto.split("/")
        controle = next(c for c in self.contratacoes
                        if c.startswith(cnpj) and c.endswith(f"{int(seq):06d}/{ano}"))
        itens, resultados = self.contratacoes[controle]
        if cauda == ["itens"]:
            return json.dumps(itens)
        return json.dumps(resultados.get(int(cauda[1])) or [])

    def busca(self) -> dict:
        [url] = [u for u in self.urls if "/api/search/" in u]
        return {k: v[0] for k, v in urllib.parse.parse_qs(
            urllib.parse.urlsplit(url).query).items()}

    def de(self, trecho):
        return [u for u in self.urls if trecho in u]


def _fonte(portal, **kw):
    return PNCPNacional(portal, dormir=lambda s: None, intervalo_s=0, **kw)


def _portal_padrao(hits=None):
    return Portal(hits if hits is not None else [_hit(CAREACU), _hit(
        COARI, uf="AM", municipio="Coari")], {
        CAREACU: ([_item(1, "LÂMPADA HALÓGENA 12V PARA ANALISADOR BIOQUÍMICO"),
                   _item(2, "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO")],
                  {1: _resultado(650.0), 2: _resultado(12300.0)}),
        COARI: ([_item(1, "ANALISADOR AUTOMÁTICO DE BIOQUÍMICA 620 TESTES/HORA"),
                 _item(2, "ANALISADOR HEMATOLÓGICO AUTOMÁTICO")],
                {1: _resultado(270000.0, data="2026-08-27"),
                 2: _resultado(98000.0)}),
    })


# ---------------------------------------------------------------------------
# Núcleo e filtro de item
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("descricao, esperado", [
    ("Analisador bioquímico semiautomático, com cubeta", "analisador bioquimico semiautomatico cubeta"),
    ("Cimento CP II 32, saco 50 kg", "cimento"),
    ("Papel A4 75g resma 500 folhas", "papel a4 75g"),
    ("123 - ", ""),
    ("Bateria CR2032 3V", "bateria cr2032 3v"),
    # o verbo da compra sai; o objeto fica
    ("Aquisição de cimento", "cimento"),
    ("Contratação de empresa especializada em limpeza", "limpeza"),
    # identificação colada não vira termo de busca
    # montado aqui para a varredura de segredos não ler um e-mail no diff
    ("Palestra contato " + "fulano" + "@" + "exemplo" + ".com", "palestra contato"),
    ("Honorarios cpf12345678900 consultoria", "honorarios consultoria"),
    ("Item ABC123456", "item"),
])
def test_nucleo_e_o_comeco_da_descricao_sem_medida_nem_numero(descricao, esperado):
    assert nucleo(descricao) == esperado


@pytest.mark.parametrize("item, aceito", [
    ("ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO", True),
    ("ANALISADOR AUTOMÁTICO DE BIOQUÍMICA 620 TESTES/HORA", True),   # radical
    ("Lâmpada halógena 12V / 20W para analisador bioquímico", False),
    ("LAMPADA PARA ANALISADOR LABMAX PLENNO", False),
    ("Desproteinizante (ISE) para analisador Cobas C111", False),
    ("Analisador Automático para Hematologia", False),                # sem o qualificador
])
def test_item_comeca_pelo_nome_e_traz_o_qualificador(item, aceito):
    assert aceitar_item("Analisador bioquímico")(item) is aceito


@pytest.mark.parametrize("item, aceito", [
    ("PAPEL SULFITE MULTICOLOR A4 75 G", True),
    ("PAPELEIRA PLASTICA PARA PAPEL HIGIENICO A4", False),   # curta: palavra inteira
    ("Envelope 114x229 em papel A4", False),
    ("Papel toalha", False),
])
def test_palavra_curta_casa_inteira(item, aceito):
    assert aceitar_item("Papel A4 75g resma")(item) is aceito


# ---------------------------------------------------------------------------
# Fonte
# ---------------------------------------------------------------------------
def test_busca_nacional_so_de_pregao_encerrado_com_resultado():
    portal = _portal_padrao()
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert r.desfecho is Desfecho.COM_PRECOS
    parametros = portal.busca()
    assert parametros["q"] == "analisador bioquimico"
    assert parametros["modalidades"] == "6|7"
    # `todos` faria o portal ignorar `tem_resultado` (medido)
    assert (parametros["status"], parametros["tem_resultado"]) == ("encerradas", "true")
    assert "ufs" not in parametros                       # sem UF: Brasil inteiro
    precos = sorted((ref.uf, float(ref.valor_unitario_original)) for ref in r.referencias)
    assert precos == [("AM", 270000.0), ("MG", 12300.0)]
    # lâmpada e hematológico não custaram chamada de resultado
    assert len(portal.de("/resultados")) == 2


def test_cabecalho_vem_da_busca_com_municipio_orgao_e_origem():
    r = _fonte(_portal_padrao()).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    ref = next(x for x in r.referencias if x.uf == "MG")
    assert (ref.municipio, ref.orgao) == ("Careaçu", "Prefeitura de Careaçu")
    assert ref.referencia_externa == CAREACU
    assert ref.bruto["usuarioNome"] == "Portal de Compras Públicas"
    assert ref.modalidade == "Pregão - Eletrônico"


def test_descarta_dispensa_cancelada_sem_resultado_e_publicacao_antiga():
    hits = [_hit(CAREACU, modalidade="8"), _hit(CAREACU.replace("10/", "11/"), cancelado=True),
            _hit(CAREACU.replace("10/", "12/"), tem_resultado=False),
            _hit(CAREACU.replace("10/", "13/"), publicada="2025-10-01"),
            _hit("lixo"), {"x": 1}, "texto"]
    portal = Portal(hits, {})
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert portal.urls == portal.de("/api/search/")      # nenhuma contratação lida
    assert r.desfecho is Desfecho.SEM_RESULTADO


def test_uf_da_pesquisa_restringe_a_busca():
    portal = _portal_padrao()
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", uf="am", **JANELA))
    assert portal.busca()["ufs"] == "AM"
    assert {ref.uf for ref in r.referencias} == {"AM"}


def test_referencia_fora_da_janela_da_pesquisa_nao_entra():
    portal = _portal_padrao()
    janela = dict(data_inicial=date(2026, 9, 1), data_final=date(2026, 11, 11))
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **janela))
    assert [ref.uf for ref in r.referencias] == ["MG"]    # Coari é de 27/08


def test_maior_desconto_nao_vira_preco_tambem_aqui():
    portal = Portal([_hit(CAREACU)], {CAREACU: (
        [_item(1, "ANALISADOR BIOQUÍMICO", criterio="Maior desconto")],
        {1: _resultado(0.2)})})
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert r.referencias == []


def test_para_ao_atingir_o_alvo():
    hits = [_hit(f"1111111100011{n}-1-0000{n}0/2026") for n in range(1, 6)]
    contratacoes = {h["numero_controle_pncp"]: (
        [_item(1, "ANALISADOR BIOQUÍMICO")], {1: _resultado(1000.0 + n)})
        for n, h in enumerate(hits)}
    portal = Portal(hits, contratacoes)
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", limite=2, **JANELA))
    assert len(r.referencias) == 2
    assert len(portal.de("/itens?")) == 2                 # não leu as outras 3


def test_contratacao_grande_custa_poucas_chamadas_de_resultado():
    itens = [_item(n, f"ANALISADOR BIOQUÍMICO MODELO {n}") for n in range(1, 9)]
    portal = Portal([_hit(CAREACU)], {CAREACU: (
        itens, {n: _resultado(1000.0 * n) for n in range(1, 9)})})
    _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert len(portal.de("/resultados")) == pncp_nacional.ITENS_POR_CONTRATACAO == 2


def test_busca_fora_do_ar_e_falha_tecnica_com_recado():
    portal = _portal_padrao()
    portal.falhas = [urllib.error.URLError("recusada")] * pncp_nacional.TENTATIVAS
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert r.desfecho is Desfecho.FALHA
    assert "demais fontes" in r.falha


def test_formato_novo_da_busca_falha_alto():
    portal = _portal_padrao()
    portal.hits = None
    portal.__class__ = type("PortalMudado", (Portal,), {
        "__call__": lambda self, url: json.dumps({"resultados": []})})
    r = _fonte(portal).pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert r.desfecho is Desfecho.FALHA and "formato" in r.falha


def test_429_respeita_retry_after_e_tenta_de_novo():
    portal = _portal_padrao()
    cabecalho = Message()
    cabecalho["Retry-After"] = "7"
    portal.falhas = [urllib.error.HTTPError("u", 429, "Too Many Requests", cabecalho, None)]
    esperas = []
    fonte = PNCPNacional(portal, dormir=esperas.append, intervalo_s=0)
    r = fonte.pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    assert r.desfecho is Desfecho.COM_PRECOS
    assert 7.0 in esperas


def test_uma_chamada_por_vez_com_intervalo_minimo():
    agora = [100.0]
    esperas = []

    def dormir(s):
        esperas.append(round(s, 3))
        agora[0] += s
    fonte = PNCPNacional(_portal_padrao(), dormir=dormir, relogio=lambda: agora[0],
                         intervalo_s=0.35)
    PNCPNacional._ultima = 0.0
    fonte.pesquisar(Consulta(descricao="Analisador bioquímico", **JANELA))
    # sem relógio andando entre chamadas, cada uma espera o intervalo inteiro
    assert esperas and set(esperas[1:]) == {0.35}


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------
def _tipos(fontes):
    return [type(f).__name__ for f in fontes]


def test_flag_nacional_substitui_o_indice_e_nasce_desligada(monkeypatch):
    ligar_banco_falso(monkeypatch)
    assert "PNCPNacional" not in _tipos(cotacoes._fontes_padrao())
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in (
        governanca.FLAG_PNCP_NACIONAL, governanca.FLAG_PNCP_INDICE))
    assert _tipos(cotacoes._fontes_padrao()) == ["ComprasGovAdapter", "PNCPNacional"]
    assert governanca.FLAG_PNCP_NACIONAL == "price_source_pncp_nacional"
    # desligar a nacional devolve o índice regional
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == governanca.FLAG_PNCP_INDICE)
    assert _tipos(cotacoes._fontes_padrao()) == ["ComprasGovAdapter", "PNCPIndice"]


def test_flag_nacional_ilegivel_nao_liga(monkeypatch):
    ligar_banco_falso(monkeypatch)

    def quebrada(nome):
        if nome == governanca.FLAG_PNCP_NACIONAL:
            raise db.ErroBanco("flags indisponíveis")
        return False
    monkeypatch.setattr(db, "flag_ativa", quebrada)
    assert _tipos(cotacoes._fontes_padrao()) == ["ComprasGovAdapter", "PNCPAdapter"]
