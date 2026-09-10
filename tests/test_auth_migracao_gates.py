from __future__ import annotations

import os
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


# ---------------------------------------------------------------------------
# O script precisa CHEGAR a recusar
#
# As provas acima exercitam funções soltas, e por isso passavam enquanto
# nenhum dos três scripts conseguia sequer iniciar: `main()` fazia
# `import db` com `src/` no `sys.path`, e `src/db.py` abre com
# `from . import trilha`. Importado como módulo solto, sem pacote, o
# import relativo estoura `ImportError` — antes de qualquer conferência,
# e FORA do `try`, então nem virava "RECUSADO".
#
# O runbook inteiro da migração de identidade depende destes três
# comandos. Prova de função não alcança o defeito: só rodar o programa
# de verdade alcança. Por isso aqui é subprocesso, pela mesma linha de
# comando que o runbook manda digitar.
# ---------------------------------------------------------------------------
import json  # noqa: E402
import subprocess  # noqa: E402

USUARIO = "679d43c6-1fcc-459c-98b4-9ad9315c1715"


@pytest.fixture
def mapa_valido(tmp_path):
    caminho = tmp_path / "contas-auth.json"
    caminho.write_text(json.dumps(
        [{"usuario_id": USUARIO, "auth_email": "servidor@example.org"}]),
        encoding="utf-8")
    return caminho


# Cada script tem a sua linha de comando, e a diferença é informativa:
# `vincular_contas_auth.py` NÃO aceita `--projeto-ref`. A guarda de
# projeto nasceu nos dois scripts novos; o antigo é o que o runbook
# deixou de usar, em favor do `aplicar_vinculos_auth.py`. Mandar os
# mesmos argumentos aos três esconderia essa diferença atrás de um erro
# de argparse — e foi o que aconteceu na primeira versão desta prova.
ARGUMENTOS = {
    "criar_contas_auth.py": ["--projeto-ref", PROD],
    "vincular_contas_auth.py": [],
    "aplicar_vinculos_auth.py": ["--projeto-ref", PROD],
}


@pytest.mark.parametrize("script", sorted(ARGUMENTOS))
def test_o_script_inicia_e_recusa_em_vez_de_estourar(script, mapa_valido):
    """
    Sem credencial, o esperado é uma RECUSA legível — não um traceback.

    A distinção importa para quem opera: "RECUSADO: banco indisponível"
    diz o que fazer; um `ImportError` de import relativo diz que o
    programa está quebrado, e some com a diferença entre "falta
    configurar" e "não funciona".
    """
    ambiente = {"PATH": os.environ.get("PATH", ""),
                "HOME": os.environ.get("HOME", "")}
    resultado = subprocess.run(
        [sys.executable, str(RAIZ / "scripts" / script),
         "--mapa", str(mapa_valido), *ARGUMENTOS[script]],
        capture_output=True, text=True, timeout=120, env=ambiente, cwd=RAIZ)

    assert "ImportError" not in resultado.stderr, resultado.stderr
    assert "Traceback" not in resultado.stderr, resultado.stderr
    assert "RECUSADO" in resultado.stdout, (resultado.stdout, resultado.stderr)
    assert resultado.returncode == 2
