"""
Provas das correções C01–C13 (plano de 13/10/2026).

Cada prova nomeia o requisito que protege. Nenhuma toca rede, banco ou
provedor real: os executores recebem clientes falsos que registram o que
TERIAM enviado — modelo, host, parâmetros — e é isso que se confere.
"""

from __future__ import annotations

import base64
import json
import time
import types
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import ambiente, auth, db, llm, politica_ia, rag, state

RAIZ = Path(__file__).resolve().parents[1]
APP = str(RAIZ / "app.py")


class _Sessao(dict):
    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError:
            raise AttributeError(nome) from None

    def __setattr__(self, nome, valor):
        self[nome] = valor


def _jwt(exp: float) -> str:
    def b64(dados: dict) -> str:
        bruto = json.dumps(dados).encode()
        return base64.urlsafe_b64encode(bruto).decode().rstrip("=")

    return f"{b64({'alg': 'HS256'})}.{b64({'exp': int(exp)})}.assinatura"


@pytest.fixture()
def sessao(monkeypatch):
    s = _Sessao()
    monkeypatch.setattr(auth.st, "session_state", s, raising=False)
    monkeypatch.setattr(db.st, "session_state", s, raising=False)
    monkeypatch.setattr(state.st, "session_state", s, raising=False)
    monkeypatch.setattr(db, "registrar_incidente", lambda *_a, **_k: "REF")
    return s


# ---------------------------------------------------------------------------
# C01 / C04 — login em formulário, senha fora do estado
# ---------------------------------------------------------------------------
def _tela_de_login(monkeypatch):
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    return at


def test_c01_campo_vazio_e_recusado_antes_da_rede(monkeypatch):
    monkeypatch.setattr(auth, "autenticar", lambda *_a: pytest.fail(
        "validação local deveria ter recusado antes da rede"))
    at = _tela_de_login(monkeypatch)
    at.button[0].click().run()
    assert any("Informe" in e.value for e in at.error)


def test_c01_senha_nao_fica_no_estado_e_usuario_e_preservado(monkeypatch):
    def recusa(_usuario, _senha):
        raise auth.ErroAuth("Login ou senha incorretos.")

    monkeypatch.setattr(auth, "autenticar", recusa)
    at = _tela_de_login(monkeypatch)
    at.text_input[0].input("servidora")
    at.text_input[1].input("SENHA-QUE-NAO-PODE-FICAR")
    at.button[0].click().run()

    assert any("incorretos" in e.value for e in at.error)
    estado = dict(at.session_state.items())
    assert "SENHA-QUE-NAO-PODE-FICAR" not in json.dumps(
        estado, default=str, ensure_ascii=False)
    # o usuário volta como valor inicial do campo; a senha, não
    assert at.session_state["_login_ultimo_usuario"] == "servidora"


def test_c01_login_valido_entra(monkeypatch):
    monkeypatch.setattr(auth, "autenticar", lambda u, s: {
        "id": "u1", "nome": "Servidora", "login": u, "papel": "usuario"})
    at = _tela_de_login(monkeypatch)
    at.text_input[0].input("servidora")
    at.text_input[1].input("certa")
    at.button[0].click().run()
    assert not at.exception
    assert at.session_state["usuario"]["login"] == "servidora"


def test_c01_um_unico_indicador_de_foco_nos_campos():
    """
    Seletores do Streamlit 1.64 (data-testid), conferidos no navegador:
    o <input> fica sem contorno e o invólucro tem um traço só — sem o anel
    claro de 3px que, ao lado da borda, lia-se como linha dupla.
    """
    css = (RAIZ / "assets" / "govconnect.css").read_text(encoding="utf-8")
    alvo = '[data-testid="stTextInputRootElement"] input:focus-visible'
    assert alvo in css
    assert "outline: none" in css[css.index(alvo):][:400]
    assert "0 0 0 3px rgba(37, 99, 235, 0.13)" not in css


def test_c04_admin_existente_fica_em_cache_curto_na_sessao(sessao, monkeypatch):
    chamadas = []
    monkeypatch.setattr(auth, "tem_admin",
                        lambda: chamadas.append(1) or True)
    assert auth.tem_admin_em_cache(agora=1000)
    assert auth.tem_admin_em_cache(agora=1100)
    assert len(chamadas) == 1
    assert auth.tem_admin_em_cache(agora=1000 + auth.TTL_ADMIN_EXISTE_S + 1)
    assert len(chamadas) == 2


def test_c04_ausencia_de_admin_nunca_e_guardada(sessao, monkeypatch):
    chamadas = []
    monkeypatch.setattr(auth, "tem_admin",
                        lambda: chamadas.append(1) or False)
    assert not auth.tem_admin_em_cache(agora=1000)
    assert not auth.tem_admin_em_cache(agora=1001)
    assert len(chamadas) == 2


# ---------------------------------------------------------------------------
# C08 — renovação, expiração e logout completo
# ---------------------------------------------------------------------------
def test_c08_login_guarda_refresh_fora_do_usuario(sessao):
    auth.entrar({"id": "u1", "_token": _jwt(time.time() + 3600),
                 "_refresh": "refresh-1", "_expira": time.time() + 3600})
    assert sessao[auth.CHAVE_REFRESH] == "refresh-1"
    assert "_refresh" not in sessao["usuario"]
    assert "refresh-1" not in str(sessao["usuario"])


def test_c08_token_valido_nao_renova(sessao, monkeypatch):
    monkeypatch.setattr(auth, "_cliente_de_login",
                        lambda: pytest.fail("não devia renovar"))
    sessao[db.CHAVE_DA_SESSAO] = _jwt(5000)
    assert auth.garantir_sessao_valida(agora=1000)


def test_c08_token_sem_prazo_legivel_nao_derruba_a_sessao(sessao, monkeypatch):
    monkeypatch.setattr(auth, "_cliente_de_login",
                        lambda: pytest.fail("não devia renovar"))
    sessao[db.CHAVE_DA_SESSAO] = "token-opaco"
    sessao.usuario = {"id": "u1"}
    assert auth.garantir_sessao_valida(agora=1000)
    assert sessao.usuario == {"id": "u1"}


def test_c08_token_perto_do_fim_e_renovado_no_servidor(sessao, monkeypatch):
    novo = _jwt(9000)
    pedidos = []

    class _Auth:
        def refresh_session(self, refresh):
            pedidos.append(refresh)
            return types.SimpleNamespace(session=types.SimpleNamespace(
                access_token=novo, refresh_token="refresh-2", expires_at=9000))

    monkeypatch.setattr(auth, "_cliente_de_login",
                        lambda: types.SimpleNamespace(auth=_Auth()))
    sessao[db.CHAVE_DA_SESSAO] = _jwt(1050)
    sessao[auth.CHAVE_REFRESH] = "refresh-1"
    sessao.usuario = {"id": "u1"}

    assert auth.garantir_sessao_valida(agora=1000)
    assert pedidos == ["refresh-1"]
    assert sessao[db.CHAVE_DA_SESSAO] == novo
    assert sessao[auth.CHAVE_REFRESH] == "refresh-2"
    assert sessao[auth.CHAVE_EXPIRA] == 9000


def test_c08_renovacao_recusada_encerra_a_sessao_e_avisa(sessao, monkeypatch):
    class _Auth:
        def refresh_session(self, _refresh):
            raise RuntimeError("refresh token revogado")

    monkeypatch.setattr(auth, "_cliente_de_login",
                        lambda: types.SimpleNamespace(auth=_Auth()))
    sessao.update(usuario={"id": "u1"}, dados={"objeto": "x"}, documentos={},
                  aprovados=set(), processo_id="p1", etapa=2)
    sessao[db.CHAVE_DA_SESSAO] = _jwt(900)
    sessao[auth.CHAVE_REFRESH] = "refresh-velho"

    assert not auth.garantir_sessao_valida(agora=1000)
    assert sessao["usuario"] is None
    assert not sessao[db.CHAVE_DA_SESSAO]
    assert auth.CHAVE_REFRESH not in sessao
    assert sessao[auth.CHAVE_AVISO_SESSAO] == auth.AVISO_SESSAO_EXPIRADA
    # nenhuma queda para a credencial de servidor: sem JWT, sem usuário
    assert db.sessao_do_usuario() is None


def test_c08_logout_nao_deixa_nada_de_a_para_b(sessao, monkeypatch):
    marca = "DADO-DO-USUARIO-A"
    sessao.update({
        "usuario": {"id": "a"}, "tenant_id": "t-a",
        "dados": {"objeto": marca}, "documentos": {"dfd": marca},
        "aprovados": {"dfd"}, "processo_id": "p-a", "etapa": 3,
        "edicoes_pendentes": {"dfd": marca}, "editor_dfd": marca,
        "rich_editor_dfd": {"edit": marca}, "govbot_campo_objeto": marca,
        "_rag_trace": {"dfd": marca}, "_decisao_cache": {"x": marca},
        "registro_geracoes": [{"erro": marca}], "openai_key_manual": marca,
        "upload_itens": object(), "_xlsx_lido": "arq-a", "pagina": "Processos",
        "_rich_editors": {"dfd": {"version": marca}},
        "preferencia_visual": "da-aba",
        db.CHAVE_DA_SESSAO: _jwt(9999), auth.CHAVE_REFRESH: "r-a",
    })
    auth.sair()

    restante = json.dumps({k: v for k, v in sessao.items()
                           if k != "upload_itens"},
                          default=str, ensure_ascii=False)
    assert marca not in restante
    assert "upload_itens" not in sessao
    assert sessao["preferencia_visual"] == "da-aba"
    assert sessao["usuario"] is None and not sessao[db.CHAVE_DA_SESSAO]


# ---------------------------------------------------------------------------
# C09 — embeddings pelo OpenRouter, com a mesma chave
# ---------------------------------------------------------------------------
def _chaves(monkeypatch, *, exclusivo, rota_ligada, openrouter="sk-or",
            embeddings="sk-legada"):
    monkeypatch.setattr(llm, "provedor_declarado",
                        lambda: "openrouter" if exclusivo else "")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: openrouter)
    monkeypatch.setattr(llm, "obter_chave_de_embeddings", lambda: embeddings)
    if rota_ligada:
        monkeypatch.setenv(llm.VAR_EMBEDDINGS_OPENROUTER, "1")
    else:
        monkeypatch.delenv(llm.VAR_EMBEDDINGS_OPENROUTER, raising=False)


def test_c09_rota_comprovada_usa_a_chave_do_openrouter(monkeypatch):
    _chaves(monkeypatch, exclusivo=True, rota_ligada=True)
    assert llm.rota_de_embeddings() == ("openrouter", "sk-or")


def test_c09_modo_exclusivo_nunca_usa_chave_legada_direta(monkeypatch):
    _chaves(monkeypatch, exclusivo=True, rota_ligada=False)
    assert llm.rota_de_embeddings() is None


def test_c09_fora_do_modo_exclusivo_o_comportamento_e_o_de_antes(monkeypatch):
    _chaves(monkeypatch, exclusivo=False, rota_ligada=False)
    assert llm.rota_de_embeddings() == ("openai", "sk-legada")


def test_c09_vetor_pedido_ao_openrouter_com_mesmo_modelo_e_dimensao(monkeypatch):
    from src import config

    _chaves(monkeypatch, exclusivo=True, rota_ligada=True)
    criados = []

    class _Cliente:
        def __init__(self, **kwargs):
            criados.append(kwargs)
            self.embeddings = self

        def create(self, **kwargs):
            criados.append(kwargs)
            return types.SimpleNamespace(data=[types.SimpleNamespace(
                embedding=[0.0] * config.EMBEDDING_V2_DIMENSOES)])

    import openai

    monkeypatch.setattr(openai, "OpenAI", _Cliente)
    vetores = rag._gerar_embeddings(["consulta"], para_consulta=True)

    assert vetores and len(vetores[0]) == config.EMBEDDING_V2_DIMENSOES
    assert criados[0]["base_url"] == config.OPENROUTER_BASE_URL
    assert criados[0]["api_key"] == "sk-or"
    assert criados[1]["model"] == "openai/text-embedding-3-small"
    assert criados[1]["dimensions"] == config.EMBEDDING_V2_DIMENSOES


def test_c09_degradado_no_modo_exclusivo_e_dito_na_tela(monkeypatch):
    _chaves(monkeypatch, exclusivo=True, rota_ligada=False)
    avisos = []
    monkeypatch.setattr(rag.st, "warning", lambda m, *_a, **_k: avisos.append(m))
    assert rag._gerar_embeddings(["x"], para_consulta=True) is None
    assert avisos and "TEXTUAL" in avisos[0] and "degradado" in avisos[0]


# ---------------------------------------------------------------------------
# C10 / C11 — política aplicada no executor real; truncamento recusado
# ---------------------------------------------------------------------------
class _Escolha:
    def __init__(self, texto, motivo="stop"):
        self.message = types.SimpleNamespace(content=texto)
        self.finish_reason = motivo


class _ClienteChat:
    """Cliente OpenAI falso: devolve, por modelo, (texto, finish_reason)."""

    def __init__(self, respostas, enviados, **kwargs):
        self.kwargs = kwargs
        self._respostas = respostas
        self._enviados = enviados
        self.chat = types.SimpleNamespace(completions=self)

    def create(self, *, model, **_kwargs):
        self._enviados.append(model)
        texto, motivo = self._respostas.get(model, ("ok", "stop"))
        return types.SimpleNamespace(
            choices=[_Escolha(texto, motivo)],
            usage=types.SimpleNamespace(prompt_tokens=1, completion_tokens=1),
            id="req")


def _openrouter_falso(monkeypatch, respostas, *, principal="openai/gpt-5-mini",
                      fallback=("google/gemini-2.5-flash",)):
    import openai

    enviados: list[str] = []
    monkeypatch.setattr(openai, "OpenAI", lambda **kw: _ClienteChat(
        respostas, enviados, **kw))
    monkeypatch.setattr(llm, "_modelos_openrouter",
                        lambda: [principal, *fallback])
    return enviados


def test_c10_executor_openrouter_aplica_o_modelo_economico(monkeypatch):
    monkeypatch.setattr(politica_ia, "ativo", lambda: True)
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda motor: "openai/gpt-4o-mini"
                        if motor == "openrouter" else "")
    enviados = _openrouter_falso(monkeypatch, {})

    llm._chamar_openrouter("s", "u", "k", tarefa="auditor")
    llm._chamar_openrouter("s", "u", "k", tarefa="dfd")

    assert enviados == ["openai/gpt-4o-mini", "openai/gpt-5-mini"]


def test_c11_resposta_truncada_nao_e_aceita(monkeypatch):
    monkeypatch.setattr(politica_ia, "ativo", lambda: False)
    enviados = _openrouter_falso(monkeypatch, {
        "openai/gpt-5-mini": ("DFD cortado no meio da cláusula", "length"),
        "google/gemini-2.5-flash": ("DFD também cortado", "length"),
    })
    with pytest.raises(llm.ErroGeracaoIA, match="cortada"):
        llm._chamar_openrouter("s", "u", "k", tarefa="dfd")
    assert enviados == ["openai/gpt-5-mini", "google/gemini-2.5-flash"]


def test_c11_truncada_cai_para_o_proximo_modelo_completo(monkeypatch):
    monkeypatch.setattr(politica_ia, "ativo", lambda: False)
    _openrouter_falso(monkeypatch, {
        "openai/gpt-5-mini": ("parcial", "length"),
        "google/gemini-2.5-flash": ("DFD completo", "stop"),
    })
    assert llm._chamar_openrouter("s", "u", "k", tarefa="dfd") == "DFD completo"


def test_c11_gemini_max_tokens_e_reconhecido():
    import enum

    class _Motivo(enum.Enum):
        MAX_TOKENS = 2

    corte = types.SimpleNamespace(candidates=[
        types.SimpleNamespace(finish_reason=_Motivo.MAX_TOKENS)])
    normal = types.SimpleNamespace(candidates=[
        types.SimpleNamespace(finish_reason="STOP")])
    assert llm._parou_no_teto_gemini(corte)
    assert not llm._parou_no_teto_gemini(normal)


def test_c10_cache_muda_quando_a_politica_muda(monkeypatch):
    monkeypatch.setattr(llm, "motor_ativo", lambda: "openrouter")
    monkeypatch.setattr(llm, "_modelos_openrouter",
                        lambda: ["openai/gpt-5-mini"])
    monkeypatch.setattr(politica_ia, "ativo", lambda: False)
    antes = llm._chave_de_cache("s", "u", "auditor")
    monkeypatch.setattr(politica_ia, "ativo", lambda: True)
    monkeypatch.setattr(politica_ia, "modelo_economico_configurado",
                        lambda motor: "openai/gpt-4o-mini")
    depois = llm._chave_de_cache("s", "u", "auditor")
    assert antes != depois


def test_c10_tarefa_critica_sem_motor_homologado_falha_com_mensagem(monkeypatch):
    from src import ai_gateway

    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    monkeypatch.setattr(llm, "motores_disponiveis",
                        lambda: [("openrouter", "k")])
    monkeypatch.setattr(llm, "_chamar_motor", lambda *_a, **_k: pytest.fail(
        "não podia chamar motor não homologado"))
    with pytest.raises(llm.ErroGeracaoIA, match="homologado"):
        llm._percorrer_motores("edital", "s", "u")


# ---------------------------------------------------------------------------
# C13 — versão gravada na imagem
# ---------------------------------------------------------------------------
def test_c13_versao_vem_do_ambiente_da_imagem(monkeypatch):
    monkeypatch.setenv("GOVDOCS_RELEASE", "v9.9.9")
    monkeypatch.setenv("GOVDOCS_COMMIT", "a" * 40)
    assert ambiente.versao() == {"release": "v9.9.9", "commit": "a" * 40}
    monkeypatch.delenv("GOVDOCS_COMMIT")
    assert ambiente.versao()["commit"] == "desconhecido"


def test_c13_imagem_e_promocao_carregam_o_commit():
    dockerfile = (RAIZ / "implantacao" / "Dockerfile").read_text(encoding="utf-8")
    compose = (RAIZ / "implantacao" / "docker-compose.yml").read_text(
        encoding="utf-8")
    promover = (RAIZ / "implantacao" / "promover.sh").read_text(encoding="utf-8")
    assert "ARG GOVDOCS_COMMIT" in dockerfile
    assert "org.opencontainers.image.revision" in dockerfile
    assert "GOVDOCS_COMMIT: ${GOVDOCS_COMMIT" in compose
    assert 'GOVDOCS_COMMIT="$(git rev-parse HEAD)"' in promover
    assert "printenv GOVDOCS_COMMIT" in promover


def test_c02_html_inicial_deixa_de_dizer_streamlit():
    dockerfile = (RAIZ / "implantacao" / "Dockerfile").read_text(encoding="utf-8")
    assert "<title>GovConnect" in dockerfile
    assert "favicon.png" in dockerfile


def test_c02_index_do_streamlit_instalado_tem_o_titulo_que_o_build_troca():
    """O `grep -q` do build falha se a versão fixada mudar este HTML."""
    import os

    import streamlit

    index = Path(os.path.dirname(streamlit.__file__)) / "static" / "index.html"
    assert "<title>Streamlit</title>" in index.read_text(encoding="utf-8")
