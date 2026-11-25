"""
CMED (Anvisa) — teto de medicamentos (PF e PMVG), em consulta própria.

A amostra é REAL: a aba "Cabeçalho" inteira e onze apresentações das listas
PMVG e PMC publicadas em 09/11/2026 17h30
(`fixtures/fontes_precos/cmed_2026_11_09/`), escolhidas pelos casos que mudam
o teto: CAP com e sem isenção, fora do CAP, ICMS 0%, uso hospitalar, análise
recursal, dois EANs, preço liberado. A lista inteira foi lida (26.694 de
26.694) e o PF confrontado com a lista PMC: 694.044 de 694.044 iguais.

Provas:
* leitura: 26 alíquotas, valor exato, asterisco ⇔ isenção declarada;
* a regra do teto: CAP → PMVG, sem CAP → PF (a planilha traz os dois);
* conferências: nome, abas, data do cabeçalho = data do nome, colunas;
* importação idempotente, lista nova substitui, mais antiga é recusada;
* consulta por termo, GGREM, registro e EAN, por alíquota;
* confronto com a lista PMC; descoberta dos links na página oficial.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from src import db, governanca
from src.precos import arquivos, cmed, cmed_servico, cotacoes
from tests.cotacoes_apoio import ligar_banco_falso

FIX = Path(__file__).parent / "fixtures" / "fontes_precos" / "cmed_2026_11_09"
NOME = "lista_pmvg_20261109_111901662.xlsx"
PMVG = FIX / NOME
PMC = FIX / "lista_pmc_20261109_111901662.xlsx"
URL = cmed.PREFIXO_ARQUIVOS + NOME + "/@@download/file"
ORENCIA_SC, ORENCIA_IV, BAYCUTEN = "505113100020505", "505107701157215", "538912020009303"
ABIRATERONA = "507525080028406"


def _copia(tmp_path: Path, mudar=None, nome: str = NOME) -> Path:
    destino = tmp_path / nome
    shutil.copy(PMVG, destino)
    if mudar:
        livro = openpyxl.load_workbook(destino)
        mudar(livro)
        livro.save(destino)
    return destino


def _ler(caminho, leitura=None, nome=None) -> dict:
    return {b["ggrem"]: b for b in cmed.ler(caminho, nome=nome, leitura=leitura)}


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_a_lista_com_as_26_aliquotas_e_o_valor_exato():
    leitura = cmed.Leitura()
    r = _ler(PMVG, leitura)
    assert (leitura.linhas, leitura.validas, dict(leitura.recusas)) == (11, 11, {})
    assert leitura.publicada_em == "2026-11-09T17:30:00-03:00"
    o = r[ORENCIA_SC]
    assert (o["produto"], o["laboratorio"]) == ("ORENCIA", "BRISTOL-MYERS SQUIBB FARMACÊUTICA LTDA")
    assert o["apresentacao"].startswith("125 MG/ML SOL INJ SC CT 4 SER")
    assert list(o["pf"]) == list(cmed.ALIQUOTAS) == list(o["pmvg"])
    assert o["pf"]["sem_impostos"] == Decimal("6662.98") and o["pf"]["0"] == Decimal("6743.91")
    assert (o["pf"]["18"], o["pmvg"]["18"]) == (Decimal("8224.28"), Decimal("6596.70"))
    assert o["pf"]["12_alc"] == Decimal("7571.57")
    assert (o["cap"], o["confaz87"], o["icms_0"]) == (True, True, False)
    assert o["eans"] == ["7896016808197"] and o["registro"] == "1018003900078"
    assert o["linha_planilha"] == 4


def test_flags_e_campos_de_cada_caso():
    r = _ler(PMVG)
    assert r[ABIRATERONA]["icms_0"] is True and r[ABIRATERONA]["confaz87"] is False
    assert r["521401102151314"]["restricao_hospitalar"] is True
    assert r["504126090096507"]["analise_recursal"] == "(AR)"
    assert r["531619040086803"]["eans"] == ["7894916503754", "7896004771793"]
    assert r["508011303163310"]["regime_preco"] == "Liberado"
    assert r[BAYCUTEN]["tarja"] is None                       # "- (*)" na planilha
    assert r[ORENCIA_IV]["tarja"] == "Tarja Vermelha"
    # "Comercialização 2025": a apresentação foi vendida no ano anterior?
    assert r[ORENCIA_IV]["comercializado"] is True and r[ABIRATERONA]["comercializado"] is False


def test_asterisco_e_a_marca_da_isencao_e_sai_do_valor(tmp_path):
    def marcar_sem_isencao(livro):
        aba = livro["Lista PMVG"]
        for linha in aba.iter_rows(min_row=2):
            if linha[3].value == BAYCUTEN:
                linha[20].value = str(linha[20].value) + "*"

    leitura = cmed.Leitura()
    r = _ler(_copia(tmp_path, marcar_sem_isencao), leitura)
    assert BAYCUTEN not in r and leitura.recusas == {cmed.ASTERISCO_INCOERENTE: 1}


@pytest.mark.parametrize("coluna, valor, motivo", [
    (3, "12345", cmed.SEM_GGREM), (20, "37.48", cmed.VALOR_ILEGIVEL),
    (20, "-", cmed.VALOR_ILEGIVEL), (50, "1,234", cmed.VALOR_ILEGIVEL),
    (66, "Talvez", cmed.SIM_NAO_ILEGIVEL), (8, "", cmed.SEM_APRESENTACAO),
])
def test_linha_fora_da_regra_e_recusada_com_motivo(tmp_path, coluna, valor, motivo):
    def mudar(livro):
        for linha in livro["Lista PMVG"].iter_rows(min_row=2):
            if linha[3].value == BAYCUTEN:
                linha[coluna].value = valor

    leitura = cmed.Leitura()
    r = _ler(_copia(tmp_path, mudar), leitura)
    assert BAYCUTEN not in r and len(r) == 10 and leitura.recusas == {motivo: 1}


def test_ggrem_repetido_e_recusado(tmp_path):
    def repetir(livro):
        aba = livro["Lista PMVG"]
        aba.append([c.value for c in aba[2]])

    leitura = cmed.Leitura()
    assert len(_ler(_copia(tmp_path, repetir), leitura)) == 11
    assert leitura.recusas == {cmed.GGREM_REPETIDO: 1}


def test_registro_fora_da_forma_some_e_a_linha_fica(tmp_path):
    def mudar(livro):
        for linha in livro["Lista PMVG"].iter_rows(min_row=2):
            if linha[3].value == BAYCUTEN:
                linha[4].value = "ABC"

    assert _ler(_copia(tmp_path, mudar))[BAYCUTEN]["registro"] is None


# ---------------------------------------------------------------------------
# Conferências do arquivo
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", ["lista_pmc_20261109_111901662.xlsx", "lista_pmvg.xlsx",
                                  "lista_pmvg_20261309_111901662.xlsx",
                                  "lista_pmvg_20261109_111901662.xlsm"])
def test_nome_fora_da_publicacao_e_recusado(nome):
    with pytest.raises((cmed.LeiauteInesperado, ValueError)):
        list(cmed.ler(PMVG, nome=nome))


def test_data_do_cabecalho_tem_de_ser_a_do_nome():
    with pytest.raises(cmed.LeiauteInesperado, match="o nome diz 2026-11-10"):
        list(cmed.ler(PMVG, nome="lista_pmvg_20261110_111901662.xlsx"))


def test_abas_e_colunas_conferidas(tmp_path):
    def trocar_coluna(livro):
        aba = livro["Lista PMVG"]
        aba.cell(row=1, column=40).value = "PMVG 0 % ALC"

    with pytest.raises(cmed.LeiauteInesperado, match="colunas"):
        list(cmed.ler(_copia(tmp_path, trocar_coluna)))

    def renomear(livro):
        livro["Lista PMVG"].title = "Lista PMC"

    outra = tmp_path / "outra"
    outra.mkdir()
    with pytest.raises(cmed.LeiauteInesperado, match="abas"):
        list(cmed.ler(_copia(outra, renomear)))


def test_cabecalho_sem_data_de_publicacao(tmp_path):
    def apagar(livro):
        livro["Cabeçalho"]["A3"] = "Publicada recentemente."

    with pytest.raises(cmed.LeiauteInesperado, match="data de publicação"):
        list(cmed.ler(_copia(tmp_path, apagar)))


# ---------------------------------------------------------------------------
# Importação: uma lista vigente por vez
# ---------------------------------------------------------------------------
def test_importa_publica_e_reimportar_nao_duplica(tmp_path):
    armazem = cmed.ArmazemEmMemoria()
    feito = cmed.importar(armazem, PMVG, url=URL)
    assert (feito.desfecho, feito.validas) == (cmed.PUBLICADO, 11)
    assert feito.publicada_em == "2026-11-09T17:30:00-03:00"
    assert armazem.versao_publicada()["url"] == URL
    assert len(armazem.registros) == 11 and all(l["vigente"] for l in armazem.registros.values())
    assert cmed.importar(armazem, PMVG, url=URL).desfecho == "ja_publicado"
    assert len(armazem.registros) == 11


def test_linha_do_indice_guarda_rastreabilidade():
    armazem = cmed.ArmazemEmMemoria()
    feito = cmed.importar(armazem, PMVG, url=URL)
    [l] = [x for x in armazem.registros.values() if x["ggrem"] == ORENCIA_SC]
    assert l["pf"]["18"] == "8224.28" and l["pmvg"]["18"] == "6596.70"
    assert l["chave_linha"] == f"2026-11-09:{ORENCIA_SC}" and len(l["registro_id"]) == 40
    assert (l["url_arquivo"], l["arquivo"], l["arquivo_sha256"]) == (URL, NOME, feito.sha256)
    assert l["linha_planilha"] == 4 and l["hash_linha"]
    assert {"orencia", "abatacepte"} <= set(l["descricao_busca"].split())


def _lista_de(tmp_path, data: str, reajuste=None) -> tuple[Path, str]:
    nome = f"lista_pmvg_{data.replace('-', '')}_120000000.xlsx"
    dia, mes, ano = data[8:], data[5:7], data[:4]

    def mudar(livro):
        livro["Cabeçalho"]["A3"] = f"Publicada em {dia}/{mes}/{ano} 12h00min."
        if reajuste:
            reajuste(livro)

    return _copia(tmp_path, mudar, nome=nome), cmed.PREFIXO_ARQUIVOS + nome + "/@@download/file"


def test_lista_nova_substitui_a_anterior_inteira(tmp_path):
    armazem = cmed.ArmazemEmMemoria()
    cmed.importar(armazem, PMVG, url=URL)

    def reajuste(livro):
        for linha in livro["Lista PMVG"].iter_rows(min_row=2):
            if linha[3].value == BAYCUTEN:
                linha[21].value = "40,00"

    caminho, url = _lista_de(tmp_path, "2026-11-20", reajuste)
    feito = cmed.importar(armazem, caminho, url=url)
    assert feito.desfecho == cmed.PUBLICADO and feito.validas_na_versao_anterior == 11
    vigentes = [l for l in armazem.registros.values() if l["vigente"]]
    assert len(vigentes) == 11 and {l["arquivo_sha256"] for l in vigentes} == {feito.sha256}
    [b] = cmed.consultar(armazem.buscar, codigo=BAYCUTEN, aliquota="18")
    assert b.pf == Decimal("40.00") and b.publicada_em.startswith("2026-11-20")
    assert sum(v["vigente"] for v in armazem.versoes.values()) == 1


def test_lista_mais_antiga_que_a_vigente_e_recusada(tmp_path):
    armazem = cmed.ArmazemEmMemoria()
    cmed.importar(armazem, PMVG, url=URL)
    # o banco devolve a data em UTC: a comparação é por instante, não por texto
    armazem.versao_publicada()["publicada_em"] = "2026-11-09T20:30:00+00:00"
    caminho, url = _lista_de(tmp_path, "2026-10-01")
    feito = cmed.importar(armazem, caminho, url=url)
    assert feito.desfecho == cmed.RECUSADO and "mais antiga" in feito.motivo
    assert {l["arquivo_sha256"] for l in armazem.registros.values() if l["vigente"]} == \
        {armazem.versao_publicada()["sha256"]}


def test_lista_que_encolheu_demais_e_recusada(tmp_path):
    armazem = cmed.ArmazemEmMemoria()
    cmed.importar(armazem, PMVG, url=URL)
    caminho, url = _lista_de(tmp_path, "2026-11-20",
                             lambda livro: livro["Lista PMVG"].delete_rows(3, 20))
    feito = cmed.importar(armazem, caminho, url=url)
    assert feito.desfecho == cmed.RECUSADO and "redução" in feito.motivo


@pytest.mark.parametrize("url", [
    "https://exemplo.com/" + NOME, cmed.PREFIXO_ARQUIVOS + "lista_pmc_20261109_111901662.xlsx",
    cmed.PREFIXO_ARQUIVOS + "lista_pmvg_20261110_111901662.xlsx", URL + "?x=1",
    cmed.PREFIXO_ARQUIVOS + "%2e%2e/" + NOME, URL.replace("/@@download/file", "/view"),
    URL.replace("https://", "http://"),
])
def test_origem_fora_da_publicacao_nao_importa(url):
    assert not cmed.url_oficial(url) or "20261110" in url or "lista_pmc" in url
    with pytest.raises(ValueError):
        cmed.importar(cmed.ArmazemEmMemoria(), PMVG, url=url)


# ---------------------------------------------------------------------------
# Consulta e a regra do teto
# ---------------------------------------------------------------------------
@pytest.fixture
def importado():
    armazem = cmed.ArmazemEmMemoria()
    cmed.importar(armazem, PMVG, url=URL)
    return armazem


def test_com_cap_o_teto_e_o_pmvg_sem_cap_e_o_pf(importado):
    [cap] = cmed.consultar(importado.buscar, codigo=ORENCIA_SC, aliquota="18")
    assert (cap.pf, cap.pmvg, cap.teto_governo) == (
        Decimal("8224.28"), Decimal("6596.70"), Decimal("6596.70"))
    assert cap.base_do_teto == "PMVG (CAP aplicado ao PF)"
    [sem] = cmed.consultar(importado.buscar, codigo=BAYCUTEN, aliquota="18")
    assert (sem.pf, sem.pmvg, sem.teto_governo) == (
        Decimal("37.48"), Decimal("30.06"), Decimal("37.48"))
    assert sem.base_do_teto == "PF (fora do CAP)"


def test_isento_de_icms_mostra_o_teto_da_coluna_0(importado):
    [cap] = cmed.consultar(importado.buscar, codigo=ORENCIA_SC, aliquota="18")
    assert cap.isento_icms and cap.teto_governo_isento == Decimal("5409.29")
    [abi] = cmed.consultar(importado.buscar, codigo=ABIRATERONA, aliquota="19")
    assert abi.isento_icms and abi.icms_0 and abi.teto_governo_isento == abi.pmvg_isento
    [sem] = cmed.consultar(importado.buscar, codigo=BAYCUTEN, aliquota="18")
    assert not sem.isento_icms


def test_aliquota_muda_o_valor(importado):
    valores = {a: cmed.consultar(importado.buscar, codigo=BAYCUTEN, aliquota=a)[0].pf
               for a in ("0", "12", "12_alc", "19", "23")}
    assert valores == {"0": Decimal("30.73"), "12": Decimal("34.92"),
                       "12_alc": Decimal("31.18"), "19": Decimal("37.94"),
                       "23": Decimal("39.91")}
    assert cmed.rotulo_aliquota("17.5_alc") == "ICMS 17,5% (Área de Livre Comércio)"


def test_busca_por_termo_ggrem_registro_e_ean(importado):
    assert {t.ggrem for t in cmed.consultar(importado.buscar, termo="dipirona sodica")} == {
        "503424050027617", "503426070030817", "504612120014716"}
    assert [t.ggrem for t in cmed.consultar(importado.buscar, codigo="1018003900078")] == [ORENCIA_SC]
    assert [t.ggrem for t in cmed.consultar(importado.buscar, codigo="7896004771793")] == [
        "531619040086803"]                                    # o 2º EAN
    assert cmed.consultar(importado.buscar, codigo="78911060009560") == []


@pytest.mark.parametrize("filtros", [{"aliquota": "19,5"}, {"aliquota": "pmc"},
                                     {"codigo": "1234"}, {"codigo": "1" * 16}])
def test_filtro_fora_da_regra_nao_vai_ao_indice(filtros):
    chamadas = []
    with pytest.raises(ValueError):
        cmed.consultar(lambda *a, **k: chamadas.append(a) or [], termo="dipirona", **filtros)
    assert chamadas == []


def test_linha_sem_rastreabilidade_ou_valor_nao_chega_a_tela(importado):
    [boa] = [l for l in importado.registros.values() if l["ggrem"] == BAYCUTEN]
    ruins = [{**boa, "url_arquivo": "https://exemplo.com/" + NOME},
             {**boa, "pf": {**boa["pf"], "18": "0"}}, {**boa, "pmvg": {**boa["pmvg"], "0": "-1"}},
             {**boa, "pf": {k: v for k, v in boa["pf"].items() if k != "18"}},
             {**boa, "ggrem": "123"}]
    assert [t.ggrem for t in cmed.consultar(lambda *a, **k: ruins + [boa], termo="baycuten",
                                            aliquota="18")] == [BAYCUTEN]


def test_cmed_nao_e_fonte_da_cesta_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    nomes = [type(f).__name__ for f in cotacoes._fontes_padrao()]
    assert not any("CMED" in n.upper() for n in nomes)
    assert governanca.FLAG_REFERENCIA_CMED == "referencia_teto_cmed"


def test_repositorio_le_pela_rpc_com_o_token_do_usuario(monkeypatch):
    from src.precos import repositorio as repo

    cliente = ligar_banco_falso(monkeypatch)
    repo.buscar_cmed(["dipirona"], codigo="7891106000956", limite=20)
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_cmed_buscar"
    assert parametros == {"p_termos": ["dipirona"], "p_codigo": "7891106000956",
                          "p_limite": 20}


# ---------------------------------------------------------------------------
# Confronto com a lista PMC e a página oficial
# ---------------------------------------------------------------------------
def test_pf_confere_com_a_lista_pmc_da_mesma_publicacao():
    relato = cmed.confrontar_pf(list(cmed.ler(PMVG)), cmed.pf_da_lista_pmc(PMC))
    assert (relato.conferidas, relato.iguais, relato.divergentes, relato.ausentes) == (
        11 * 26, 11 * 26, [], [])


def test_confronto_aponta_divergencia_e_ausencia():
    brutas = list(cmed.ler(PMVG))
    da_pmc = cmed.pf_da_lista_pmc(PMC)
    da_pmc[BAYCUTEN]["18"] = Decimal("37.49")
    del da_pmc[ORENCIA_SC]
    relato = cmed.confrontar_pf(brutas, da_pmc)
    assert relato.divergentes == [{"ggrem": BAYCUTEN, "aliquota": "18",
                                   "pmvg": "37.48", "pmc": "37.49"}]
    assert relato.ausentes == [ORENCIA_SC]


PAGINA = (
    # a antiga ANTES da nova: quem vale é a data e a hora do nome, não a ordem
    '<a href="/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/'
    'lista_pmvg_20261020_090000000.xlsx/@@download/file">antiga</a>'
    '<a href="/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/'
    'lista_pmc_20261109_111901662.xlsx/@@download/file">PMC</a>'
    '<a href="/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/'
    'lista_pmvg_20261109_111901662.xlsx/@@download/file">PMVG</a>'
    '<a href="https://exemplo.com/anvisa/pt-br/assuntos/medicamentos/cmed/precos/arquivos/'
    'lista_pmvg_20991231_000000000.xlsx/@@download/file">fora</a>')


def test_descobre_a_lista_mais_recente_na_pagina_oficial():
    listas = cmed_servico.listas_da_pagina(PAGINA)
    assert listas == {
        "pmc": cmed.PREFIXO_ARQUIVOS + "lista_pmc_20261109_111901662.xlsx/@@download/file",
        "pmvg": URL}
    assert cmed.url_oficial(listas["pmvg"]) and arquivos.url_permitida(listas["pmvg"])
    assert cmed_servico.nome_da_url(URL) == NOME


def test_so_a_lista_pmvg_na_pasta_oficial_e_endereco_valido():
    assert cmed.url_oficial(URL) and cmed.url_oficial(URL.removesuffix("/@@download/file"))
    for ruim in ("https://exemplo.com/" + NOME, URL.replace("pmvg", "pmc"), URL + "?a=1",
                 URL.replace("/@@download/file", "/view"), cmed.PREFIXO_ARQUIVOS,
                 cmed.PREFIXO_ARQUIVOS + "%2e%2e/" + NOME, URL.replace("https", "http"),
                 cmed.PREFIXO_ARQUIVOS + "lista_pmvg_2026_1.xlsx"):
        assert not cmed.url_oficial(ruim), ruim


def test_baixador_so_alcanca_a_pagina_de_precos_da_cmed():
    assert arquivos.url_permitida(cmed.URL_PAGINA)
    for ruim in ("https://www.gov.br/anvisa/pt-br/outra/x.xlsx", cmed.URL_PAGINA + "x/y",
                 cmed.PREFIXO_ARQUIVOS + "%2e%2e/x", URL + "?a=1",
                 cmed.PREFIXO_ARQUIVOS + "../../../saude/x"):
        assert not arquivos.url_permitida(ruim)


def test_linha_de_comando_exige_url_oficial_para_arquivo_local():
    for argv in (["importar", "--arquivo", str(PMVG)],
                 ["importar", "--arquivo", str(PMVG), "--url", "https://exemplo.com/" + NOME]):
        with pytest.raises(SystemExit, match="--url oficial"):
            cmed_servico.main(argv)


def test_importar_por_linha_de_comando(capsys):
    assert cmed_servico.main(["importar", "--arquivo", str(PMVG), "--url", URL]) == 0
    saida = capsys.readouterr().out
    assert '"desfecho": "publicado"' in saida and '"validas": 11' in saida


def test_armazem_do_banco_exige_credencial_do_ambiente(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_KEY"):
        cmed_servico.armazem_do_banco()
