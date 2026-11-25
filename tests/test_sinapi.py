"""
SINAPI (CAIXA/IBGE) como referência de custo de engenharia — 23/11/2026.

A amostra é REAL: as dez linhas de topo de cada aba e linhas de dados do
relatório oficial de 10/2026 (`fixtures/fontes_precos/sinapi_2026_10_amostra.xlsx`),
mais o texto dos PDFs oficiais do Pará da mesma competência
(`sinapi_2026_10_pdf_pa.json`). Nenhuma chamada de rede.

O que estas provas guardam:

* competência, UF, código, unidade, tipo (insumo ou composição) e regime
  (sem desoneração, com desoneração, sem encargos) saem do arquivo como a
  CAIXA publicou; o código da composição sai da fórmula HYPERLINK;
* preço em branco e custo zerado NÃO viram referência — ficam contados;
* importação idempotente e por VERSÃO: retificação da mesma competência é
  versão nova, publicada inteira; arquivo truncado é recusado e a anterior
  continua; leiaute diferente não importa nada;
* o que o importador leu bate com a edição oficial em PDF;
* a consulta é PRÓPRIA (custo referencial), não fonte da cesta de compras,
  e nasce desligada.
"""

from __future__ import annotations

import io
import json
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from src import db, governanca
from src.precos import arquivos, cotacoes, sinapi
from tests.cotacoes_apoio import ligar_banco_falso

FIX = Path(__file__).parent / "fixtures" / "fontes_precos"
AMOSTRA = FIX / "sinapi_2026_10_amostra.xlsx"
PDF = json.loads((FIX / "sinapi_2026_10_pdf_pa.json").read_text("utf-8"))
URL = sinapi.url_da_competencia("2026-10")
NOME = "SINAPI_Referência_2026_10.xlsx"


def _zip(tmp_path, nome="SINAPI-2026-10-formato-xlsx.zip", mudar=None) -> Path:
    """O ZIP mensal com a amostra real; `mudar(livro)` altera antes."""
    livro = openpyxl.load_workbook(AMOSTRA)
    if mudar is not None:
        mudar(livro)
    conteudo = io.BytesIO()
    livro.save(conteudo)
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(NOME, conteudo.getvalue())
        z.writestr("SINAPI_mao_de_obra_2026_10.xlsx", b"PK\x05\x06" + b"\0" * 18)
    return caminho


def _celula(aba, codigo, coluna_uf="PA"):
    """Muda a célula do PA da linha do código, na aba."""
    def mudar(livro, valor):
        ws = livro[aba]
        insumo = aba.startswith("I")
        uf_linha = 10 if insumo else 9
        coluna = next(c.column for c in ws[uf_linha] if c.value == coluna_uf)
        for linha in ws.iter_rows(min_row=11):
            texto = str(linha[1].value)
            if texto == str(codigo) or texto.endswith(f",{codigo})"):
                # `cell(..., value=None)` não apaga: a atribuição apaga
                ws.cell(row=linha[0].row, column=coluna).value = valor
                return
        raise AssertionError("código fora da amostra")
    return mudar


@pytest.fixture
def arquivo(tmp_path):
    return _zip(tmp_path)


@pytest.fixture
def armazem(arquivo):
    a = sinapi.ArmazemEmMemoria()
    assert sinapi.importar(a, arquivo, url=URL).desfecho == sinapi.PUBLICADO
    return a


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_as_seis_abas_com_competencia_regime_e_unidade(arquivo):
    leitura = sinapi.Leitura()
    linhas = list(sinapi.ler(arquivo, leitura=leitura))
    assert (leitura.competencia, leitura.data_emissao) == ("2026-10", "2026-11-12")
    assert dict(leitura.por_aba) == {"ISD": 4, "ICD": 4, "ISE": 4,
                                     "CSD": 3, "CCD": 3, "CSE": 3}
    cimento = {l["regime"]: l for l in linhas
               if l["tipo"] == sinapi.INSUMO and l["codigo"] == "1379"}
    assert set(cimento) == {sinapi.SEM_DESONERACAO, sinapi.COM_DESONERACAO,
                            sinapi.SEM_ENCARGOS}
    linha = cimento[sinapi.SEM_DESONERACAO]
    assert (linha["uf"], linha["unidade"], linha["valor"]) == ("PA", "KG", Decimal("1.08"))
    assert (linha["classificacao"], linha["origem_preco"]) == ("MATERIAL", "C")
    assert linha["descricao"] == "CIMENTO PORTLAND COMPOSTO CP II-32"
    assert linha["aba"] == "ISD" and linha["linha_planilha"] > 10


def test_codigo_da_composicao_sai_da_formula_hyperlink(arquivo):
    piso = [l for l in sinapi.ler(arquivo)
            if l["tipo"] == sinapi.COMPOSICAO and l["codigo"] == "104658"]
    assert {l["regime"]: l["valor"] for l in piso} == {
        sinapi.SEM_DESONERACAO: Decimal("189.32"),
        sinapi.COM_DESONERACAO: piso[1]["valor"],
        sinapi.SEM_ENCARGOS: piso[2]["valor"]}
    assert piso[0]["unidade"] == "M2" and piso[0]["classificacao"] == "Acessibilidade"
    assert piso[0]["percentual_sp"] == Decimal("0")


def test_preco_em_branco_e_custo_zerado_nao_viram_referencia(arquivo):
    leitura = sinapi.Leitura()
    list(sinapi.ler(arquivo, leitura=leitura))
    # uma linha de insumo sem coleta no PA, nas três abas; uma composição
    # com custo zerado, nas três
    assert leitura.recusadas == {sinapi.SEM_PRECO: 3, sinapi.PRECO_ZERADO: 3}
    assert leitura.validas + 6 == leitura.linhas


@pytest.mark.parametrize("valor, motivo", [
    (0, sinapi.PRECO_ZERADO), (None, sinapi.SEM_PRECO), ("-", sinapi.SEM_PRECO),
    (-1.5, sinapi.PRECO_ZERADO), ("abc", sinapi.VALOR_ILEGIVEL),
])
def test_valor_que_nao_e_custo_e_recusado(tmp_path, valor, motivo):
    caminho = _zip(tmp_path, mudar=lambda l: _celula("ISD", 1379)(l, valor))
    leitura = sinapi.Leitura()
    linhas = list(sinapi.ler(caminho, leitura=leitura))
    assert not any(l["codigo"] == "1379" and l["aba"] == "ISD" for l in linhas)
    assert leitura.recusadas[motivo] >= 1


def test_so_as_ufs_pedidas(arquivo):
    linhas = list(sinapi.ler(arquivo, ufs=("PA", "SP")))
    assert {l["uf"] for l in linhas} == {"PA", "SP"}
    with pytest.raises(ValueError):
        list(sinapi.ler(arquivo, ufs=("XX",)))


def _trocar_titulo(livro):
    livro["ICD"]["A2"] = "RELATÓRIO DE PREÇOS DE INSUMOS - ENCARGOS SOCIAIS SEM DESONERAÇÃO"


def _trocar_mes(livro):
    livro["CSE"]["B3"] = "09/2026"


def _tirar_uf(livro):
    livro["ISD"]["S10"] = "XX"


def _trocar_cabecalho(livro):
    livro["CSD"]["B10"] = "Código"


def _tirar_aba(livro):
    del livro["CCD"]


@pytest.mark.parametrize("mudar, trecho", [
    (_trocar_titulo, "não é"), (_trocar_mes, "competências diferentes"),
    (_tirar_uf, "27 UFs"), (_trocar_cabecalho, "cabeçalho mudou"),
    (_tirar_aba, "faltam as abas"),
])
def test_leiaute_diferente_nao_importa_nada(tmp_path, mudar, trecho):
    caminho = _zip(tmp_path, mudar=mudar)
    armazem = sinapi.ArmazemEmMemoria()
    with pytest.raises(sinapi.LeiauteInesperado, match=trecho):
        sinapi.importar(armazem, caminho, url=URL)
    assert armazem.versoes == {} and armazem.registros == {}


def test_competencia_do_arquivo_tem_de_ser_a_do_endereco(arquivo):
    with pytest.raises(ValueError, match="competência"):
        sinapi.importar(sinapi.ArmazemEmMemoria(), arquivo,
                        url=sinapi.url_da_competencia("2026-09"))
    with pytest.raises(sinapi.LeiauteInesperado):
        list(sinapi.ler(arquivo, competencia="2026-09"))


@pytest.mark.parametrize("url", [
    "https://exemplo.com/Downloads/sinapi-relatorios-mensais/SINAPI-2026-10-formato-xlsx.zip",
    "http://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-2026-10-formato-xlsx.zip",
    "https://www.caixa.gov.br/Downloads/outra-pasta/SINAPI-2026-10-formato-xlsx.zip",
    "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/x.zip?u=https://exemplo.com",
])
def test_arquivo_so_do_endereco_oficial(tmp_path, url):
    # recusa ANTES de abrir o arquivo: o caminho nem existe
    with pytest.raises(ValueError, match="endereço oficial"):
        sinapi.importar(sinapi.ArmazemEmMemoria(), tmp_path / "nao-existe.zip", url=url)


def test_endereco_e_montado_so_com_digitos():
    assert sinapi.url_da_competencia("2026-10") == (
        "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/"
        "SINAPI-2026-10-formato-xlsx.zip")
    assert arquivos.url_permitida(sinapi.url_da_competencia("2026-10"))
    for ruim in ("2026-13", "26-10", "2026-10/../x", ""):
        with pytest.raises(ValueError):
            sinapi.url_da_competencia(ruim)


# ---------------------------------------------------------------------------
# Importação por versão
# ---------------------------------------------------------------------------
def test_importacao_publica_e_guarda_a_origem_oficial(armazem, arquivo):
    versao = armazem.versao_publicada("2026-10")
    assert versao["sha256"] == arquivos.sha256_do_arquivo(arquivo)
    assert versao["validas"] == 21 and versao["ufs"] == ["PA"]
    assert versao["url"] == URL and versao["data_emissao"] == "2026-11-12"
    linha = armazem.registros["sinapi:2026-10:insumo:1379:PA:sem_desoneracao"]
    assert linha["vigente"] and linha["url_arquivo"] == URL
    assert linha["arquivo_sha256"] == versao["sha256"]
    assert linha["valor"] == "1.08" and len(linha["hash_linha"]) == 64
    assert linha["versao_parser"] == sinapi.VERSAO_PARSER


def test_mesmo_arquivo_nao_e_importado_de_novo(armazem, arquivo):
    gravacoes = []
    armazem.gravar_registros = lambda linhas: gravacoes.append(len(linhas))
    assert sinapi.importar(armazem, arquivo, url=URL).desfecho == "ja_publicado"
    assert gravacoes == [] and len(armazem.versoes) == 1


def test_retificacao_da_competencia_e_versao_nova_publicada_inteira(
        tmp_path, armazem):
    chave = "sinapi:2026-10:insumo:1379:PA:sem_desoneracao"
    # a CAIXA corrige um preço: outro arquivo, outro SHA
    retificado = _zip(tmp_path, "retificado.zip",
                      mudar=lambda l: _celula("ISD", 1379)(l, 1.12))
    feito = sinapi.importar(armazem, retificado, url=URL)
    assert feito.desfecho == sinapi.PUBLICADO and len(armazem.versoes) == 2
    assert feito.validas_na_versao_anterior == 21
    assert armazem.versao_publicada("2026-10")["sha256"] == feito.sha256
    assert armazem.registros[chave]["valor"] == "1.12"       # mesma chave
    assert armazem.registros[chave]["arquivo_sha256"] == feito.sha256
    assert all(l["vigente"] and l["arquivo_sha256"] == feito.sha256
               for l in armazem.registros.values())


def test_preco_zerado_corrigido_depois_entra_na_versao_nova(tmp_path):
    chave = "sinapi:2026-10:insumo:1379:PA:sem_desoneracao"
    a = sinapi.ArmazemEmMemoria()
    zerado = _zip(tmp_path, "zerado.zip", mudar=lambda l: _celula("ISD", 1379)(l, 0))
    assert sinapi.importar(a, zerado, url=URL).desfecho == sinapi.PUBLICADO
    assert chave not in a.registros
    corrigido = _zip(tmp_path, "corrigido.zip")
    assert sinapi.importar(a, corrigido, url=URL).desfecho == sinapi.PUBLICADO
    assert a.registros[chave]["vigente"] and a.registros[chave]["valor"] == "1.08"


def test_arquivo_que_encolheu_demais_e_recusado_e_a_versao_anterior_fica(
        tmp_path, armazem):
    vigente = armazem.versao_publicada("2026-10")["sha256"]

    def zerar_quase_tudo(livro):
        for aba in sinapi.ABAS:
            ws = livro[aba]
            for linha in ws.iter_rows(min_row=11):
                for celula in linha[4:]:
                    if isinstance(celula.value, (int, float)) and celula.value > 0:
                        celula.value = 0
        _celula("ISD", 1379)(livro, 1.08)

    feito = sinapi.importar(armazem, _zip(tmp_path, "ruim.zip", mudar=zerar_quase_tudo),
                            url=URL)
    assert feito.desfecho == sinapi.RECUSADO and "redução" in feito.motivo
    assert armazem.versao_publicada("2026-10")["sha256"] == vigente
    assert sum(l["vigente"] for l in armazem.registros.values()) == 21


# ---------------------------------------------------------------------------
# Confronto com a edição oficial em PDF
# ---------------------------------------------------------------------------
def test_leitor_do_pdf_le_insumo_e_composicao_do_texto_oficial():
    insumos = sinapi.valores_do_pdf(PDF["insumo"], sinapi.INSUMO)
    assert insumos["1379"] == (Decimal("1.08"), Decimal("1.08"))
    assert insumos["45333"] == (Decimal("177.69"), Decimal("177.69"))
    composicoes = sinapi.valores_do_pdf(PDF["composicao"], sinapi.COMPOSICAO)
    # a descrição "- MENSALISTA" não é valor: o custo é 61,97 / 57,40
    assert composicoes["101312"] == (Decimal("61.97"), Decimal("57.40"))
    assert composicoes["104658"][0] == Decimal("189.32")


def test_o_que_foi_importado_bate_com_o_pdf_oficial(armazem):
    pdf = {sinapi.INSUMO: sinapi.valores_do_pdf(PDF["insumo"], sinapi.INSUMO),
           sinapi.COMPOSICAO: sinapi.valores_do_pdf(PDF["composicao"],
                                                   sinapi.COMPOSICAO)}
    linhas = [l for l in armazem.registros.values()
              if l["codigo"] in {"1379", "11270", "13284", "45333",
                                 "104658", "101312"}]
    feito = sinapi.confrontar_com_pdf(linhas, pdf)
    assert feito.conferidas == 12 and feito.iguais == 12
    assert feito.divergentes == [] and feito.ausentes_no_pdf == []
    # e uma divergência de verdade é denunciada
    alterado = [{**linhas[0], "valor": "9.99"}] if linhas[0]["regime"] != \
        sinapi.SEM_ENCARGOS else [{**linhas[1], "valor": "9.99"}]
    assert sinapi.confrontar_com_pdf(alterado, pdf).divergentes


# ---------------------------------------------------------------------------
# Consulta própria
# ---------------------------------------------------------------------------
def test_consulta_por_termos_e_por_codigo(armazem):
    consulta = sinapi.ConsultaSINAPI(armazem.buscar)
    r = consulta.consultar(termo="Cimento Portland CP II", tipo=sinapi.INSUMO)
    assert r.falha is None and r.competencia == "2026-10"
    primeira = r.referencias[0]
    assert primeira.codigo in {"1379", "13284"}
    assert primeira.natureza == sinapi.NATUREZA == "custo_referencial"
    assert primeira.regime == sinapi.SEM_DESONERACAO       # padrão
    assert primeira.rotulo_regime == "encargos sociais sem desoneração"
    [piso] = consulta.consultar(codigo="104658").referencias
    assert piso.tipo == sinapi.COMPOSICAO and piso.valor == Decimal("189.32")
    assert piso.identificacao == "SINAPI Composição 104658 — PA 10/2026"
    assert piso.url_arquivo == URL and piso.aba == "CSD"
    com = consulta.consultar(codigo="104658", regime=sinapi.COM_DESONERACAO)
    assert com.referencias[0].regime == sinapi.COM_DESONERACAO


def test_consulta_recusa_filtro_fora_da_regra_sem_ir_ao_indice(armazem):
    chamadas = []

    def espia(*a, **k):
        chamadas.append(1)
        return []

    consulta = sinapi.ConsultaSINAPI(espia)
    assert consulta.consultar(codigo="1&x=1").falha
    assert consulta.consultar(termo="x", regime="outro").falha
    assert consulta.consultar(termo="x", tipo="outro").falha
    assert consulta.consultar(termo="de a").referencias == []
    with pytest.raises(ValueError):
        consulta.consultar(termo="cimento", competencia="2026-13")
    assert chamadas == []


def test_indice_fora_do_ar_vira_recado():
    def fora(*a, **k):
        raise ConnectionError("banco fora")

    r = sinapi.ConsultaSINAPI(fora).consultar(termo="cimento")
    assert r.referencias == [] and "não respondeu" in r.falha
    assert sinapi.ConsultaSINAPI(lambda *a, **k: "x").consultar(
        termo="cimento").falha


def test_linha_do_indice_sem_valor_ou_fora_do_endereco_oficial_e_ignorada(armazem):
    linha = next(iter(armazem.registros.values()))
    assert sinapi.referencia_da_linha(linha) is not None
    for mudanca in ({"valor": "0"}, {"valor": "x"}, {"registro_id": ""},
                    {"url_arquivo": "https://exemplo.com/sinapi.zip"}):
        assert sinapi.referencia_da_linha({**linha, **mudanca}) is None


def test_competencia_mais_recente_por_padrao(tmp_path, armazem):
    # uma competência anterior importada depois não toma o lugar da recente
    def setembro(livro):
        for aba in sinapi.ABAS:
            livro[aba]["B3"] = "09/2026"

    anterior = _zip(tmp_path, "SINAPI-2026-09-formato-xlsx.zip", mudar=setembro)
    assert sinapi.importar(armazem, anterior,
                           url=sinapi.url_da_competencia("2026-09")).desfecho == \
        sinapi.PUBLICADO
    consulta = sinapi.ConsultaSINAPI(armazem.buscar)
    assert consulta.consultar(codigo="1379").competencia == "2026-10"
    assert consulta.consultar(codigo="1379", competencia="2026-09"
                              ).referencias[0].competencia == "2026-09"


# ---------------------------------------------------------------------------
# Categoria própria — fora da cesta
# ---------------------------------------------------------------------------
def test_sinapi_nao_e_fonte_da_cesta_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    nomes = [type(f).__name__ for f in cotacoes._fontes_padrao()]
    assert not any("SINAPI" in n.upper() for n in nomes)
    assert governanca.FLAG_REFERENCIA_SINAPI == "referencia_custos_sinapi"


def test_repositorio_le_pela_rpc_com_o_token_do_usuario(monkeypatch):
    from src.precos import repositorio as repo

    cliente = ligar_banco_falso(monkeypatch)
    repo.buscar_sinapi(["cimento"], uf="pa", regime=sinapi.SEM_DESONERACAO,
                       tipo=sinapi.INSUMO, limite=20)
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_sinapi_buscar"
    assert parametros == {"p_termos": ["cimento"], "p_codigo": None,
                          "p_uf": "PA", "p_competencia": None,
                          "p_regime": "sem_desoneracao", "p_tipo": "insumo",
                          "p_limite": 20}


# ---------------------------------------------------------------------------
# Download: o laço de 302 da CAIXA (medido em 23/11/2026) é passageiro
# ---------------------------------------------------------------------------
class _Resposta(io.BytesIO):
    def __init__(self, dados, url):
        super().__init__(dados)
        self.headers = {"Content-Length": str(len(dados)), "Last-Modified": "hoje"}
        self._url = url

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_laco_de_redirecionamento_da_caixa_e_tentado_de_novo(tmp_path, arquivo):
    import urllib.error

    from src.precos import sinapi_servico

    url = sinapi.url_da_competencia("2026-10")
    tentativas = []
    dados = arquivo.read_bytes()

    def abrir(requisicao):
        tentativas.append(requisicao.full_url)
        if len(tentativas) == 1:
            raise urllib.error.HTTPError(requisicao.full_url, 302, "laço", {}, None)
        return _Resposta(dados, requisicao.full_url)

    caminho = sinapi_servico._baixar(url, tmp_path, "s.zip", abrir=abrir,
                                     dormir=lambda s: None)
    assert tentativas == [url, url]
    assert caminho.read_bytes() == dados


def test_outro_erro_http_nao_e_repetido(tmp_path):
    import urllib.error

    from src.precos import sinapi_servico

    tentativas = []

    def abrir(requisicao):
        tentativas.append(1)
        raise urllib.error.HTTPError(requisicao.full_url, 404, "não há", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        sinapi_servico._baixar(sinapi.url_da_competencia("2030-01"), tmp_path, "s.zip",
                               abrir=abrir, dormir=lambda s: None)
    assert tentativas == [1]


def test_laco_que_nao_passa_desiste_na_terceira(tmp_path):
    import urllib.error

    from src.precos import sinapi_servico

    tentativas = []

    def abrir(requisicao):
        tentativas.append(1)
        raise urllib.error.HTTPError(requisicao.full_url, 302, "laço", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        sinapi_servico._baixar(sinapi.url_da_competencia("2026-10"), tmp_path, "s.zip",
                               abrir=abrir, dormir=lambda s: None)
    assert len(tentativas) == 3
