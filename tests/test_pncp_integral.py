"""
Importação nacional (Compras.gov em lote + fila durável), sem rede:
paginação inteira ou parcial, mesma conferência e mesma chave do PNCP,
queda e retomada sem duplicar, 429 com Retry-After, reserva exclusiva
entre processos, pausa, líder único.
"""
from __future__ import annotations

import json
import threading
import urllib.parse
from datetime import date, datetime, timedelta, timezone

import pytest

from src.precos import pncp_indice
from src.precos import pncp_integral as pi

DIA = date(2026, 10, 29)


def _resultado(controle, item, seq=1, valor=100.0, qtd=2.0, pj=True, **extra):
    id_compra = controle.replace("-", "")[:17].ljust(17, "0")
    return {"idCompraItem": f"{id_compra}{item:05d}", "idContratacaoPNCP": controle,
            "numeroItemPncp": item, "sequencialResultado": seq,
            "niFornecedor": "10498974000109" if pj else "12345678901",
            "tipoPessoa": "PJ" if pj else "PF",
            "nomeRazaoSocialFornecedor": "EMPRESA LTDA" if pj else "FULANO DE TAL",
            "quantidadeHomologada": qtd, "valorUnitarioHomologado": valor,
            "valorTotalHomologado": valor * qtd, "percentualDesconto": 0,
            "situacaoCompraItemResultadoId": 1, "situacaoCompraItemResultadoNome": "Informado",
            "dataResultadoPncp": "2026-10-29T00:00:00", "dataCancelamentoPncp": None,
            "moedaEstrangeiraId": None, **extra}


def _contratacao(controle):
    return {"numeroControlePNCP": controle, "anoCompraPncp": 2026, "sequencialCompraPncp": 1,
            "orgaoEntidadeCnpj": controle[:14], "orgaoEntidadeRazaoSocial": "PREFEITURA X",
            "unidadeOrgaoUfSigla": "PA", "unidadeOrgaoMunicipioNome": "Belém",
            "modalidadeIdPncp": 6, "modalidadeNome": "Pregão - Eletrônico",
            "dataPublicacaoPncp": "2026-10-01T00:00:00", "situacaoCompraNomePncp": "Divulgada"}


def _item(numero, descricao="CANETA ESFEROGRAFICA AZUL", criterio="Menor preço", situacao="2"):
    return {"numeroItemPncp": numero, "descricaoResumida": descricao, "unidadeMedida": "UN",
            "quantidade": 2.0, "materialOuServico": "M", "criterioJulgamentoNome": criterio,
            "situacaoCompraItem": situacao, "situacaoCompraItemNome": "Homologado"}


class Fonte:
    """Dados Abertos falsos: dia paginado, contratações e itens por id."""

    def __init__(self, resultados, contratacoes, itens, *, pagina=2, falhas=None,
                 corta_pagina=None):
        self.resultados, self.contratacoes, self.itens = resultados, contratacoes, itens
        self.pagina, self.falhas = pagina, list(falhas or [])
        self.corta_pagina = corta_pagina
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        if self.falhas:
            status, cab = self.falhas.pop(0)
            return status, cab, b""
        partes = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(partes.query))
        rota = partes.path.rsplit("/", 1)[-1]
        if rota.startswith("3_"):
            n = int(q["pagina"])
            ini = (n - 1) * self.pagina
            fatia = self.resultados[ini:ini + self.pagina]
            if self.corta_pagina == n:
                fatia = []
            restantes = max(0, -(-len(self.resultados) // self.pagina) - n)
            corpo = {"resultado": fatia, "totalRegistros": len(self.resultados),
                     "paginasRestantes": restantes}
        elif rota.startswith("1.1_"):
            corpo = {"resultado": [self.contratacoes[q["codigo"]]], "totalRegistros": 1}
        else:
            itens = self.itens[q["codigo"]]
            corpo = {"resultado": itens, "totalRegistros": len(itens)}
        return 200, {}, json.dumps(corpo).encode()


def _cenario(**kw):
    c1, c2 = "11111111000111-1-000001/2026", "22222222000122-1-000002/2026"
    ids = {c: c.replace("-", "")[:17].ljust(17, "0") for c in (c1, c2)}
    resultados = [_resultado(c1, 1), _resultado(c1, 2, valor=50.0),
                  _resultado(c2, 1, pj=False), _resultado(c2, 2)]
    contratacoes = {ids[c]: _contratacao(c) for c in (c1, c2)}
    itens = {ids[c1]: [_item(1), _item(2, descricao="PAPEL A4 75G")],
             ids[c2]: [_item(1, descricao="CADERNO 96 FOLHAS"),
                       _item(2, descricao="OLEO DIESEL S10", criterio="Maior desconto")]}
    fonte = Fonte(resultados, contratacoes, itens, **kw)
    lim = pi.Limitador(1000, dormir=lambda s: None)
    return fonte, pi.ComprasGovLote(pi.ClienteHttp(lim, abrir=fonte))


def test_dia_inteiro_passa_pela_mesma_conferencia_do_pncp():
    fonte, lote = _cenario()
    armazem = pncp_indice.ArmazemEmMemoria()
    totais = pi.importar_dia(lote, armazem, DIA)
    assert totais.resultados == 4 and totais.contratacoes == 2
    # julgamento por desconto recusado pela regra do índice
    assert totais.gravadas == 3
    assert totais.recusadas == {pncp_indice.CRITERIO_MAIOR_DESCONTO: 1}
    # pessoa física entra SEM nome nem documento (mesma regra do PNCP)
    pf = armazem.resultados["22222222000122-1-000002/2026#1#1"]
    assert pf["fornecedor_cnpj"] is None
    assert "FULANO" not in json.dumps(pf, ensure_ascii=False)
    chaves = set(armazem.resultados)
    assert "11111111000111-1-000001/2026#1#1" in chaves      # a chave do PNCP
    linha = armazem.resultados["11111111000111-1-000001/2026#1#1"]
    assert linha["plataforma"] == "Compras.gov.br" and linha["uf"] == "PA"
    assert linha["valor_unitario"].startswith("100")
    # um cabeçalho e uma lista de itens por contratação, não por item
    assert sum("/1.1_" in u for u in fonte.urls) == 2
    assert sum("/2.1_" in u for u in fonte.urls) == 2


def test_pagina_faltando_e_parcial_nunca_concluida():
    _, lote = _cenario(corta_pagina=2)
    with pytest.raises(pi.RespostaParcial):
        lote.resultados_do_dia(DIA)


def test_reimportar_o_mesmo_dia_nao_duplica():
    _, lote = _cenario()
    armazem = pncp_indice.ArmazemEmMemoria()
    pi.importar_dia(lote, armazem, DIA)
    antes = dict(armazem.resultados)
    _, lote2 = _cenario()
    pi.importar_dia(lote2, armazem, DIA)        # queda depois de gravar, antes do ack
    assert set(armazem.resultados) == set(antes)


def test_429_com_retry_after_e_respeitado_pelo_host():
    esperas = []
    relogio = [0.0]
    lim = pi.Limitador(1.0, relogio=lambda: relogio[0], dormir=esperas.append)
    http = pi.ClienteHttp(lim, abrir=lambda url: (429, {"Retry-After": "120"}, b""))
    with pytest.raises(pi.FalhaTransitoria) as erro:
        http.json("https://dadosabertos.compras.gov.br/x")
    assert erro.value.espera_s == 120
    lim.aguardar("dadosabertos.compras.gov.br")
    assert esperas and esperas[-1] >= 119


@pytest.mark.parametrize("status", [500, 503])
def test_5xx_e_transitorio_e_desacelera(status):
    lim = pi.Limitador(1.0, dormir=lambda s: None)
    http = pi.ClienteHttp(lim, abrir=lambda url: (status, {}, b""))
    with pytest.raises(pi.FalhaTransitoria):
        http.json("https://h/x")
    assert lim.intervalo > lim.base


def test_json_invalido_e_transitorio_nao_vazio():
    http = pi.ClienteHttp(pi.Limitador(1000, dormir=lambda s: None),
                          abrir=lambda url: (200, {}, b"<html>manutencao</html>"))
    with pytest.raises(pi.FalhaTransitoria):
        http.json("https://h/x")


# ---------------------------------------------------------------------------
# Fila e execução
# ---------------------------------------------------------------------------
def _fila_com(dias):
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "comprasgov_lote", "particao": d.isoformat(),
                 "prioridade": i} for i, d in enumerate(dias)])
    return fila


def test_execucao_confirma_com_totais_e_agenda_revisita():
    _, lote = _cenario()
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    estado = pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(), fila=fila)
    gravada = fila.tarefas[0]
    assert estado == "concluida" and gravada["totais"]["gravadas"] == 3
    assert gravada["proxima_em"] > datetime.now(timezone.utc)


def test_falha_transitoria_volta_para_a_fila_com_espera():
    _, lote = _cenario(falhas=[(503, {}, )] * 1)
    lote.http._abrir = lambda url: (503, {}, b"")
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "pendente"
    assert fila.tarefas[0]["proxima_em"] > datetime.now(timezone.utc)
    assert "503" in fila.tarefas[0]["erro"]


def test_resposta_parcial_vira_parcial_e_esgotada_vira_falha():
    _, lote = _cenario(corta_pagina=2)
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "parcial"
    fila.tarefas[0].update(tentativas=pi.TENTATIVAS_MAX, proxima_em=datetime.now(timezone.utc))
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    _, lote2 = _cenario(corta_pagina=2)
    assert pi.executar(tarefa, lote=lote2, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "falha"


def test_dois_processos_nunca_recebem_a_mesma_tarefa():
    fila = _fila_com([DIA - timedelta(days=i) for i in range(200)])
    pegas: list[int] = []
    trava = threading.Lock()

    def trabalhador(nome):
        while True:
            lote = fila.reservar(nome, ["comprasgov_lote"], 3, 60)
            if not lote:
                return
            with trava:
                pegas.extend(t["id"] for t in lote)

    threads = [threading.Thread(target=trabalhador, args=(f"w{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(pegas) == 200 and len(set(pegas)) == 200


def test_queda_com_lease_vencido_reentrega_e_o_dono_antigo_nao_confirma():
    fila = _fila_com([DIA])
    velha = fila.reservar("w1", ["comprasgov_lote"], 1, 60)[0]
    fila.tarefas[0]["lease_ate"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    nova = fila.reservar("w2", ["comprasgov_lote"], 1, 60)[0]
    assert nova["token"] != velha["token"]
    assert fila.concluir(velha, "concluida") is False
    assert fila.concluir(nova, "concluida") is True


def test_pausa_e_lider_unico():
    _, lote = _cenario()
    fila = _fila_com([DIA])
    a = pi.Servico(fila=fila, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(), dono="a")
    b = pi.Servico(fila=fila, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(), dono="b")
    fila.ajustar_controle(pausado=True)
    assert a.passo() == 0
    fila.ajustar_controle(pausado=False)
    assert a.passo() == 1          # a é o líder
    fila.criar([{"campanha": "c", "fonte": "comprasgov_lote", "particao": "2026-10-28"}])
    assert b.passo() == 0          # b não escreve enquanto a lidera


def test_plano_poe_o_ano_da_cotacao_na_frente_do_historico():
    tarefas = pi.plano_comprasgov("c", ate=date(2026, 11, 12), desde=date(2025, 1, 1))
    recentes = [t for t in tarefas if t["faixa"] == "recente"]
    historicas = [t for t in tarefas if t["faixa"] == "historico"]
    assert len(recentes) == 365 and historicas
    assert max(t["prioridade"] for t in recentes) < min(t["prioridade"] for t in historicas)
    assert recentes[0]["particao"] == "2026-11-12"   # o mais novo primeiro
    assert len({t["particao"] for t in tarefas}) == len(tarefas)


def test_reabrir_falhas_nao_reseta_o_resto():
    fila = _fila_com([DIA, DIA - timedelta(days=1)])
    fila.tarefas[0]["estado"] = "falha"
    fila.tarefas[1]["estado"] = "concluida"
    assert fila.reabrir(None, ["falha"], None) == 1
    assert [t["estado"] for t in fila.tarefas] == ["pendente", "concluida"]


def test_relatorio_por_fonte_e_faixa():
    linhas = [{"fonte": "comprasgov_lote", "faixa": "recente", "estado": "concluida",
               "totais": {"resultados": 10, "gravadas": 7, "chamadas": 30}},
              {"fonte": "comprasgov_lote", "faixa": "recente", "estado": "pendente",
               "totais": {}}]
    r = pi.relatorio(linhas)["comprasgov_lote/recente"]
    assert r == {"total": 2, "estados": {"concluida": 1, "pendente": 1},
                 "resultados": 10, "gravadas": 7, "chamadas": 30}
