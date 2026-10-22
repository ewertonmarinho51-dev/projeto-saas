"""
Fixtures da prova de autorização real. A pilha mora em `pilha.py`,
compartilhada com o E2E do web.

Sem a pilha: com `GOVCONECT_EXIGIR_RLS=1` (CI) é ERRO; sem a variável,
pula — "não consegui verificar" nunca vira "verificado".
"""

from __future__ import annotations

import os

import pytest

import pilha as modulo_pilha


@pytest.fixture(scope="session")
def pilha():
    if falta := modulo_pilha.faltando():
        if os.getenv("GOVCONECT_EXIGIR_RLS") == "1":
            pytest.fail(f"pilha RLS exigida e ausente: {', '.join(falta)}")
        pytest.skip("pilha RLS ausente (rode no job api-rls do CI)")
    with modulo_pilha.subir() as p:
        yield p


@pytest.fixture(scope="session")
def api(pilha):
    from fastapi.testclient import TestClient

    from govconect_api.config import carregar
    from govconect_api.main import criar_app

    config = carregar({"APP_ENV": "test", "SUPABASE_URL": pilha.url,
                       "SUPABASE_KEY": pilha.anon,
                       "GOVCONECT_LIMITE_POR_MINUTO": "10000"})
    return TestClient(criar_app(config), raise_server_exceptions=False)
