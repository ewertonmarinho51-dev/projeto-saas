"""
SEOP-PA — Planilha Padrão em PDF, importação SUPERVISIONADA (23/11/2026).

A fixture é o texto REAL, extraído pelo PyMuPDF, de páginas dos dois PDFs
oficiais de outubro de 2026 (`fixtures/fontes_precos/seop_pa_2026_10_paginas.json`):
as páginas 1, 2 e 48 da Planilha Padrão e as páginas do PDF analítico em que
estão as composições daquelas linhas — cada uma no seu número de página
original. Nenhuma rede.

O que estas provas guardam:

* o cabeçalho da publicação (competência, BDI, desoneração, leis sociais) é
  lido e conferido; PDF de outro mês ou sem cabeçalho não é lido;
* cada linha sai com item, código, descrição (mesmo quebrada em duas linhas),
  unidade, valor exato e a PÁGINA do PDF; valor zero e código repetido são
  recusados e contados, com a página;
* cada linha é confrontada com a composição de mesmo código no PDF analítico;
* importar só põe a versão EM CONFERÊNCIA: nada aparece na consulta até uma
  pessoa aprovar; com divergência, a aprovação exige aceitá-la;
* republicação da competência é versão nova, que só vale quando aprovada;
* nunca entra na cesta de preços de compras.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from src import db, governanca
from src.precos import arquivos, cotacoes, seop
from tests.cotacoes_apoio import ligar_banco_falso

FIX = json.loads((Path(__file__).parent / "fixtures" / "fontes_precos" /
                  "seop_pa_2026_10_paginas.json").read_text("utf-8"))
COMPETENCIA = "2026-10"
URL = FIX["_origem"]["planilha"]
URL_ANALITICO = FIX["_origem"]["analitico"]


def _paginas(fonte: dict, total: int, trocas: dict | None = None) -> list[str]:
    """As páginas do PDF com o texto real onde a fixture tem; vazias no resto
    (o número da página continua o do original)."""
    paginas = [fonte.get(str(n), "") for n in range(1, total + 1)]
    for n, (de, para) in (trocas or {}).items():
        assert de in paginas[n - 1], (n, de)
        paginas[n - 1] = paginas[n - 1].replace(de, para, 1)
    return paginas


PLANILHA = _paginas(FIX["planilha"], FIX["paginas_planilha"])
ANALITICO = _paginas(FIX["analitico"], FIX["paginas_analitico"])


def _ler(textos=PLANILHA, competencia=COMPETENCIA):
    leitura = seop.Leitura()
    linhas = seop.ler_planilha(Path("p.pdf"), competencia, leitura=leitura,
                               textos=textos)
    return linhas, leitura


@pytest.fixture
def pdfs(tmp_path, monkeypatch):
    """Dois arquivos locais (o SHA-256 é o dos bytes) cujo texto é o da
    fixture; `trocar` cria uma republicação com outro texto e outro SHA."""
    textos = {"planilha.pdf": PLANILHA, "cpus.pdf": ANALITICO}
    monkeypatch.setattr(seop, "_paginas", lambda caminho: textos[caminho.name])

    def criar(nome, conteudo, paginas):
        caminho = tmp_path / nome
        caminho.write_bytes(conteudo)
        textos[nome] = paginas
        return caminho

    criar("planilha.pdf", b"planilha-out-2026", PLANILHA)
    criar("cpus.pdf", b"cpus-out-2026", ANALITICO)
    return tmp_path, criar


def _importar(armazem, pasta, planilha="planilha.pdf", analitico="cpus.pdf"):
    return seop.importar(armazem, pasta / planilha, competencia=COMPETENCIA,
                         url=URL, analitico=pasta / analitico if analitico else None,
                         url_analitico=URL_ANALITICO if analitico else None)


# ---------------------------------------------------------------------------
# Leitura da Planilha Padrão
# ---------------------------------------------------------------------------
def test_cabecalho_da_publicacao_e_conferido():
    _, leitura = _ler()
    cab = leitura.cabecalho
    assert (cab.competencia, cab.bdi, cab.desoneracao) == (
        "2026-10", "SEM BDI", "SEM DESONERAÇÃO")
    assert cab.leis_sociais == {"horista": "119,42%", "mensalista": "72,70%"}
    assert leitura.paginas == 48


def test_cada_linha_sai_com_a_pagina_e_o_valor_exato():
    linhas, leitura = _ler()
    por_codigo = {l.codigo: l for l in linhas}
    andaime = por_codigo["011450"]
    assert (andaime.item, andaime.unidade, andaime.valor, andaime.pagina) == (
        "1.1", "m2/mês", Decimal("30.28"), 1)
    # descrição quebrada em duas linhas no PDF
    assert andaime.descricao == ("Aluguel de andaime metálico tipo fachadeiro "
                                 "(incluindo montagem edesmontagem)")
    assert andaime.grupo == "SERVIÇOS PRELIMINARES"
    # separador de milhar
    assert por_codigo["011329"].valor == Decimal("2175.00")
    assert por_codigo["280004"].pagina == 2 and por_codigo["280004"].unidade == "h"
    assert por_codigo["270768"].pagina == 48
    assert por_codigo["270768"].descricao == "Resina p/ piso em korodur"
    assert leitura.validas == len(linhas) and leitura.lidas == len(linhas) + 1


def test_valor_zero_e_recusado_com_a_pagina():
    linhas, leitura = _ler()
    assert "000006" not in {l.codigo for l in linhas}
    assert leitura.motivos == {seop.VALOR_ZERO: 1}
    [recusa] = leitura.recusadas
    assert (recusa["pagina"], recusa["item"], recusa["codigo"]) == (1, "1.18", "000006")
    assert "Mobilização" in recusa["texto"]


def test_codigo_repetido_na_planilha_e_recusado():
    repetida = PLANILHA[:2] + [PLANILHA[0]] + PLANILHA[3:]
    linhas, leitura = _ler(repetida)
    primeira = {l.codigo for l in linhas if l.pagina == 1}
    assert leitura.motivos[seop.CODIGO_REPETIDO] == len(primeira)
    assert all(l.pagina != 3 for l in linhas)


@pytest.mark.parametrize("trocas, mensagem", [
    ({1: ("OUTUBRO 2026", "SETEMBRO 2026"), 2: ("OUTUBRO 2026", "SETEMBRO 2026")},
     "setembro de 2026"),
    ({1: ("PLANILHA PADRÃO", "TABELA"), 2: ("PLANILHA PADRÃO", "TABELA")},
     "cabeçalho"),
    # o Excel repete as leis sociais no topo de toda página: some das duas
    ({1: ("L.S.h", "LS horista"), 2: ("L.S.h", "LS horista")}, "leis sociais"),
])
def test_pdf_fora_do_esperado_nao_e_lido(trocas, mensagem):
    textos = _paginas(FIX["planilha"], FIX["paginas_planilha"], trocas)
    with pytest.raises(seop.ArquivoInvalido, match=mensagem):
        _ler(textos)


def test_competencia_pedida_tem_de_ser_a_do_pdf():
    with pytest.raises(seop.ArquivoInvalido, match="esperado setembro de 2026"):
        _ler(competencia="2026-09")


def test_le_o_pdf_de_verdade(tmp_path):
    import pymupdf

    documento = pymupdf.open()
    pagina = documento.new_page()
    pagina.insert_text((40, 60), "\n".join([
        "L.S.h", "119,42%", "L.S.m", "72,70%",
        "PLANILHA PADRAO - OUTUBRO 2026 (SEM BDI) - SEM DESONERACAO",
        "1", "SERVICOS PRELIMINARES:", "1.1", "011450", "Andaime", "m2", "30,28"]),
        fontsize=9)
    caminho = tmp_path / "planilha.pdf"
    documento.save(caminho)
    linhas = seop.ler_planilha(caminho, COMPETENCIA)
    assert [(l.codigo, l.unidade, l.valor, l.pagina) for l in linhas] == [
        ("011450", "m2", Decimal("30.28"), 1)]


# ---------------------------------------------------------------------------
# Confronto com o PDF analítico
# ---------------------------------------------------------------------------
def test_analitico_traz_o_valor_de_cada_composicao_com_a_pagina():
    analitico = seop.ler_analitico(Path("a.pdf"), textos=ANALITICO)
    assert analitico["011450"] == {"unidade": "m2/mês", "valor": Decimal("30.28"),
                                   "pagina": 1}
    assert analitico["010767"]["valor"] == Decimal("991.94")


def test_cada_linha_da_planilha_bate_com_o_analitico():
    linhas, _ = _ler()
    confronto = seop.confrontar(linhas, seop.ler_analitico(Path("a.pdf"),
                                                           textos=ANALITICO))
    assert confronto.conferidas == confronto.iguais == len(linhas)
    assert confronto.divergentes == []


def test_divergencia_aparece_com_as_duas_paginas():
    alterada = _paginas(FIX["planilha"], FIX["paginas_planilha"],
                        {1: ("\n30,28\n", "\n30,29\n")})
    linhas, _ = _ler(alterada)
    confronto = seop.confrontar(linhas, seop.ler_analitico(Path("a.pdf"),
                                                           textos=ANALITICO))
    assert confronto.motivos == {seop.VALOR_DIVERGENTE: 1}
    [d] = confronto.divergentes
    assert (d["codigo"], d["planilha"], d["analitico"], d["pagina"],
            d["pagina_analitico"]) == ("011450", "30.29", "30.28", 1, 1)
    sem = seop.confrontar(linhas, {})
    assert sem.motivos[seop.SEM_COMPOSICAO] == len(linhas)


# ---------------------------------------------------------------------------
# Importação supervisionada
# ---------------------------------------------------------------------------
def test_importar_so_poe_em_conferencia_e_a_consulta_nao_ve(pdfs):
    pasta, _ = pdfs
    a = seop.ArmazemEmMemoria()
    feito = _importar(a, pasta)
    assert feito.desfecho == seop.EM_CONFERENCIA
    assert feito.cabecalho["bdi"] == "SEM BDI"
    assert feito.confronto["iguais"] == feito.validas == len(a.registros)
    versao = a.versao(COMPETENCIA, feito.sha256)
    assert versao["estado"] == seop.EM_CONFERENCIA and not versao["vigente"]
    assert versao["sha256_analitico"] == arquivos.sha256_do_arquivo(pasta / "cpus.pdf")
    assert versao["recusadas"][0]["codigo"] == "000006"
    # nada visível antes da aprovação
    assert seop.consultar(a.buscar, codigo="011450") == []


def test_aprovacao_publica_com_quem_conferiu(pdfs):
    pasta, _ = pdfs
    a = seop.ArmazemEmMemoria()
    feito = _importar(a, pasta)
    with pytest.raises(seop.AprovacaoRecusada, match="quem conferiu"):
        seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256, por=" ")
    with pytest.raises(seop.AprovacaoRecusada, match="não há versão"):
        seop.aprovar(a, competencia=COMPETENCIA, sha256="f" * 64, por="Ana Souza")
    versao = seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256,
                          por="Ana Souza")
    assert (versao["estado"], versao["vigente"], versao["aprovado_por"]) == (
        seop.PUBLICADO, True, "Ana Souza")
    assert versao["aprovado_em"] and versao["divergencias_aceitas"] == 0
    [x] = seop.consultar(a.buscar, codigo="011450")
    assert (x["valor"], x["unidade"], x["item"], x["pagina"]) == ("30.28", "m2/mês", "1.1", 1)
    assert x["url_verificacao"] == URL + "#page=1"
    assert (x["bdi"], x["desoneracao"]) == ("SEM BDI", "SEM DESONERAÇÃO")
    assert x["natureza"] == "custo_referencia_engenharia"
    assert x["competencia_exibicao"] == "outubro/2026"
    assert "não preço de compra" in x["rotulo_natureza"]
    # aprovar de novo: a versão já não está em conferência
    with pytest.raises(seop.AprovacaoRecusada):
        seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256, por="Ana Souza")


def test_sem_confronto_nao_aprova(pdfs):
    pasta, _ = pdfs
    a = seop.ArmazemEmMemoria()
    feito = _importar(a, pasta, analitico=None)
    with pytest.raises(seop.AprovacaoRecusada, match="analítico"):
        seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256, por="Ana Souza")


def test_divergencia_exige_aceite_explicito(pdfs):
    pasta, criar = pdfs
    criar("divergente.pdf", b"divergente", _paginas(
        FIX["planilha"], FIX["paginas_planilha"], {1: ("\n30,28\n", "\n30,29\n")}))
    a = seop.ArmazemEmMemoria()
    feito = _importar(a, pasta, planilha="divergente.pdf")
    assert len(feito.confronto["divergentes"]) == 1
    [linha] = [l for l in a.registros.values() if l["codigo"] == "011450"]
    assert linha["conferencia"]["motivo"] == seop.VALOR_DIVERGENTE
    with pytest.raises(seop.AprovacaoRecusada, match="1 linha"):
        seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256, por="Ana Souza")
    versao = seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256,
                          por="Ana Souza", aceitar_divergencias=True)
    assert versao["divergencias_aceitas"] == 1


def test_mesmo_pdf_nao_e_importado_de_novo(pdfs):
    pasta, _ = pdfs
    a = seop.ArmazemEmMemoria()
    _importar(a, pasta)
    gravacoes = []
    a.gravar_registros = lambda linhas: gravacoes.append(len(linhas))
    assert _importar(a, pasta).desfecho == "ja_importado" and gravacoes == []


def test_republicacao_so_vale_quando_aprovada(pdfs):
    pasta, criar = pdfs
    a = seop.ArmazemEmMemoria()
    primeira = _importar(a, pasta)
    seop.aprovar(a, competencia=COMPETENCIA, sha256=primeira.sha256, por="Ana Souza")
    # a SEOP republica outubro com o andaime corrigido (e o analítico também)
    criar("planilha2.pdf", b"planilha-out-2026-v2", _paginas(
        FIX["planilha"], FIX["paginas_planilha"], {1: ("\n30,28\n", "\n31,00\n")}))
    criar("cpus2.pdf", b"cpus-out-2026-v2", _paginas(
        FIX["analitico"], FIX["paginas_analitico"], {1: ("\n30,28\n30,28\n",
                                                          "\n31,00\n31,00\n")}))
    segunda = _importar(a, pasta, "planilha2.pdf", "cpus2.pdf")
    assert segunda.desfecho == seop.EM_CONFERENCIA and segunda.confronto["divergentes"] == []
    # até aprovar, vale a anterior
    assert seop.consultar(a.buscar, codigo="011450")[0]["valor"] == "30.28"
    seop.aprovar(a, competencia=COMPETENCIA, sha256=segunda.sha256, por="Ana Souza")
    assert seop.consultar(a.buscar, codigo="011450")[0]["valor"] == "31.00"
    assert not a.versao(COMPETENCIA, primeira.sha256)["vigente"]
    assert len(a.registros) == 2 * primeira.validas            # nada apagado


def test_republicacao_que_encolheu_demais_e_recusada(pdfs):
    pasta, criar = pdfs
    a = seop.ArmazemEmMemoria()
    primeira = _importar(a, pasta)
    seop.aprovar(a, competencia=COMPETENCIA, sha256=primeira.sha256, por="Ana Souza")
    # só a página 2: 29 linhas válidas contra 64 da versão publicada
    criar("curta.pdf", b"curta", ["", PLANILHA[1]] + [""] * 46)
    feito = _importar(a, pasta, planilha="curta.pdf")
    assert feito.desfecho == seop.RECUSADO and "versão publicada" in feito.motivo
    assert a.versao_publicada(COMPETENCIA)["sha256"] == primeira.sha256


@pytest.mark.parametrize("url, aceita", [
    (URL, True), (URL_ANALITICO, True),
    ("https://seop.pa.gov.br/sites/default/files/x.pdf?a=1", False),
    ("http://seop.pa.gov.br/sites/default/files/plainha_padrao_outubro_2026.pdf", False),
    ("https://seop.pa.gov.br/planilha-de-custo-0", False),
    ("https://seop.pa.gov.br/sites/default/files/../x.pdf", False),
    ("https://exemplo.com/sites/default/files/x.pdf", False),
])
def test_pdf_so_da_pasta_oficial(url, aceita):
    assert seop.url_permitida(url) is aceita
    assert arquivos.url_permitida(url) is (aceita or url.endswith("/../x.pdf"))


def test_importar_recusa_endereco_de_fora(pdfs):
    pasta, _ = pdfs
    with pytest.raises(ValueError, match="pasta oficial"):
        seop.importar(seop.ArmazemEmMemoria(), pasta / "planilha.pdf",
                      competencia=COMPETENCIA, url="https://exemplo.com/x.pdf")


# ---------------------------------------------------------------------------
# Consulta e separação da cesta
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filtros", [{"codigo": "11450"}, {"codigo": "01145A"},
                                     {"competencia": "2026-13"}])
def test_consulta_recusa_filtro_fora_da_regra(filtros):
    with pytest.raises(ValueError):
        seop.consultar(lambda *a, **k: [], termo="andaime", **filtros)


def test_consulta_por_termo_e_sem_termo(pdfs):
    pasta, _ = pdfs
    a = seop.ArmazemEmMemoria()
    feito = _importar(a, pasta)
    seop.aprovar(a, competencia=COMPETENCIA, sha256=feito.sha256, por="Ana Souza")
    achados = seop.consultar(a.buscar, termo="andaime metálico")
    assert {"011450", "010786"} <= {x["codigo"] for x in achados}
    assert seop.consultar(a.buscar, termo="de a") == []


def test_seop_nunca_entra_na_cesta_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    nomes = " ".join(type(f).__name__.lower() + getattr(getattr(f, "fonte", None), "id", "")
                     for f in cotacoes._fontes_padrao())
    assert "seop" not in nomes
    assert governanca.FLAG_REFERENCIA_SEOP_PA == "referencia_custos_seop_pa"
