import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

RAIZ_API = Path(__file__).resolve().parent.parent
if str(RAIZ_API) not in sys.path:
    sys.path.insert(0, str(RAIZ_API))

from govconect_api.config import carregar  # noqa: E402
from govconect_api.main import criar_app  # noqa: E402

AMBIENTE_DE_TESTE = {"APP_ENV": "test",
                     "SUPABASE_URL": "https://exemplo-staging.supabase.co"}


@pytest.fixture
def config():
    return carregar(AMBIENTE_DE_TESTE)


@pytest.fixture
def cliente(config):
    # raise_server_exceptions=False: o teste vê o que o NAVEGADOR veria,
    # inclusive o envelope do 500, em vez da exceção crua do servidor.
    return TestClient(criar_app(config), raise_server_exceptions=False)
