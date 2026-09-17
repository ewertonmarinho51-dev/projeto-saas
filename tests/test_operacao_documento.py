import pytest
from src.operacao_documento import (executar, ocupada, confirmar_versao,
                                    OperacaoEmCurso, ContextoAlterado)


def test_exclusao_mutua_libera_apos_falha_e_permite_retry():
    s = {"dados": {"objeto": "Exemplo"}}
    with pytest.raises(ValueError):
        with executar(s, "etp", "1"):
            assert ocupada(s)
            with pytest.raises(OperacaoEmCurso):
                with executar(s, "etp", "2"):
                    pytest.fail("Concorrência admitida")
            raise ValueError("Falha simulada")
    assert not ocupada(s)
    with executar(s, "etp", "2"):
        pass
    with pytest.raises(OperacaoEmCurso):
        with executar(s, "etp", "2"):
            pytest.fail("Replay admitido")


def test_contexto_modificado_recusa_commit():
    s = {"documentos": {"etp": "A"}, "aprovados": {"etp"}}
    with executar(s, "tr", "1") as (etapa, base):
        etapa("GERANDO")
        s["documentos"]["etp"] = "B"
        with pytest.raises(ContextoAlterado):
            confirmar_versao(s, base)
        with pytest.raises(ValueError):
            etapa("PREPARANDO")
