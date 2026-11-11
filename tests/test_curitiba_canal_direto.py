"""
Canal direto de Curitiba (Dados Abertos, "Itens Processo").

ATENÇÃO: os CSVs destas provas são SINTÉTICOS — montados com os campos que
a especificação lista, não baixados do portal (que respondeu HTTP 503 em
10/11/2026). Provam a REGRA (só valor contratado com contrato válido e
vigente, evidência recuperável, origem e canal, aviso de uso secundário, a
trava que mantém o canal desligado), não a cobertura. Nenhum número daqui
vale como preço real.

A validação com a amostra de 01/11/2026 é a pendência do canal
(`curitiba.PENDENCIA`); até ela, `MAPEAMENTO_CONFIRMADO` é falso.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from src.precos import busca, curitiba, estatistica, links, portais
from src.precos.fontes import Consulta, Desfecho
from src.precos.modelo import NaturezaValor

ITENS = (
    "Órgão;Processo;Item;Descrição;Quantidade;Unidade de Medida;Contrato;"
    "Início da Vigência;Fim da Vigência;Valor Unitário\n"
    # válido: contrato vigente na data-base
    "SMAD;PE 101/2026;1;PAPEL SULFITE A4 75 G/M2 RESMA 500 FOLHAS;1.200;RESMA;"
    "C-10/2026;01/03/2026;28/02/2027;24,90\n"
    # contrato cancelado em Dados Básicos
    "SMAD;PE 101/2026;2;CANETA ESFEROGRÁFICA AZUL;5.000;UNIDADE;C-11/2026;"
    "01/03/2026;28/02/2027;1,10\n"
    # sem contrato vinculado: o valor não é contratado
    "SME;PE 77/2026;1;ÁGUA MINERAL 20 L;300;UNIDADE;;;;12,00\n"
    # vigência que não cobre a data-base
    "SMS;PE 12/2025;3;PAPEL SULFITE A4 75 G/M2 RESMA 500 FOLHAS;100;RESMA;"
    "C-02/2025;01/01/2025;31/12/2025;21,00\n"
    # contrato vigente, mas a vigência DA LINHA não cobre a data-base
    "SMAD;PE 101/2026;3;GRAMPEADOR DE MESA;20;UNIDADE;C-10/2026;"
    "01/01/2025;31/12/2025;30,00\n"
    # unitário ilegível
    "SMS;PE 13/2026;1;ALCOOL 70;10;LITRO;C-10/2026;01/03/2026;28/02/2027;abc\n"
).encode("cp1252")

DADOS_BASICOS = (
    "Contrato;Situação;Início da Vigência;Fim da Vigência\n"
    "C-10/2026;VIGENTE;01/03/2026;28/02/2027\n"
    "C-11/2026;CANCELADO;01/03/2026;28/02/2027\n"
    "C-02/2025;ENCERRADO;01/01/2025;31/12/2025\n"
).encode("utf-8")

URL_ITENS = "https://mid-dadosabertos.curitiba.pr.gov.br/sintetico/Itens_Processo.csv"
URL_BASICOS = "https://mid-dadosabertos.curitiba.pr.gov.br/sintetico/Dados_Basicos.csv"
DATA_BASE = date(2026, 11, 1)


def _normalizar():
    return curitiba.normalizar(
        curitiba.Arquivo(URL_ITENS, "2026-11-01", ITENS),
        curitiba.Arquivo(URL_BASICOS, "2026-11-01", DADOS_BASICOS),
        data_base=DATA_BASE)


def test_so_entra_valor_contratado_com_contrato_valido_e_vigente():
    r = _normalizar()
    assert [l["id_externo"] for l in r.validas] == ["PE 101/2026#1#C-10/2026"]
    assert r.quarentena == {curitiba.CONTRATO_INVALIDO: 2, curitiba.SEM_CONTRATO: 1,
                            curitiba.FORA_DA_VIGENCIA: 1, "PRECO_UNITARIO_INVALIDO": 1}


def test_evidencia_recuperavel_e_numero_no_formato_declarado():
    [linha] = _normalizar().validas
    assert linha["valor_unitario"] == "24.90" and linha["quantidade"] == "1200"
    assert linha["url_recurso"] == URL_ITENS and linha["versao_recurso"] == "2026-11-01"
    assert len(linha["sha256_recurso"]) == 64 and linha["linha_arquivo"] == 2
    assert linha["inicio_vigencia"] == "2026-03-01" and linha["fim_vigencia"] == "2027-02-28"


def test_coluna_faltando_e_erro_com_o_nome_dela_nao_palpite():
    sem_valor = "Órgão;Processo;Item;Descrição;Quantidade;Unidade;Contrato;" \
                "Início da Vigência;Fim da Vigência\nSMAD;1;1;X;1;UN;C;;\n"
    with pytest.raises(curitiba.LeiauteDesconhecido, match="valor_unitario"):
        curitiba.ler_csv(sem_valor.encode(), curitiba.COLUNAS_ITENS)


def test_referencia_contratada_com_origem_canal_e_aviso():
    [linha] = _normalizar().validas
    ref = curitiba.referencia_da_linha(linha)
    assert ref.natureza_valor is NaturezaValor.CONTRATADO
    assert ref.fonte.id == "curitiba_itens" and ref.uf == "PR"
    a = portais.atribuir(ref.fonte.id, ref.bruto)
    assert a.rotulo == "Origem Portal de Dados Abertos de Curitiba · Coleta direta no portal de origem"
    assert "uso secundário" in ref.bruto["origem_direta"]["aviso"].lower() or \
        "forma secundária" in ref.bruto["origem_direta"]["aviso"]
    vinculos = links.resolver({"fonte_id": ref.fonte.id, "bruto": ref.bruto,
                               "referencia_externa": ref.referencia_externa,
                               "orgao": ref.orgao})
    assert vinculos.contratacao_url == URL_ITENS
    assert vinculos.identificacao == "Processo PE 101/2026 · contrato C-10/2026"


def test_adaptador_entra_no_pipeline_comum_e_pode_compor_a_cesta():
    indice = curitiba.IndiceEmMemoria(_normalizar().validas)
    fonte = curitiba.CuritibaDireta(indice.buscar)
    item = {"descricao": "papel sulfite A4 75 g/m², 500 folhas", "unidade": "RESMA",
            "quantidade": "100"}
    coleta = busca.coletar(item, [fonte], filtros={"data_base": "2026-11-01"})
    assert coleta.desfechos == {"curitiba_itens": Desfecho.COM_PRECOS.value}
    [(ref, comp)] = coleta.referencias
    assert ref.valor_unitario_normalizado == Decimal("24.90")
    assert comp.score >= estatistica.PISO_COMPARABILIDADE
    assert any("forma secundária" in o for o in coleta.ocorrencias)


def test_canal_desligado_ate_a_validacao_com_o_arquivo_real():
    assert curitiba.MAPEAMENTO_CONFIRMADO is False
    assert curitiba.habilitada(flag_ativa=lambda nome: True) is False
    assert portais.REGISTRO["curitiba"].situacao is portais.Situacao.AGUARDANDO_ACESSO
    assert "503" in curitiba.PENDENCIA


def test_flag_ilegivel_nao_liga(monkeypatch):
    monkeypatch.setattr(curitiba, "MAPEAMENTO_CONFIRMADO", True)

    def quebrada(nome):
        raise RuntimeError("sem banco")

    assert curitiba.habilitada(flag_ativa=quebrada) is False
    assert curitiba.habilitada(flag_ativa=lambda n: n == curitiba.FLAG) is True
