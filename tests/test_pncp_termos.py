"""
Busca NACIONAL do PNCP pelos itens cotados, no indexador (0043):
`Coletor.indexar_termo` e `pncp_indice_servico.rodada_por_termos`.

O portal é a API falsa de `test_pncp_nacional` (formato observado em
11/11/2026). Sem rede, sem banco.
"""

from __future__ import annotations

import urllib.error
from datetime import date, datetime, timedelta, timezone

import pytest

from src.precos import pncp_indice as indice
from src.precos import pncp_indice_servico as servico
from src.precos.fontes import Consulta
from tests.test_pncp_nacional import (CAREACU, COARI, JANELA, Portal, _hit, _item,
                                      _portal_padrao, _resultado)

HOJE = date(2026, 11, 11)
NUCLEO = "analisador bioquimico"


def _coletor(portal, armazem=None, **kw):
    kw.setdefault("pausa_s", 0)
    return indice.Coletor(armazem or indice.ArmazemEmMemoria(), abrir_url=portal,
                          dormir=kw.pop("dormir", lambda s: None), **kw)


def _itens_lidos(portal):
    return portal.de("/itens?")


# ---------------------------------------------------------------------------
# Coletor.indexar_termo
# ---------------------------------------------------------------------------
def test_grava_no_indice_os_resultados_nacionais_que_casam():
    portal = _portal_padrao()
    coletor = _coletor(portal)
    relato = coletor.indexar_termo(NUCLEO, hoje=HOJE)
    armazem = coletor.armazem
    assert relato == {"achadas": 2, "lidas": 2, "puladas": 0, "validos": 2}
    assert sorted((l["uf"], l["valor_unitario"]) for l in armazem.resultados.values()) == [
        ("AM", "270000.0"), ("MG", "12300.0")]
    # lâmpada e hematológico: nem chamada de resultado
    assert len(portal.de("/resultados")) == 2
    contratacao = armazem.contratacao(CAREACU)
    assert contratacao["estado"] == indice.PARCIAL
    assert contratacao["resumo"]["termos"] == [NUCLEO]
    assert contratacao["atualizacao_global"] == ""
    assert contratacao["uf"] == "MG" and contratacao["modalidade_id"] == 6
    linha = armazem.resultados[f"{CAREACU}#2#1"]
    assert (linha["municipio"], linha["orgao"]) == ("Careaçu", "Prefeitura de Careaçu")
    assert linha["orgao_cnpj"] == CAREACU.split("-")[0]
    assert linha["plataforma"] == "Portal de Compras Públicas"
    # a busca usa só os pregões do coletor, encerrados com resultado
    parametros = portal.busca()
    assert (parametros["q"], parametros["modalidades"], parametros["status"]) == (
        NUCLEO, "6|7", "encerradas")


def test_a_cotacao_acha_pelo_indice_de_sempre():
    coletor = _coletor(_portal_padrao())
    coletor.indexar_termo(NUCLEO, hoje=HOJE)
    r = indice.PNCPIndice(coletor.armazem.buscar).pesquisar(
        Consulta(descricao="ANALISADOR BIOQUÍMICO", limite=50, **JANELA))
    assert sorted(ref.uf for ref in r.referencias) == ["AM", "MG"]


def test_nao_rele_o_mesmo_termo_mas_le_outro_termo():
    portal = _portal_padrao()
    coletor = _coletor(portal)
    coletor.indexar_termo(NUCLEO, hoje=HOJE)
    antes = len(_itens_lidos(portal))
    relato = coletor.indexar_termo(NUCLEO, hoje=HOJE)
    assert relato["puladas"] == 2 and len(_itens_lidos(portal)) == antes
    coletor.indexar_termo("analisador bioquimico semiautomatico", hoje=HOJE)
    assert len(_itens_lidos(portal)) == antes + 2
    assert coletor.armazem.contratacao(CAREACU)["resumo"]["termos"] == [
        NUCLEO, "analisador bioquimico semiautomatico"]


@pytest.mark.parametrize("estado,pulada", [
    (indice.COLETADA, True), (indice.PENDENTE, True), (indice.FORA_DO_PILOTO, True),
    (indice.FALHA, True), (indice.SEM_RESULTADO, False)])
def test_contratacao_ja_conhecida_da_coleta_regional(estado, pulada):
    portal = _portal_padrao()
    armazem = indice.ArmazemEmMemoria()
    armazem.salvar_contratacao(CAREACU, estado=estado)
    _coletor(portal, armazem).indexar_termo(NUCLEO, hoje=HOJE)
    lidas = [u for u in _itens_lidos(portal) if CAREACU.split("-")[0] in u]
    assert (not lidas) is pulada


def test_compras_gov_fica_fora_como_na_regional():
    hits = [_hit(CAREACU), _hit(COARI, uf="AM", municipio="Coari")]
    hits[0]["usuario_nome"] = indice.PLATAFORMA_COMPRAS_GOV
    portal = _portal_padrao(hits)
    relato = _coletor(portal).indexar_termo(NUCLEO, hoje=HOJE)
    assert relato["puladas"] == 1 and relato["lidas"] == 1


def test_dispensa_e_publicacao_antiga_ficam_fora():
    hits = [_hit(CAREACU, modalidade="8"),
            _hit(COARI, publicada=(HOJE - timedelta(days=indice.TERMO_PUBLICACAO_DIAS + 1)
                                   ).isoformat())]
    portal = _portal_padrao(hits)
    relato = _coletor(portal).indexar_termo(NUCLEO, hoje=HOJE)
    assert relato["achadas"] == 0 and portal.urls == portal.de("/api/search/")


def test_limita_contratacoes_e_itens_por_termo():
    hits = [_hit(f"1111111100011{n}-1-0000{n}0/2026") for n in range(1, 6)]
    itens = [_item(k, f"ANALISADOR BIOQUÍMICO MODELO {k}") for k in range(1, 7)]
    portal = Portal(hits, {h["numero_controle_pncp"]: (
        itens, {k: _resultado(1000.0 * k) for k in range(1, 7)}) for h in hits})
    relato = _coletor(portal).indexar_termo(NUCLEO, hoje=HOJE, max_contratacoes=3,
                                            itens_por_contratacao=2)
    assert relato["lidas"] == 3
    assert len(_itens_lidos(portal)) == 3 and len(portal.de("/resultados")) == 6


def test_descoberta_regional_poe_a_parcial_na_fila_da_leitura_completa():
    armazem = indice.ArmazemEmMemoria()
    _coletor(_portal_padrao(), armazem).indexar_termo(NUCLEO, hoje=HOJE)
    regional = _coletor(_portal_padrao(), armazem)
    regional._registrar_descoberta({
        "numeroControlePNCP": CAREACU, "dataAtualizacaoGlobal": "2026-10-30T10:00:00",
        "usuarioNome": "Portal de Compras Públicas", "modalidadeId": 6,
        "unidadeOrgao": {"ufSigla": "MG"}, "valorTotalHomologado": 12300})
    assert armazem.contratacao(CAREACU)["estado"] == indice.PENDENTE


def test_interrompida_no_meio_a_proxima_rodada_rele():
    portal = _portal_padrao()
    armazem = indice.ArmazemEmMemoria()
    # busca + itens e resultado de Careaçu + itens de Coari: para antes do
    # resultado de Coari
    with pytest.raises(indice.OrcamentoEsgotado):
        _coletor(portal, armazem, max_chamadas=4).indexar_termo(NUCLEO, hoje=HOJE)
    assert armazem.contratacao(CAREACU)["resumo"]["termos"] == [NUCLEO]
    assert armazem.contratacao(COARI)["resumo"]["termos"] == []
    relato = _coletor(portal, armazem).indexar_termo(NUCLEO, hoje=HOJE)
    assert (relato["puladas"], relato["lidas"]) == (1, 1)     # só Coari, de novo
    assert armazem.contratacao(COARI)["resumo"]["termos"] == [NUCLEO]
    assert len(armazem.resultados) == 2


def test_busca_que_derruba_a_conexao_ganha_novas_tentativas():
    portal = _portal_padrao()
    portal.falhas = [urllib.error.URLError("reset")] * 3      # 1 `_json` inteiro
    esperas = []
    relato = _coletor(portal, dormir=esperas.append).indexar_termo(NUCLEO, hoje=HOJE)
    assert relato["lidas"] == 2
    assert indice.TERMO_ESPERA_BUSCA_S in esperas


def test_busca_com_formato_novo_e_erro_da_fonte():
    from src.precos.fontes import ErroFonte

    portal = _portal_padrao()
    portal.hits = "mudou"
    portal.__class__ = type("Mudado", (Portal,), {
        "__call__": lambda self, url: '{"resultados": []}'})
    with pytest.raises(ErroFonte, match="formato"):
        _coletor(portal).indexar_termo(NUCLEO, hoje=HOJE)


# ---------------------------------------------------------------------------
# rodada_por_termos
# ---------------------------------------------------------------------------
def _rodada(armazem, portal, **kw):
    kw.setdefault("max_chamadas", 100)
    kw.setdefault("max_termos", 10)
    return servico.rodada_por_termos(armazem, pausa=0, abrir_url=portal,
                                     dormir=lambda s: None, hoje=HOJE, **kw)


def test_nucleos_vem_dos_itens_cotados_sem_repetir():
    assert servico.nucleos_das_descricoes([
        "ANALISADOR BIOQUÍMICO", "Analisador bioquimico", "123", "Cimento CP II 32, saco"]) == [
        NUCLEO, "cimento"]


def test_nucleo_fora_do_check_da_0043_nao_entra():
    # "A4" sozinho daria "a4": 2 caracteres, e o CHECK recusaria o lote todo
    longo = " ".join(f"paralelepipedo{letra}" * 3 for letra in "abcd")   # > 120
    assert servico.nucleos_das_descricoes(["A4", longo, "Cola bastão"]) == ["cola bastao"]


def test_rodada_registra_busca_e_agenda_a_volta():
    armazem = indice.ArmazemEmMemoria()
    armazem.descricoes = ["ANALISADOR BIOQUÍMICO", "Analisador Bioquímico"]
    relato = _rodada(armazem, _portal_padrao())
    assert relato["termos"] == {"novos": 1, "buscados": 1, "falhas": 0}
    termo = armazem.termos[NUCLEO]
    assert (termo["contratacoes"], termo["resultados"], termo["falhas"]) == (2, 2, 0)
    volta = datetime.fromisoformat(termo["proxima_busca"]) - datetime.fromisoformat(
        termo["buscado_em"])
    assert volta == timedelta(days=indice.TERMO_REBUSCA_DIAS)
    # antes do prazo, o termo não volta
    portal = _portal_padrao()
    assert _rodada(armazem, portal)["termos"]["buscados"] == 0 and not portal.urls


def test_termo_nunca_buscado_vem_primeiro():
    armazem = indice.ArmazemEmMemoria()
    armazem.salvar_termo("cimento", buscado_em="2026-11-01T00:00:00+00:00",
                         proxima_busca="2026-11-02T00:00:00+00:00")
    armazem.descricoes = ["ANALISADOR BIOQUÍMICO"]
    portal = _portal_padrao()
    _rodada(armazem, portal, max_termos=1)
    assert portal.busca()["q"] == NUCLEO


def test_termo_que_falhou_volta_mais_cedo_com_o_motivo():
    armazem = indice.ArmazemEmMemoria()
    armazem.descricoes = ["ANALISADOR BIOQUÍMICO"]
    portal = _portal_padrao()
    portal.falhas = [urllib.error.URLError("reset")] * 20
    relato = _rodada(armazem, portal)
    assert relato["termos"]["falhas"] == 1
    termo = armazem.termos[NUCLEO]
    assert termo["falhas"] == 1 and "PNCP" in termo["erro"]
    assert termo.get("buscado_em") is None
    falta = datetime.fromisoformat(termo["proxima_busca"]) - datetime.now(timezone.utc)
    assert timedelta(hours=indice.TERMO_FALHA_HORAS - 1) < falta <= timedelta(
        hours=indice.TERMO_FALHA_HORAS)


def test_orcamento_esgotado_nao_marca_o_termo():
    armazem = indice.ArmazemEmMemoria()
    armazem.descricoes = ["ANALISADOR BIOQUÍMICO"]
    relato = _rodada(armazem, _portal_padrao(), max_chamadas=2)
    assert relato["coleta"]["interrompida"] and relato["termos"]["buscados"] == 0
    assert armazem.termos[NUCLEO].get("buscado_em") is None


def test_ciclo_roda_a_busca_por_termo_depois_das_ufs(monkeypatch, capsys):
    chamadas = []
    monkeypatch.setattr(servico, "rodada", lambda armazem, uf, **kw:
                        chamadas.append(("uf", uf)) or {"uf": uf})
    monkeypatch.setattr(servico, "rodada_por_termos", lambda armazem, **kw:
                        chamadas.append(("termos", kw["max_termos"])) or {"termos": {}})
    servico.ciclo(indice.ArmazemEmMemoria(), ["PA"], intervalo_s=1, uma_vez=True,
                  termos={"max_termos": 7})
    assert chamadas == [("uf", "PA"), ("termos", 7)]
    assert '"busca_por_termo"' in capsys.readouterr().out
    chamadas.clear()
    servico.ciclo(indice.ArmazemEmMemoria(), ["PA"], intervalo_s=1, uma_vez=True)
    assert chamadas == [("uf", "PA")]


def test_falha_da_busca_por_termo_nao_derruba_o_ciclo(monkeypatch, capsys):
    monkeypatch.setattr(servico, "rodada", lambda armazem, uf, **kw: {"uf": uf})

    def quebra(armazem, **kw):
        raise RuntimeError("tabela ausente")
    monkeypatch.setattr(servico, "rodada_por_termos", quebra)
    assert servico.ciclo(indice.ArmazemEmMemoria(), ["PA"], intervalo_s=1, uma_vez=True,
                         termos={}) == 0
    assert '"erro": "RuntimeError"' in capsys.readouterr().out


def test_linha_de_comando_liga_a_busca_por_termo_por_padrao():
    import argparse

    p = argparse.ArgumentParser()
    servico.argumentos_do_ciclo(p)
    capturado = {}

    def ciclo(armazem, ufs, **kw):
        capturado.update(kw)
        return 0
    original = servico.ciclo
    servico.ciclo = ciclo
    try:
        servico.rodar_ciclo(p.parse_args([]), None)
        assert capturado["termos"]["max_termos"] == 40
        assert capturado["termos"]["max_chamadas"] == 600
        assert capturado["termos"]["pausa"] >= 0.35
        servico.rodar_ciclo(p.parse_args(["--sem-termos"]), None)
        assert capturado["termos"] is None
    finally:
        servico.ciclo = original
