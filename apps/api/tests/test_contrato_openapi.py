from pathlib import Path

from govconect_api.contrato import gerar

ARQUIVO = Path(__file__).resolve().parent.parent / "openapi.v1.json"


def test_contrato_versionado_bate_com_o_codigo():
    assert ARQUIVO.read_text(encoding="utf-8") == gerar(), (
        "Contrato mudou. Regere com `python -m govconect_api.contrato "
        "> openapi.v1.json` e explique a mudança no PR.")


def test_identidade_nao_e_entrada_de_nenhuma_operacao():
    # tenant, papel e dono derivam do token verificado. Nenhum parâmetro
    # nem corpo do contrato pode aceitá-los do cliente.
    texto = gerar()
    import json

    for caminho, operacoes in json.loads(texto)["paths"].items():
        for metodo, op in operacoes.items():
            nomes = {p["name"] for p in op.get("parameters", [])}
            assert not nomes & {"tenant_id", "auth_user_id", "papel"}, \
                f"{metodo.upper()} {caminho}"
