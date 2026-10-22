"""
Logs estruturados e métricas RED (P06, ADR-005).

O que importa provar não é que "tem log": é o que NÃO vai para ele —
caminho com ids, query, token, texto de exceção, id do município — e que
a métrica agrupa por MODELO de rota (URL varrida não vira série nova).
"""

import io
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient

from govconect_api import observabilidade
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, TENANT_A, Emissor, PostgrestFalso


@pytest.fixture
def linhas():
    """As linhas JSON do log de acesso, com o formatador de produção."""
    saida = io.StringIO()
    manipulador = logging.StreamHandler(saida)
    manipulador.setFormatter(observabilidade.FormatoJson())
    logger = logging.getLogger("govconect_api.acesso")
    logger.addHandler(manipulador)
    # `setLevel`, não atribuição: só ele limpa o cache de `isEnabledFor`.
    nivel = logger.level
    logger.setLevel(logging.INFO)
    yield lambda: [json.loads(l) for l in saida.getvalue().splitlines() if l.strip()]
    logger.removeHandler(manipulador)
    logger.setLevel(nivel)


@pytest.fixture
def metricas(monkeypatch):
    novas = observabilidade.Metricas()
    monkeypatch.setattr(observabilidade, "METRICAS", novas)
    from govconect_api import camadas, main

    monkeypatch.setattr(camadas, "METRICAS", novas)
    monkeypatch.setattr(main, "METRICAS", novas)
    return novas


def _api():
    emissor = Emissor()
    banco = PostgrestFalso()
    rest = banco.cliente()
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    app = criar_app(config, rest=rest, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para))
    return TestClient(app, raise_server_exceptions=False), emissor


def test_linha_de_acesso_tem_modelo_de_rota_e_nada_do_pedido(linhas, metricas):
    cliente, _ = _api()
    pid = str(uuid.uuid4())
    token_falso = "abc.def.ghi"
    cliente.get(f"/api/v1/precos/pesquisas/{pid}?nome=segredo-da-query",
                headers={"Authorization": f"Bearer {token_falso}"})
    (linha,) = [l for l in linhas() if l.get("evento") == "requisicao"]
    assert linha["rota"] == "/api/v1/precos/pesquisas/{pesquisa_id}"
    assert linha["status"] in (401, 404)
    assert isinstance(linha["duracao_ms"], float) and linha["request_id"]
    texto = json.dumps(linha)
    for proibido in (pid, "segredo-da-query", token_falso, "Bearer"):
        assert proibido not in texto, proibido


def test_municipio_vai_pseudonimizado(linhas, metricas):
    cliente, emissor = _api()
    r = cliente.get("/api/v1/me", headers={"Authorization": f"Bearer {emissor.token()}"})
    assert r.status_code == 200
    (linha,) = [l for l in linhas() if l.get("evento") == "requisicao"]
    assert linha["tenant"] == observabilidade.pseudonimo(TENANT_A)
    assert TENANT_A not in json.dumps(linha)


def test_metricas_agrupam_por_rota_e_classe(metricas):
    cliente, emissor = _api()
    cliente.get("/api/v1/me")                                         # 401
    cliente.get("/api/v1/me", headers={"Authorization": f"Bearer {emissor.token()}"})
    for _ in range(3):
        cliente.get(f"/caminho-varrido/{uuid.uuid4()}")              # 404, sem rota
    texto = cliente.get("/health/metrics").text
    assert 'govconect_requisicoes_total{metodo="GET",rota="/api/v1/me",classe="4xx"} 1' in texto
    assert 'govconect_requisicoes_total{metodo="GET",rota="/api/v1/me",classe="2xx"} 1' in texto
    assert 'rota="desconhecida",classe="4xx"} 3' in texto
    assert "caminho-varrido" not in texto
    assert 'govconect_duracao_segundos_count{rota="/api/v1/me"} 2' in texto


def test_sonda_de_saude_nao_polui_o_log(linhas, metricas):
    cliente, _ = _api()
    cliente.get("/health/live")
    assert not [l for l in linhas() if l.get("evento") == "requisicao"]


def test_excecao_vai_so_com_o_tipo():
    registro = logging.LogRecord("govconect_api", logging.ERROR, "", 0, "falhou", None, None)
    try:
        raise RuntimeError("https://x.supabase.co?apikey=sb_publishable_vazou")
    except RuntimeError:
        import sys

        registro.exc_info = sys.exc_info()
    linha = json.loads(observabilidade.FormatoJson().format(registro))
    assert linha["excecao"] == "RuntimeError"
    assert "vazou" not in json.dumps(linha)


def test_extra_so_com_tipo_simples():
    registro = logging.LogRecord("govconect_api", logging.INFO, "", 0, "x", None, None)
    registro.campo = "ok"
    registro.objeto = {"token": "nao-vai"}
    linha = json.loads(observabilidade.FormatoJson().format(registro))
    assert linha["campo"] == "ok" and "objeto" not in linha


def test_metricas_rotulos_escapados():
    m = observabilidade.Metricas()
    m.job(tipo='a"b', estado="ok")
    assert 'tipo="a\\"b"' in m.texto()
