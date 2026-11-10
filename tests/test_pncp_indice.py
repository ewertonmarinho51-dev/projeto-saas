"""
Piloto do índice do PNCP por descrição (10/11/2026, Pará).

A fixture é resposta REAL da API pública do PNCP, de três contratações
paraenses publicadas por plataformas que não são o Compras.gov
(`tests/fixtures/pncp_indice_pa_2026-11-10.json`). Nenhuma chamada de rede.

O que estas provas guardam:

* o coletor descobre, lê itens e resultados e grava só o unitário
  HOMOLOGADO conferido (item, unidade, quantidade, total e etapa);
* o job é limitado e RETOMÁVEL: o orçamento de chamadas para a rodada, e a
  seguinte continua na página e no item em que parou, sem reler;
* é idempotente e incremental: nada muda sem mudança na fonte, e a
  contratação atualizada volta à fila;
* Compras.gov fica fora do piloto por padrão; fornecedor pessoa física não
  é gravado;
* a busca do usuário lê SÓ o índice, entra no pipeline comum e funde a
  mesma compra vista no Compras.gov;
* índice fora do ar é falha da fonte, não da pesquisa;
* a fonte nasce desligada, e flag ilegível não a liga.
"""

from __future__ import annotations

import copy
import json
import urllib.parse
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from src import db, governanca
from src.precos import busca, cotacoes, estatistica, pncp
from src.precos import pncp_indice as indice
from src.precos import repositorio as repo
from src.precos.fontes import Consulta, Desfecho
from src.precos.modelo import Fonte, NaturezaValor, Referencia
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX
from tests.test_precos_fase4 import _FonteFalsa

FIXTURE = json.loads((Path(__file__).parent / "fixtures" /
                      "pncp_indice_pa_2026-11-10.json").read_text("utf-8"))
CIMENTO = "05832977000199-1-000024/2025"
ATE = date(2026, 9, 30)


class ApiFalsa:
    """As três rotas oficiais, respondidas pela fixture; 2 por página."""

    def __init__(self, contratacoes=None):
        self.contratacoes = copy.deepcopy(
            contratacoes if contratacoes is not None else FIXTURE["contratacoes"])
        self.chamadas: list[str] = []

    def _da(self, cnpj, ano, seq):
        for c in self.contratacoes:
            if pncp.controle_da_entrada(
                    c["contratacao"]["numeroControlePNCP"]) == (cnpj, ano, seq):
                return c
        raise AssertionError("contratação fora da fixture")

    def __call__(self, url: str) -> str:
        self.chamadas.append(url)
        partes = urllib.parse.urlsplit(url)
        consulta = urllib.parse.parse_qs(partes.query)
        if partes.path.endswith(indice.ROTA_DESCOBERTA):
            if consulta["codigoModalidadeContratacao"] != ["6"]:
                return json.dumps({"data": [], "paginasRestantes": 0})
            pagina = int(consulta["pagina"][0])
            todas = [c["contratacao"] for c in self.contratacoes]
            fatia = todas[(pagina - 1) * 2:pagina * 2]
            return json.dumps({"data": fatia, "paginasRestantes":
                               max(0, -(-len(todas) // 2) - pagina)})
        _, _, resto = partes.path.partition("/orgaos/")
        cnpj, _, ano, seq, *cauda = resto.split("/")
        contratacao = self._da(cnpj, ano, seq)
        if cauda == ["itens"]:
            return json.dumps(contratacao["itens"])
        numero = cauda[1]
        return json.dumps(contratacao["resultados"].get(numero) or [])

    def de(self, trecho: str) -> list[str]:
        return [u for u in self.chamadas if trecho in u]


def _coletor(api, armazem=None, **kw):
    kw.setdefault("pausa_s", 0)
    return indice.Coletor(armazem or indice.ArmazemEmMemoria(), abrir_url=api,
                          dormir=lambda s: None, **kw)


def _indexar(api=None, armazem=None, **kw):
    coletor = _coletor(api or ApiFalsa(), armazem, **kw)
    coletor.descobrir("PA", modalidades=(6,), ate=ATE)
    coletor.coletar()
    return coletor


# ---------------------------------------------------------------------------
# Coleta
# ---------------------------------------------------------------------------
def test_coleta_grava_so_o_unitario_homologado_conferido():
    coletor = _indexar()
    armazem, rodada = coletor.armazem, coletor.rodada
    assert (rodada.descobertas, rodada.novas, rodada.contratacoes_lidas) == (3, 3, 3)
    assert rodada.validos == len(armazem.resultados) == 5
    assert not rodada.falhas and not rodada.interrompida
    assert {c["estado"] for c in armazem.contratacoes.values()} == {indice.COLETADA}
    linha = armazem.resultados[f"{CIMENTO}#1#1"]
    # identificação de item, unidade, quantidade e etapa, como a fonte deu
    assert (linha["numero_item"], linha["unidade"]) == (1, "Unidade")
    assert Decimal(linha["valor_unitario"]) == Decimal("39.0")
    assert Decimal(linha["quantidade"]) * Decimal(linha["valor_unitario"]) == \
        Decimal(linha["valor_total"])
    assert linha["bruto"]["item"]["situacaoCompraItemNome"] == "Homologado"
    assert linha["uf"] == "PA" and linha["municipio"] == "Santana do Araguaia"
    assert linha["plataforma"] == "ECustomize Consultoria em Software S.A"
    assert linha["descricao_busca"] == "cimento cp 2 f"
    assert linha["versao_coletor"] == indice.VERSAO_COLETOR
    assert len(linha["hash_linha"]) == 64


def test_orcamento_interrompe_e_a_rodada_seguinte_continua_sem_reler():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    inteira = _indexar()
    rodadas = 0
    while True:
        rodadas += 1
        coletor = _coletor(api, armazem, max_chamadas=3)
        coletor.descobrir("PA", modalidades=(6,), ate=ATE)
        if not coletor.rodada.interrompida:
            coletor.coletar()
        if not coletor.rodada.interrompida:
            break
        assert coletor.rodada.chamadas == 3
        assert rodadas < 20, "o job não avança"
    assert rodadas > 3                       # parou e retomou de verdade
    assert armazem.resultados.keys() == inteira.armazem.resultados.keys()
    assert {c["estado"] for c in armazem.contratacoes.values()} == {indice.COLETADA}
    # nenhum resultado de item foi lido duas vezes
    lidas = api.de("/resultados")
    assert len(lidas) == len(set(lidas))
    # nem página da descoberta já concluída
    paginas = api.de(indice.ROTA_DESCOBERTA)
    assert len(paginas) == len(set(paginas)) == 2


def test_descoberta_interrompida_retoma_na_pagina_em_que_parou():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    primeira = _coletor(api, armazem, max_chamadas=1)
    primeira.descobrir("PA", modalidades=(6,), ate=ATE)
    assert primeira.rodada.interrompida and primeira.rodada.descobertas == 2
    cursor = armazem.cursor("PA", 6)
    assert (cursor["proxima_pagina"], cursor["concluido"]) == (2, False)
    segunda = _coletor(api, armazem, max_chamadas=1)
    segunda.descobrir("PA", modalidades=(6,), ate=date(2026, 10, 20))
    # termina a janela INTERROMPIDA (não a nova) e não relê a página 1
    assert not segunda.rodada.interrompida and segunda.rodada.descobertas == 1
    paginas = [urllib.parse.parse_qs(urllib.parse.urlsplit(u).query)
               for u in api.de(indice.ROTA_DESCOBERTA)]
    assert [p["pagina"] for p in paginas] == [["1"], ["2"]]
    assert {p["dataFinal"][0] for p in paginas} == {"20260930"}
    assert armazem.cursor("PA", 6)["concluido"] is True
    assert len(armazem.contratacoes) == 3


def test_indice_local_persiste_entre_execucoes(tmp_path):
    arquivo = tmp_path / "indice.json"
    primeiro = indice.ArmazemEmMemoria(arquivo)
    _indexar(armazem=primeiro)
    primeiro.persistir()
    segundo = indice.ArmazemEmMemoria(arquivo)
    assert segundo.resultados.keys() == primeiro.resultados.keys()
    assert segundo.cursor("PA", 6)["concluido"] is True


def test_rodar_de_novo_sem_mudanca_nao_refaz_nada():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    antes = len(api.chamadas)
    de_novo = _indexar(api, armazem)
    assert len(api.chamadas) == antes        # mesma janela: nem consulta
    assert de_novo.rodada.novas == 0
    # janela seguinte: revisita, mas nada mudou na fonte
    coletor = _coletor(api, armazem)
    coletor.descobrir("PA", modalidades=(6,), ate=date(2026, 10, 15))
    coletor.coletar()
    assert coletor.rodada.descobertas == 3 and coletor.rodada.novas == 0
    assert coletor.rodada.contratacoes_lidas == 0
    cursor = armazem.cursor("PA", 6)
    assert cursor["data_final"] == "2026-10-15"
    assert cursor["data_inicial"] == "2026-08-16"     # recuou a revisita


def test_contratacao_atualizada_volta_para_a_fila():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    alvo = api.contratacoes[0]
    alvo["contratacao"]["dataAtualizacaoGlobal"] = "2026-10-10T09:00:00"
    alvo["resultados"]["1"][0].update(valorUnitarioHomologado=40.0,
                                      valorTotalHomologado=4000000.0)
    coletor = _coletor(api, armazem)
    coletor.descobrir("PA", modalidades=(6,), ate=date(2026, 10, 15))
    coletor.coletar()
    assert coletor.rodada.novas == 1 and coletor.rodada.contratacoes_lidas == 1
    assert Decimal(armazem.resultados[f"{CIMENTO}#1#1"]["valor_unitario"]) == 40
    assert len(armazem.resultados) == 5      # substituído, não duplicado


def test_compras_gov_fica_fora_do_piloto_por_padrao():
    contratacoes = copy.deepcopy(FIXTURE["contratacoes"])
    contratacoes[0]["contratacao"]["usuarioNome"] = indice.PLATAFORMA_COMPRAS_GOV
    fora = _indexar(ApiFalsa(contratacoes))
    assert fora.rodada.fora_do_piloto == 1 and fora.rodada.novas == 2
    assert fora.armazem.contratacao(CIMENTO)["estado"] == indice.FORA_DO_PILOTO
    assert not any(k.startswith(CIMENTO) for k in fora.armazem.resultados)
    dentro = _indexar(ApiFalsa(contratacoes), incluir_compras_gov=True)
    assert any(k.startswith(CIMENTO) for k in dentro.armazem.resultados)


@pytest.mark.parametrize("mudanca_item, mudanca_resultado, motivo", [
    ({"situacaoCompraItem": 1, "situacaoCompraItemNome": "Em andamento"}, {},
     indice.ITEM_NAO_HOMOLOGADO),
    ({"unidadeMedida": " "}, {}, "SEM_UNIDADE"),
    ({"descricao": ""}, {}, "SEM_DESCRICAO"),
    ({}, {"valorTotalHomologado": 1.0}, indice.RESULTADO_NAO_CONFERIVEL),
    ({}, {"dataCancelamento": "2026-09-01"}, indice.RESULTADO_NAO_CONFERIVEL),
    ({}, {"valorUnitarioHomologado": 0}, indice.RESULTADO_NAO_CONFERIVEL),
])
def test_o_que_nao_prova_preco_fica_contado_e_nao_gravado(
        mudanca_item, mudanca_resultado, motivo):
    contratacoes = copy.deepcopy(FIXTURE["contratacoes"])
    contratacoes[0]["itens"][0].update(mudanca_item)
    contratacoes[0]["resultados"]["1"][0].update(mudanca_resultado)
    coletor = _indexar(ApiFalsa(contratacoes))
    assert coletor.rodada.quarentena == {motivo: 1}
    assert f"{CIMENTO}#1#1" not in coletor.armazem.resultados
    assert len(coletor.armazem.resultados) == 4


def test_fornecedor_pessoa_fisica_nao_e_gravado():
    contratacoes = copy.deepcopy(FIXTURE["contratacoes"])
    contratacoes[0]["resultados"]["1"][0].update(
        tipoPessoa="PF", niFornecedor="12345678901",
        nomeRazaoSocialFornecedor="FULANO DE TAL")
    linha = _indexar(ApiFalsa(contratacoes)).armazem.resultados[f"{CIMENTO}#1#1"]
    assert linha["fornecedor_cnpj"] is None
    assert "FULANO" not in json.dumps(linha) and "12345678901" not in json.dumps(linha)


def test_falha_da_fonte_conta_tentativas_e_nao_derruba_a_rodada():
    import urllib.error

    api = ApiFalsa()

    def instavel(url):
        if "/000024/" in url or "/compras/2025/24/" in url:
            raise urllib.error.HTTPError(url, 503, "fora", None, None)
        return api(url)

    armazem = indice.ArmazemEmMemoria()
    for esperado in (indice.PENDENTE, indice.PENDENTE, indice.FALHA):
        coletor = _coletor(instavel, armazem)
        coletor.descobrir("PA", modalidades=(6,), ate=ATE)
        coletor.coletar()
        assert armazem.contratacao(CIMENTO)["estado"] == esperado
        assert any(CIMENTO in f for f in coletor.rodada.falhas)
    assert len(armazem.resultados) == 3      # as outras duas entraram


# ---------------------------------------------------------------------------
# Busca do usuário — só o índice
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def armazem():
    return _indexar().armazem


def test_busca_por_descricao_devolve_preco_rastreavel(armazem):
    fonte = indice.PNCPIndice(armazem.buscar)
    resultado = fonte.pesquisar(Consulta(descricao="Cimento CP 2 F", uf="PA"))
    assert resultado.desfecho is Desfecho.COM_PRECOS and resultado.chamadas == 1
    ref = next(r for r in resultado.referencias
               if r.id_externo == f"{CIMENTO}#1#1")
    assert ref.fonte.id == "pncp"
    assert ref.natureza_valor is NaturezaValor.HOMOLOGADO
    assert ref.valor_unitario_original == Decimal("39.0")
    assert ref.unidade_original == "Unidade" and ref.uf == "PA"
    assert ref.referencia_externa == CIMENTO
    assert pncp.url_de_verificacao(ref.bruto) == (
        "https://pncp.gov.br/app/editais/05832977000199/2025/24")
    assert ref.bruto["indice"]["plataforma"].startswith("ECustomize")
    assert ref.bruto["idCompraOrigem"] is None     # origem fora do Compras.gov


def test_busca_respeita_uf_janela_e_termos(armazem):
    fonte = indice.PNCPIndice(armazem.buscar)
    assert fonte.pesquisar(Consulta(descricao="cimento", uf="RS")).referencias == []
    assert fonte.pesquisar(Consulta(
        descricao="cimento", data_inicial=date(2026, 1, 1))).referencias == []
    assert fonte.pesquisar(Consulta(descricao="grampeador")).desfecho is \
        Desfecho.SEM_RESULTADO
    # acento não separa: "AÇÚCAR"/"acucar", "CONCRETO"/"concreto"
    [concreto] = fonte.pesquisar(Consulta(descricao="CONCRÉTO usinado")).referencias
    assert concreto.unidade_original == "M3"
    vazio = fonte.pesquisar(Consulta(descricao="de a"))
    assert vazio.referencias == [] and vazio.falha is None


def test_entra_no_pipeline_comum_e_pode_compor_a_cesta(armazem):
    item = {"id": "x", "numero": 1, "descricao": "CIMENTO CP 2 F",
            "unidade": "UNIDADE", "quantidade": "100"}
    coleta = busca.coletar(item, [indice.PNCPIndice(armazem.buscar)],
                           filtros={"data_base": "2025-06-30"})
    assert not coleta.erro and coleta.desfechos == {"pncp": "success_with_prices"}
    assert coleta.elegiveis(estatistica.PISO_COMPARABILIDADE) >= 1


def test_mesma_compra_no_compras_gov_e_no_indice_conta_uma_vez():
    contratacoes = copy.deepcopy(FIXTURE["contratacoes"][:1])
    contratacoes[0]["contratacao"].update(
        usuarioNome=indice.PLATAFORMA_COMPRAS_GOV,
        linkSistemaOrigem="https://cnetmobile.estaleiro.serpro.gov.br/"
                          "comprasnet-web/public/landing?compra=92545005900472026")
    armazem = _indexar(ApiFalsa(contratacoes), incluir_compras_gov=True).armazem
    linha = armazem.resultados[f"{CIMENTO}#1#1"]
    assert linha["id_compra_origem"] == "92545005900472026"
    precos = Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial")
    do_compras = Referencia(
        fonte=precos, id_externo="cg-1", bruto={"idCompra": "92545005900472026"},
        descricao_original="CIMENTO CP 2 F", unidade_original="UNIDADE",
        valor_unitario_original=Decimal("39.0"),
        ni_fornecedor=linha["fornecedor_cnpj"],
        natureza_valor=NaturezaValor.PRATICADO, data_compra=date(2025, 5, 8))
    item = {"id": "x", "numero": 1, "descricao": "CIMENTO CP 2 F",
            "unidade": "UNIDADE"}
    coleta = busca.coletar(
        item, [_FonteFalsa(precos, [do_compras]),
               indice.PNCPIndice(armazem.buscar)],
        filtros={"data_base": "2025-06-30"})
    ids = {r.id_externo for r, _ in coleta.referencias}
    assert "cg-1" in ids and f"{CIMENTO}#1#1" not in ids
    assert any("mesma compra" in o or "contada" in o for o in coleta.ocorrencias)


def test_indice_fora_do_ar_e_falha_da_fonte_nao_da_pesquisa():
    def fora(termos, **kw):
        raise ConnectionError("banco fora")

    fonte = indice.PNCPIndice(fora)
    resultado = fonte.pesquisar(Consulta(descricao="cimento"))
    assert resultado.desfecho is Desfecho.FALHA and not fonte.healthcheck()
    precos = Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial")
    de_pe = _FonteFalsa(precos, [Referencia(
        fonte=precos, id_externo="cg-1", bruto={},
        descricao_original="CIMENTO", unidade_original="UNIDADE",
        valor_unitario_original=Decimal("40"),
        natureza_valor=NaturezaValor.PRATICADO)])
    coleta = busca.coletar({"id": "x", "numero": 1, "descricao": "CIMENTO",
                            "unidade": "UNIDADE"}, [de_pe, fonte])
    assert not coleta.erro and coleta.unicas == 1
    assert coleta.desfechos == {"compras_gov_precos": "success_with_prices",
                                "pncp": "failure"}
    # resposta que não é lista (RPC ausente, dublê): falha, nunca exceção
    assert indice.PNCPIndice(lambda t, **kw: "x").pesquisar(
        Consulta(descricao="cimento")).desfecho is Desfecho.FALHA


# ---------------------------------------------------------------------------
# Habilitação por flag e leitura pelo repositório
# ---------------------------------------------------------------------------
def _tipos(fontes):
    return [type(f).__name__ for f in fontes]


def test_fonte_nasce_desligada_e_flag_ilegivel_nao_liga(monkeypatch):
    ligar_banco_falso(monkeypatch)
    assert _tipos(cotacoes._fontes_padrao()) == ["ComprasGovAdapter", "PNCPAdapter"]

    def quebrada(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebrada)
    assert "PNCPIndice" not in _tipos(cotacoes._fontes_padrao())


def test_flag_ligada_troca_o_adapter_de_evidencia_pelo_indice(monkeypatch):
    cliente = ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: nome == governanca.FLAG_PNCP_INDICE)
    fontes = cotacoes._fontes_padrao()
    assert _tipos(fontes) == ["ComprasGovAdapter", "PNCPIndice"]
    assert governanca.FLAG_PNCP_INDICE == "price_source_pncp_indice"
    # a fonte lê pela RPC, com o JWT do usuário e os filtros da consulta
    fontes[1].pesquisar(Consulta(descricao="Cimento CP", uf="pa",
                                 data_inicial=date(2026, 5, 1),
                                 data_final=date(2026, 10, 1), limite=50))
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_pncp_buscar"
    assert parametros == {"p_termos": ["cimento"], "p_uf": "PA",
                          "p_desde": "2026-05-01", "p_ate": "2026-10-01",
                          "p_limite": 50}


def test_pesquisa_do_item_grava_a_referencia_do_indice(monkeypatch, armazem):
    ligar_banco_falso(monkeypatch)
    c = cotacoes.criar_cotacao(CTX, {"nome": "Piloto PNCP",
                                     "data_base": "2025-06-30"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), {
        "descricao": "CIMENTO CP 2 F", "unidade": "UNIDADE", "quantidade": "10"})
    r = cotacoes.pesquisar_item(CTX, str(c["id"]), str(item["id"]),
                                modo="manual",
                                fontes=[indice.PNCPIndice(armazem.buscar)])
    assert r.desfechos == {"pncp": "success_with_prices"}
    linhas = repo.listar_referencias(str(item["id"]))
    gravada = next(l for l in linhas if l["id_externo"] == f"{CIMENTO}#1#1")
    assert gravada["fonte_id"] == "pncp" and gravada["status"] == "candidate"
    assert gravada["natureza_valor"] == "homologado"
    assert gravada["referencia_externa"] == CIMENTO
