"""
Índice do PNCP no fluxo automático, com ORIGEM e CANAL separados (PR 1 da
cotação automática multiportal, 10/11/2026).

O que estas provas guardam:

* a origem da compra (o portal) e o canal de leitura (PNCP) são campos
  separados — "Origem Licitanet · Coleta via PNCP" — e chegam à API e ao
  relatório;
* a origem só é atribuída quando publicador (`usuarioNome`) e link de
  origem corroboram; contradição ou ausência é "Origem não identificada",
  com a evidência guardada;
* cada portal da especificação tem situação registrada (via PNCP
  verificada, direta validada, evidência manual, aguardando acesso);
* a revisita do índice tira da busca o resultado cancelado ou corrigido
  depois da coleta — sem apagar — e o reativa se ele voltar a valer;
* a indexação agendada roda descoberta e coleta com orçamentos separados;
* a cotação AUTOMÁTICA em lote (o caminho do worker) consulta o índice
  quando a flag está ligada e grava a referência com a origem.
"""

from __future__ import annotations

import copy
from datetime import date
from pathlib import Path

import pytest

from src import db, governanca
from src.precos import cotacoes, pncp, portais, relatorio_view
from src.precos import pncp_indice as indice
from src.precos import repositorio as repo
from src.precos.fontes import Consulta, Desfecho
from src.precos.modelo import Fonte
from tests.cotacoes_apoio import ligar_banco_falso
from tests.test_cotacoes_g2_servico import CTX
from tests.test_pncp_indice import ATE, CIMENTO, FIXTURE, ApiFalsa, _coletor, _indexar
from tests.test_precos_fase4 import _FonteFalsa


# ---------------------------------------------------------------------------
# Atribuição da origem
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("publicador, link, esperado, corroborada", [
    ("ECustomize Consultoria em Software S.A",
     "https://www.portaldecompraspublicas.com.br/processos/PA/x", "pcp", True),
    ("Bolsa Nacional De Compras - BNC",
     "https://bnccompras.com/Process/ProcessView?param1=x", "bnc", True),
    ("M2A tecnologia", "http://precodereferencia.m2atecnologia.com.br/c/x", "m2a", True),
    ("LICITANET", "", "licitanet", True),                       # só o publicador
    # por palavra inteira: "Licitações Eletrônicas" não é "Licitações-e"
    ("Licitanet Licitações Eletrônicas LTDA", "https://licitanet.com.br/sessao/1",
     "licitanet", True),
    ("Licitações-E BB", "https://licitacoes-e2.bb.com.br/x", "licitacoes_e", True),
    ("", "https://licitacoes-e2.bb.com.br/aop/x", "licitacoes_e", True),  # só o link
])
def test_publicador_e_link_que_corroboram_dao_a_origem(publicador, link, esperado,
                                                      corroborada):
    a = portais.atribuir_pncp(publicador, link)
    assert (a.origem_id, a.corroborada) == (esperado, corroborada)
    assert a.canal_id == portais.CANAL_PNCP
    assert a.rotulo == f"Origem {portais.REGISTRO[esperado].nome} · Coleta via PNCP"


def test_publicador_e_link_que_se_contradizem_nao_viram_palpite():
    a = portais.atribuir_pncp("Licitanet", "https://bnccompras.com/Process/x")
    assert a.origem_id == portais.NAO_IDENTIFICADA and not a.corroborada
    assert a.rotulo == "Origem não identificada · Coleta via PNCP"
    # a evidência do PNCP fica guardada para a revisão
    assert a.publicador == "Licitanet" and a.link_origem.startswith("https://bnccompras")


def test_sem_evidencia_reconhecida_e_origem_nao_identificada():
    a = portais.atribuir_pncp("Sistema Municipal Próprio", "https://exemplo.test/x")
    assert a.origem_id == portais.NAO_IDENTIFICADA
    assert a.publicador == "Sistema Municipal Próprio"
    assert portais.atribuir_pncp(None, None).origem_id == portais.NAO_IDENTIFICADA


def test_dominio_parecido_nao_engana_o_link():
    # "naolicitanet.com.br" não é subdomínio de licitanet.com.br
    assert portais.portal_do_link("https://naolicitanet.com.br/x") is None
    assert portais.portal_do_link("https://app.licitanet.com.br/x").id == "licitanet"


def test_cada_portal_da_especificacao_tem_situacao_registrada():
    situacoes = {p["id"]: p["situacao"] for p in portais.situacao_dos_portais()}
    esperados = {"licitanet", "licitacoes_e", "pcp", "bll", "bnc", "compras_para",
                 "m2a", "comprasbr", "bbmnet", "licitar_digital", "curitiba",
                 "tcm_pa", "tce_rs", "tce_pr", "compras_gov"}
    assert esperados <= set(situacoes)
    assert set(situacoes.values()) <= {s.value for s in portais.Situacao}
    # medição de produção de 12/11/2026: o que tem resultado no índice entra
    # via PNCP; o que não apareceu (Compras BR), aguarda aparecer nele
    for via_pncp in ("licitanet", "pcp", "bll", "bnc", "bbmnet", "licitar_digital"):
        assert situacoes[via_pncp] == portais.Situacao.VIA_PNCP_VERIFICADA.value
    assert situacoes["comprasbr"] == portais.Situacao.AGUARDANDO_ACESSO.value
    assert situacoes["tcm_pa"] == portais.Situacao.EVIDENCIA_MANUAL.value


def test_plataformas_privadas_nao_tem_canal_direto_nem_trilha_de_licenca():
    """Decisão de 12/11/2026: as plataformas privadas e o TCM-PA chegam pelo
    PNCP (Lei 14.133, art. 174) e saíram de `fontes_externas`. Uma volta
    para lá teria de ser decisão nova, não resto de cadastro."""
    from src.precos import fontes_externas

    privadas = ("licitanet", "pcp", "bll", "bnc", "comprasbr", "bbmnet",
                "licitar_digital", "tcm_pa")
    for pid in privadas:
        portal = portais.REGISTRO[pid]
        assert portal.registro_externo == "" and portal.pendencia_direta == ""
        assert "12/11/2026" in portal.evidencia
        assert pid not in fontes_externas.REGISTRO
    assert sorted(fontes_externas.REGISTRO) == ["bps", "tce_rs"]
    # todo `registro_externo` que sobrou aponta para entrada que existe
    for portal in portais.REGISTRO.values():
        assert not portal.registro_externo or \
            portal.registro_externo in fontes_externas.REGISTRO
    # canal direto sem prova real não é declarado ativo
    for portal in portais.REGISTRO.values():
        if portal.situacao is portais.Situacao.DIRETA_VALIDADA:
            assert portal.id == "compras_gov"


def test_toda_contratacao_da_fixture_real_tem_origem_identificada():
    for c in FIXTURE["contratacoes"]:
        contratacao = c["contratacao"]
        a = portais.atribuir_pncp(contratacao.get("usuarioNome"),
                                  contratacao.get("linkSistemaOrigem"))
        assert a.origem_id != portais.NAO_IDENTIFICADA, contratacao["usuarioNome"]
        assert a.corroborada


# ---------------------------------------------------------------------------
# A origem chega à referência, à API e ao relatório
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def armazem():
    return _indexar().armazem


def test_referencia_do_indice_carrega_publicador_e_link(armazem):
    fonte = indice.PNCPIndice(armazem.buscar)
    ref = next(r for r in fonte.pesquisar(Consulta(descricao="Cimento CP 2 F")).referencias
               if r.id_externo == f"{CIMENTO}#1#1")
    assert ref.bruto["usuarioNome"].startswith("ECustomize")
    a = portais.atribuir(ref.fonte.id, ref.bruto)
    assert a.rotulo == "Origem Portal de Compras Públicas · Coleta via PNCP"


def test_relatorio_imprime_origem_so_quando_difere_da_fonte(armazem):
    fonte = indice.PNCPIndice(armazem.buscar)
    ref = fonte.pesquisar(Consulta(descricao="Cimento CP 2 F")).referencias[0]
    linha = repo.linha_de_referencia(ref, tenant_id="t", item_id="i")
    assert relatorio_view._origem_canal(linha) == (
        "Origem Portal de Compras Públicas · Coleta via PNCP")
    assert relatorio_view._origem_canal({"fonte_id": "compras_gov_precos"}) == ""


# ---------------------------------------------------------------------------
# Revisita: correção e cancelamento tardios
# ---------------------------------------------------------------------------
def _revisitar(api, armazem):
    alvo = api.contratacoes[0]
    alvo["contratacao"]["dataAtualizacaoGlobal"] = "2026-10-10T09:00:00"
    coletor = _coletor(api, armazem)
    coletor.descobrir("PA", modalidades=(6,), ate=date(2026, 10, 15))
    coletor.coletar()
    return coletor


def test_resultado_cancelado_depois_da_coleta_sai_da_busca_sem_ser_apagado():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    chave = f"{CIMENTO}#1#1"
    assert any(l["id_externo"] == chave for l in armazem.buscar(["cimento"]))
    api.contratacoes[0]["resultados"]["1"][0]["dataCancelamento"] = "2026-10-09"
    coletor = _revisitar(api, armazem)
    assert coletor.rodada.invalidados == 1
    linha = armazem.resultados[chave]
    assert linha["vigente"] is False                 # guardada, não apagada
    assert "revisita" in linha["invalidado_motivo"]
    assert all(l["id_externo"] != chave for l in armazem.buscar(["cimento"]))
    # a fonte também recusa linha não vigente que escape do filtro
    assert indice.PNCPIndice(lambda *a, **k: [linha]).pesquisar(
        Consulta(descricao="cimento cp 2 f")).referencias == []


def test_item_que_perde_o_resultado_sai_e_o_que_volta_a_valer_e_reativado():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    chave = f"{CIMENTO}#1#1"
    original = copy.deepcopy(api.contratacoes[0]["itens"])
    for item in api.contratacoes[0]["itens"]:
        if item["numeroItem"] == 1:
            item["temResultado"] = False          # resultado revogado
    _revisitar(api, armazem)
    assert armazem.resultados[chave]["vigente"] is False
    # nova atualização: o item volta a ter o resultado homologado
    api.contratacoes[0]["itens"] = original
    api.contratacoes[0]["contratacao"]["dataAtualizacaoGlobal"] = "2026-10-20T09:00:00"
    coletor = _coletor(api, armazem)
    coletor.descobrir("PA", modalidades=(6,), ate=date(2026, 10, 25))
    coletor.coletar()
    assert armazem.resultados[chave]["vigente"] is True
    assert any(l["id_externo"] == chave for l in armazem.buscar(["cimento"]))


def test_retomada_no_meio_invalida_item_a_item_o_que_relê():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    chave = f"{CIMENTO}#2#1"
    assert armazem.resultados[chave].get("vigente", True) is True
    api.contratacoes[0]["resultados"]["2"][0]["dataCancelamento"] = "2026-10-09"
    armazem.salvar_contratacao(CIMENTO, estado=indice.PENDENTE, itens_lidos_ate=1)
    coletor = _coletor(api, armazem)
    coletor.coletar()
    assert coletor.rodada.invalidados == 1
    assert armazem.resultados[chave]["vigente"] is False
    assert armazem.resultados[f"{CIMENTO}#1#1"].get("vigente", True) is True


def test_retomada_no_meio_nao_invalida_o_que_a_rodada_anterior_confirmou():
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    _indexar(api, armazem)
    # contratação reaberta como pendente a partir do item 1 (retomada)
    armazem.salvar_contratacao(CIMENTO, estado=indice.PENDENTE, itens_lidos_ate=1)
    coletor = _coletor(api, armazem)
    coletor.coletar()
    assert coletor.rodada.invalidados == 0
    assert armazem.resultados[f"{CIMENTO}#1#1"].get("vigente", True) is True


# ---------------------------------------------------------------------------
# Indexação agendada
# ---------------------------------------------------------------------------
def test_ciclo_agendado_reparte_o_orcamento_entre_descoberta_e_coleta(capsys):
    from src.precos import pncp_indice_servico as script
    api, armazem = ApiFalsa(), indice.ArmazemEmMemoria()
    relato = script.rodada(armazem, "PA", dias=30, ate=ATE, modalidades=(6,),
                           max_chamadas=10, max_contratacoes=10, pausa=0,
                           fracao_descoberta=0.3, abrir_url=api,
                           dormir=lambda s: None)
    assert relato["descoberta"]["chamadas"] <= 3
    # a coleta fica com TODO o resto do orçamento (e para nele)
    assert relato["coleta"]["chamadas"] > 0 and relato["coleta"]["interrompida"]
    assert relato["descoberta"]["chamadas"] + relato["coleta"]["chamadas"] == 10


def test_ciclo_uma_vez_registra_cada_uf_e_nao_derruba_na_falha(capsys):
    from src.precos import pncp_indice_servico as script

    class Quebrado(indice.ArmazemEmMemoria):
        def cursor(self, uf, modalidade):
            raise RuntimeError("banco fora")

    assert script.ciclo(Quebrado(), ["PA", "AP"], intervalo_s=1, uma_vez=True,
                        dias=30, ate=ATE, modalidades=(6,), max_chamadas=5,
                        max_contratacoes=1, pausa=0) == 0
    linhas = capsys.readouterr().out.strip().splitlines()
    assert len(linhas) == 2 and all('"erro": "RuntimeError"' in l for l in linhas)


# ---------------------------------------------------------------------------
# O caminho do worker: cotação automática em lote, com a flag ligada
# ---------------------------------------------------------------------------
def test_lote_automatico_consulta_o_indice_e_grava_a_origem(monkeypatch, armazem):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome in (
        governanca.FLAG_PNCP_INDICE, governanca.FLAG_TETO_AUTOMATICO))
    import src.precos as precos_pkg

    compras = _FonteFalsa(Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial"))
    monkeypatch.setattr(precos_pkg, "fontes_padrao",
                        lambda: [compras, pncp.PNCPAdapter()])
    # a RPC com o JWT do usuário, respondida pelo índice de bancada
    monkeypatch.setattr(repo, "buscar_indice_pncp", armazem.buscar)
    # o corte é o dia da execução: fixado na data dos dados da fixture
    monkeypatch.setattr(cotacoes, "hoje_da_execucao", lambda: date(2025, 6, 30))
    c = cotacoes.criar_cotacao(CTX, {"nome": "Lote PNCP", "data_base": "2025-06-30"})
    item = cotacoes.salvar_item(CTX, str(c["id"]), {
        "descricao": "CIMENTO CP 2 F", "unidade": "UNIDADE", "quantidade": "10"})
    resultados, restantes = cotacoes.pesquisar_em_lote(CTX, str(c["id"]),
                                                       modo="automatico", tamanho=5)
    assert restantes == 0 and len(resultados) == 1
    assert resultados[0].desfechos["pncp"] == Desfecho.COM_PRECOS.value
    # o Compras.gov continua (uma vez por fase da expansão, amostra curta)
    assert compras.chamadas >= 1
    gravadas = [l for l in repo.listar_referencias(str(item["id"]))
                if l["fonte_id"] == "pncp"]
    assert gravadas
    assert {portais.atribuir("pncp", l["bruto"]).origem_id for l in gravadas} == {"pcp"}


def test_servico_agendado_mora_em_src_e_a_imagem_nao_carrega_scripts(monkeypatch):
    from pathlib import Path

    from src.precos import pncp_indice_servico as servico

    raiz = Path(__file__).resolve().parent.parent
    assert "scripts/" not in (raiz / "implantacao" / "Dockerfile.api").read_text("utf-8")
    compose = (raiz / "implantacao" / "docker-compose.yml").read_text("utf-8")
    assert '"-m", "src.precos.pncp_indice_servico", "ciclo", "--banco"' in compose
    # sem a credencial no ambiente, para com a mensagem — sem imprimir nada dela
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_KEY no ambiente"):
        servico.main(["ciclo", "--banco", "--uma-vez"])
