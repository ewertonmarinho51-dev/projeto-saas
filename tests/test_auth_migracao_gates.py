from __future__ import annotations

import pathlib
import sys

import pytest

RAIZ = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))

import aplicar_vinculos_auth as gates  # noqa: E402
import criar_contas_auth as criar  # noqa: E402

PROD = "nxibohgoekphxblqtqku"
TENANT = "11111111-1111-1111-1111-111111111111"
SECRETARIA = "22222222-2222-2222-2222-222222222222"


def test_project_ref_so_aceita_host_supabase():
    assert criar.project_ref_da_url(f"https://{PROD}.supabase.co") == PROD
    assert criar.project_ref_da_url("https://example.org") == ""
    assert gates.project_ref_da_url(f"https://{PROD}.supabase.co") == PROD


def test_projeto_divergente_e_recusado():
    with pytest.raises(criar.ErroCriacao, match="projeto divergente"):
        criar.conferir_projeto("https://outro.supabase.co", PROD)
    with pytest.raises(gates.ErroGate, match="projeto divergente"):
        gates.conferir_projeto("https://outro.supabase.co", PROD)


def test_metadata_e_derivado_sem_inventar_governanca():
    meta = criar.app_metadata_da_linha({
        "papel": "admin",
        "tenant_id": TENANT,
        "secretaria_id": SECRETARIA,
        "papel_governanca": None,
    })
    assert meta == {
        "papel": "admin",
        "tenant_id": TENANT,
        "secretaria_id": SECRETARIA,
    }


def test_metadata_sem_secretaria_omite_chave():
    meta = criar.app_metadata_da_linha({
        "papel": "usuario",
        "tenant_id": TENANT,
        "secretaria_id": None,
        "papel_governanca": None,
    })
    assert "secretaria_id" not in meta
    assert "papel_governanca" not in meta


def test_metadata_recusa_papel_ou_uuid_invalidos():
    with pytest.raises(criar.ErroCriacao, match="papel inválido"):
        criar.app_metadata_da_linha({"papel": "superadmin", "tenant_id": TENANT})
    with pytest.raises(criar.ErroCriacao, match="tenant_id inválido"):
        criar.app_metadata_da_linha({"papel": "admin", "tenant_id": "nao-uuid"})


def test_aplicacao_completa_recusa_orfaos():
    with pytest.raises(gates.ErroGate, match="deixaria 1 processos"):
        gates.validar_sobras(antes=6, a_preencher=5,
                             canario=False, quantidade_vinculos=2)


def test_canario_permite_sobra_so_com_um_usuario():
    assert gates.validar_sobras(antes=6, a_preencher=1,
                                canario=True, quantidade_vinculos=1) == 5
    with pytest.raises(gates.ErroGate, match="exatamente um vínculo"):
        gates.validar_sobras(antes=6, a_preencher=6,
                             canario=True, quantidade_vinculos=2)


def test_aplicacao_completa_sem_orfaos_passa():
    assert gates.validar_sobras(antes=6, a_preencher=6,
                                canario=False, quantidade_vinculos=2) == 0
