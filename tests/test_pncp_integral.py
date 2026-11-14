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


def test_pagina_faltando_grava_o_lido_e_registra_a_falta():
    # medido em produção (14/11/2026): 9.599 de 9.695 descartava o dia INTEIRO
    fonte, lote = _cenario(corta_pagina=2)
    armazem = pncp_indice.ArmazemEmMemoria()
    totais = pi.importar_dia(lote, armazem, DIA)
    assert totais.declarados == 4 and totais.resultados == 2 and totais.faltantes == 2
    assert totais.gravadas == 2 and len(armazem.resultados) == 2
    # tentou de novo antes de desistir (paginação instável na fonte)
    # só a página curta é relida, até as passadas acabarem
    assert sum("/3_" in u for u in fonte.urls) == 2 + (pi.PASSADAS_DO_DIA - 1)


def test_segunda_passada_completa_a_uniao():
    fonte, lote = _cenario()
    chamadas = {"n": 0}
    original = fonte.__call__

    def instavel(url):
        if "/3_" in url:
            chamadas["n"] += 1
            if chamadas["n"] == 2:          # 1ª passada perde a página 2
                fonte.corta_pagina = 2
                resposta = original(url)
                fonte.corta_pagina = None
                return resposta
        return original(url)
    lote.http._abrir = instavel
    unicas, declarado, recebidas = lote.resultados_do_dia(DIA)
    assert len(unicas) == declarado == recebidas == 4   # a página curta foi trocada


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
    assert lim.intervalo("h") > lim.base


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
    assert recentes[0]["particao"] == "2026-11-12"   # o mais novo primeiro
    # orçamento por faixa: o histórico entra intercalado (1 a cada 4
    # recentes), nunca inteiro depois do ano — e o ano ainda vai na frente
    ordem = sorted(tarefas, key=lambda t: t["prioridade"])
    primeiras = [t["faixa"] for t in ordem[:50]]
    assert primeiras.count("historico") >= 10 and primeiras.count("recente") >= 35
    assert ordem[0]["faixa"] == "recente"
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
    linhas[0]["totais"].update(inseridas=5, atualizadas=2, recusadas={"x": 3},
                               tempos={"requisicao_s": 1.5, "gravacao_s": 0.5})
    r = pi.relatorio(linhas)["comprasgov_lote/recente"]
    assert r["total"] == 2 and r["estados"] == {"concluida": 1, "pendente": 1}
    assert (r["resultados"], r["gravadas"], r["chamadas"]) == (10, 7, 30)
    assert (r["inseridas"], r["atualizadas"]) == (5, 2)
    assert r["recusadas"] == {"x": 3} and r["tempos"]["requisicao_s"] == 1.5


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
        if "/contratacoes/publicacao" in partes.path or "/contratacoes/atualizacao" in partes.path:
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
    # publicação com menos de 30 dias: faixa própria, relida até sair resultado
    assert all(t["faixa"] == "atualizacao" for t in tarefas)


def test_nenhuma_faixa_fica_indefinidamente_no_fim():
    # 14/11/2026: a publicação fresca ia inteira para o fim e o histórico
    # esperava o ano todo. Com o passo por faixa, a cada janela da fila as
    # três faixas recebem a sua parte (4 : 2 : 1).
    tarefas = pi.plano_pncp("c", ate=date(2026, 11, 13), desde=date(2023, 1, 1),
                            modalidades=(6,))
    ordem = sorted(tarefas, key=lambda t: t["prioridade"])
    primeiras = [t["faixa"] for t in ordem[:140]]
    assert primeiras.count("historico") >= 15            # orçamento mínimo do histórico
    assert primeiras.count("atualizacao") >= 25          # e da publicação fresca
    assert primeiras.count("recente") >= 60              # o ano da cotação domina


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
    assert saida == {"tarefas": 10 + 10 * len(pi.MODALIDADES), "recentes": 10,
                     "atualizacao": 140, "historicas": 0}



def test_429_de_um_host_nao_freia_o_outro():
    lim = pi.Limitador(1.0, dormir=lambda s: None)
    lim.respeitar("pncp.gov.br", 30)
    assert lim.intervalo("pncp.gov.br") > lim.base
    assert lim.intervalo("dadosabertos.compras.gov.br") == lim.base


def test_dia_recente_lido_vazio_volta_amanha():
    ontem = date.today() - timedelta(days=1)
    fonte = Fonte([], {}, {})
    lote = pi.ComprasGovLote(pi.ClienteHttp(pi.Limitador(1000, dormir=lambda s: None),
                                            abrir=fonte))
    fila = _fila_com([ontem])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "pendente"
    espera = fila.tarefas[0]["proxima_em"] - datetime.now(timezone.utc)
    assert timedelta(hours=23) < espera < timedelta(days=1, minutes=1)


# ---------------------------------------------------------------------------
# Ingestão medida (14/11/2026): gravar o lido, contar o que entrou, retomar
# ---------------------------------------------------------------------------
def test_gravacao_conta_inseridas_atualizadas_e_inalteradas():
    armazem = pncp_indice.ArmazemEmMemoria()
    _, lote = _cenario()
    t1 = pi.importar_dia(lote, armazem, DIA)
    assert (t1.inseridas, t1.atualizadas, t1.inalteradas) == (3, 0, 0)
    _, lote = _cenario()
    t2 = pi.importar_dia(lote, armazem, DIA)          # releitura: nada novo
    assert (t2.inseridas, t2.atualizadas, t2.inalteradas) == (0, 0, 3)
    fonte, lote = _cenario()
    fonte.resultados[0]["valorUnitarioHomologado"] = 90.0   # correção na fonte
    fonte.resultados[0]["valorTotalHomologado"] = 180.0
    t3 = pi.importar_dia(lote, armazem, DIA)
    assert (t3.inseridas, t3.atualizadas, t3.inalteradas) == (0, 1, 2)
    assert armazem.resultados["11111111000111-1-000001/2026#1#1"]["valor_unitario"] \
        .startswith("90")
    assert len(armazem.resultados) == 3                  # nunca duplica


def test_tempos_por_fase_e_recusas_por_motivo_ficam_nos_totais():
    _, lote = _cenario()
    r = pi.importar_dia(lote, pncp_indice.ArmazemEmMemoria(), DIA).registro()
    assert set(r["tempos"]) == {"espera_s", "requisicao_s", "transformacao_s",
                                "validacao_s", "gravacao_s"}
    assert r["recebidos"] == 4 and r["declarados"] == 4 and r["chamadas"] == 6
    assert r["recusadas"] == {pncp_indice.CRITERIO_MAIOR_DESCONTO: 1}


def test_rede_cai_no_meio_do_dia_o_lido_fica_e_a_retomada_nao_repete():
    fonte, lote = _cenario()
    original = fonte.__call__
    c2 = "22222222000122"
    lote.http._abrir = lambda url: (503, {}, b"") if ("/2.1_" in url and c2 in url) \
        else original(url)
    armazem = pncp_indice.ArmazemEmMemoria()
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=armazem, fila=fila) == "pendente"
    gravada = fila.tarefas[0]
    assert len(armazem.resultados) == 2                       # a 1ª contratação ficou
    assert gravada["checkpoint"]["compra_feita_ate"].startswith("11111111000111")
    assert gravada["totais"]["gravadas"] == 2 and "503" in gravada["erro"]
    # avançou: volta logo (não espera a escada de tentativas)
    assert gravada["proxima_em"] < datetime.now(timezone.utc) + timedelta(minutes=2)
    gravada["proxima_em"] = datetime.now(timezone.utc)
    _, lote2 = _cenario()
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote2, armazem=armazem, fila=fila) == "pendente"
    final = fila.tarefas[0]
    assert final["totais"]["puladas_por_retomada"] == 2       # não releu a 1ª
    assert final["totais"]["inseridas"] == 1                  # a PF; o desconto é recusado
    assert "compra_feita_ate" not in final["checkpoint"]      # a próxima leitura é completa
    assert len(armazem.resultados) == 3


class ArmazemQueRecusa(pncp_indice.ArmazemEmMemoria):
    def gravar_resultados(self, linhas):
        raise RuntimeError("new row violates check constraint")


def test_falha_de_gravacao_nunca_e_ocultada():
    _, lote = _cenario()
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=ArmazemQueRecusa(), fila=fila) == "pendente"
    t = fila.tarefas[0]
    assert t["erro"].startswith("gravação: RuntimeError")
    assert t["totais"]["falhas_gravacao"] == 3 and t["totais"]["gravadas"] == 0


def test_dia_de_ontem_com_resultado_e_relido_amanha_mesmo_assim():
    ontem = date.today() - timedelta(days=1)
    _, lote = _cenario()
    fila = _fila_com([ontem])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    assert pi.executar(tarefa, lote=lote, armazem=pncp_indice.ArmazemEmMemoria(),
                       fila=fila) == "pendente"
    espera = fila.tarefas[0]["proxima_em"] - datetime.now(timezone.utc)
    assert timedelta(hours=23) < espera < timedelta(days=1, minutes=1)
    assert fila.tarefas[0]["totais"]["gravadas"] == 3


def test_plano_do_dia_cria_o_dia_novo_e_a_atualizacao_sem_duplicar():
    hoje = date(2026, 11, 14)
    fila = pi.FilaEmMemoria()
    s = pi.Servico(fila=fila, lote=None, armazem=None, campanha="c",
                   fontes_da_pista=("comprasgov_lote",))
    assert s.planejar(hoje) == 2 + 2 * len(pi.MODALIDADES)
    assert s.planejar(hoje) == 0                                  # uma vez por dia
    s._planejado_em = None
    assert s.planejar(hoje) == 0                                  # e idempotente
    particoes = {t["particao"] for t in fila.tarefas}
    assert {"2026-11-13", "2026-11-12", "6:2026-11-13", "u:6:2026-11-13"} <= particoes
    assert all(t["faixa"] == "urgente" and t["prioridade"] < 0 for t in fila.tarefas)


def test_atualizacao_reagenda_contratacao_ja_lida():
    controle = "17935388000115-1-000108/2026"
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "pncp_contratacao", "particao": controle},
                {"campanha": "c", "fonte": "pncp_descoberta", "particao": "u:6:2026-11-13"}])
    fila.tarefas[0].update(estado="concluida",
                           proxima_em=datetime.now(timezone.utc) + timedelta(days=60))
    tarefa = fila.reservar("w", ["pncp_descoberta"], 1, 60)[0]
    portal = PortalPncp([_contr_pncp(controle)], [], {})
    totais = pi.executar_descoberta(tarefa, pncp=_pncp(portal), fila=fila)
    assert totais["reagendadas"] == 1 and totais["enfileiradas"] == 0
    assert fila.tarefas[0]["estado"] == "pendente"
    assert fila.tarefas[0]["proxima_em"] <= datetime.now(timezone.utc)
    assert any("/contratacoes/atualizacao" in u for u in portal.urls)


def _tarefa_careacu(fila, controle="17935388000115-1-000108/2026", **ck):
    fila.criar([{"campanha": "c", "fonte": "pncp_contratacao", "particao": controle,
                 "checkpoint": {"cabecalho": pncp_indice.resumo_da_contratacao(
                     _contr_pncp(controle)), **ck}}])
    return fila.reservar("w", ["pncp_contratacao"], 1, 60)[0]


def test_429_no_meio_da_contratacao_grava_o_lido_e_retoma_do_item():
    itens, resultados = _careacu()
    item3 = {**itens[1], "numeroItem": 3, "descricao": "CENTRIFUGA"}
    itens.append(item3)
    resultados[3] = [{**resultados[2][0], "numeroItem": 3, "valorUnitarioHomologado": 900.0,
                      "valorTotalHomologado": 900.0}]
    portal = PortalPncp([], itens, resultados)
    bloqueado = {"sim": True}

    def abrir(url):
        if bloqueado["sim"] and "/itens/3/resultados" in url:
            return 429, {"Retry-After": "0"}, b""
        return portal(url)
    pncp = _pncp(abrir)
    fila = pi.FilaEmMemoria()
    armazem = pncp_indice.ArmazemEmMemoria()
    tarefa = _tarefa_careacu(fila)
    assert pi.executar(tarefa, lote=None, armazem=armazem, fila=fila, pncp=pncp) == "pendente"
    t = fila.tarefas[0]
    assert t["checkpoint"]["item_feito_ate"] == 2 and len(armazem.resultados) == 1
    assert "429" in t["erro"]
    bloqueado["sim"] = False
    t["proxima_em"] = datetime.now(timezone.utc)
    tarefa = fila.reservar("w", ["pncp_contratacao"], 1, 60)[0]
    pi.executar(tarefa, lote=None, armazem=armazem, fila=fila, pncp=pncp)
    assert len(armazem.resultados) == 2
    assert sum("/itens/2/resultados" in u for u in portal.urls) == 1   # não releu o 2


def test_releitura_completa_invalida_resultado_que_sumiu_da_fonte():
    itens, resultados = _careacu()
    fila = pi.FilaEmMemoria()
    armazem = pncp_indice.ArmazemEmMemoria()
    controle = "17935388000115-1-000108/2026"
    linha, _ = pncp_indice.linha_do_resultado(
        pncp_indice.resumo_da_contratacao(_contr_pncp(controle)), itens[1],
        {**resultados[2][0], "sequencialResultado": 2})
    armazem.gravar_resultados([linha])
    tarefa = _tarefa_careacu(fila, leituras=1)
    totais = pi.executar_contratacao(tarefa, pncp=_pncp(PortalPncp([], itens, resultados)),
                                     armazem=armazem)
    assert totais["invalidadas"] == 1
    assert armazem.resultados[f"{controle}#2#2"]["vigente"] is False
    assert armazem.resultados[f"{controle}#2#1"]["vigente"] is True


def test_429_do_pncp_nao_para_a_pista_do_comprasgov():
    # duas pistas, um limitador por host: a do PNCP dorme o Retry-After, a
    # do Compras.gov termina o dia enquanto isso (relógio real)
    import time as _t
    lim = pi.Limitador(1000)
    fonte, _ = _cenario()
    lote = pi.ComprasGovLote(pi.ClienteHttp(lim, abrir=fonte))
    pncp = pi.PncpItemAItem(pi.ClienteHttp(
        lim, abrir=lambda url: (429, {"Retry-After": "1"}, b"")))
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "comprasgov_lote", "particao": DIA.isoformat()},
                {"campanha": "c", "fonte": "pncp_descoberta", "particao": "6:2026-10-29"}])
    fila.ajustar_controle(req_por_s=1000)
    armazem = pncp_indice.ArmazemEmMemoria()
    pista_pncp = pi.Servico(fila=fila, lote=None, pncp=pncp, armazem=armazem, dono="p",
                            fontes_da_pista=("pncp_contratacao", "pncp_descoberta"))
    pista_lote = pi.Servico(fila=fila, lote=lote, armazem=armazem, dono="p",
                            fontes_da_pista=("comprasgov_lote",))
    t = threading.Thread(target=pista_pncp.rodar, kwargs={"uma_vez": True})
    t.start()
    _t.sleep(0.1)                     # a pista do PNCP já está dormindo o 429
    inicio = _t.monotonic()
    assert pista_lote.passo() == 1
    lote_s = _t.monotonic() - inicio
    assert t.is_alive() and lote_s < 0.5          # não esperou o Retry-After do outro host
    assert len(armazem.resultados) == 3
    t.join()
    assert lim.intervalo("pncp.gov.br") > lim.intervalo("dadosabertos.compras.gov.br")
    assert fila.tarefas[1]["estado"] == "pendente" and "429" in fila.tarefas[1]["erro"]


def test_excecao_inesperada_volta_a_tarefa_e_a_pista_segue(monkeypatch):
    fila = _fila_com([DIA])
    s = pi.Servico(fila=fila, lote=None, armazem=None, fontes_da_pista=("comprasgov_lote",))

    def explode(*a, **k):
        raise KeyError("campo novo na fonte")
    monkeypatch.setattr(pi, "executar", explode)
    assert s.passo() == 1
    t = fila.tarefas[0]
    assert t["estado"] == "pendente" and t["erro"].startswith("inesperado: KeyError")


def test_ritmo_por_minuto_e_gargalo_medido():
    linhas = [{"fonte": "comprasgov_lote", "estado": "pendente", "erro": "",
               "totais": {"inseridas": 600, "atualizadas": 30, "inalteradas": 10,
                          "tempos": {"espera_s": 50.0, "requisicao_s": 400.0,
                                     "validacao_s": 5.0, "gravacao_s": 20.0}}},
              {"fonte": "pncp_contratacao", "estado": "pendente", "erro": "http 429",
               "totais": {"inseridas": 3, "tempos": {"espera_s": 90.0}}}]
    r = pi.ritmo(linhas, 30)
    assert r["fontes"]["comprasgov_lote"]["inseridas_por_min"] == 20.0
    assert r["fontes"]["comprasgov_lote"]["gargalo"] == "requisicao_s"
    assert r["fontes"]["pncp_contratacao"]["gargalo"] == "espera_s"
    assert r["fontes"]["pncp_contratacao"]["erros"] == {"http 429": 1}


def test_cliente_tenta_de_novo_o_429_antes_de_falhar_a_tarefa():
    respostas = [(429, {"Retry-After": "0"}, b""), (200, {}, b'{"ok": 1}')]
    http = pi.ClienteHttp(pi.Limitador(1000, dormir=lambda s: None),
                          abrir=lambda url: respostas.pop(0))
    assert http.json("https://pncp.gov.br/x") == {"ok": 1}
    assert http.chamadas == 2 and http.falhas == {"429": 1}


def test_cada_pista_tem_o_seu_ritmo_e_o_controle_so_mexe_no_pncp():
    lim = pi.Limitador(1.0, dormir=lambda s: None)
    fila = pi.FilaEmMemoria()
    fila.ajustar_controle(req_por_s=0.5)
    lote = pi.ComprasGovLote(pi.ClienteHttp(lim))
    pncp = pi.PncpItemAItem(pi.ClienteHttp(lim))
    pi.Servico(fila=fila, lote=lote, armazem=None, dono="p", req_por_s=2.0,
               fontes_da_pista=("comprasgov_lote",)).passo()
    pi.Servico(fila=fila, lote=None, pncp=pncp, armazem=None, dono="p",
               fontes_da_pista=("pncp_contratacao", "pncp_descoberta")).passo()
    assert lim.intervalo("dadosabertos.compras.gov.br") == 0.5    # 2 req/s, próprio
    assert lim.intervalo("pncp.gov.br") == 2.0                    # 0,5 req/s, do controle


def test_parada_limpa_solta_a_lideranca_e_o_novo_assume_na_hora():
    # promoção de 14/11/2026: o contêiner novo ficou 10 min parado no lease
    fila = pi.FilaEmMemoria()
    assert fila.liderar("antigo:1", 600)
    assert not fila.liderar("novo:1", 600)            # ainda vigente
    saidas = []
    pi.parar_limpo(fila, "antigo:1", sair=saidas.append)()
    assert saidas == [0]
    assert fila.liderar("novo:1", 600)                # assume sem esperar
    assert not fila.liberar("antigo:1")               # o antigo não solta o do novo


def test_linha_repetida_pela_fonte_nao_e_falta():
    # 13/11/2025 medido: 12.811 linhas declaradas e recebidas, 145 idênticas
    fonte, lote = _cenario()
    fonte.resultados.append(dict(fonte.resultados[0]))     # a fonte repete uma linha
    totais = pi.importar_dia(lote, pncp_indice.ArmazemEmMemoria(), DIA)
    assert totais.declarados == totais.recebidos == 5
    assert totais.resultados == 4 and totais.repetidas_na_fonte == 1
    assert totais.faltantes == 0


def test_pagina_vazia_no_meio_nao_encerra_a_leitura():
    # em produção a leitura parava na 1ª página vazia e pulava as seguintes
    fonte, lote = _cenario(pagina=1)
    vazias = {"n": 0}
    original = fonte.__call__

    def abrir(url):
        q = dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(url).query))
        if "/3_" in url and q.get("pagina") == "2" and vazias["n"] == 0:
            vazias["n"] += 1
            return 200, {}, json.dumps({"resultado": [], "totalRegistros": 4,
                                        "paginasRestantes": 0}).encode()
        return original(url)
    lote.http._abrir = abrir
    unicas, declarado, recebidas = lote.resultados_do_dia(DIA)
    assert len(unicas) == declarado == recebidas == 4


class _Consulta:
    def __init__(self, registro, tabela):
        self.registro, self.tabela = registro, tabela

    def upsert(self, dados, **kw):
        self.registro.append((self.tabela, "upsert", dados, kw))
        return self

    def select(self, *a):
        return self

    def in_(self, *a):
        return self

    def execute(self):
        return type("R", (), {"data": []})()


class _ClienteFalso:
    def __init__(self):
        self.registro = []

    def table(self, nome):
        return _Consulta(self.registro, nome)


def test_gravacao_cria_a_contratacao_antes_do_resultado_por_causa_da_fk():
    # 14/11/2026: a 1ª gravação do lote em produção foi recusada pela FK
    from src.precos.pncp_indice_servico import ArmazemSupabase
    _, lote = _cenario()
    cliente = _ClienteFalso()
    totais = pi.importar_dia(lote, ArmazemSupabase(cliente), DIA)
    ordem = [(t, op) for t, op, *_ in cliente.registro]
    assert ordem[0] == ("precos_pncp_contratacoes", "upsert")
    assert ("precos_pncp_resultados", "upsert") in ordem
    assert ordem.index(("precos_pncp_contratacoes", "upsert")) < \
        ordem.index(("precos_pncp_resultados", "upsert"))
    _, _, contratacoes, kw = cliente.registro[0]
    assert kw.get("ignore_duplicates") is True               # não pisa no coletor antigo
    assert {c["numero_controle"] for c in contratacoes} == {
        "11111111000111-1-000001/2026", "22222222000122-1-000002/2026"}
    assert all(c["estado"] == "coletada" and c["modalidade_id"] == 6 for c in contratacoes)
    assert totais.inseridas == 3


def test_contratacao_descoberta_entra_na_faixa_da_sua_publicacao_nao_no_urgente():
    # 14/11/2026: 6.025 alterações de um dia, todas na frente, 0 resultado
    hoje = date.today()
    velha = {**_contr_pncp("17935388000115-1-000108/2026"),
             "dataPublicacaoPncp": (hoje - timedelta(days=200)).isoformat() + "T10:00:00"}
    fresca = {**_contr_pncp("11415535000140-1-000008/2026"),
              "dataPublicacaoPncp": (hoje - timedelta(days=3)).isoformat() + "T10:00:00"}
    fila = pi.FilaEmMemoria()
    fila.criar([{"campanha": "c", "fonte": "pncp_descoberta", "faixa": "urgente",
                 "prioridade": pi.PRIORIDADE_URGENTE,
                 "particao": f"u:6:{(hoje - timedelta(days=1)).isoformat()}"}])
    tarefa = fila.reservar("w", ["pncp_descoberta"], 1, 60)[0]
    pi.executar_descoberta(tarefa, pncp=_pncp(PortalPncp([velha, fresca], [], {})), fila=fila)
    lugar = {t["particao"]: (t["faixa"], t["prioridade"])
             for t in fila.tarefas if t["fonte"] == "pncp_contratacao"}
    assert lugar["17935388000115-1-000108/2026"] == ("recente", 200)
    assert lugar["11415535000140-1-000008/2026"] == ("atualizacao", 6)


def test_reinicio_no_meio_do_dia_retoma_do_ultimo_lote_gravado():
    # 14/11/2026: docker restart no meio de 2026-10-06 — o dia voltava do zero
    _, lote = _cenario()
    fila = _fila_com([DIA])
    armazem = pncp_indice.ArmazemEmMemoria()
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]

    class Morte(BaseException):
        pass
    original = armazem.gravar_resultados
    gravacoes = {"n": 0}

    def grava_e_morre(linhas):
        gravacoes["n"] += 1
        if gravacoes["n"] == 2:
            raise Morte()               # SIGKILL: nenhum except roda
        return original(linhas)
    armazem.gravar_resultados = grava_e_morre
    with pytest.raises(Morte):
        pi.importar_dia(lote, armazem, DIA, lote_gravacao=1,
                        renovar=lambda p=None: fila.renovar(tarefa, 60, checkpoint=p))
    assert fila.tarefas[0]["checkpoint"]["compra_feita_ate"].startswith("11111111000111")
    armazem.gravar_resultados = original
    fila.tarefas[0].update(lease_ate=datetime.now(timezone.utc) - timedelta(seconds=1))
    nova = fila.reservar("w2", ["comprasgov_lote"], 1, 60)[0]
    _, lote2 = _cenario()
    assert pi.executar(nova, lote=lote2, armazem=armazem, fila=fila) == "pendente"
    assert fila.tarefas[0]["totais"]["puladas_por_retomada"] == 2
    assert len(armazem.resultados) == 3


def test_ponto_de_retomada_so_grava_o_dono_do_token():
    fila = _fila_com([DIA])
    tarefa = fila.reservar("w", ["comprasgov_lote"], 1, 60)[0]
    fila.tarefas[0]["token"] = "outro"
    assert fila.renovar(tarefa, 60, checkpoint={"compra_feita_ate": "x"}) is False
    assert "compra_feita_ate" not in fila.tarefas[0]["checkpoint"]
