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


def test_dia_recente_lido_volta_pendente_para_revisita_com_a_leitura_registrada():
    # a 0045 nunca reentrega `concluida` (revisão de 13/11/2026): o que
    # precisa ser relido é confirmado `pendente` com data futura
    _, lote = _cenario()
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    estado = pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(), fila=fila)
    gravada = fila.tarefas[0]
    assert estado == "pendente" and gravada["totais"]["gravadas"] == 3
    assert gravada["checkpoint"]["lido_em"] and gravada["checkpoint"]["leituras"] == 1
    assert gravada["proxima_em"] > datetime.now(timezone.utc) + timedelta(days=6)
    assert fila.reservar("w", ["comprasgov_lote"], 1, 60) == []   # só depois da data


def test_dia_historico_lido_e_final_e_nao_volta():
    _, lote = _cenario()
    velho = date.today() - timedelta(days=500)
    fila = _fila_com([velho])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "concluida"
    fila.tarefas[0]["proxima_em"] = datetime.now(timezone.utc) - timedelta(days=1)
    assert fila.reservar("w", ["comprasgov_lote"], 1, 60) == []


def test_confirmacao_recusada_e_contada_nao_silenciosa():
    _, lote = _cenario()
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    fila.tarefas[0]["token"] = "outro-dono"           # lease perdido no meio
    antes = pi.CONFIRMACOES_RECUSADAS[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "confirmacao_recusada"
    assert pi.CONFIRMACOES_RECUSADAS[0] == antes + 1


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
    fila.tarefas[0]["tentativas"] = pi.TENTATIVAS_MAX
    assert fila.reabrir(None, ["falha"], None) == 1
    assert [t["estado"] for t in fila.tarefas] == ["pendente", "concluida"]
    assert fila.tarefas[0]["tentativas"] == 0          # não cai em falha de novo


def test_reabrir_sem_filtro_exige_todas(capsys):
    assert pi.main(["retry-failed"]) == 2
    assert "--todas" in capsys.readouterr().out


def test_relatorio_por_fonte_e_faixa():
    linhas = [{"fonte": "comprasgov_lote", "faixa": "recente", "estado": "concluida",
               "totais": {"resultados": 10, "gravadas": 7, "chamadas": 30}},
              {"fonte": "comprasgov_lote", "faixa": "recente", "estado": "pendente",
               "totais": {}}]
    r = pi.relatorio(linhas)["comprasgov_lote/recente"]
    assert r == {"total": 2, "estados": {"concluida": 1, "pendente": 1},
                 "resultados": 10, "gravadas": 7, "chamadas": 30,
                 "contratacoes": 0, "itens": 0}


# ---------------------------------------------------------------------------
# PNCP item a item
# ---------------------------------------------------------------------------
def _contr_pncp(controle, usuario="BLL Compras"):
    cnpj, _, resto = controle.partition("-1-")
    seq, _, ano = resto.partition("/")
    return {"numeroControlePNCP": controle, "usuarioNome": usuario, "modalidadeId": 6,
            "modalidadeNome": "Pregão - Eletrônico", "anoCompra": int(ano),
            "sequencialCompra": int(seq), "dataPublicacaoPncp": "2026-10-29T10:00:00",
            "orgaoEntidade": {"cnpj": cnpj, "razaoSocial": "MUNICIPIO DE CAREACU"},
            "unidadeOrgao": {"ufSigla": "MG", "municipioNome": "Careaçu"}}


class PortalPncp:
    """PNCP falso: publicação paginada, itens e resultados por item."""

    def __init__(self, contratacoes, itens, resultados, *, pagina=2, total=None,
                 quantidade=None):
        self.contratacoes, self.itens, self.resultados = contratacoes, itens, resultados
        self.pagina, self.total, self.quantidade = pagina, total, quantidade
        self.urls: list[str] = []

    def __call__(self, url):
        self.urls.append(url)
        partes = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(partes.query))
        if "/contratacoes/publicacao" in partes.path:
            n = int(q["pagina"])
            fatia = self.contratacoes[(n - 1) * self.pagina:n * self.pagina]
            restantes = max(0, -(-len(self.contratacoes) // self.pagina) - n)
            corpo = {"data": fatia, "totalRegistros": self.total or len(self.contratacoes),
                     "paginasRestantes": restantes}
        elif partes.path.endswith("/itens/quantidade"):
            corpo = self.quantidade if self.quantidade is not None else len(self.itens)
        elif partes.path.endswith("/itens"):
            corpo = self.itens if q.get("pagina") == "1" else []
        else:
            numero = int(partes.path.split("/itens/")[1].split("/")[0])
            corpo = self.resultados.get(numero, [])
        return 200, {}, json.dumps(corpo).encode()


def _pncp(portal):
    return pi.PncpItemAItem(pi.ClienteHttp(pi.Limitador(1000, dormir=lambda s: None),
                                           abrir=portal))


def test_descoberta_enfileira_so_o_que_nao_vem_em_lote():
    contratacoes = [_contr_pncp("17935388000115-1-000108/2026"),
                    _contr_pncp("11415535000140-1-000008/2026"),
                    _contr_pncp("00038174000143-1-000438/2026", usuario="Compras.gov.br")]
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "pncp_descoberta", "particao": "6:2026-10-29"}])
    tarefa = fila.reservar("w", ["pncp_descoberta"], 1, 60)[0]
    totais = pi.executar_descoberta(tarefa, pncp=_pncp(PortalPncp(contratacoes, [], {})),
                                    fila=fila)
    assert totais["contratacoes"] == 3 and totais["comprasgov"] == 1
    assert totais["enfileiradas"] == 2
    novas = [t for t in fila.tarefas if t["fonte"] == "pncp_contratacao"]
    assert {t["particao"] for t in novas} == {"17935388000115-1-000108/2026",
                                              "11415535000140-1-000008/2026"}
    assert novas[0]["checkpoint"]["cabecalho"]["unidadeOrgao"]["ufSigla"] == "MG"


def test_descoberta_com_menos_que_o_declarado_e_parcial():
    contratacoes = [_contr_pncp("17935388000115-1-000108/2026")]
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "pncp_descoberta", "particao": "6:2026-10-29"}])
    tarefa = fila.reservar("w", ["pncp_descoberta"], 1, 60)[0]
    with pytest.raises(pi.RespostaParcial):
        pi.executar_descoberta(tarefa, pncp=_pncp(PortalPncp(contratacoes, [], {}, total=5)),
                               fila=fila)


def _careacu():
    item = {"numeroItem": 2, "descricao": "ANALISADOR BIOQUÍMICO SEMIAUTOMÁTICO",
            "unidadeMedida": "UN", "quantidade": 1, "situacaoCompraItem": 2,
            "criterioJulgamentoNome": "Menor preço", "materialOuServico": "M"}
    nao = {**item, "numeroItem": 1, "situacaoCompraItem": 1, "descricao": "AGITADOR"}
    resultado = {"numeroItem": 2, "sequencialResultado": 1, "niFornecedor": "34700478000146",
                 "tipoPessoa": "PJ", "nomeRazaoSocialFornecedor": "AGNUS BRASIL",
                 "quantidadeHomologada": 1, "valorUnitarioHomologado": 12300.0,
                 "valorTotalHomologado": 12300.0, "dataResultado": "2026-10-29"}
    return [nao, item], {2: [resultado]}


def test_contratacao_le_todos_os_itens_e_so_resultado_homologado():
    itens, resultados = _careacu()
    portal = PortalPncp([], itens, resultados)
    fila = pi.FilaEmMemoria()
    controle = "17935388000115-1-000108/2026"
    fila.criar([{"campanha": "c", "fonte": "pncp_contratacao", "particao": controle,
                 "checkpoint": {"cabecalho": pncp_indice.resumo_da_contratacao(
                     _contr_pncp(controle))}}])
    tarefa = fila.reservar("w", ["pncp_contratacao"], 1, 60)[0]
    armazem = pncp_indice.ArmazemEmMemoria()
    # um item ainda sem homologação: volta para revisita, com a leitura feita
    assert pi.executar(tarefa, lote=None, armazem=armazem, fila=fila,
                       pncp=_pncp(portal)) == "pendente"
    linha = armazem.resultados[f"{controle}#2#1"]
    assert linha["valor_unitario"].startswith("12300") and linha["uf"] == "MG"
    assert sum("/resultados" in u for u in portal.urls) == 1   # só o homologado
    gravada = fila.tarefas[0]
    assert gravada["totais"]["gravadas"] == 1 and gravada["totais"]["itens"] == 2
    assert gravada["checkpoint"]["cabecalho"]["numeroControlePNCP"] == controle  # preservado


def test_itens_a_menos_que_a_quantidade_declarada_e_parcial():
    itens, resultados = _careacu()
    portal = PortalPncp([], itens, resultados, quantidade=39)
    with pytest.raises(pi.RespostaParcial):
        _pncp(portal).itens("17935388000115", 2026, 108)


def test_plano_pncp_uma_modalidade_por_dia_com_o_ano_na_frente():
    tarefas = pi.plano_pncp("c", ate=date(2026, 11, 12), desde=date(2026, 11, 11),
                            modalidades=(6, 8))
    assert [t["particao"] for t in tarefas] == ["6:2026-11-12", "8:2026-11-12",
                                                "6:2026-11-11", "8:2026-11-11"]
    assert all(t["faixa"] == "recente" for t in tarefas)


def test_contratacao_toda_homologada_e_final():
    itens, resultados = _careacu()
    itens = [i for i in itens if i["situacaoCompraItem"] == 2]
    fila = pi.FilaEmMemoria()
    controle = "17935388000115-1-000108/2026"
    fila.criar([{"campanha": "c", "fonte": "pncp_contratacao", "particao": controle,
                 "checkpoint": {"cabecalho": pncp_indice.resumo_da_contratacao(
                     _contr_pncp(controle))}}])
    tarefa = fila.reservar("w", ["pncp_contratacao"], 1, 60)[0]
    assert pi.executar(tarefa, lote=None, armazem=pncp_indice.ArmazemEmMemoria(), fila=fila,
                       pncp=_pncp(PortalPncp([], itens, resultados))) == "concluida"


def test_fila_em_memoria_impoe_os_limites_da_rpc():
    fila = _fila_com([DIA - timedelta(days=i) for i in range(150)])
    assert len(fila.reservar("w", ["comprasgov_lote"], 500, 1)) == 100
    t = next(t for t in fila.tarefas if t["estado"] == "em_execucao")
    assert t["lease_ate"] - datetime.now(timezone.utc) > timedelta(seconds=25)


def test_reconciliacao_reabre_so_o_que_diverge():
    fonte, lote = _cenario()      # o dia declara 4 resultados
    fila = _fila_com([DIA, DIA - timedelta(days=1)])
    fila.tarefas[0].update(checkpoint={"lido_em": "x"}, totais={"resultados": 4},
                           estado="concluida")
    fila.tarefas[1].update(checkpoint={"lido_em": "x"}, totais={"resultados": 3},
                           estado="concluida")
    r = pi.reconciliar(fila.tarefas, lote=lote, pncp=None, reabrir=fila.reabrir_uma)
    assert r["conferidas"] == 2 and r["batem"] == 1
    assert r["divergentes"] == [{"particao": (DIA - timedelta(days=1)).isoformat(),
                                 "fonte": "comprasgov_lote", "lido": 3, "declarado": 4}]
    assert [t["estado"] for t in fila.tarefas] == ["concluida", "pendente"]


def test_reconciliacao_sem_resposta_nao_muda_nada():
    _, lote = _cenario()
    lote.http._abrir = lambda url: (503, {}, b"")
    fila = _fila_com([DIA])
    fila.tarefas[0].update(checkpoint={"lido_em": "x"}, totais={"resultados": 1},
                           estado="concluida")
    r = pi.reconciliar(fila.tarefas, lote=lote, pncp=None, reabrir=fila.reabrir_uma)
    assert r["sem_resposta"] == 1 and fila.tarefas[0]["estado"] == "concluida"


def test_cli_plan_simulado_conta_as_particoes(capsys):
    assert pi.main(["plan", "--campanha", "c", "--desde", "2026-11-01", "--ate", "2026-11-10",
                    "--simular", "--fontes", "comprasgov_lote", "pncp_descoberta"]) == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida == {"tarefas": 10 + 10 * len(pi.MODALIDADES), "recentes": 150,
                     "historicas": 0}
