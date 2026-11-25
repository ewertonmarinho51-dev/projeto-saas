"""
SICRO (DNIT) — custo referencial de obras de transportes, em consulta própria.

A amostra é REAL: os sete relatórios sintéticos em XLSX do `pa-07-2026.7z`
oficial (sha256 3a545a7d…2592de5), recortados nas linhas de 17 referências e
três casos de recusa, com o cabeçalho de cada um intacto
(`fixtures/fontes_precos/sicro_pa_2026_07/`), e o mesmo conjunto num 7-Zip
(`sicro_pa_2026_07.7z`). O arquivo inteiro foi confrontado com os PDFs da
mesma edição: 10.737 valores de 10.737 iguais.

Provas:
* leitura: composição sem desoneração, material sem encargos, mão de obra e
  equipamento nos dois regimes, improdutivo, origem do preço na UF;
* recusas: "-", preço zerado, linha repetida idêntica, código repetido com
  valor diferente, código fora da forma, valor ilegível;
* conferências: cabeçalho, relatório faltando, UF/competência dos nomes;
* importação idempotente, por versão, recusa de arquivo que encolheu;
* consulta: filtros, material em qualquer regime, rastreabilidade;
* confronto com o PDF; descoberta no portal; extração do 7-Zip.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from src import db, governanca
from src.precos import arquivos, cotacoes, sicro, sicro_servico
from tests.cotacoes_apoio import ligar_banco_falso

FIX = Path(__file__).parent / "fixtures" / "fontes_precos"
AMOSTRA = FIX / "sicro_pa_2026_07"
SETE_ZIP = FIX / "sicro_pa_2026_07.7z"
URL = (sicro.URL_RELATORIOS + "norte/para/2026/julho/pa-07-2026.7z")
SHA = "3a545a7d0a71d20dc5c72cb02bd9d921639922b18af2b1ae6b2a71cab2592de5"


def _pasta(tmp_path: Path, mudar=None, nome: str = "rel") -> Path:
    """A amostra copiada; `mudar(relatorio, aba)` altera cada planilha."""
    destino = tmp_path / nome
    shutil.copytree(AMOSTRA, destino)
    if mudar:
        for caminho in destino.glob("*.xlsx"):
            livro = openpyxl.load_workbook(caminho)
            relatorio = caminho.name.removeprefix("PA 07-2026 Relatório Sintético de ") \
                .removesuffix(".xlsx")
            if mudar(relatorio, livro.active) is not False:
                livro.save(caminho)
    return destino


def _ler(pasta, leitura=None) -> dict:
    return {(l["tipo"], l["regime"], l["codigo"]): l
            for l in sicro.ler(pasta, uf="PA", competencia="2026-07", leitura=leitura)}


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_os_seis_relatorios_com_o_valor_exato(tmp_path):
    leitura = sicro.Leitura()
    r = _ler(_pasta(tmp_path), leitura)
    assert (leitura.linhas, leitura.validas) == (21, 17)
    composicao = r[("composicao", "sem_desoneracao", "1106050")]
    assert composicao["valor"] == Decimal("65.12") and composicao["unidade"] == "m³"
    assert composicao["descricao"].startswith("Lançamento livre de concreto usinado")
    assert composicao["origem_preco"] is None and composicao["valor_improdutivo"] is None
    assert composicao["planilha"] == "PA 07-2026 Relatório Sintético de Composições de Custos.xlsx"
    assert r[("material", "nao_se_aplica", "M0004")]["valor"] == Decimal("6.5605")
    # mão de obra: quatro casas, e o regime muda o valor
    assert r[("mao_de_obra", "sem_desoneracao", "P9801")]["valor"] == Decimal("24.8197")
    assert r[("mao_de_obra", "com_desoneracao", "P9801")]["valor"] == Decimal("23.6691")
    # equipamento: produtivo e improdutivo, unidade hora
    equipamento = r[("equipamento", "sem_desoneracao", "E9009")]
    assert (equipamento["valor"], equipamento["valor_improdutivo"]) == (
        Decimal("489.8398"), Decimal("149.9339"))
    assert equipamento["unidade"] == "h" and equipamento["origem_preco"] == "PRE"
    # o equipamento composto (sem colunas de custo de propriedade) também
    assert r[("equipamento", "com_desoneracao", "E9013")]["valor"] == Decimal("760.2139")


def test_composicao_e_so_sem_desoneracao_e_material_sem_encargos(tmp_path):
    r = _ler(_pasta(tmp_path))
    assert {k[1] for k in r if k[0] == "composicao"} == {"sem_desoneracao"}
    assert {k[1] for k in r if k[0] == "material"} == {"nao_se_aplica"}
    assert {k[1] for k in r if k[0] in ("mao_de_obra", "equipamento")} == {
        "sem_desoneracao", "com_desoneracao"}


def test_origem_do_preco_vem_da_coluna_da_uf(tmp_path):
    r = _ler(_pasta(tmp_path))
    assert r[("material", "nao_se_aplica", "M0003")]["origem_preco"] == "PC"
    assert r[("material", "nao_se_aplica", "M0004")]["origem_preco"] == "PCT"
    assert r[("mao_de_obra", "com_desoneracao", "P9801")]["origem_preco"] == "SDP"
    assert sicro.ORIGENS["PFM"] == "preço com frete metodológico"


def test_recusas_com_motivo(tmp_path):
    leitura = sicro.Leitura()
    r = _ler(_pasta(tmp_path), leitura)
    assert dict(leitura.recusas) == {sicro.PRECO_ZERADO: 1, sicro.SEM_PRECO: 1,
                                     sicro.REPETIDA_IDENTICA: 2}
    assert ("composicao", "sem_desoneracao", "0307730") not in r      # zerada
    assert ("material", "nao_se_aplica", "M0104") not in r            # "-"
    motivos = {(x["codigo"], x["motivo"]) for x in leitura.recusadas}
    assert ("0307730", sicro.PRECO_ZERADO) in motivos and ("M0104", sicro.SEM_PRECO) in motivos


def test_codigo_repetido_com_valor_diferente_sai_inteiro(tmp_path):
    def mudar(relatorio, aba):
        if relatorio != "Materiais":
            return False
        aba.append(["M0004", "Aço CA 50", "kg", 9.99])

    leitura = sicro.Leitura()
    r = _ler(_pasta(tmp_path, mudar), leitura)
    assert ("material", "nao_se_aplica", "M0004") not in r
    assert ("material", "nao_se_aplica", "M0003") in r
    assert leitura.recusas[sicro.CODIGO_REPETIDO] == 1


@pytest.mark.parametrize("celula, motivo", [
    ("M00X4", sicro.CODIGO_INVALIDO), ("1106050", sicro.CODIGO_INVALIDO),
])
def test_codigo_fora_da_forma_do_tipo(tmp_path, celula, motivo):
    def mudar(relatorio, aba):
        if relatorio != "Materiais":
            return False
        aba["A2"] = celula

    leitura = sicro.Leitura()
    _ler(_pasta(tmp_path, mudar), leitura)
    assert leitura.recusas[motivo] == 1


@pytest.mark.parametrize("valor", [1.23456, -2.5, "abc", "1,50", True])
def test_valor_ilegivel_e_recusado(tmp_path, valor):
    def mudar(relatorio, aba):
        if relatorio != "Materiais":
            return False
        aba["D2"] = valor

    leitura = sicro.Leitura()
    r = _ler(_pasta(tmp_path, mudar), leitura)
    assert leitura.recusas[sicro.VALOR_ILEGIVEL] == 1
    assert ("material", "nao_se_aplica", "M0003") not in r


def test_cabecalho_diferente_nao_le_nada(tmp_path):
    def mudar(relatorio, aba):
        if relatorio != "Equipamentos":
            return False
        aba["J1"] = "Custo Improdutivo\n (R$/h)"          # colunas trocadas

    with pytest.raises(sicro.LeiauteInesperado, match="cabeçalho"):
        list(sicro.ler(_pasta(tmp_path, mudar), uf="PA", competencia="2026-07"))


def test_relatorio_faltando_ou_de_outra_edicao(tmp_path):
    pasta = _pasta(tmp_path)
    (pasta / "PA 07-2026 Relatório Sintético de Materiais.xlsx").unlink()
    with pytest.raises(sicro.LeiauteInesperado, match="Materiais"):
        list(sicro.ler(pasta, uf="PA", competencia="2026-07"))
    outra = _pasta(tmp_path, nome="outra")
    (outra / "PA 07-2026 Relatório Sintético de Materiais.xlsx").rename(
        outra / "PA 04-2026 Relatório Sintético de Materiais.xlsx")
    with pytest.raises(sicro.LeiauteInesperado, match="não é de PA 07/2026"):
        list(sicro.ler(outra, uf="PA", competencia="2026-07"))
    with pytest.raises(sicro.LeiauteInesperado):
        list(sicro.ler(_pasta(tmp_path, nome="am"), uf="AM", competencia="2026-07"))


def test_origem_sem_a_coluna_da_uf_e_recusada(tmp_path):
    def mudar(relatorio, aba):
        if relatorio != "Origem de Preços do SICRO":
            return False
        for celula in aba[5]:
            if celula.value == "PA":
                celula.value = "XX"

    with pytest.raises(sicro.LeiauteInesperado, match="coluna PA"):
        list(sicro.ler(_pasta(tmp_path, mudar), uf="PA", competencia="2026-07"))


# ---------------------------------------------------------------------------
# Importação por versão
# ---------------------------------------------------------------------------
def _importar(armazem, pasta, sha=SHA, arquivo="pa-07-2026.7z", url=URL):
    return sicro.importar(armazem, pasta, uf="PA", competencia="2026-07", sha256=sha,
                          url=url, arquivo=arquivo)


def test_importa_publica_e_reimportar_nao_duplica(tmp_path):
    armazem = sicro.ArmazemEmMemoria()
    feito = _importar(armazem, _pasta(tmp_path))
    assert (feito.desfecho, feito.validas) == (sicro.PUBLICADO, 17)
    assert len(armazem.registros) == 17 and all(l["vigente"] for l in armazem.registros.values())
    assert armazem.versao_publicada("2026-07", "PA")["url"] == URL
    assert _importar(armazem, _pasta(tmp_path, nome="de-novo")).desfecho == "ja_publicado"
    assert len(armazem.registros) == 17


def test_linha_do_indice_guarda_rastreabilidade(tmp_path):
    armazem = sicro.ArmazemEmMemoria()
    _importar(armazem, _pasta(tmp_path))
    [l] = [x for x in armazem.registros.values()
           if (x["codigo"], x["regime"]) == ("E9009", "com_desoneracao")]
    assert (l["valor"], l["valor_improdutivo"]) == ("481.7889", "141.883")
    assert l["chave_linha"] == "2026-07:PA:equipamento:com_desoneracao:E9009"
    assert l["planilha"] == "PA 07-2026 Relatório Sintético de Equipamentos - com desoneração.xlsx"
    assert (l["linha_planilha"], l["url_arquivo"], l["arquivo"]) == (2, URL, "pa-07-2026.7z")
    assert l["arquivo_sha256"] == SHA and len(l["registro_id"]) == 40
    assert "e9009" in l["descricao_busca"].split() and l["hash_linha"]


def test_edicao_revisada_substitui_a_anterior_inteira(tmp_path):
    armazem = sicro.ArmazemEmMemoria()
    _importar(armazem, _pasta(tmp_path))

    def reajuste(relatorio, aba):
        if relatorio != "Materiais":
            return False
        aba["D2"] = 7.5

    feito = _importar(armazem, _pasta(tmp_path, reajuste, nome="rev"), sha="b" * 64,
                      arquivo="pa-07-2026-revisado.7z",
                      url=URL.replace(".7z", "-revisado.7z"))
    assert feito.desfecho == sicro.PUBLICADO and feito.validas_na_versao_anterior == 17
    vigentes = [l for l in armazem.registros.values() if l["vigente"]]
    assert len(vigentes) == 17 and {l["arquivo_sha256"] for l in vigentes} == {"b" * 64}
    [aco] = sicro.consultar(armazem.buscar, codigo="M0003")
    assert aco.valor == Decimal("7.5") and aco.arquivo == "pa-07-2026-revisado.7z"
    assert sum(v["vigente"] for v in armazem.versoes.values()) == 1


def test_edicao_que_encolheu_demais_e_recusada(tmp_path):
    armazem = sicro.ArmazemEmMemoria()
    _importar(armazem, _pasta(tmp_path))

    def encolher(relatorio, aba):
        if relatorio == "Origem de Preços do SICRO":
            return False
        aba.delete_rows(3, aba.max_row)

    feito = _importar(armazem, _pasta(tmp_path, encolher, nome="menor"), sha="c" * 64)
    assert feito.desfecho == sicro.RECUSADO and "redução" in feito.motivo
    assert {l["arquivo_sha256"] for l in armazem.registros.values() if l["vigente"]} == {SHA}


def test_edicao_sem_referencia_valida_e_recusada(tmp_path):
    def esvaziar(relatorio, aba):
        if relatorio == "Origem de Preços do SICRO":
            return False
        aba.delete_rows(2, aba.max_row)

    armazem = sicro.ArmazemEmMemoria()
    assert _importar(armazem, _pasta(tmp_path, esvaziar)).desfecho == sicro.RECUSADO
    assert armazem.registros == {}


@pytest.mark.parametrize("url, arquivo", [
    ("https://exemplo.com/pa-07-2026.7z", "pa-07-2026.7z"),
    ("http://www.gov.br/dnit/pt-br/assuntos/planejamento-e-pesquisa/custos-referenciais/"
     "sistemas-de-custos/sicro/relatorios/relatorios-sicro/x.7z", "pa-07-2026.7z"),
    (URL, "am-07-2026.7z"), (URL, "pa-04-2026.7z"), (URL, "pa-07-2026.zip"),
    (URL + "?x=1", "pa-07-2026.7z"),
])
def test_origem_fora_da_publicacao_nao_importa(tmp_path, url, arquivo):
    with pytest.raises(ValueError):
        _importar(sicro.ArmazemEmMemoria(), _pasta(tmp_path), url=url, arquivo=arquivo)


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@pytest.fixture
def importado(tmp_path):
    armazem = sicro.ArmazemEmMemoria()
    _importar(armazem, _pasta(tmp_path))
    return armazem


def test_consulta_por_termo_e_por_codigo(importado):
    achados = sicro.consultar(importado.buscar, termo="concreto usinado")
    assert {a.codigo for a in achados} == {"1106050", "1106051"}
    [p] = sicro.consultar(importado.buscar, codigo="e9009")
    assert p.valor == Decimal("489.8398") and p.valor_improdutivo == Decimal("149.9339")
    assert p.rotulo_tipo == "Equipamento" and p.rotulo_origem == "preço referencial estimado"
    assert p.identificacao == "SICRO Equipamento E9009 — PA 07/2026"
    assert p.natureza == "custo_referencial" and p.url_arquivo == URL


def test_regime_filtra_mas_material_aparece_nos_dois(importado):
    sem = sicro.consultar(importado.buscar, termo="ajudante aco", regime=sicro.SEM_DESONERACAO)
    com = sicro.consultar(importado.buscar, termo="ajudante aco", regime=sicro.COM_DESONERACAO)
    assert {(a.codigo, a.valor) for a in sem if a.tipo == "mao_de_obra"} == {
        ("P9801", Decimal("24.8197")), ("P9802", Decimal("28.727"))}
    assert {(a.codigo, a.valor) for a in com if a.tipo == "mao_de_obra"} == {
        ("P9801", Decimal("23.6691")), ("P9802", Decimal("27.3475"))}
    assert {a.codigo for a in sem if a.tipo == "material"} == \
        {a.codigo for a in com if a.tipo == "material"} == {"M0003", "M0004"}
    # composição não existe com desoneração
    assert sicro.consultar(importado.buscar, codigo="1106050",
                           regime=sicro.COM_DESONERACAO) == []


def test_filtro_por_tipo(importado):
    assert {a.tipo for a in sicro.consultar(importado.buscar, termo="ajudante aco",
                                            tipo=sicro.MATERIAL)} == {"material"}


@pytest.mark.parametrize("filtros", [
    {"codigo": "110605"}, {"codigo": "X0004"}, {"codigo": "M00045"}, {"uf": "XX"},
    {"competencia": "07/2026"}, {"regime": "sem_encargos"}, {"tipo": "servico"},
])
def test_filtro_fora_da_regra_nao_vai_ao_indice(filtros):
    chamadas = []
    with pytest.raises(ValueError):
        sicro.consultar(lambda *a, **k: chamadas.append(a) or [], termo="x", **filtros)
    assert chamadas == []


def test_linha_sem_rastreabilidade_nao_chega_a_tela(importado):
    [boa] = [l for l in importado.registros.values() if l["codigo"] == "M0004"]
    ruins = [{**boa, "url_arquivo": "https://exemplo.com/x.7z"}, {**boa, "valor": "0"},
             {**boa, "valor": "-1"}, {**boa, "valor_improdutivo": "-1"},
             {**boa, "codigo": "1106050"}, {**boa, "valor": "NaN"},
             {k: v for k, v in boa.items() if k != "planilha"}]
    assert [r.codigo for r in sicro.consultar(lambda *a, **k: ruins + [boa],
                                              termo="aco")] == ["M0004"]


def test_sicro_nao_e_fonte_da_cesta_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    nomes = [type(f).__name__ for f in cotacoes._fontes_padrao()]
    assert not any("SICRO" in n.upper() for n in nomes)
    assert governanca.FLAG_REFERENCIA_SICRO == "referencia_custos_sicro"


def test_repositorio_le_pela_rpc_com_o_token_do_usuario(monkeypatch):
    from src.precos import repositorio as repo

    cliente = ligar_banco_falso(monkeypatch)
    repo.buscar_sicro(["concreto"], codigo="m0004", uf="pa",
                      regime=sicro.COM_DESONERACAO, tipo=sicro.MATERIAL, limite=20)
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_sicro_buscar"
    assert parametros == {"p_termos": ["concreto"], "p_codigo": "M0004", "p_uf": "PA",
                          "p_competencia": None, "p_regime": "com_desoneracao",
                          "p_tipo": "material", "p_limite": 20}


# ---------------------------------------------------------------------------
# Confronto com o PDF oficial
# ---------------------------------------------------------------------------
# As linhas como o `pymupdf` as extrai das páginas oficiais de jul/2026
PDF_COMPOSICOES = ["SISTEMA DE CUSTOS REFERENCIAIS DE OBRAS - SICRO",
                   "Relatório Sintético de Composições de Custos", "Pará - julho/2026",
                   "Código", "Descrição do Serviço", "Unidade", "Custo Unitário", "(R$)",
                   "1106050", "Lançamento livre de concreto usinado por meio de caminhão",
                   "betoneira - confecção em central dosadora de 30 m³/h", "m³", "65,12",
                   "0308313", "Aparelho de apoio", "un", "31.434,19", "223/223"]
PDF_EQUIPAMENTOS = ["E9013", "Caminhão tanque de asfalto com capacidade de 31.000 l - 368 kW",
                    "762,6573", "182,2997",
                    "A9335 Cavalo mecânico estradeiro 8 x 2, PBT 29.000 kg - 368 kW",
                    "1.113.599,3081", "66,8160", "20,6127", "8,3520", "100,2239",
                    "441,8524", "42,3328", "680,1898", "138,1135"]


def test_le_o_pdf_independente_do_xlsx():
    assert sicro.valores_do_pdf(PDF_COMPOSICOES) == {
        "1106050": Decimal("65.12"), "0308313": Decimal("31434.19")}
    # componente A#### com a descrição na mesma linha; produtivo e improdutivo
    assert sicro.valores_do_pdf(PDF_EQUIPAMENTOS, posicao=-2) == {
        "E9013": Decimal("762.6573"), "A9335": Decimal("680.1898")}
    assert sicro.valores_do_pdf(PDF_EQUIPAMENTOS)["A9335"] == Decimal("138.1135")


def test_confronto_aponta_divergencia_e_ausencia():
    linhas = [{"codigo": "1106050", "valor": "65.12"}, {"codigo": "0308313", "valor": "31434.20"},
              {"codigo": "9999999", "valor": "1"}]
    relato = sicro.confrontar_com_pdf(linhas, sicro.valores_do_pdf(PDF_COMPOSICOES))
    assert (relato.conferidas, relato.iguais) == (3, 1)
    assert relato.divergentes == [{"codigo": "0308313", "xlsx": "31434.20", "pdf": "31434.19"}]
    assert relato.ausentes_no_pdf == ["9999999"]


# ---------------------------------------------------------------------------
# Portal do DNIT e 7-Zip
# ---------------------------------------------------------------------------
REGIAO = "".join(f'<a href="{sicro.URL_RELATORIOS}{c}">x</a>' for c in (
    "norte/para/2026/abril/abril-2026", "norte/para/2026/julho/julho-2026",
    "norte/para/2025/outubro-2025/outubro-2025",
    "norte/para/2025/outubro-2025/outubro-2025-revisado",
    "norte/amapa/2026/julho/julho-2026", "norte/para/2026/julho/julho-2026/../../x"))
PAGINA = (f'<a href="{sicro.URL_RELATORIOS}norte/para/2026/julho/pa-07-2026.7z">Julho/2026</a>'
          '<a href="https://exemplo.com/pa-07-2026.7z">x</a>')


def test_descobre_a_pagina_da_edicao_e_prefere_a_revisada():
    assert sicro_servico.pagina_da_edicao(REGIAO, "PA", "2026-07") == \
        sicro.URL_RELATORIOS + "norte/para/2026/julho/julho-2026"
    assert sicro_servico.pagina_da_edicao(REGIAO, "PA", "2025-10").endswith(
        "outubro-2025/outubro-2025-revisado")
    assert sicro_servico.pagina_da_edicao(REGIAO, "PA", "2026-10") is None
    assert sicro_servico.pagina_da_edicao(REGIAO, "AP", "2026-07").endswith(
        "norte/amapa/2026/julho/julho-2026")


def test_o_7zip_vem_da_mesma_pasta_da_pagina_e_com_o_nome_oficial():
    pagina = sicro.URL_RELATORIOS + "norte/para/2026/julho/julho-2026"
    assert sicro_servico.arquivo_da_edicao(PAGINA, pagina, "PA", "2026-07") == URL
    assert sicro_servico.arquivo_da_edicao(PAGINA, pagina, "PA", "2026-04") is None
    fora = PAGINA.replace("norte/para/2026/julho/pa", "norte/para/2026/abril/pa")
    assert sicro_servico.arquivo_da_edicao(fora, pagina, "PA", "2026-07") is None


def test_descobrir_le_a_regiao_e_a_pagina(tmp_path):
    lidas = []

    def ler(url, pasta):
        lidas.append(url)
        return REGIAO if url.endswith("norte/norte") else PAGINA

    assert sicro_servico.descobrir("PA", "2026-07", tmp_path, ler=ler) == (
        sicro.URL_RELATORIOS + "norte/para/2026/julho/julho-2026", URL)
    assert lidas[0] == sicro.URL_RELATORIOS + "norte/norte"
    with pytest.raises(SystemExit, match="ainda não publicou"):
        sicro_servico.descobrir("PA", "2027-01", tmp_path, ler=ler)


def test_baixador_so_alcanca_a_arvore_do_sicro():
    assert arquivos.url_permitida(URL)
    for ruim in ("https://www.gov.br/dnit/pt-br/outra/coisa.7z",
                 "https://www.gov.br/saude/x.7z", URL + "?a=1",
                 URL.replace("relatorios-sicro/", "relatorios-sicro/../../"),
                 URL.replace("relatorios-sicro/", "relatorios-sicro/%2e%2e/%2E%2E/"),
                 URL.replace("relatorios-sicro/", "relatorios-sicro/..%5c")):
        assert not arquivos.url_permitida(ruim)
        assert not sicro.url_oficial(ruim)


def _extrator_ou_pula():
    try:
        return sicro_servico.extrator()
    except SystemExit:
        pytest.skip("sem bsdtar nem 7z nesta máquina")


def test_extrai_o_7zip_e_importa(tmp_path):
    programa = _extrator_ou_pula()
    pasta = sicro_servico.extrair(SETE_ZIP, tmp_path / "x", programa=programa)
    assert len(list(pasta.glob("*.xlsx"))) == 7
    feito = _importar(sicro.ArmazemEmMemoria(), pasta)
    assert (feito.desfecho, feito.validas) == (sicro.PUBLICADO, 17)


def test_extracao_recusa_pasta_suja_e_arquivo_estranho(tmp_path, monkeypatch):
    programa = ("bsdtar", "tar-falso")
    suja = tmp_path / "suja"
    suja.mkdir()
    (suja / "x").write_text("x")
    monkeypatch.setattr(sicro_servico, "_listar", lambda *a: (7, 1000))
    with pytest.raises(ValueError, match="vazia"):
        sicro_servico.extrair(SETE_ZIP, suja, programa=programa)

    def extrair_estranho(comando, **_):
        destino = Path(comando[comando.index("-C") + 1])
        (destino / "setup.exe").write_bytes(b"MZ")

    monkeypatch.setattr(sicro_servico.subprocess, "run", extrair_estranho)
    with pytest.raises(arquivos.ArquivoRecusado, match="setup.exe"):
        sicro_servico.extrair(SETE_ZIP, tmp_path / "nova", programa=programa)


@pytest.mark.parametrize("entradas, total", [(0, 10), (41, 10), (7, 400_000_001)])
def test_extracao_recusa_7zip_fora_do_teto(tmp_path, monkeypatch, entradas, total):
    monkeypatch.setattr(sicro_servico, "_listar", lambda *a: (entradas, total))
    with pytest.raises(arquivos.ArquivoRecusado):
        sicro_servico.extrair(SETE_ZIP, tmp_path / "x", programa=("bsdtar", "tar-falso"))


def test_linha_de_comando_exige_url_oficial_para_arquivo_local(monkeypatch):
    monkeypatch.setattr(sicro_servico, "extrator", lambda: ("bsdtar", "tar"))
    for argv in (["importar", "--competencia", "2026-07", "--arquivo", str(SETE_ZIP)],
                 ["importar", "--competencia", "2026-07", "--arquivo", str(SETE_ZIP),
                  "--url", "https://exemplo.com/sicro_pa_2026_07.7z"]):
        with pytest.raises(SystemExit, match="--url oficial"):
            sicro_servico.main(argv)


def test_armazem_do_banco_exige_credencial_do_ambiente(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_KEY"):
        sicro_servico.armazem_do_banco()
