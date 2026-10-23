import pytest

from govconect_api.config import ConfiguracaoInvalida, carregar

PROD = {"APP_ENV": "production", "SUPABASE_URL": "https://prod.exemplo.co",
        "SUPABASE_KEY": "chave-publicavel-de-teste"}


def test_padrao_e_desenvolvimento_sem_supabase():
    config = carregar({})
    assert config.ambiente == "development"
    assert config.supabase_url == ""


def test_ambiente_desconhecido_recusa():
    with pytest.raises(ConfiguracaoInvalida):
        carregar({"APP_ENV": "prod"})


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_modo_aberto_em_ambiente_protegido_nao_sobe(ambiente):
    with pytest.raises(ConfiguracaoInvalida, match="MODO_ABERTO"):
        carregar({**PROD, "APP_ENV": ambiente, "GOVDOCS_MODO_ABERTO": "1"})


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_ambiente_protegido_exige_supabase_https(ambiente):
    with pytest.raises(ConfiguracaoInvalida):
        carregar({"APP_ENV": ambiente})
    with pytest.raises(ConfiguracaoInvalida):
        carregar({"APP_ENV": ambiente, "SUPABASE_URL": "http://prod.exemplo.co"})


@pytest.mark.parametrize("ambiente", ["development", "staging", "production"])
def test_cors_curinga_recusado_em_todo_ambiente(ambiente):
    with pytest.raises(ConfiguracaoInvalida, match=r"não aceita '\*'"):
        carregar({**PROD, "APP_ENV": ambiente, "GOVCONECT_CORS_ORIGINS": "*"})


@pytest.mark.parametrize("origem", [
    "http://app.exemplo.co",            # http fora de localhost
    "http://localhost:3000",            # localhost em produção
    "https://app.exemplo.co/caminho",   # origem não tem caminho
    "app.exemplo.co",                   # sem esquema
])
def test_origem_invalida_em_producao(origem):
    with pytest.raises(ConfiguracaoInvalida):
        carregar({**PROD, "GOVCONECT_CORS_ORIGINS": origem})


def test_localhost_vale_so_em_desenvolvimento():
    config = carregar({"GOVCONECT_CORS_ORIGINS": "http://localhost:3000"})
    assert config.origens_cors == ("http://localhost:3000",)


def test_mensagem_de_erro_nao_carrega_segredo():
    # O nome da variável sim; o valor nunca. SUPABASE_URL não é segredo,
    # mas a regra é a mesma para todas — exceção vira hábito.
    with pytest.raises(ConfiguracaoInvalida) as erro:
        carregar({"APP_ENV": "production",
                  "SUPABASE_URL": "http://valor-que-nao-deve-aparecer.co"})
    assert "valor-que-nao-deve-aparecer" not in str(erro.value)


def test_segredo_hs256_recusado_em_producao():
    # Produção verifica pelo JWKS (ES256). O segredo compartilhado lá só
    # abriria uma segunda porta, mais fraca, ao lado da certa.
    with pytest.raises(ConfiguracaoInvalida, match="SUPABASE_JWT_SECRET"):
        carregar({**PROD, "SUPABASE_JWT_SECRET": "segredo-qualquer-de-teste"})
    assert carregar({**PROD, "APP_ENV": "staging",
                     "SUPABASE_JWT_SECRET": "segredo-qualquer-de-teste"}).jwt_segredo_hs256


def _jwt_legado(papel: str) -> str:
    # Montado na hora, e não escrito no arquivo: um literal com cara de
    # JWT faria a varredura de segredos do CI tropeçar nele.
    import base64
    import json

    parte = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")  # noqa: E731
    return f"{parte({'alg': 'HS256'})}.{parte({'role': papel})}.assinatura"


@pytest.mark.parametrize("chave", [
    "sb_secret_" + "x" * 20,
    _jwt_legado("service_role"),
])
def test_chave_de_servidor_no_lugar_da_publicavel_e_recusada(chave):
    with pytest.raises(ConfiguracaoInvalida, match="chave de servidor"):
        carregar({**PROD, "SUPABASE_KEY": chave})


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_ambiente_protegido_exige_chave_publicavel(ambiente):
    with pytest.raises(ConfiguracaoInvalida, match="SUPABASE_KEY"):
        carregar({"APP_ENV": ambiente, "SUPABASE_URL": "https://prod.exemplo.co"})


@pytest.mark.parametrize("ambiente", ["staging", "production"])
def test_redis_sem_senha_nao_sobe_em_ambiente_protegido(ambiente):
    # O aviso da fila leva o token do usuário (ADR-004).
    with pytest.raises(ConfiguracaoInvalida, match="sem senha"):
        carregar({**PROD, "APP_ENV": ambiente, "REDIS_URL": "redis://redis:6379/0"})


def test_redis_com_senha_sobe_e_a_senha_nao_vai_para_o_repr():
    config = carregar({**PROD, "REDIS_URL": "redis://:senha-de-teste-123@redis:6379/0"})
    assert config.redis_url.endswith("@redis:6379/0")
    assert "senha-de-teste-123" not in repr(config)


def test_redis_sem_senha_vale_em_desenvolvimento():
    assert carregar({"APP_ENV": "development",
                     "REDIS_URL": "redis://127.0.0.1:6379/0"}).redis_url
