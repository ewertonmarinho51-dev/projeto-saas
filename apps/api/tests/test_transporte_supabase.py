"""
Conexões reaproveitadas até o Supabase, sem misturar usuários.

`db.cliente_do_usuario()` passou a dividir o transporte entre chamadas
(contexto TLS e conexão custavam 1.100 ms por consulta). Compartilhar é
seguro só porque o transporte guarda sockets e nada mais: estas provas usam o
cliente de verdade, com um transporte falso que registra o que saiu.
"""

import threading

import httpx
import pytest

from src import db
from src.streamlit_opcional import configurar_supabase, sessao_da_requisicao


class _Registro(httpx.BaseTransport):
    def __init__(self):
        self.pedidos: list[httpx.Request] = []
        self.fechado = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self.pedidos.append(request)
        return httpx.Response(200, json=[{"token": request.headers.get("authorization")}])

    def close(self) -> None:
        self.fechado = True


@pytest.fixture
def transporte(monkeypatch):
    configurar_supabase("https://projeto.supabase.invalid", "chave-publicavel-de-teste")
    registro = _Registro()
    monkeypatch.setattr(db, "_transporte_do_supabase", lambda: registro)
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)
    return registro


def _consultar(token: str) -> None:
    with sessao_da_requisicao(token, "tenant"):
        db.cliente_do_usuario().table("processos").select("id").execute()


def test_cada_pedido_leva_o_token_de_quem_chamou(transporte):
    _consultar("token-de-a")
    _consultar("token-de-b")
    _consultar("token-de-a")
    assert [p.headers["authorization"] for p in transporte.pedidos] == [
        "Bearer token-de-a", "Bearer token-de-b", "Bearer token-de-a"]


def test_usuarios_ao_mesmo_tempo_nao_trocam_de_token(transporte):
    barreira = threading.Barrier(8)

    def um_usuario(token: str) -> None:
        barreira.wait()
        for _ in range(10):
            _consultar(token)

    fios = [threading.Thread(target=um_usuario, args=(f"token-{i}",)) for i in range(8)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    vistos = [p.headers["authorization"] for p in transporte.pedidos]
    assert len(vistos) == 80
    assert all(vistos.count(f"Bearer token-{i}") == 10 for i in range(8))


def test_sem_sessao_nao_nasce_cliente(transporte):
    assert db.cliente_do_usuario() is None
    assert transporte.pedidos == []


def test_o_cliente_de_um_usuario_nao_guarda_o_token_no_que_e_compartilhado(transporte):
    with sessao_da_requisicao("token-de-a", "tenant"):
        cliente = db.cliente_do_usuario()
    assert "authorization" not in {nome.lower() for nome in cliente.postgrest.session.headers}
    assert vars(transporte).keys() == {"pedidos", "fechado"}, "transporte não guarda estado de usuário"


def test_transporte_de_verdade_e_um_so_e_mantem_a_conexao_entre_cliques():
    db._transporte_do_supabase.clear()
    primeiro = db._transporte_do_supabase()
    assert db._transporte_do_supabase() is primeiro
    piscina = primeiro._pool
    assert piscina._keepalive_expiry == 120, "o padrão do httpx fecha em 5 s"
    assert piscina._http2 is True
    db._transporte_do_supabase.clear()
