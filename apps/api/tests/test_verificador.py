"""
Verificação do JWT: só passa o token do projeto, do usuário, no prazo e
com vínculo ativo no mesmo município. 05_SEGURANCA, ataques 1 e 3.
"""

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from govconect_api.seguranca import SemVinculo, TokenRecusado
from govconect_api.verificador import VerificadorSupabase

from apoio_jwt import (EMISSOR, LINHA_A, SECRETARIA_A, TENANT_A, USUARIO_A,
                       Emissor, PostgrestFalso)


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def banco():
    return PostgrestFalso()


@pytest.fixture
def verificador(emissor, banco):
    return VerificadorSupabase(emissor=EMISSOR, rest=banco.cliente(),
                               chave_para=emissor.chave_para)


def test_token_valido_vira_identidade_derivada_do_app_metadata(verificador, emissor, banco):
    token = emissor.token()
    eu = verificador.verificar(token)
    assert (eu.auth_user_id, eu.tenant_id, eu.papel, eu.secretaria_id, eu.usuario_id) == \
        (USUARIO_A, TENANT_A, "usuario", SECRETARIA_A, LINHA_A)
    # O vínculo foi lido COM O TOKEN DO USUÁRIO, e só ele.
    chamada = banco.chamadas[0]
    assert chamada.headers["authorization"] == f"Bearer {token}"
    assert chamada.headers["apikey"] == "chave-publicavel-de-teste"
    assert chamada.url.params["auth_user_id"] == f"eq.{USUARIO_A}"


def test_token_nao_aparece_no_repr_da_identidade(verificador, emissor):
    token = emissor.token()
    assert token not in repr(verificador.verificar(token))


@pytest.mark.parametrize("caso, kwargs", [
    ("vencido", {"exp_em": -120}),
    ("outra_audiencia", {"aud": "anon"}),
    ("outro_emissor", {"iss": "https://outro-projeto.supabase.co/auth/v1"}),
    ("anon", {"role": "anon"}),
    ("service_role", {"role": "service_role"}),
    ("sub_nao_uuid", {"sub": "admin"}),
])
def test_claims_invalidas_sao_recusadas(verificador, emissor, caso, kwargs):
    with pytest.raises(TokenRecusado):
        verificador.verificar(emissor.token(**kwargs))


def test_assinatura_de_outra_chave_e_recusada(verificador, emissor):
    intrusa = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(TokenRecusado):
        verificador.verificar(emissor.token(chave=intrusa))


def test_kid_desconhecido_e_recusado(verificador, emissor):
    with pytest.raises(TokenRecusado):
        verificador.verificar(emissor.token(kid="kid-inventado"))


def test_alg_none_e_recusado(verificador):
    token = jwt.encode({"sub": USUARIO_A, "role": "authenticated"}, None,
                       algorithm="none")
    with pytest.raises(TokenRecusado):
        verificador.verificar(token)


def test_confusao_de_algoritmo_hs256_e_recusada(verificador, emissor):
    # Ataque clássico: assinar HS256 usando a CHAVE PÚBLICA como segredo,
    # esperando que o servidor aceite o `alg` que o token declara.
    from cryptography.hazmat.primitives import serialization

    publica = emissor.chave.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    token = jwt.encode({"sub": USUARIO_A, "role": "authenticated",
                        "aud": "authenticated", "iss": EMISSOR, "iat": 1,
                        "exp": 9_999_999_999}, publica.decode()[:64],
                       algorithm="HS256", headers={"kid": emissor.kid})
    with pytest.raises(TokenRecusado):
        verificador.verificar(token)


@pytest.mark.parametrize("kwargs", [
    {"tenant": None},
    {"tenant": "nao-e-uuid"},
    {"papel": "proprietario"},
    {"secretaria": "nao-e-uuid"},
])
def test_vinculo_ausente_ou_torto_e_negado(verificador, emissor, kwargs):
    with pytest.raises(SemVinculo):
        verificador.verificar(emissor.token(**kwargs))


def test_tenant_so_em_user_metadata_nao_vale(verificador, emissor):
    # user_metadata é editável pelo próprio usuário. Não é fonte de nada.
    token = emissor.token(tenant=None, extra={
        "user_metadata": {"tenant_id": TENANT_A, "papel": "admin"}})
    with pytest.raises(SemVinculo):
        verificador.verificar(token)


def test_usuario_desativado_perde_acesso_antes_do_exp(verificador, emissor, banco):
    banco.usuarios = [{"id": LINHA_A, "ativo": False, "tenant_id": TENANT_A}]
    with pytest.raises(SemVinculo):
        verificador.verificar(emissor.token())


def test_sem_linha_em_usuarios_e_negado(verificador, emissor, banco):
    banco.usuarios = []
    with pytest.raises(SemVinculo):
        verificador.verificar(emissor.token())


def test_tenant_do_cadastro_divergente_do_token_e_negado(verificador, emissor, banco):
    banco.usuarios = [{"id": LINHA_A, "ativo": True,
                       "tenant_id": "bbbbbbbb-0000-4000-8000-000000000002"}]
    with pytest.raises(SemVinculo):
        verificador.verificar(emissor.token())


def test_modo_hs256_nao_aceita_es256(banco, emissor):
    v = VerificadorSupabase(emissor=EMISSOR, rest=banco.cliente(),
                            segredo_hs256="segredo-local-de-teste-com-tamanho")
    with pytest.raises(TokenRecusado):
        v.verificar(emissor.token())


def test_modo_hs256_aceita_hs256_do_mesmo_segredo(banco, emissor):
    segredo = "segredo-local-de-teste-com-tamanho"
    v = VerificadorSupabase(emissor=EMISSOR, rest=banco.cliente(),
                            segredo_hs256=segredo)
    eu = v.verificar(emissor.token(chave=segredo, alg="HS256"))
    assert eu.tenant_id == TENANT_A


def test_exige_exatamente_um_modo(banco, emissor):
    with pytest.raises(ValueError):
        VerificadorSupabase(emissor=EMISSOR, rest=banco.cliente())
    with pytest.raises(ValueError):
        VerificadorSupabase(emissor=EMISSOR, rest=banco.cliente(),
                            chave_para=emissor.chave_para, segredo_hs256="x" * 32)
