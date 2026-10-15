"""
Pesquisa Automática no motor compartilhado — 210 itens sintéticos (Gate 3).

Sem rede e sem IA paga: a fonte é um dublê que responde POR DESCRIÇÃO, e
a triagem (o lugar onde a IA entra) é um contador. Os itens são
sintéticos e identificados como tal — nenhum número aqui é pesquisa
oficial.

Distribuição dos 210:
* ``SEM-``   — fonte saudável, nenhuma referência     → INCOMPLETO
* ``DUAS-``  — duas referências                         → INCOMPLETO
* ``QUEDA-`` — a fonte cai sempre para este item        → ERRO
* demais     — quatro referências 20/22/24/26           → REVISÃO, média 23,00
"""

from __future__ import annotations

from decimal import Decimal

from src.precos import estatistica, execucao
from src.precos.estados import EstadoItem
from src.precos.fontes import Consulta, ResultadoBusca
from src.precos.modelo import NaturezaValor
from tests.test_precos_fase4 import FONTE_OFICIAL, _RepositorioFalso, _referencia

PESQUISA = {"id": "p210", "filtros": {},
            "versao_regras": estatistica.REGRAS_MEDIA_PADRAO}


def _descricao(n: int) -> str:
    if n <= 5 or n % 37 == 0:
        return f"QUEDA-{n} CANETA ESFEROGRAFICA AZUL"
    if n % 7 == 0:
        return f"SEM-{n} CANETA ESFEROGRAFICA AZUL"
    if n % 11 == 0:
        return f"DUAS-{n} CANETA ESFEROGRAFICA AZUL"
    return f"ITEM-{n} CANETA ESFEROGRAFICA AZUL"


def _itens() -> list[dict]:
    return [{"id": f"i{n}", "numero": n, "estado": EstadoItem.PENDENTE.value,
             "descricao": _descricao(n), "unidade": "UNIDADE",
             "quantidade": "100"} for n in range(1, 211)]


class _FontePorItem:
    """Responde conforme o prefixo da descrição; conta as chamadas."""

    fonte = FONTE_OFICIAL

    def __init__(self):
        self.chamadas: dict[str, int] = {}

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        prefixo = consulta.descricao.split()[0]
        self.chamadas[prefixo] = self.chamadas.get(prefixo, 0) + 1
        if prefixo.startswith("QUEDA-"):
            raise TimeoutError("fonte lenta")
        if prefixo.startswith("SEM-"):
            valores = ()
        elif prefixo.startswith("DUAS-"):
            valores = ("20.00", "22.00")
        else:
            valores = ("20.00", "22.00", "24.00", "26.00")
        descricao = consulta.descricao.split(" ", 1)[1]
        referencias = [
            _referencia(FONTE_OFICIAL, f"{prefixo}-r{i}", v, descricao=descricao)
            for i, v in enumerate(valores)]
        for ref in referencias:
            ref.natureza_valor = NaturezaValor.HOMOLOGADO
        return ResultadoBusca(fonte=FONTE_OFICIAL, referencias=referencias)


class _TriagemContada:
    """O ponto onde a IA entraria. Conta; não decide nada."""

    def __init__(self):
        self.por_item: dict[str, int] = {}

    def __call__(self, pesquisa, item, registradas, repositorio):
        chave = str(item["id"])
        self.por_item[chave] = self.por_item.get(chave, 0) + 1


def _rodar(itens, repositorio, fonte, triagem, *, max_rodadas):
    """
    O laço da tela (`_render_execucao`): um lote por rodada até a fila
    DESTA execução esvaziar. `tentados` é o que a sessão guarda.
    """
    tentados: set[str] = set()
    for rodada in range(1, max_rodadas + 1):
        atuais = list(repositorio.itens.values())
        if not execucao.proximo_lote(atuais, ja_tentados=tentados):
            return rodada - 1
        execucao.executar_lote(PESQUISA, atuais, [fonte], repositorio,
                               triagem=triagem, tentados=tentados)
    raise AssertionError(f"não terminou em {max_rodadas} rodadas")


def test_210_itens_terminam_mesmo_com_itens_que_sempre_falham():
    """
    Antes: `error` entrava na fila pela ordem da planilha, À FRENTE dos
    pendentes. Com os itens 1–5 sempre falhando, todo lote era [1..5] de
    novo e a pesquisa nunca saía do lugar.
    """
    itens = _itens()
    repositorio = _RepositorioFalso(itens)
    fonte, triagem = _FontePorItem(), _TriagemContada()

    rodadas = _rodar(itens, repositorio, fonte, triagem, max_rodadas=60)
    assert rodadas == 42, "210 itens ÷ lotes de 5, sem rodada desperdiçada"

    finais = list(repositorio.itens.values())
    estados = {}
    for item in finais:
        estados.setdefault(item["estado"], []).append(item["descricao"])
    assert all(d.startswith("QUEDA-") for d in estados[EstadoItem.ERRO.value])
    assert all(d.startswith(("SEM-", "DUAS-"))
               for d in estados[EstadoItem.INCOMPLETO.value])
    assert all(d.startswith("ITEM-")
               for d in estados[EstadoItem.EM_REVISAO.value])
    assert sum(map(len, estados.values())) == 210, "nenhuma linha perdida"

    # nada inventado: todo preço é a média das quatro referências dadas
    for item in finais:
        if item["estado"] == EstadoItem.EM_REVISAO.value:
            assert item["preco_estimado"] == Decimal("23.00")

    # cada fonte foi chamada UMA vez por item numa execução
    assert max(fonte.chamadas.values()) == 1
    # a triagem (IA) roda só onde houve referência, e uma vez
    assert set(triagem.por_item.values()) == {1}
    assert not any(repositorio.itens[i]["descricao"].startswith(("SEM-", "QUEDA-"))
                   for i in triagem.por_item)


def test_retomada_apos_interrupcao_nao_repete_busca_nem_ia():
    itens = _itens()
    repositorio = _RepositorioFalso(itens)
    fonte, triagem = _FontePorItem(), _TriagemContada()

    # a aba fecha no meio: 10 lotes e a interrupção
    tentados: set[str] = set()
    for _ in range(10):
        execucao.executar_lote(PESQUISA, list(repositorio.itens.values()),
                               [fonte], repositorio, triagem=triagem,
                               tentados=tentados)
    # um item fica "buscando" — o processo morreu durante a chamada
    repositorio.itens["i150"]["estado"] = EstadoItem.BUSCANDO.value
    feitos = dict(fonte.chamadas)

    _rodar(itens, repositorio, fonte, triagem, max_rodadas=60)

    # retomar é nova execução: só a falha técnica ganha nova tentativa
    for prefixo, vezes in feitos.items():
        esperado = vezes + 1 if prefixo.startswith("QUEDA-") else vezes
        assert fonte.chamadas[prefixo] == esperado, f"{prefixo}: {fonte.chamadas[prefixo]}"
    assert set(triagem.por_item.values()) == {1}, "IA cobrada duas vezes"
    assert repositorio.itens["i150"]["estado"] != EstadoItem.BUSCANDO.value
    for ref in repositorio.referencias.values():
        chaves = [(r.fonte.id, r.id_externo) for r in ref]
        assert len(chaves) == len(set(chaves)), "referência duplicada"


def test_falha_tecnica_volta_na_execucao_seguinte_e_so_nela():
    """Retry limitado: uma tentativa por execução, por clique do usuário."""
    itens = _itens()
    repositorio = _RepositorioFalso(itens)
    fonte, triagem = _FontePorItem(), _TriagemContada()
    _rodar(itens, repositorio, fonte, triagem, max_rodadas=60)
    assert fonte.chamadas["QUEDA-1"] == 1

    # "Pesquisar" de novo: só os itens com erro voltam à fila
    lote = execucao.proximo_lote(list(repositorio.itens.values()), 300)
    assert {i["descricao"].split()[0] for i in lote} == {
        f"QUEDA-{n}" for n in (1, 2, 3, 4, 5, 37, 74, 111, 148, 185)}


def test_fila_prioriza_interrompido_depois_pendente_e_erro_por_ultimo():
    itens = [{"id": "a", "numero": 1, "estado": EstadoItem.ERRO.value},
             {"id": "b", "numero": 2, "estado": EstadoItem.PENDENTE.value},
             {"id": "c", "numero": 3, "estado": EstadoItem.BUSCANDO.value},
             {"id": "d", "numero": 4, "estado": EstadoItem.PENDENTE.value},
             {"id": "e", "numero": 5, "estado": EstadoItem.CLASSIFICANDO.value}]
    assert [i["id"] for i in execucao.proximo_lote(itens, 5)] == [
        "c", "e", "b", "d", "a"]
