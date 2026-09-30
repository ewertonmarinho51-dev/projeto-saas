"""
Equipe de planejamento: dado do cadastro, não redação de modelo.

POR QUE ESTA CLÁUSULA E NÃO OUTRA

A regra 15 do system prompt já dizia que nome, cargo e matrícula de
agente só entram no documento se constarem do processo — e o modelo,
que não tem acesso ao cadastro, cumpria a regra do único jeito que
podia: escrevendo `[PREENCHER: nome e matrícula do agente]`. Nas
instalações em que a portaria de designação ESTÁ cadastrada, isso é uma
pendência inventada: o dado existe, e quem não o tinha era o modelo.

Tirar a cláusula do modelo economiza a saída dela e melhora o
documento. As provas abaixo guardam as duas metades — e, principalmente,
que a AUSÊNCIA de portaria continua virando pendência visível, nunca
uma frase que disfarce a falta.
"""

from __future__ import annotations

import pytest

from src import clausulas_deterministicas as cd


@pytest.fixture(autouse=True)
def _flag_ligada(monkeypatch):
    monkeypatch.setattr(cd, "ativo", lambda: True)


PORTARIA = {
    "id": "p1", "numero": "45", "ano": 2026,
    "membros": [
        {"nome": "Servidor A", "cargo": "Analista", "matricula": "1234",
         "ordem": 1, "ativo": True},
        {"nome": "Servidor B", "funcao": "Presidente", "matricula": "5678",
         "ordem": 0, "ativo": True},
        {"nome": "Servidor C", "cargo": "Ex-membro", "matricula": "9999",
         "ordem": 2, "ativo": False},
    ],
}


def test_a_equipe_cadastrada_entra_com_nome_cargo_e_matricula():
    texto = cd.texto_da_equipe(PORTARIA)
    assert "Servidor A" in texto and "1234" in texto
    assert "Servidor B" in texto and "Presidente" in texto


def test_membro_inativo_nao_entra():
    """
    Quem saiu da equipe não assina o documento de hoje. O filtro é o
    mesmo `portarias.membros_vigentes` que o bloco de assinaturas usa —
    duas listas diferentes de membros no mesmo documento seria pior que
    nenhuma.
    """
    assert "Servidor C" not in cd.texto_da_equipe(PORTARIA)


def test_a_ordem_declarada_e_respeitada():
    """O presidente (ordem 0) vem antes do analista (ordem 1)."""
    texto = cd.texto_da_equipe(PORTARIA)
    assert texto.index("Servidor B") < texto.index("Servidor A")


def test_sem_portaria_a_pendencia_continua_visivel():
    """
    A mutação que importa: devolver uma frase evasiva ("a equipe será
    designada oportunamente") faria a emissão DESBLOQUEAR sem ninguém
    saber quem é a equipe. O marcador é o que segura o documento.
    """
    texto = cd.texto_da_equipe(None)
    assert texto.startswith("[PREENCHER:")


def test_portaria_sem_membros_cita_a_portaria_e_pede_os_nomes():
    texto = cd.texto_da_equipe({"numero": "45", "ano": 2026, "membros": []})
    assert "[PREENCHER:" in texto


def test_a_instrucao_proibe_o_modelo_de_escrever_nome():
    instrucao = cd.instrucao_para_o_prompt("etp")
    assert cd.MARCADOR_EQUIPE in instrucao
    assert "PROIBIDO escrever nome" in instrucao
    assert "16" in instrucao, "a instrução tem de dizer QUAL cláusula"


def test_documento_sem_clausula_de_equipe_nao_recebe_instrucao():
    """O TR e o Mapa de Riscos não têm essa cláusula nos perfis."""
    for doc in ("tr", "mapa_riscos", "edital"):
        assert cd.instrucao_para_o_prompt(doc) == ""


def test_a_injecao_substitui_o_marcador(monkeypatch):
    monkeypatch.setattr(cd, "_portaria_do_processo", lambda: PORTARIA)
    texto = ("## 9. EQUIPE DE PLANEJAMENTO\n\n"
             f"{cd.MARCADOR_EQUIPE}\n\n## 10. OUTRA")
    saida = cd.injetar(texto, "dfd")
    assert cd.MARCADOR_EQUIPE not in saida
    assert "Servidor A" in saida
    assert "## 10. OUTRA" in saida, "a cláusula seguinte foi comida"


def test_marcador_repetido_nao_duplica_a_equipe(monkeypatch):
    """
    O modelo às vezes repete o marcador. Duplicar a tabela de membros
    faria o documento designar a mesma equipe duas vezes.
    """
    monkeypatch.setattr(cd, "_portaria_do_processo", lambda: PORTARIA)
    texto = f"## 9. EQUIPE\n\n{cd.MARCADOR_EQUIPE}\n\n{cd.MARCADOR_EQUIPE}"
    saida = cd.injetar(texto, "dfd")
    assert saida.count("Servidor A") == 1
    assert cd.MARCADOR_EQUIPE not in saida


def test_sem_marcador_o_texto_do_modelo_e_preservado(monkeypatch):
    """
    Documento gerado antes da flag, ou modelo que ignorou a instrução:
    apagar o que ele escreveu deixaria a cláusula obrigatória vazia.
    """
    monkeypatch.setattr(cd, "_portaria_do_processo", lambda: PORTARIA)
    texto = "## 9. EQUIPE DE PLANEJAMENTO\n\nA equipe é [PREENCHER: nomes]."
    assert cd.injetar(texto, "dfd") == texto


def test_flag_desligada_nao_muda_prompt_nem_documento(monkeypatch):
    monkeypatch.setattr(cd, "ativo", lambda: False)
    assert cd.instrucao_para_o_prompt("dfd") == ""
    texto = f"## 9. EQUIPE\n\n{cd.MARCADOR_EQUIPE}"
    assert cd.injetar(texto, "dfd") == texto


def test_a_clausula_declarada_existe_no_perfil():
    """
    Um número errado aqui mandaria o modelo marcar a cláusula errada — e
    a equipe apareceria no lugar da estimativa de valor.
    """
    from src import perfis

    for doc_key, numero in cd.CLAUSULAS_DA_EQUIPE.items():
        clausula = next(c for c in perfis.PERFIS[doc_key]["clausulas"]
                        if c["n"] == numero)
        assert "EQUIPE DE PLANEJAMENTO" in clausula["titulo"], (
            f"{doc_key}/{numero} não é a cláusula de equipe: "
            f"{clausula['titulo']}")


def test_falha_do_cadastro_nao_derruba_a_geracao(monkeypatch):
    """
    Portaria indisponível (banco fora, migração 0025 não aplicada,
    conflito de portarias) tem de virar pendência — nunca exceção no
    meio da geração do documento.
    """
    from src import db

    def explode(*_a, **_k):
        raise RuntimeError("banco fora")

    monkeypatch.setattr(db, "listar_portarias", explode)
    assert cd._portaria_do_processo() is None
    assert cd.texto_da_equipe(None).startswith("[PREENCHER:")
