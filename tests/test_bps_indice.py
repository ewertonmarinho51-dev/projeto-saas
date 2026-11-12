"""
BPS (Banco de Preços em Saúde) como fonte de preço — 11/11/2026.

Linhas REAIS do arquivo oficial (`fixtures/fontes_precos/bps_2026.csv`) e
respostas REAIS da API oficial para os mesmos CATMATs
(`fixtures/fontes_precos/bps_api_2026-11-11.json`). Nenhuma chamada de rede.

O que estas provas guardam:

* a linha do arquivo é achada na resposta oficial do seu CATMAT com preço,
  quantidade, data, instituição e fornecedor iguais — é o que autoriza a
  consulta oficial como evidência verificável;
* a importação é idempotente e por VERSÃO validada: o mesmo arquivo não é
  relido; retificação do ano é versão nova, publicada inteira; arquivo que
  encolheu demais ou mistura anos é recusado e a versão anterior continua;
* a identidade da compra não depende do `co_seq_bps`, que o Ministério
  refaz a cada publicação;
* a busca compara CATMAT, apresentação e unidade de fornecimento: com
  código, só o código; sem ele, o nome do medicamento tem de estar no item;
* só compra pública, preço pago, sem ordem judicial;
* a fonte nasce desligada, e só a flag não a liga: falta a licença.
"""

from __future__ import annotations

import csv
import io
import json
import urllib.error
import urllib.parse
import zipfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src import db
from src.precos import (bps, busca, cotacoes, estatistica, etl_bps,
                        fontes_externas, links, unidades)
from src.precos import evidencia as ev
from src.precos import repositorio as repo
from src.precos.fontes import Consulta, Desfecho
from src.precos.modelo import NaturezaValor
from tests.cotacoes_apoio import ligar_banco_falso

FIX = Path(__file__).parent / "fixtures" / "fontes_precos"
URL = fontes_externas.REGISTRO["bps"].downloads[0]
API = json.loads((FIX / "bps_api_2026-11-11.json").read_text("utf-8"),
                 parse_float=Decimal)["respostas"]
CABECALHO, *LINHAS = list(csv.reader(
    (FIX / "bps_2026.csv").read_text("utf-8-sig").splitlines(), delimiter=";"))
COL = {nome: i for i, nome in enumerate(CABECALHO)}


def _zip(tmp_path, nome, linhas=LINHAS, mudancas=None) -> Path:
    """Um `2026_csv.zip` com as linhas reais, opcionalmente alteradas:
    `mudancas` = {índice da linha: {coluna: valor}}."""
    linhas = [list(l) for l in linhas]
    for indice, campos in (mudancas or {}).items():
        for coluna, valor in campos.items():
            linhas[indice][COL[coluna]] = valor
    texto = io.StringIO()
    escritor = csv.writer(texto, delimiter=";", lineterminator="\n")
    escritor.writerow(CABECALHO)
    escritor.writerows(linhas)
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("2026.csv", "﻿" + texto.getvalue())
    return caminho


def _api(chamadas=None, quebra=None, pagina=200):
    def abrir(url):
        if chamadas is not None:
            chamadas.append(url)
        q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        catmat = q["codigoCatmat"][0]
        if quebra == catmat:
            raise urllib.error.URLError("fora")
        registros = API.get(catmat, [])
        inicio = int(q["offset"][0])
        return json.dumps({"bps": registros[inicio:inicio + pagina]},
                          default=str).replace('"precoUnitario": "', '"precoUnitario": ') \
            if False else _cru(registros[inicio:inicio + int(q["limit"][0])])
    return abrir


def _cru(registros) -> str:
    """JSON como a API escreve: número sem aspas, com o texto original."""
    return json.dumps({"bps": registros},
                      default=lambda v: float(v)).replace("NaN", "null")


def _evidencias(caminho):
    return list(etl_bps.ler(caminho, url_snapshot=URL, sha256="s" * 64))


@pytest.fixture
def arquivo(tmp_path):
    return _zip(tmp_path, "2026_csv.zip")


@pytest.fixture
def armazem(arquivo):
    a = bps.ArmazemEmMemoria()
    assert bps.importar(a, arquivo, url=URL).desfecho == bps.PUBLICADO
    return a


# ---------------------------------------------------------------------------
# Confronto com a API oficial
# ---------------------------------------------------------------------------
def test_linhas_do_arquivo_aparecem_na_resposta_oficial_do_catmat(arquivo):
    chamadas: list[str] = []
    validas = bps.amostra(_evidencias(arquivo), 60)
    confronto = bps.confrontar(validas, abrir_url=_api(chamadas))
    assert (confronto.conferidas, confronto.achadas) == (3, 3)
    assert confronto.nao_achadas == [] and confronto.falhas == []
    assert confronto.catmats == 3 and len(chamadas) == 3
    assert all(u.startswith(etl_bps.URL_API + "?codigoCatmat=") for u in chamadas)


@pytest.mark.parametrize("mudanca", [
    {"vl_preco_unitario": "5029.74"}, {"qt_medicamento": "724"},
    {"dt_compra": "10/01/2026"}, {"cnpj_fornecedor": "00000000000191"},
    {"cnpj_instituicao": "00000000000191"},
])
def test_linha_que_difere_da_api_e_denunciada(tmp_path, mudanca):
    alterado = _zip(tmp_path, "x.zip", mudancas={
        0: {**mudanca, "vl_preco_total": ""}})
    confronto = bps.confrontar(bps.amostra(_evidencias(alterado), 60),
                               abrir_url=_api())
    assert confronto.achadas == 2
    assert [n["catmat"] for n in confronto.nao_achadas] == ["446467"]


def test_api_fora_do_ar_e_falha_do_confronto_nao_divergencia(arquivo):
    confronto = bps.confrontar(bps.amostra(_evidencias(arquivo), 60),
                               abrir_url=_api(quebra="446467"))
    assert confronto.conferidas == 2 and confronto.achadas == 2
    assert confronto.nao_achadas == [] and len(confronto.falhas) == 1


def test_consulta_a_api_pagina_e_guarda_o_texto_do_numero(monkeypatch):
    monkeypatch.setattr(bps, "PAGINA_API", 2)
    chamadas: list[str] = []
    registros = bps.consultar_api("267077", abrir_url=_api(chamadas))
    assert len(registros) == len(API["267077"]) == 5
    assert [urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)["offset"]
            for u in chamadas] == [["0"], ["2"], ["4"]]
    assert Decimal("1.0393") in {r["precoUnitario"] for r in registros}
    assert all(isinstance(r["precoUnitario"], Decimal) for r in registros)
    with pytest.raises(ValueError):
        bps.consultar_api("446467&x=1", abrir_url=_api())


# ---------------------------------------------------------------------------
# Importação por versão
# ---------------------------------------------------------------------------
def test_importacao_publica_so_o_que_e_compra_publica_valida(arquivo):
    a = bps.ArmazemEmMemoria()
    feito = bps.importar(a, arquivo, url=URL, last_modified="hoje")
    assert (feito.desfecho, feito.ano, feito.linhas, feito.validas) == (
        bps.PUBLICADO, 2026, 5, 3)
    assert feito.quarentena == {ev.COMPRA_JUDICIAL: 2, ev.MODALIDADE_FORA: 1}
    versao = a.versao_publicada(2026)
    assert versao["sha256"] == feito.sha256 and versao["validas"] == 3
    assert versao["url"] == URL and versao["versao_parser"] == etl_bps.VERSAO_PARSER
    [linha] = [l for l in a.registros.values() if l["catmat"] == "446467"]
    # CATMAT, apresentação e unidade de fornecimento, como a fonte deu
    assert (linha["unidade"], linha["apresentacao"]) == ("FRASCO", "FRASCO 1,00 ML")
    assert Decimal(linha["valor_unitario"]) == Decimal("5029.73")
    assert (linha["esfera"], linha["uf"], linha["data_compra"]) == (
        "ESTADUAL", "SP", "2026-01-09")
    # origem oficial, versão do arquivo e chave da linha
    assert linha["url_evidencia"].endswith("codigoCatmat=446467")
    assert linha["url_arquivo"] == URL
    assert linha["arquivo_sha256"] == feito.sha256
    assert linha["co_seq_bps"] == "27507687"
    assert linha["registro_id"].startswith("bps-") and len(linha["hash_linha"]) == 64


def test_mesmo_arquivo_nao_e_importado_de_novo(arquivo):
    a = bps.ArmazemEmMemoria()
    bps.importar(a, arquivo, url=URL)
    gravacoes = []
    a.gravar_registros = lambda linhas: gravacoes.append(len(linhas))
    assert bps.importar(a, arquivo, url=URL).desfecho == "ja_publicado"
    assert gravacoes == [] and len(a.versoes) == 1


def test_retificacao_do_mesmo_ano_e_versao_nova_e_a_chave_nao_muda(
        tmp_path, armazem):
    antes = {l["catmat"]: l for l in armazem.registros.values()}
    # o Ministério republica: números de linha novos, um preço retificado
    retificado = _zip(tmp_path, "novo.zip", mudancas={
        0: {"co_seq_bps": "33224771"},
        1: {"co_seq_bps": "33224772"},
        2: {"co_seq_bps": "33224773", "vl_preco_unitario": "1.05",
            "vl_preco_total": "7560.0"}})
    feito = bps.importar(armazem, retificado, url=URL)
    assert feito.desfecho == bps.PUBLICADO and len(armazem.versoes) == 2
    assert armazem.versao_publicada(2026)["sha256"] == feito.sha256
    assert feito.validas_na_versao_anterior == 3
    fonte = bps.BPSIndice(armazem.buscar)
    # mesma compra, mesma chave — só o número da linha mudou
    [pali] = fonte.pesquisar(Consulta(descricao="x", codigo_catalogo="446467",
                                      tipo_catalogo="CATMAT")).referencias
    assert pali.id_externo == antes["446467"]["registro_id"]
    assert pali.referencia_externa == "BPS 33224771"
    assert pali.bruto["arquivo_sha256"] == feito.sha256
    # o preço retificado é outra observação; a antiga saiu da busca
    [beza] = fonte.pesquisar(Consulta(descricao="x", codigo_catalogo="267077",
                                      tipo_catalogo="CATMAT")).referencias
    assert beza.valor_unitario_original == Decimal("1.05")
    assert beza.id_externo != antes["267077"]["registro_id"]
    assert antes["267077"]["registro_id"] in armazem.registros   # nada apagado


@pytest.mark.parametrize("linhas, mudancas, motivo", [
    (LINHAS[:1] + LINHAS[3:], None, "redução acima do tolerado"),
    (LINHAS, {0: {"ano_compra": "2025"}}, "mistura anos"),
    (LINHAS[3:], None, "sem linha válida"),
])
def test_arquivo_que_nao_passa_na_validacao_nao_e_publicado(
        tmp_path, armazem, linhas, mudancas, motivo):
    vigente = armazem.versao_publicada(2026)["sha256"]
    feito = bps.importar(armazem, _zip(tmp_path, "ruim.zip", linhas, mudancas),
                         url=URL)
    assert feito.desfecho == bps.RECUSADO and motivo in feito.motivo
    assert armazem.versao_publicada(2026)["sha256"] == vigente
    achadas = bps.BPSIndice(armazem.buscar).pesquisar(Consulta(
        descricao="x", codigo_catalogo="267077")).referencias
    assert len(achadas) == 1                     # a versão anterior continua


def test_arquivo_so_do_endereco_oficial(arquivo):
    with pytest.raises(ValueError, match="oficial"):
        bps.importar(bps.ArmazemEmMemoria(), arquivo,
                     url="https://exemplo.com/2026_csv.zip")


def test_linhas_identicas_sao_a_mesma_compra(tmp_path):
    a = bps.ArmazemEmMemoria()
    feito = bps.importar(a, _zip(tmp_path, "dup.zip", LINHAS + LINHAS[:1],
                                 {5: {"co_seq_bps": "99999999"}}), url=URL)
    assert (feito.validas, feito.duplicadas) == (3, 1)


# ---------------------------------------------------------------------------
# Busca — CATMAT, apresentação e unidade de fornecimento
# ---------------------------------------------------------------------------
def test_com_catmat_a_busca_e_so_pelo_codigo(armazem):
    chamadas = []

    def espia(termos, **kw):
        chamadas.append((termos, kw["catmat"]))
        return armazem.buscar(termos, **kw)

    resultado = bps.BPSIndice(espia).pesquisar(Consulta(
        descricao="SOLUÇÃO INJETÁVEL CONCENTRAÇÃO 100 MG/ML FRASCO",
        codigo_catalogo="446467", tipo_catalogo="CATMAT"))
    assert chamadas == [([], "446467")]          # sem termos: só a identidade
    [ref] = resultado.referencias
    assert resultado.desfecho is Desfecho.COM_PRECOS and resultado.codigo_confirmado
    assert ref.fonte.id == "bps" and ref.natureza_valor is NaturezaValor.PRATICADO
    assert (ref.codigo_catalogo, ref.tipo_catalogo) == ("446467", "CATMAT")
    assert ref.valor_unitario_original == Decimal("5029.73")
    assert ref.unidade_original == "FRASCO" and ref.quantidade_original == 723
    assert ref.data_compra == date(2026, 1, 9) and ref.uf == "SP"
    assert ref.bruto["compra_publica"] is True and ref.bruto["esfera"] == "ESTADUAL"
    # o que o revisor compara fica à vista na referência
    assert any("CATMAT 446467" in m and "FRASCO 1,00 ML" in m
               and "compra pública (estadual)" in m for m in ref.motivos)
    assert bps.url_de_verificacao(ref.bruto) == (
        "https://apidadosabertos.saude.gov.br/economia-da-saude/bps"
        "?codigoCatmat=446467")


def test_codigo_que_o_bps_nao_conhece_cai_na_descricao(armazem):
    resultado = bps.BPSIndice(armazem.buscar).pesquisar(Consulta(
        descricao="BEZAFIBRATO 200 MG COMPRIMIDO", codigo_catalogo="123456"))
    assert resultado.chamadas == 2 and not resultado.codigo_confirmado
    assert [r.codigo_catalogo for r in resultado.referencias] == ["267077"]


def test_sem_codigo_o_nome_do_medicamento_tem_de_estar_no_item(armazem):
    fonte = bps.BPSIndice(armazem.buscar)
    [beza] = fonte.pesquisar(Consulta(
        descricao="Bezafibrato 200mg comprimido")).referencias
    assert beza.unidade_original == "COMPRIMIDO"
    # palavras de catálogo que todo injetável compartilha não trazem outro
    # medicamento (era levetiracetam numa busca de palivizumabe)
    assert fonte.pesquisar(Consulta(
        descricao="LEVETIRACETAM CONCENTRAÇÃO 100 MG/ML FORMA FARMACÊUTICA "
                  "SOLUÇÃO INJETÁVEL")).referencias == []
    # associação só casa com item que também a declare
    assert fonte.pesquisar(Consulta(
        descricao="BETAMETASONA SAL DIPROPIONATO SOLUÇÃO TÓPICA")).referencias == []
    [beta] = fonte.pesquisar(Consulta(
        descricao="BETAMETASONA DIPROPIONATO ASSOCIADA AO ÁCIDO SALICÍLICO "
                  "SOLUÇÃO TÓPICA")).referencias
    assert beta.codigo_catalogo == "403991"
    assert fonte.pesquisar(Consulta(descricao="de a")).falha is None


def test_ordem_judicial_e_leilao_nunca_chegam_a_busca(armazem):
    fonte = bps.BPSIndice(armazem.buscar)
    for descricao, catmat in (("SOMATROPINA 6,66 MG/ML", "448765"),
                              ("EVOLOCUMABE 140 MG/ML", "439820")):
        assert fonte.pesquisar(Consulta(descricao=descricao)).referencias == []
        assert fonte.pesquisar(Consulta(
            descricao="x", codigo_catalogo=catmat)).referencias == []


def test_linha_do_indice_sem_compra_publica_nao_vira_referencia(armazem):
    linha = dict(next(iter(armazem.registros.values())))
    assert bps.referencia_da_linha(linha) is not None
    for mudanca in ({"esfera": "PRIVADA"}, {"valor_unitario": "0"},
                    {"valor_unitario": None}, {"registro_id": ""}):
        assert bps.referencia_da_linha({**linha, **mudanca}) is None


def test_entra_no_pipeline_comum_com_a_unidade_de_fornecimento(armazem):
    item = {"id": "x", "numero": 1, "descricao": "BEZAFIBRATO 200 MG",
            "unidade": "COMPRIMIDO", "quantidade": "1000"}
    coleta = busca.coletar(item, [bps.BPSIndice(armazem.buscar)],
                           filtros={"data_base": "2026-11-11"})
    assert not coleta.erro and coleta.desfechos == {"bps": "success_with_prices"}
    [(ref, _)] = coleta.referencias
    assert ref.valor_unitario_normalizado == Decimal("1.0393")
    assert ref.fonte.tipo == "sistema_oficial"       # procedência registrada
    assert coleta.elegiveis(estatistica.PISO_COMPARABILIDADE) == 1
    # comprimido não é cápsula: sem conversão, sem preço na unidade do item
    outro = busca.coletar({**item, "unidade": "CAPSULA"},
                          [bps.BPSIndice(armazem.buscar)],
                          filtros={"data_base": "2026-11-11"})
    assert outro.referencias[0][0].valor_unitario_normalizado is None


@pytest.mark.parametrize("sigla, canonica", [
    ("COMPRIMIDO", "COMPRIMIDO"), ("cápsulas", "CAPSULA"), ("AMPOLA", "AMPOLA"),
    ("FRASCO-AMPOLA", "FRASCO-AMPOLA"), ("Frasco ampola", "FRASCO-AMPOLA"),
    ("BISNAGA", "BISNAGA"), ("SERINGA", "SERINGA"), ("DRÁGEA", "DRAGEA"),
    ("TUBETE", "TUBETE"), ("ENVELOPE", "ENVELOPE"), ("SACHÊ", "SACHE"),
    ("BOLSA", "BOLSA"), ("CP", None), ("FA", None), ("ENV", None),
])
def test_unidades_de_fornecimento_de_medicamento(sigla, canonica):
    assert unidades.canonizar(sigla) == canonica


def test_indice_fora_do_ar_e_falha_da_fonte_nao_da_pesquisa():
    def fora(termos, **kw):
        raise ConnectionError("banco fora")

    fonte = bps.BPSIndice(fora)
    assert fonte.pesquisar(Consulta(descricao="dipirona")).desfecho is Desfecho.FALHA
    assert not fonte.healthcheck()
    assert bps.BPSIndice(lambda t, **kw: "x").pesquisar(
        Consulta(descricao="dipirona")).desfecho is Desfecho.FALHA


def test_link_impresso_e_a_consulta_oficial_e_so_host_oficial(armazem):
    [ref] = bps.BPSIndice(armazem.buscar).pesquisar(Consulta(
        descricao="x", codigo_catalogo="267077")).referencias
    resolvido = links.resolver({"fonte_id": "bps", "bruto": ref.bruto,
                                "referencia_externa": ref.referencia_externa,
                                "orgao": ref.orgao})
    assert resolvido.fonte_url == "https://dadosabertos.saude.gov.br/dataset/bps"
    assert resolvido.contratacao_url == resolvido.dados_url == (
        "https://apidadosabertos.saude.gov.br/economia-da-saude/bps"
        "?codigoCatmat=267077")
    assert resolvido.identificacao == "BPS 27507743"
    # o endereço é remontado do código, nunca copiado do registro
    falso = links.resolver({"fonte_id": "bps", "bruto": {
        **ref.bruto, "catmat": "1&x=https://exemplo.com",
        "url_evidencia": "https://exemplo.com/roubo"}})
    assert falso.contratacao_url is None
    # nem quando o endereço gravado é de host oficial: vale o do CATMAT
    trocado = links.resolver({"fonte_id": "bps", "bruto": {
        **ref.bruto, "url_evidencia":
            "https://apidadosabertos.saude.gov.br/outra-consulta"}})
    assert trocado.contratacao_url.endswith("/bps?codigoCatmat=267077")


# ---------------------------------------------------------------------------
# Habilitação — flag, mapeamento e LICENÇA
# ---------------------------------------------------------------------------
def _tipos(fontes):
    return [type(f).__name__ for f in fontes]


def test_licenca_aprovada_com_prova_e_a_fonte_nasce_desligada(monkeypatch):
    ligar_banco_falso(monkeypatch)
    registro = fontes_externas.REGISTRO["bps"]
    assert registro.flag == "price_source_bps" and registro.mapeamento_confirmado
    assert registro.licenca is fontes_externas.Licenca.APROVADA
    assert "SemDerivações" in registro.nota_licenca and registro.prova_licenca
    # aprovar a licença não liga nada: sem a flag, a fonte fica fora
    assert "BPSIndice" not in _tipos(cotacoes._fontes_padrao())
    # e sem a prova, nem a flag liga
    import dataclasses

    monkeypatch.setitem(fontes_externas.REGISTRO, "bps",
                        dataclasses.replace(registro, prova_licenca=""))
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == registro.flag)
    assert "BPSIndice" not in _tipos(cotacoes._fontes_padrao())


def test_com_licenca_aprovada_e_flag_a_fonte_entra_e_le_pela_rpc(monkeypatch):
    import dataclasses

    cliente = ligar_banco_falso(monkeypatch)
    registro = fontes_externas.REGISTRO["bps"]
    monkeypatch.setitem(fontes_externas.REGISTRO, "bps", dataclasses.replace(
        registro, licenca=fontes_externas.Licenca.APROVADA,
        prova_licenca="decisão de teste"))
    assert "BPSIndice" not in _tipos(cotacoes._fontes_padrao())   # flag off

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    assert "BPSIndice" not in _tipos(cotacoes._fontes_padrao())   # ilegível
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == registro.flag)
    fontes = cotacoes._fontes_padrao()
    assert _tipos(fontes)[-1] == "BPSIndice"
    fontes[-1].pesquisar(Consulta(descricao="Bezafibrato 200", uf="pa",
                                  data_inicial=date(2026, 1, 1),
                                  data_final=date(2026, 11, 11), limite=50))
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_bps_buscar"
    assert parametros == {"p_termos": ["bezafibrato", "200"], "p_catmat": None,
                          "p_uf": "PA", "p_desde": "2026-01-01",
                          "p_ate": "2026-11-11", "p_limite": 50}
    assert repo.buscar_indice_bps.__name__ == "buscar_indice_bps"
