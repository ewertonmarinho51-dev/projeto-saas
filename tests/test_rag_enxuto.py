"""
RAG enxuto: menos trechos, sem perder tema.

O bloco de referências era o segundo maior item da conta — 4.600 tokens
por documento, 31% da entrada de um processo de 20 itens. O teto que
existia era de CONTAGEM, e contagem não controla tamanho: dez trechos
de 1.500 caracteres custam dez vezes mais que dez de 150, e o teto de
dez aceitava os dois igualmente.

O que estas provas guardam é o que o corte NÃO pode fazer: calar um
tema inteiro, jogar fora a melhor evidência, ou mudar o prompt quando a
flag está desligada.
"""

from __future__ import annotations

import pytest

from src import rag


@pytest.fixture(autouse=True)
def _flag_ligada(monkeypatch):
    monkeypatch.setattr(rag.db, "flag_ativa",
                        lambda nome: nome == rag.FLAG_RAG_ENXUTO)


def _trecho(i: int, tema: str = "geral", score: float = 0.5,
            texto: str | None = None, categoria: str = "lei") -> dict:
    return {
        "conteudo": texto if texto is not None
        else f"Trecho {i} sobre {tema}. " + f"palavra{i} " * 200,
        "titulo": f"Fonte {i}", "categoria": categoria, "score": score,
        "tema": tema, "tema_rotulo": tema, "documento_id": f"d{i}", "ordem": i,
    }


def test_o_bloco_respeita_o_orcamento_de_caracteres():
    dez = [_trecho(i, score=0.9 - i * 0.01) for i in range(10)]
    escolhidos = rag._enxugar(dez)
    total = sum(len(t["conteudo"]) for t in escolhidos)
    assert total <= rag.ORCAMENTO_CARACTERES_RAG
    assert escolhidos, "cortar tudo não é enxugar, é desligar o RAG"


def test_o_que_sobrevive_ao_corte_e_sempre_o_mais_relevante():
    """
    A mutação que importa: cortar pela ORDEM da lista em vez de pela
    relevância manteria o que estava no topo por acaso de ordenação e
    jogaria fora a melhor evidência.
    """
    fracos = [_trecho(i, score=0.10 + i * 0.001) for i in range(9)]
    forte = _trecho(99, score=0.99)
    escolhidos = rag._enxugar(fracos + [forte])
    assert any(t["documento_id"] == "d99" for t in escolhidos)


def test_um_trecho_gigante_sozinho_nao_e_descartado():
    """
    Se o primeiro trecho já estourar o orçamento, cortá-lo deixaria o
    documento sem referência nenhuma — pior que a economia.
    """
    gigante = _trecho(1, texto="x" * (rag.ORCAMENTO_CARACTERES_RAG * 3))
    assert rag._enxugar([gigante]) == [gigante]


def test_trechos_que_dizem_a_mesma_coisa_ocupam_uma_vaga_so():
    """
    A base tem o mesmo dispositivo em fontes diferentes: a lei, o manual
    que a transcreve, o acórdão que a cita. Três vagas, uma informação.
    """
    texto = ("Art. 18. A fase preparatória do processo licitatório é "
             "caracterizada pelo planejamento e deve compatibilizar-se "
             "com o plano de contratações anual. ") * 6
    copias = [_trecho(1, score=0.9, texto=texto),
              _trecho(2, score=0.8, texto=texto + "Observação final."),
              _trecho(3, score=0.7, texto=texto)]
    escolhidos = rag._enxugar(copias)
    assert len(escolhidos) == 1
    assert escolhidos[0]["score"] == 0.9, "ficou a cópia menos relevante"


def test_trechos_diferentes_nao_sao_confundidos_com_copia():
    """
    A mutação simétrica: um limiar frouxo trataria evidências distintas
    como duplicata e calaria a que faltava — economia pela perda de
    informação, que é o oposto do pedido.
    """
    a = _trecho(1, texto="Art. 18 da Lei 14.133 sobre fase preparatória. " * 8)
    b = _trecho(2, texto="Art. 155 sobre infrações e sanções administrativas. " * 8)
    assert len(rag._enxugar([a, b])) == 2


def test_com_a_flag_desligada_o_prompt_e_byte_a_byte_o_de_antes(monkeypatch):
    monkeypatch.setattr(rag.db, "flag_ativa", lambda nome: False)
    dez = [_trecho(i) for i in range(10)]
    assert rag._enxugar(dez) == dez


def test_a_deduplicacao_acontece_antes_do_corte_por_orcamento():
    """
    A ordem importa: cortar primeiro gastaria vagas do orçamento com
    cópias e descartaria a evidência NOVA que vinha atrás delas.
    """
    copia = "Art. 23 sobre pesquisa de preços e valor estimado. " * 25
    lista = [_trecho(1, score=0.99, texto=copia),
             _trecho(2, score=0.98, texto=copia),
             _trecho(3, score=0.97, texto=copia),
             _trecho(4, score=0.10, tema="sancoes",
                     texto="Art. 156 sobre as sanções aplicáveis. " * 25)]
    escolhidos = rag._enxugar(lista)
    assert any(t["tema"] == "sancoes" for t in escolhidos), (
        "as cópias consumiram o orçamento e o tema que faltava ficou de "
        "fora — deduplicar depois de cortar é inútil")
