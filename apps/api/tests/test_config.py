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
