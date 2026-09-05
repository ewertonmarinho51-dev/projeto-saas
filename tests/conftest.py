"""Garante que a raiz do projeto esteja no sys.path.

O AppTest executa app.py no processo do pytest; sem isto, `from src
import ...` falha quando o pytest é invocado como binário (`pytest`),
que — ao contrário de `python -m pytest` — não inclui o diretório
atual no sys.path.
"""

import pytest
import sys
import types
import uuid
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)


# ---------------------------------------------------------------------------
# Trilha de governança nos bancos falsos
#
# A trilha deixou de ser `insert` direto pelo cliente de SERVIDOR e
# passou a ser a RPC `registrar_evento_governanca`, chamada pelo
# cliente do USUÁRIO. Os bancos falsos dos testes de domínio precisam
# acompanhar — senão testam um caminho que o app não usa mais.
#
# Esta emulação é DELIBERADAMENTE mínima: confere o vocabulário (o que
# um erro de nome de evento faria o servidor recusar) e grava `ator`
# como identidade fixa da sessão falsa. Ela NÃO emula papel, tenant nem
# secretaria — quem prova autorização é o ensaio contra um Postgres de
# verdade, e um fake que fingisse fazer isso daria falsa segurança.
# ---------------------------------------------------------------------------
ATOR_FALSO = "00000000-0000-0000-0000-0000000000a7"


def ligar_trilha_falsa(monkeypatch, db_mod, cliente, tabelas) -> None:
    """
    Faz o cliente falso responder à RPC da trilha e ser o cliente do
    usuário. Sem isto, `cliente_do_usuario()` devolve None e a trilha
    recusa — que é o comportamento certo em produção e ruído no teste
    de domínio.
    """
    from src import trilha

    def rpc(nome, parametros):
        assert nome == "registrar_evento_governanca", nome
        # o servidor confere; o fake confere o mesmo, para que um nome
        # de evento errado apareça aqui e não só no ensaio
        trilha.exigir_evento_valido(parametros["p_tipo_evento"],
                                    parametros["p_entidade_tipo"])
        registro = {
            "id": str(uuid.uuid4()),
            "tenant_id": db_mod.tenant_atual(),
            "ator": ATOR_FALSO,
            "tipo_evento": parametros["p_tipo_evento"],
            "entidade_tipo": parametros["p_entidade_tipo"],
            "entidade_id": parametros["p_entidade_id"],
            "payload": parametros["p_payload"],
        }
        tabelas.setdefault("governanca_eventos", []).append(registro)
        return types.SimpleNamespace(
            execute=lambda: types.SimpleNamespace(data=registro["id"]))

    cliente.rpc = rpc
    monkeypatch.setattr(db_mod, "cliente_do_usuario", lambda: cliente)


# ---------------------------------------------------------------------------
# Motor institucional de PDF (DOCX → LibreOffice → PDF)
#
# As provas do PDF real dependem do LibreOffice Writer. Sem ele, nenhum
# filtro de documento carrega, `export.motor_pdf()` responde "fpdf2" e as
# provas PULAM — foi assim que um defeito grave ficou invisível: os 210
# códigos da planilha saíam partidos no PDF ("57270" + "4"), e a prova
# que teria acusado isso nunca rodou, nem aqui nem na CI.
#
# Pular é aceitável na máquina de quem desenvolve. Em CI/release não é:
# ali a ausência do motor institucional é FALHA DE AMBIENTE, e o
# interruptor abaixo é o que faz essa diferença ser explícita em vez de
# depender de quem lê a saída notar 10 linhas de 's'.
# ---------------------------------------------------------------------------
VARIAVEL_MOTOR_OBRIGATORIO = "GOVDOCS_EXIGIR_LIBREOFFICE"


def motor_institucional_obrigatorio() -> bool:
    """O ambiente declara que o LibreOffice é requisito, não conveniência?"""
    import os

    valor = (os.environ.get(VARIAVEL_MOTOR_OBRIGATORIO) or "").strip().lower()
    return valor not in ("", "0", "false", "nao", "não", "off")


def exigir_motor_institucional() -> None:
    """
    Falha (CI/release) ou pula (local) quando o motor não é o LibreOffice.

    Chamada pelas provas que medem o PDF REAL. Nunca silencia: ou o teste
    roda, ou o motivo aparece nomeado na saída.
    """
    import pytest

    from src import export

    motor = export.motor_pdf()
    if motor == "libreoffice":
        return
    recado = (
        f"motor de PDF efetivo é '{motor}', não 'libreoffice': a conversão "
        "DOCX→PDF não roda neste ambiente (falta o pacote "
        "libreoffice-writer — o meta-pacote 'libreoffice' de packages.txt o "
        "inclui). As provas do PDF institucional não podem ser executadas."
    )
    if motor_institucional_obrigatorio():
        pytest.fail(
            f"{recado} Este ambiente declarou "
            f"{VARIAVEL_MOTOR_OBRIGATORIO}=1: aqui a ausência do motor "
            "institucional é falha, não skip."
        )
    pytest.skip(recado)


@pytest.fixture
def motor_institucional():
    """Provas que exigem o PDF real pedem esta fixture."""
    exigir_motor_institucional()


# ---------------------------------------------------------------------------
# Ensaio SQL local (PostgreSQL descartável)
#
# Mesma armadilha, outro assunto. As provas de autorização — a matriz da
# 0020 e, agora, o isolamento das tabelas de pesquisa de preços da 0021 —
# só rodam com um PostgreSQL local. Sem ele PULAM, e uma saída cheia de
# "s" é indistinguível de uma cheia de "." para quem lê rápido.
#
# Pular é aceitável na máquina de quem desenvolve, onde nem sempre há um
# cluster à mão. Em CI/release não é: ali a ausência do banco de ensaio é
# FALHA DE AMBIENTE, e o interruptor abaixo torna a diferença explícita —
# do mesmo jeito que `GOVDOCS_EXIGIR_LIBREOFFICE` fez com o motor de PDF,
# depois que um defeito grave ficou invisível porque a prova que o
# pegaria nunca rodava.
# ---------------------------------------------------------------------------
VARIAVEL_ENSAIO_SQL = "GOVDOCS_ENSAIO_PG_DSN"
VARIAVEL_ENSAIO_SQL_OBRIGATORIO = "GOVDOCS_EXIGIR_ENSAIO_SQL"


def ensaio_sql_obrigatorio() -> bool:
    """O ambiente declara que o ensaio SQL é requisito, não conveniência?"""
    import os

    valor = (os.environ.get(VARIAVEL_ENSAIO_SQL_OBRIGATORIO) or "")
    return valor.strip().lower() not in ("", "0", "false", "nao", "não", "off")


def exigir_ensaio_sql() -> None:
    """
    Falha (CI/release) ou pula (local) quando não há PostgreSQL de ensaio.

    Nunca silencia: ou as provas de autorização rodam, ou o motivo
    aparece nomeado na saída.
    """
    import os

    if (os.environ.get(VARIAVEL_ENSAIO_SQL) or "").strip():
        return
    recado = (
        f"{VARIAVEL_ENSAIO_SQL} não está definida: não há PostgreSQL local "
        "descartável para aplicar o schema e exercer as políticas de RLS. "
        "As provas de autorização não podem ser executadas "
        "(ver scripts/ensaio_local.py)."
    )
    if ensaio_sql_obrigatorio():
        pytest.fail(
            f"{recado} Este ambiente declarou "
            f"{VARIAVEL_ENSAIO_SQL_OBRIGATORIO}=1: aqui a ausência do banco "
            "de ensaio é falha, não skip."
        )
    pytest.skip(recado)


@pytest.fixture
def ensaio_sql():
    """Provas que exigem o banco de ensaio pedem esta fixture."""
    exigir_ensaio_sql()


# ---------------------------------------------------------------------------
# Dublê de PostgREST para a pesquisa de preços
#
# Vive aqui, e não dentro de um arquivo de teste, porque a Fase 4 passou
# a precisar do mesmo dublê que a Fase 3 — e duas cópias de um dublê que
# emula chave única divergem calado, do mesmo jeito que duas cópias de um
# classificador de veredito.
#
# FRONTEIRA, dita de novo: isto NÃO prova isolamento, RLS nem unicidade.
# Emula os índices únicos apenas para exercitar o caminho de erro do
# Python. A prova de verdade roda contra um PostgreSQL em
# `tests/test_precos_fase3_rls.py`.
# ---------------------------------------------------------------------------
class TabelaPrecosFalsa:
    """
    Emulação mínima do PostgREST, com UMA responsabilidade extra: honrar
    a chave única da tabela, para que o caminho de corrida perdida do
    repositório seja exercitado de verdade.
    """

    def __init__(self, banco: list, nome: str, unicas: tuple):
        self.banco = banco
        self.nome = nome
        self.unicas = unicas
        self._acao = ""
        self._dados = None
        self._filtros: list[tuple] = []
        self._conflito = ""

    def insert(self, dados):
        self._acao, self._dados = "insert", dados
        return self

    def upsert(self, dados, on_conflict=""):
        self._acao, self._dados = "upsert", dados
        self._conflito = on_conflict
        return self

    def update(self, dados):
        self._acao, self._dados = "update", dados
        return self

    def select(self, *_):
        self._acao = "select"
        return self

    def eq(self, campo, valor):
        self._filtros.append((campo, valor))
        return self

    def or_(self, _expressao):
        return self

    def order(self, *_, **__):
        return self

    def limit(self, *_):
        return self

    # -- execução ---------------------------------------------------------
    def _chave(self, registro, colunas):
        return tuple(str(registro.get(c)) for c in colunas)

    def _colide(self, registro):
        for colunas in self.unicas:
            if any(registro.get(c) in (None, "") for c in colunas):
                continue   # índice parcial: chave vazia não colide
            alvo = self._chave(registro, colunas)
            for existente in self.banco:
                if self._chave(existente, colunas) == alvo:
                    return existente
        return None

    def _gravar(self, registro):
        linha = {"id": str(uuid.uuid4()), **registro}
        self.banco.append(linha)
        return linha

    def execute(self):
        if self._acao == "insert":
            if self._colide(self._dados) is not None:
                raise RuntimeError(
                    'duplicate key value violates unique constraint')
            return types.SimpleNamespace(data=[self._gravar(self._dados)])

        if self._acao == "upsert":
            registros = (self._dados if isinstance(self._dados, list)
                         else [self._dados])
            gravados = []
            colunas = tuple(self._conflito.split(",")) if self._conflito else ()
            for registro in registros:
                existente = (self._colide(registro) if colunas
                             else None)
                if existente is not None:
                    # Preserva o que já estava e não veio de novo — é o
                    # que o `on conflict do update` faz com as colunas
                    # de fora da lista.
                    existente.update(registro)
                    gravados.append(existente)
                else:
                    gravados.append(self._gravar(registro))
            return types.SimpleNamespace(data=gravados)

        filtrados = [r for r in self.banco
                     if all(str(r.get(c)) == str(v) for c, v in self._filtros)]
        if self._acao == "update":
            for r in filtrados:
                r.update(self._dados)
        return types.SimpleNamespace(data=filtrados)


class ClientePrecosFalso:
    # Só as chaves que a 0021 realmente cria.
    UNICAS = {
        "pesquisas_preco": (("tenant_id", "idempotency_key"),),
        "pesquisa_preco_itens": (("pesquisa_id", "numero"),),
        "pesquisa_preco_referencias": (("item_id", "fonte_id", "id_externo"),),
        "pesquisa_preco_eventos": (("pesquisa_id", "idempotency_key"),),
    }

    def __init__(self):
        self.tabelas: dict[str, list] = {}
        self.rpcs: list[tuple] = []

    def table(self, nome):
        return TabelaPrecosFalsa(self.tabelas.setdefault(nome, []), nome,
                       self.UNICAS.get(nome, ()))

    def rpc(self, nome, parametros):
        self.rpcs.append((nome, parametros))
        return types.SimpleNamespace(
            execute=lambda: types.SimpleNamespace(data=str(uuid.uuid4())))
