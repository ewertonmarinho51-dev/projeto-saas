"""
Usuários e papéis (M7c, ADR-010): a única parte da API com credencial de
servidor. O que se prova:

* a guarda: só admin; sem a chave, 503 em convidar/trocar escopo e o resto
  funciona;
* a fronteira de tenant da Admin API (que atravessa o RLS): o escopo vem do
  JWT do chamador, a conta alvo é LIDA e conferida antes de toda escrita,
  e conta de outro município é 404 sem escrita;
* ninguém altera o próprio papel nem se desativa;
* desativar não usa a chave;
* o cliente restrito só fala com `/auth/v1/admin/users`, recusa chave que
  não seja `sb_secret_` e não sobe o corpo do provedor;
* a configuração recusa o JWT legado `service_role` e não expõe a chave.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from govconect_api.admin_auth import AdminDoAuth, ContaJaExiste, ErroAdminAuth
from govconect_api.config import ConfiguracaoInvalida, carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

BASE = "/api/v1/admin/usuarios"
ALVO = "cccccccc-0000-4000-8000-000000000001"
UID_ALVO = "cccccccc-0000-4000-8000-0000000000a1"
SEC = "dddddddd-0000-4000-8000-000000000001"
OUTRO_TENANT = "99999999-0000-4000-8000-000000000009"


CHAMADOR = {"app_metadata": {"papel": "admin", "tenant_id": TENANT_A}}


class AdminFalso:
    def __init__(self, contas=None, existe=False, quebrar=False):
        # A conta de quem chama, conferida AO VIVO antes de toda escrita.
        self.contas = {USUARIO_A: CHAMADOR, **(contas or {})}
        self.existe, self.quebrar = existe, quebrar
        self.chamadas: list = []

    def conta(self, uid):
        self.chamadas.append(("conta", uid))
        if self.quebrar:
            raise ErroAdminAuth("fora")
        return self.contas.get(uid)

    def criar(self, email, nome, escopo):
        self.chamadas.append(("criar", email, nome, escopo))
        if self.existe:
            raise ContaJaExiste()
        return "eeeeeeee-0000-4000-8000-0000000000b1"

    def atualizar_escopo(self, uid, escopo):
        self.chamadas.append(("atualizar", uid, escopo))

    def bloquear(self, uid, bloquear):
        self.chamadas.append(("bloquear", uid, bloquear))

    def desfazer_criacao(self, uid):
        self.chamadas.append(("desfazer", uid))

    def escritas(self):
        return [c for c in self.chamadas if c[0] in ("criar", "atualizar", "bloquear", "desfazer")]


@pytest.fixture
def emissor():
    return Emissor()


def _linha(**extra):
    base = {"id": ALVO, "nome": "Ana", "login": "ana@exemplo.gov.br", "papel": "usuario", "ativo": True,
            "secretaria_id": None, "auth_user_id": UID_ALVO}
    return {**base, **extra}


def _banco():
    """PostgREST falso com a 1ª leitura de `usuarios` reservada ao verificador
    (o vínculo do admin que chama), antes das respostas da rota."""
    b = PostgrestFalso()
    b.responder("GET", "usuarios", 200, b.usuarios)
    return b


def _api(emissor, banco, admin=None):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, admin_auth=admin, verificador=VerificadorSupabase(
        emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)), raise_server_exceptions=False)


def _h(emissor, papel="admin"):
    return {"Authorization": f"Bearer {emissor.token(papel=papel)}"}


# ---------------------------------------------------------------------------
# Guarda
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("metodo,caminho,corpo", [
    ("GET", "", None), ("POST", "", {"nome": "Bia", "email": "bia@x.gov.br"}),
    ("PATCH", f"/{ALVO}", {"ativo": False}),
])
def test_so_admin(emissor, metodo, caminho, corpo):
    admin = AdminFalso()
    r = _api(emissor, _banco(), admin).request(metodo, BASE + caminho, json=corpo, headers=_h(emissor, "usuario"))
    assert r.status_code == 403
    assert admin.chamadas == []


def test_lista_diz_se_a_gestao_de_acesso_esta_ligada_e_quem_e_voce(emissor):
    banco = _banco()
    banco.responder("GET", "usuarios", 200, [_linha(), _linha(id="x", auth_user_id=USUARIO_A, papel="admin")])
    banco.responder("GET", "secretarias", 200, [{"id": SEC, "nome": "Educação"}])
    corpo = _api(emissor, banco).get(BASE, headers=_h(emissor)).json()
    assert corpo["gestao_de_acesso"] is False
    assert [u["eu"] for u in corpo["usuarios"]] == [False, True]
    pedido = [c for c in banco.chamadas if c.url.path.endswith("/usuarios")][-1]
    assert pedido.url.params["tenant_id"] == f"eq.{TENANT_A}"


def test_sem_a_chave_convidar_e_503(emissor):
    r = _api(emissor, _banco()).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 503 and r.json()["code"] == "ADMIN_AUTH_UNAVAILABLE"


# ---------------------------------------------------------------------------
# Convidar
# ---------------------------------------------------------------------------
def test_convite_cria_a_conta_com_o_escopo_do_chamador_e_vincula(emissor):
    banco = _banco()
    banco.responder("GET", "secretarias", 200, [{"id": SEC}])
    banco.responder("POST", "usuarios", 201, [_linha(id="novo", login="bia@x.gov.br", nome="Bia",
                                                      auth_user_id="eeeeeeee-0000-4000-8000-0000000000b1")])
    admin = AdminFalso()
    r = _api(emissor, banco, admin).post(BASE, headers=_h(emissor), json={
        "nome": " Bia Souza ", "email": " Bia@X.gov.br ", "papel": "usuario", "secretaria_id": SEC})
    assert r.status_code == 201, r.text
    assert admin.escritas() == [("criar", "bia@x.gov.br", "Bia Souza",
                                 {"papel": "usuario", "tenant_id": TENANT_A, "secretaria_id": SEC})]
    linha = banco.corpo(next(c for c in banco.chamadas if c.method == "POST"))
    assert linha["tenant_id"] == TENANT_A and linha["login"] == "bia@x.gov.br"
    assert linha["auth_user_id"] == "eeeeeeee-0000-4000-8000-0000000000b1"
    assert not linha["senha_hash"].startswith("pbkdf2")


@pytest.mark.parametrize("corpo", [
    {"nome": "Bia", "email": "bia@x.gov.br", "tenant_id": OUTRO_TENANT},
    {"nome": "Bia", "email": "bia@x.gov.br", "papel": "superadmin"},
    {"nome": "Bia", "email": "bia@x.gov.br", "papel_governanca": "proprietario"},
    {"nome": "Bia", "email": "nao-e-email"},
])
def test_convite_recusa_escopo_no_corpo_e_dado_invalido(emissor, corpo):
    admin = AdminFalso()
    r = _api(emissor, _banco(), admin).post(BASE, headers=_h(emissor), json=corpo)
    assert r.status_code == 422
    assert admin.escritas() == []


def test_secretaria_de_outro_municipio_nao_entra_no_escopo(emissor):
    banco = _banco()
    banco.responder("GET", "secretarias", 200, [])
    admin = AdminFalso()
    r = _api(emissor, banco, admin).post(BASE, headers=_h(emissor),
                                         json={"nome": "Bia", "email": "bia@x.gov.br", "secretaria_id": SEC})
    assert r.status_code == 422 and admin.escritas() == []


def test_email_ja_cadastrado_e_409_sem_dizer_mais(emissor):
    admin = AdminFalso(existe=True)
    banco = _banco()
    r = _api(emissor, banco, admin).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 409 and r.json()["message"] == "Já existe uma conta com este e-mail."
    assert not any(c.method == "POST" for c in banco.chamadas), "nada vinculado"


def test_vinculo_que_falha_desfaz_a_conta_criada(emissor):
    banco = _banco()
    banco.responder("POST", "usuarios", 409, {"code": "23505"})
    admin = AdminFalso()
    r = _api(emissor, banco, admin).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 409
    assert admin.chamadas[-1] == ("desfazer", "eeeeeeee-0000-4000-8000-0000000000b1")


# ---------------------------------------------------------------------------
# Alterar
# ---------------------------------------------------------------------------
def _banco_com_alvo(**extra):
    b = _banco()
    b.responder("GET", "usuarios", 200, [_linha(**extra)])
    b.responder("GET", "secretarias", 200, [{"id": SEC}])
    b.responder("PATCH", "usuarios", 200, [_linha(**extra)])
    return b


def test_usuario_de_outro_municipio_e_404_sem_tocar_o_auth(emissor):
    banco = _banco()
    banco.responder("GET", "usuarios", 200, [])
    admin = AdminFalso()
    r = _api(emissor, banco, admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "admin"})
    assert r.status_code == 404 and admin.chamadas == []


def test_conta_do_auth_de_outro_tenant_e_404_sem_escrita(emissor):
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {"tenant_id": OUTRO_TENANT, "papel": "usuario"}}})
    r = _api(emissor, _banco_com_alvo(), admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "admin"})
    assert r.status_code == 404
    assert admin.escritas() == []


def test_trocar_papel_preserva_o_resto_do_app_metadata(emissor):
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {
        "tenant_id": TENANT_A, "papel": "usuario", "secretaria_id": SEC, "papel_governanca": "auditor"}}})
    banco = _banco_com_alvo()
    r = _api(emissor, banco, admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "admin"})
    assert r.status_code == 200, r.text
    assert admin.escritas() == [("atualizar", UID_ALVO, {
        "tenant_id": TENANT_A, "papel": "admin", "secretaria_id": SEC, "papel_governanca": "auditor"})]
    assert banco.corpo([c for c in banco.chamadas if c.method == "PATCH"][-1]) == {"papel": "admin"}


def test_tirar_a_secretaria_remove_a_chave_do_escopo(emissor):
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {"tenant_id": TENANT_A, "papel": "usuario",
                                                            "secretaria_id": SEC}}})
    r = _api(emissor, _banco_com_alvo(), admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor),
                                                      json={"secretaria_id": None})
    assert r.status_code == 200
    # O GoTrue MESCLA app_metadata: só `null` apaga a chave.
    assert admin.escritas()[-1][2] == {"tenant_id": TENANT_A, "papel": "usuario", "secretaria_id": None}


@pytest.mark.parametrize("corpo", [{"papel": "usuario"}, {"ativo": False}])
def test_ninguem_altera_a_si_mesmo(emissor, corpo):
    admin = AdminFalso()
    r = _api(emissor, _banco_com_alvo(auth_user_id=USUARIO_A), admin).patch(
        f"{BASE}/{ALVO}", headers=_h(emissor), json=corpo)
    assert r.status_code == 409 and admin.chamadas == []


def test_desativar_sem_a_chave_ainda_corta_a_interface(emissor):
    banco = _banco_com_alvo()
    r = _api(emissor, banco, None).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"ativo": False})
    assert r.status_code == 200, r.text
    patch = [c for c in banco.chamadas if c.method == "PATCH"][-1]
    assert banco.corpo(patch) == {"ativo": False} and patch.url.params["tenant_id"] == f"eq.{TENANT_A}"


@pytest.mark.parametrize("ativo", [False, True])
def test_desativar_com_a_chave_bloqueia_a_conta_no_auth(emissor, ativo):
    """Sem o bloqueio, o desativado renovaria o token e falaria com o PostgREST
    direto: nenhuma política do banco olha `usuarios.ativo`."""
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {"tenant_id": TENANT_A, "papel": "usuario"}}})
    r = _api(emissor, _banco_com_alvo(), admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"ativo": ativo})
    assert r.status_code == 200, r.text
    assert admin.escritas() == [("bloquear", UID_ALVO, not ativo)]


def test_conta_do_login_antigo_so_muda_a_linha(emissor):
    admin = AdminFalso()
    r = _api(emissor, _banco_com_alvo(auth_user_id=None), admin).patch(
        f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "admin"})
    assert r.status_code == 200 and admin.chamadas == []


def test_admin_api_fora_e_503_sem_gravar_a_linha(emissor):
    banco = _banco_com_alvo()
    r = _api(emissor, banco, AdminFalso(quebrar=True)).patch(f"{BASE}/{ALVO}", headers=_h(emissor),
                                                            json={"papel": "admin"})
    assert r.status_code == 503
    assert not any(c.method == "PATCH" for c in banco.chamadas)


# ---------------------------------------------------------------------------
# O cliente restrito e a configuração
# ---------------------------------------------------------------------------
CHAVE = "sb_secret_" + "z" * 24


def _cliente(responder):
    chamadas = []

    def manipulador(request: httpx.Request):
        chamadas.append(request)
        return responder(request)
    return AdminDoAuth("https://exemplo-staging.supabase.co", CHAVE,
                       transporte=httpx.MockTransport(manipulador)), chamadas


def test_cliente_so_fala_com_a_admin_api_de_usuarios():
    cliente, chamadas = _cliente(lambda r: httpx.Response(200, json={"id": "u1"}))
    cliente.criar("a@b.gov.br", "A", {"papel": "usuario", "tenant_id": TENANT_A})
    cliente.atualizar_escopo("u1", {"papel": "admin"})
    cliente.conta("u1")
    cliente.desfazer_criacao("u1")
    assert all(c.url.path.startswith("/auth/v1/admin/users") for c in chamadas)
    assert all(c.headers["apikey"] == CHAVE for c in chamadas)
    assert '"email_confirm":true' in chamadas[0].content.decode().replace(" ", "")


def test_cliente_nao_sobe_o_corpo_do_provedor():
    cliente, _ = _cliente(lambda r: httpx.Response(422, json={"msg": "a@b.gov.br já existe", "code": "email_exists"}))
    with pytest.raises(ContaJaExiste) as erro:
        cliente.criar("a@b.gov.br", "A", {})
    assert "a@b.gov.br" not in str(erro.value)
    cliente, _ = _cliente(lambda r: httpx.Response(500, json={"msg": "segredo interno"}))
    with pytest.raises(ErroAdminAuth) as erro:
        cliente.conta("u1")
    assert "segredo" not in str(erro.value)


def test_cliente_recusa_chave_que_nao_e_secreta_nova():
    with pytest.raises(ValueError):
        AdminDoAuth("https://x.supabase.co", "sb_publishable_xyz")


def _jwt_legado(papel):
    import base64
    import json

    carga = base64.urlsafe_b64encode(json.dumps({"role": papel}).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJIUzI1NiJ9.{carga}.assinatura"


@pytest.mark.parametrize("chave", [_jwt_legado("service_role"), "chave-qualquer"])
def test_configuracao_recusa_chave_errada(chave):
    with pytest.raises(ConfiguracaoInvalida, match="GOVCONECT_AUTH_ADMIN_KEY"):
        carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                  "SUPABASE_KEY": "chave-publicavel-de-teste", "GOVCONECT_AUTH_ADMIN_KEY": chave})


def test_configuracao_nao_expoe_a_chave():
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "GOVCONECT_AUTH_ADMIN_KEY": CHAVE})
    assert config.auth_admin_chave == CHAVE and CHAVE not in repr(config)


def test_chave_de_servidor_continua_fora_do_dominio():
    from src.streamlit_opcional import configurar_supabase

    with pytest.raises(ValueError):
        configurar_supabase("https://x.exemplo.co", CHAVE)


# ---------------------------------------------------------------------------
# Achados da revisão de segurança (26/10/2026)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("meta", [
    {"papel": "usuario", "tenant_id": TENANT_A},          # rebaixado há pouco: JWT ainda diz admin
    {"papel": "admin", "tenant_id": OUTRO_TENANT},
])
def test_admin_conferido_ao_vivo_antes_de_escrever(emissor, meta):
    admin = AdminFalso(contas={USUARIO_A: {"app_metadata": meta},
                               UID_ALVO: {"app_metadata": {"tenant_id": TENANT_A, "papel": "admin"}}})
    banco = _banco_com_alvo(papel="admin")
    banco.responder("GET", "usuarios", 200, [{"id": "outro"}])
    r = _api(emissor, banco, admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "usuario"})
    assert r.status_code == 403
    r = _api(emissor, _banco(), admin).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 403
    assert admin.escritas() == []


def test_admin_bloqueado_no_auth_nao_escreve(emissor):
    admin = AdminFalso(contas={USUARIO_A: {**CHAMADOR, "banned_until": "2126-01-01T00:00:00Z"}})
    r = _api(emissor, _banco(), admin).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 403 and admin.escritas() == []


@pytest.mark.parametrize("corpo", [{"papel": "usuario"}, {"ativo": False}])
def test_ultimo_admin_ativo_nao_sai(emissor, corpo):
    banco = _banco()
    banco.responder("GET", "usuarios", 200, [_linha(papel="admin")])
    banco.responder("GET", "usuarios", 200, [])           # nenhum OUTRO admin ativo
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {"tenant_id": TENANT_A, "papel": "admin"}}})
    r = _api(emissor, banco, admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json=corpo)
    assert r.status_code == 409 and r.json()["code"] == "LAST_ADMIN"
    assert admin.escritas() == [] and not any(c.method == "PATCH" for c in banco.chamadas)


def test_rebaixar_com_outro_admin_ativo_passa(emissor):
    banco = _banco()
    banco.responder("GET", "usuarios", 200, [_linha(papel="admin")])
    banco.responder("GET", "usuarios", 200, [{"id": "outro"}])
    banco.responder("PATCH", "usuarios", 200, [_linha(papel="usuario")])
    admin = AdminFalso(contas={UID_ALVO: {"app_metadata": {"tenant_id": TENANT_A, "papel": "admin"}}})
    r = _api(emissor, banco, admin).patch(f"{BASE}/{ALVO}", headers=_h(emissor), json={"papel": "usuario"})
    assert r.status_code == 200, r.text
    pedido = [c for c in banco.chamadas if c.method == "GET" and "neq." in str(c.url.params.get("id", ""))][-1]
    assert pedido.url.params["papel"] == "eq.admin" and pedido.url.params["ativo"] == "is.true"


def test_postgrest_fora_no_vinculo_desfaz_a_conta_e_sobe_o_erro(emissor, monkeypatch):
    from govconect_api.erros import ErroApi
    from govconect_api.supabase_rest import ClienteRest

    original = ClienteRest.requisitar

    def requisitar(self, token, metodo, tabela, **kw):
        if metodo == "POST" and tabela == "usuarios":
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco de dados indisponível")
        return original(self, token, metodo, tabela, **kw)

    monkeypatch.setattr(ClienteRest, "requisitar", requisitar)
    admin = AdminFalso()
    r = _api(emissor, _banco(), admin).post(BASE, headers=_h(emissor), json={"nome": "Bia", "email": "bia@x.gov.br"})
    assert r.status_code == 503
    assert admin.escritas()[-1] == ("desfazer", "eeeeeeee-0000-4000-8000-0000000000b1")


def test_auth_recusa_email_por_outro_motivo_nao_vira_ja_existe():
    from govconect_api.admin_auth import EmailRecusado

    cliente, _ = _cliente(lambda r: httpx.Response(422, json={"code": "validation_failed", "msg": "invalid"}))
    with pytest.raises(EmailRecusado):
        cliente.criar("a@b.gov.br", "A", {})


def test_bloqueio_vai_como_ban_duration():
    import json as _json

    cliente, chamadas = _cliente(lambda r: httpx.Response(200, json={}))
    cliente.bloquear("u1", True)
    cliente.bloquear("u1", False)
    assert [_json.loads(c.content)["ban_duration"] for c in chamadas] == ["876000h", "none"]


def test_chave_nao_aparece_no_log_nem_no_erro(caplog):
    cliente, _ = _cliente(lambda r: httpx.Response(503, text=f"eco {CHAVE}"))
    with caplog.at_level("DEBUG"), pytest.raises(ErroAdminAuth) as erro:
        cliente.conta("u1")
    assert CHAVE not in caplog.text and CHAVE not in str(erro.value)


def test_worker_tira_a_chave_do_proprio_ambiente(monkeypatch):
    import os

    from govconect_api import fila

    monkeypatch.setenv("GOVCONECT_AUTH_ADMIN_KEY", CHAVE)
    fila.sem_credencial_de_servidor()
    assert "GOVCONECT_AUTH_ADMIN_KEY" not in os.environ
