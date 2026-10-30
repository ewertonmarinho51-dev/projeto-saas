"""
Credencial documental do WordCraft Workspace (ADR-011).

O commit de uma revisão nativa e a emissão oficial vão a RPCs que o banco
concede SÓ a `service_role` (`documento_editor_checkpoint`, `_aprovar`,
`_fontes_aprovacao`, `_emitir`): elas confiam nas claims e no build do motor que o
servidor declara, e por isso não podem ser chamadas pelo navegador nem com
o JWT do usuário. A ADR-002 tirou a chave de servidor da API; a ADR-010
abriu a primeira exceção estreita. Esta é a segunda, aceita pelo operador, e
só vale com `GOVCONECT_DOCUMENTOS_ESCRITA_KEY` provisionada.

Estreita quer dizer, mecanicamente:

* o cliente de servidor só existe aqui, e só durante `escrita_documental`;
* ele chama SÓ as RPCs de `RPCS` — nada de `.table()`, nada de outra RPC.
  Tudo o mais que o domínio pedir no meio do commit (cabeça do documento,
  processo, catálogo institucional) vai com o JWT do usuário e o RLS decide;
* as RPCs ainda conferem, com as claims verificadas pelo
  `documento_editor_contexto` do PRÓPRIO usuário, o vínculo, o processo e a
  competência — a credencial não concede acesso a documento nenhum.
"""

from __future__ import annotations

from contextlib import contextmanager

from src import db

RPCS = frozenset({
    "documento_editor_checkpoint",
    "documento_editor_aprovar",
    "documento_editor_fontes_aprovacao",
    "documento_editor_emitir",
})


class EscritaIndisponivel(RuntimeError):
    """Sem credencial documental: nada foi enviado ao banco."""


class ClienteDocumental:
    """Interface mínima que `DocumentoService` usa de `db._cliente()`."""

    def __init__(self, usuario, servidor) -> None:
        self._usuario = usuario
        self._servidor = servidor

    def rpc(self, nome: str, parametros: dict | None = None, *args, **kwargs):
        destino = self._servidor if nome in RPCS else self._usuario
        return destino.rpc(nome, parametros or {}, *args, **kwargs)

    def table(self, nome: str):
        return self._usuario.table(nome)

    def __getattr__(self, nome: str):
        # Qualquer outra porta (storage, auth, postgrest cru) não existe aqui.
        raise AttributeError(nome)


def _cliente_de_servidor(url: str, chave: str):
    from supabase import create_client  # import tardio: só quem escreve paga

    return create_client(url, chave)


@contextmanager
def escrita_documental(url: str, chave: str, *, fabrica=_cliente_de_servidor):
    """Abre a janela da credencial documental para UMA operação.

    Exige a sessão da requisição já aberta (`sessao_da_requisicao`): sem o
    JWT do usuário não há com que fazer as leituras do commit, e a escrita
    recusa antes de criar o cliente de servidor.
    """
    if not (url and chave):
        raise EscritaIndisponivel("credencial documental não provisionada")
    usuario = db.cliente_do_usuario()
    if usuario is None:
        raise EscritaIndisponivel("sem sessão do usuário")
    marca = db.CLIENTE_DOCUMENTAL.set(ClienteDocumental(usuario, fabrica(url, chave)))
    try:
        yield
    finally:
        db.CLIENTE_DOCUMENTAL.reset(marca)
