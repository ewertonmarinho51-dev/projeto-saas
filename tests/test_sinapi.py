"""
SINAPI (CAIXA/IBGE) — custo de referência de engenharia, 23/11/2026.

A fixture é feita de linhas REAIS do arquivo oficial de 10/2026
(`fixtures/fontes_precos/sinapi_2026_10_amostra.json`): as dez primeiras
linhas de cada uma das seis abas de preço, com todas as colunas de UF, e
algumas linhas de dados no NÚMERO de linha em que estão no original —
inclusive um insumo com preço em branco e uma composição com custo zero no
Pará. O teste monta o XLSX e o ZIP mensal a partir dela. Nenhuma rede.

O que estas provas guardam:

* leitura por competência, UF, tipo (insumo/composição) e regime
  (sem desoneração, com desoneração, sem encargos), com o código da
  composição tirado da fórmula `HYPERLINK` (o valor em cache é 0);
* preço em branco ou zero é recusado e contado, nunca gravado;
* importação idempotente e por versão validada: retificação da mesma
  competência é versão nova, publicada inteira; a anterior fica guardada;
  arquivo que encolheu demais é recusado e a anterior continua valendo;
* o mês declarado na planilha tem de ser o da competência pedida, e o
  arquivo só é aceito do endereço oficial da competência;
* o índice reproduz a edição oficial célula a célula (`confrontar`);
* a consulta devolve a origem verificável e a natureza por extenso;
* o SINAPI nunca entra na cesta de preços de compras.
"""

from __future__ import annotations

import dataclasses
import io
import json
import urllib.error
import zipfile
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from src import db
from src.precos import arquivos, cotacoes, fontes_externas, sinapi, sinapi_servico
from tests.cotacoes_apoio import ligar_banco_falso

FIX = json.loads((Path(__file__).parent / "fixtures" / "fontes_precos" /
                  "sinapi_2026_10_amostra.json").read_text("utf-8"))
COMPETENCIA = "2026-10"
URL = sinapi.url_do_arquivo(COMPETENCIA)
PA_INSUMO, PA_COMPOSICAO = 18, 30


def _valor(celula):
    return float(celula["f"]) if isinstance(celula, dict) else celula


def _zip(tmp_path, nome="sinapi.zip", *, mudancas=None, sem_abas=(),
         mes="10/2026", nome_planilha="SINAPI_Referência_2026_10.xlsx",
         extra=None):
    """
    O ZIP mensal com a planilha de referência montada da fixture.
    `mudancas` = {(aba, linha, coluna): valor}; `sem_abas` tira abas;
    `mes` troca o "Mês de Referência" de todas as abas.
    """
    livro = openpyxl.Workbook()
    livro.remove(livro.active)
    for aba, dados in FIX["abas"].items():
        if aba in sem_abas:
            continue
        folha = livro.create_sheet(aba)
        for numero, linha in enumerate(dados["topo"], start=1):
            for coluna, celula in enumerate(linha, start=1):
                if celula is not None:
                    folha.cell(numero, coluna, _valor(celula))
        folha.cell(3, 2, mes)
        for registro in dados["dados"]:
            for coluna, celula in enumerate(registro["celulas"], start=1):
                if celula is not None:
                    folha.cell(registro["linha"], coluna, _valor(celula))
    for (aba, linha, coluna), valor in (mudancas or {}).items():
        livro[aba].cell(linha, coluna + 1, valor)
    planilha = io.BytesIO()
    livro.save(planilha)
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(nome_planilha, planilha.getvalue())
        z.writestr("SINAPI_mao_de_obra_2026_10.xlsx", b"PK\x05\x06" + b"\x00" * 18)
        for nome_extra, conteudo in (extra or {}).items():
            z.writestr(nome_extra, conteudo)
    return caminho


def _celulas_pa(aba):
    coluna = PA_COMPOSICAO if aba.startswith("C") else PA_INSUMO
    return [_valor(r["celulas"][coluna]) for r in FIX["abas"][aba]["dados"]]


@pytest.fixture
def arquivo(tmp_path):
    return _zip(tmp_path)


@pytest.fixture
def armazem(arquivo):
    a = sinapi.ArmazemEmMemoria()
    feito = sinapi.importar(a, arquivo, competencia=COMPETENCIA, uf="PA")
    assert feito.desfecho == sinapi.PUBLICADO, feito.motivo
    return a


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_as_seis_abas_com_tipo_regime_e_codigo_da_formula(arquivo):
    leitura = sinapi.Leitura()
    registros = list(sinapi.ler(arquivo, COMPETENCIA, ("PA",), leitura=leitura))
    por_aba = {aba: [r for r in registros if r.aba == aba] for aba in sinapi.ABAS}
    # o que a fixture tem com preço positivo no PA, aba a aba
    for aba in sinapi.ABAS:
        esperado = sum(1 for v in _celulas_pa(aba) if v not in (None, "") and v > 0)
        assert len(por_aba[aba]) == esperado > 0, aba
    assert {(r.tipo, r.regime) for r in registros} == set(sinapi.ABAS.values())
    cimento = next(r for r in por_aba["ISD"] if r.codigo == "1379")
    assert (cimento.descricao, cimento.unidade) == ("CIMENTO PORTLAND COMPOSTO CP II-32", "KG")
    assert cimento.valor == Decimal("1.08") and cimento.origem_preco == "C"
    assert (cimento.aba, cimento.linha, cimento.uf) == ("ISD", 1169, "PA")
    assert cimento.classificacao == "MATERIAL"
    # composição: o código vem da fórmula HYPERLINK, não do 0 em cache
    piso = {r.aba: r for r in registros if r.codigo == "104658"}
    assert {a: str(r.valor) for a, r in piso.items()} == {
        "CSD": "189.32", "CCD": "186.58", "CSE": "169"}
    assert piso["CSD"].unidade == "M2" and piso["CSD"].linha == 11
    assert piso["CSD"].classificacao == "Acessibilidade"
    assert piso["CSD"].percentual_sp == Decimal("0")
    assert leitura.emissao == "12/11/2026"
    assert leitura.encargos["PA"] == {
        "sem_desoneracao": {"horista": "1.1942", "mensalista": "0.727"},
        "com_desoneracao": {"horista": "1.0326", "mensalista": "0.5998"}}


def test_preco_em_branco_e_custo_zero_sao_recusados_e_contados(arquivo):
    leitura = sinapi.Leitura()
    codigos = {(r.aba, r.codigo) for r in
               sinapi.ler(arquivo, COMPETENCIA, ("PA",), leitura=leitura)}
    em_branco = sum(1 for aba in ("ISD", "ICD", "ISE")
                    for v in _celulas_pa(aba) if v in (None, ""))
    zerados = sum(1 for aba in ("CSD", "CCD", "CSE")
                  for v in _celulas_pa(aba) if v == 0)
    assert em_branco >= 3 and zerados >= 1
    assert leitura.motivos[sinapi.PRECO_VAZIO] == em_branco
    assert leitura.motivos[sinapi.PRECO_ZERO] == zerados
    assert ("CSD", "105006") not in codigos       # "sem custo" no PA em 10/2026
    assert leitura.linhas == leitura.validos + sum(leitura.motivos.values())


def test_varias_ufs_de_uma_vez(arquivo):
    ufs = {r.uf for r in sinapi.ler(arquivo, COMPETENCIA, ("PA", "SP"))}
    assert ufs == {"PA", "SP"}
    with pytest.raises(ValueError, match="UF"):
        list(sinapi.ler(arquivo, COMPETENCIA, ("XX",)))


@pytest.mark.parametrize("formula, codigo", [
    ('=HYPERLINK("#"&CELL("address",OFFSET(Analítico!$B$1,MATCH(104658,'
     'Analítico!$B:$B,0)-1,3)),104658)', "104658"),
    ("=HYPERLINK(\"#A1\";93358)", "93358"),
    (45333, "45333"), (45333.0, "45333"), ("1379", "1379"),
    (0, None), (12.5, None), ("=SOMA(A1:A2)", None), ("ABC", None), (None, None),
    (True, None),
])
def test_codigo_da_celula(formula, codigo):
    assert sinapi.codigo_da_celula(formula) == codigo


def test_numero_vira_decimal_pelo_texto_gravado_nunca_pelo_binario():
    assert sinapi._decimal(269.08) == Decimal("269.08")
    assert sinapi._decimal(0.1) == Decimal("0.1")       # Decimal(0.1) seria 0.1000…055
    assert sinapi._decimal(3061.34) == Decimal("3061.34")
    assert sinapi._decimal(17) == Decimal("17")
    for vazio in (None, "", True, "abc"):
        assert sinapi._decimal(vazio) is None


@pytest.mark.parametrize("ajuste, mensagem", [
    ({"mes": "09/2026"}, "mês de referência"),
    ({"sem_abas": ("CCD",)}, "faltam as abas"),
    ({"mudancas": {("ISD", 10, 1): "Código"}}, "cabeçalho"),
    ({"nome_planilha": "SINAPI_Referência_2026_09.xlsx"}, "planilha de referência"),
])
def test_arquivo_fora_do_leiaute_e_recusado_antes_de_ler(tmp_path, ajuste, mensagem):
    caminho = _zip(tmp_path, **ajuste)
    with pytest.raises(sinapi.ArquivoInvalido, match=mensagem):
        list(sinapi.ler(caminho, COMPETENCIA, ("PA",)))


def test_zip_com_arquivo_inesperado_e_recusado(tmp_path):
    caminho = _zip(tmp_path, extra={"leia-me.exe": b"MZ"})
    with pytest.raises(arquivos.ArquivoRecusado, match="extensão"):
        list(sinapi.ler(caminho, COMPETENCIA, ("PA",)))


@pytest.mark.parametrize("competencia", ["2026-13", "26-10", "2026/10", "", "2026-10x"])
def test_competencia_invalida(competencia):
    with pytest.raises(ValueError, match="AAAA-MM"):
        sinapi.url_do_arquivo(competencia)


# ---------------------------------------------------------------------------
# Importação por versão
# ---------------------------------------------------------------------------
def test_importacao_publica_a_versao_com_origem_e_chave_da_linha(arquivo):
    a = sinapi.ArmazemEmMemoria()
    feito = sinapi.importar(a, arquivo, competencia=COMPETENCIA, uf="pa",
                            last_modified="Thu, 12 Nov 2026 19:46:26 GMT")
    assert (feito.desfecho, feito.uf, feito.competencia) == (sinapi.PUBLICADO, "PA", COMPETENCIA)
    versao = a.versao_publicada(COMPETENCIA, "PA")
    assert versao["sha256"] == feito.sha256 == arquivos.sha256_do_arquivo(arquivo)
    assert versao["url"] == URL and versao["emissao"] == "12/11/2026"
    assert versao["encargos"]["sem_desoneracao"]["horista"] == "1.1942"
    assert versao["validos"] == feito.validos == len(a.registros)
    linha = next(l for l in a.registros.values()
                 if l["codigo"] == "1379" and l["aba"] == "ISD")
    assert linha["chave_linha"] == "2026-10:PA:insumo:sem_desoneracao:1379"
    assert (linha["valor"], linha["unidade"], linha["origem_preco"]) == ("1.08", "KG", "C")
    assert (linha["aba"], linha["linha_planilha"]) == ("ISD", 1169)
    assert linha["arquivo_sha256"] == feito.sha256 and linha["url_arquivo"] == URL
    assert linha["descricao_busca"] == "cimento portland composto cp ii-32"
    assert linha["versao_parser"] == sinapi.VERSAO_PARSER and len(linha["hash_linha"]) == 64
    assert all(l["vigente"] for l in a.registros.values())


def test_mesmo_arquivo_nao_e_importado_de_novo(arquivo, armazem):
    gravacoes = []
    armazem.gravar_registros = lambda linhas: gravacoes.append(len(linhas))
    assert sinapi.importar(armazem, arquivo, competencia=COMPETENCIA,
                           uf="PA").desfecho == "ja_publicado"
    assert gravacoes == [] and len(armazem.versoes) == 1


def test_retificacao_da_mesma_competencia_e_versao_nova(tmp_path, armazem):
    antes = {l["chave_linha"]: l for l in armazem.registros.values()}
    # a CAIXA republica com o cimento corrigido (linha 1169, coluna do PA)
    retificado = _zip(tmp_path, "retificado.zip",
                      mudancas={("ISD", 1169, PA_INSUMO): 1.12})
    feito = sinapi.importar(armazem, retificado, competencia=COMPETENCIA, uf="PA")
    assert feito.desfecho == sinapi.PUBLICADO and len(armazem.versoes) == 2
    assert feito.validos_na_versao_anterior == len(antes)
    assert armazem.versao_publicada(COMPETENCIA, "PA")["sha256"] == feito.sha256
    [cimento] = sinapi.consultar(armazem.buscar, codigo="1379", tipo="insumo")
    assert cimento["valor"] == "1.12" and cimento["arquivo_sha256"] == feito.sha256
    # mesma chave nas duas versões; a antiga fica guardada, sem valer
    chave = "2026-10:PA:insumo:sem_desoneracao:1379"
    guardadas = [l for l in armazem.registros.values() if l["chave_linha"] == chave]
    assert sorted((l["valor"], l["vigente"]) for l in guardadas) == [
        ("1.08", False), ("1.12", True)]
    assert len(armazem.registros) == 2 * len(antes)


def test_arquivo_que_encolheu_demais_e_recusado_e_o_anterior_continua(tmp_path, armazem):
    vigente = armazem.versao_publicada(COMPETENCIA, "PA")["sha256"]
    # a mesma competência republicada com quase tudo zerado no PA
    zerado = {(aba, r["linha"], PA_COMPOSICAO if aba.startswith("C") else PA_INSUMO): 0
              for aba, dados in FIX["abas"].items() for r in dados["dados"]
              if not (aba == "ISD" and r["linha"] == 1169)}
    feito = sinapi.importar(armazem, _zip(tmp_path, "zerado.zip", mudancas=zerado),
                            competencia=COMPETENCIA, uf="PA")
    assert feito.desfecho == sinapi.RECUSADO and "redução" in feito.motivo
    assert feito.recusas[sinapi.PRECO_ZERO] > 0
    assert armazem.versao_publicada(COMPETENCIA, "PA")["sha256"] == vigente
    assert sinapi.consultar(armazem.buscar, codigo="104658", regime=None)


def test_sem_nenhum_preco_valido_nao_publica(tmp_path):
    a = sinapi.ArmazemEmMemoria()
    zerado = {(aba, r["linha"], PA_COMPOSICAO if aba.startswith("C") else PA_INSUMO): 0
              for aba, dados in FIX["abas"].items() for r in dados["dados"]}
    feito = sinapi.importar(a, _zip(tmp_path, "zero.zip", mudancas=zerado),
                            competencia=COMPETENCIA, uf="PA")
    assert feito.desfecho == sinapi.RECUSADO and a.versao_publicada(COMPETENCIA, "PA") is None


@pytest.mark.parametrize("url", [
    "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-2026-09-formato-xlsx.zip",
    "https://www.caixa.gov.br/Downloads/outra-pasta/SINAPI-2026-10-formato-xlsx.zip",
    "https://exemplo.com/SINAPI-2026-10-formato-xlsx.zip",
    "http://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-2026-10-formato-xlsx.zip",
])
def test_arquivo_so_do_endereco_oficial_da_competencia(arquivo, url):
    with pytest.raises(ValueError, match="endereço oficial"):
        sinapi.importar(sinapi.ArmazemEmMemoria(), arquivo, competencia=COMPETENCIA,
                        uf="PA", url=url)


@pytest.mark.parametrize("url, aceita", [
    (URL, True),
    ("https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/x.zip?a=1", False),
    ("https://www.caixa.gov.br/site/Paginas/downloads.aspx", False),
    ("https://www.caixa.gov.br/Downloads/sinapi-historico-de-encargos-e-notas/Notas_SINAPI.pdf",
     False),
    ("https://caixa.gov.br/Downloads/sinapi-relatorios-mensais/x.zip", False),
])
def test_download_so_aceita_os_relatorios_mensais_da_caixa(url, aceita):
    assert arquivos.url_permitida(url) is aceita


# ---------------------------------------------------------------------------
# Conferência contra a edição oficial
# ---------------------------------------------------------------------------
def test_o_indice_reproduz_a_planilha_celula_a_celula(arquivo, armazem):
    linhas = list(armazem.registros.values())
    confronto = sinapi.confrontar(linhas, arquivo)
    assert confronto.conferidos == confronto.iguais == len(linhas)
    assert confronto.divergentes == []


def test_linha_do_indice_que_difere_da_planilha_e_denunciada(arquivo, armazem):
    linhas = [dict(l) for l in armazem.registros.values()]
    alvo = next(l for l in linhas if l["codigo"] == "104658" and l["aba"] == "CSD")
    alvo["valor"] = "189.33"
    confronto = sinapi.confrontar(linhas, arquivo)
    assert confronto.iguais == len(linhas) - 1
    assert confronto.divergentes == [{"aba": "CSD", "linha": 11, "codigo": "104658",
                                      "indice": "189.33", "oficial": "189.32"}]


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def test_consulta_por_codigo_traz_os_tres_regimes_com_a_origem(armazem):
    achados = sinapi.consultar(armazem.buscar, codigo="104658", regime=None)
    assert sorted((x["regime"], x["valor"]) for x in achados) == [
        ("com_desoneracao", "186.58"), ("sem_desoneracao", "189.32"),
        ("sem_encargos", "169")]
    x = next(x for x in achados if x["regime"] == "sem_desoneracao")
    assert x["natureza"] == "custo_referencia_engenharia"
    assert "não preço de compra" in x["rotulo_natureza"]
    assert (x["rotulo_tipo"], x["rotulo_regime"]) == ("composição", "sem desoneração")
    assert (x["competencia_exibicao"], x["uf"], x["unidade"]) == ("10/2026", "PA", "M2")
    assert x["url_verificacao"] == URL and x["url_fonte"] == sinapi.URL_PAGINA
    assert (x["aba"], x["linha_planilha"]) == ("CSD", 11)


def test_consulta_por_termos_com_filtros(armazem):
    [cimento, *_] = sinapi.consultar(armazem.buscar, termo="Cimento Portland composto",
                                     tipo="insumo")
    assert cimento["codigo"] == "1379" and cimento["rotulo_origem"] == "coletado"
    assert {x["tipo"] for x in sinapi.consultar(armazem.buscar, termo="piso podotátil")} \
        == {"composicao"}
    assert sinapi.consultar(armazem.buscar, termo="cimento", tipo="composicao") == []
    assert sinapi.consultar(armazem.buscar, termo="cimento", competencia="2026-09") == []
    assert sinapi.consultar(armazem.buscar, termo="cimento", uf="SP") == []
    assert sinapi.consultar(armazem.buscar, termo="de a") == []


@pytest.mark.parametrize("filtros", [
    {"codigo": "10465A"}, {"uf": "XX"}, {"competencia": "2026-13"},
    {"tipo": "servico"}, {"regime": "desonerado"},
])
def test_consulta_recusa_filtro_fora_da_regra(armazem, filtros):
    with pytest.raises(ValueError):
        sinapi.consultar(armazem.buscar, termo="cimento", **filtros)


# ---------------------------------------------------------------------------
# Fora da cesta de compras e fechado por padrão
# ---------------------------------------------------------------------------
def test_sinapi_nunca_entra_na_cesta_de_precos_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    registro = fontes_externas.REGISTRO["sinapi"]
    monkeypatch.setitem(fontes_externas.REGISTRO, "sinapi", dataclasses.replace(
        registro, licenca=fontes_externas.Licenca.APROVADA, prova_licenca="teste"))
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    assert fontes_externas.habilitada("sinapi")
    nomes = [type(f).__name__.lower() + getattr(getattr(f, "fonte", None), "id", "")
             for f in cotacoes._fontes_padrao()]
    assert not any("sinapi" in n for n in nomes)


def test_consulta_nasce_fechada_e_so_a_flag_nao_abre():
    registro = fontes_externas.REGISTRO["sinapi"]
    assert registro.flag == "price_source_sinapi" and registro.mapeamento_confirmado
    assert registro.licenca is fontes_externas.Licenca.NAO_AVALIADA
    assert not registro.prova_licenca
    assert not fontes_externas.habilitada("sinapi", flag_ativa=lambda nome: True)
    assert registro.downloads == (URL,)


# ---------------------------------------------------------------------------
# Download
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

    def __exit__(self, *a):
        self.close()


def test_laco_de_redirecionamento_da_caixa_e_tentado_de_novo(tmp_path, arquivo):
    tentativas = []
    dados = arquivo.read_bytes()

    def abrir(requisicao):
        tentativas.append(requisicao.full_url)
        if len(tentativas) == 1:
            raise urllib.error.HTTPError(requisicao.full_url, 302, "laço", {}, None)
        return _Resposta(dados, requisicao.full_url)

    snap = sinapi_servico.baixar(COMPETENCIA, tmp_path / "s.zip", abrir=abrir,
                                 dormir=lambda s: None)
    assert len(tentativas) == 2 and tentativas[0] == URL
    assert snap.sha256 == arquivos.sha256_do_arquivo(arquivo)


def test_outro_erro_http_nao_e_mascarado(tmp_path):
    def abrir(requisicao):
        raise urllib.error.HTTPError(requisicao.full_url, 404, "não há", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        sinapi_servico.baixar("2030-01", tmp_path / "s.zip", abrir=abrir,
                              dormir=lambda s: None)
