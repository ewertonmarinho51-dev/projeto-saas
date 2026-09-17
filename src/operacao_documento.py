"""Exclusão mútua e commit atômico da geração na instância Streamlit.

Só guarda controle efêmero. Conteúdo, aprovação e persistência continuam em
state. O lock real sobrevive a um rerun concorrente até o finally do gerador.
"""
from __future__ import annotations

import hashlib
import json
import threading
import uuid
from contextlib import contextmanager

_guarda = threading.Lock()
_ativas: set[str] = set()
ESTAGIOS = ("PREPARANDO", "GERANDO", "REVISANDO", "FINALIZANDO", "PRONTO")


class OperacaoEmCurso(RuntimeError):
    pass


class ContextoAlterado(RuntimeError):
    pass


def versao(sessao) -> str:
    valores = [sessao.get(k) for k in ("dados", "documentos", "edicoes_pendentes", "aprovados")]
    return hashlib.sha256(json.dumps(valores, ensure_ascii=False, sort_keys=True,
                                     default=lambda v: sorted(v) if isinstance(v, set) else str(v)).encode()).hexdigest()


def _chave(sessao) -> str:
    usuario = sessao.get("usuario") or {}
    processo = sessao.get("processo_id")
    if not processo:
        processo = sessao.setdefault("_geracao_sessao", uuid.uuid4().hex)
    return json.dumps([sessao.get("tenant_id"), usuario.get("id"),
                       usuario.get("secretaria_id"), processo], sort_keys=True)


def ocupada(sessao) -> bool:
    op = sessao.get("_operacao_documento") or {}
    with _guarda:
        return bool(op.get("chave") in _ativas)


@contextmanager
def executar(sessao, documento, request_id, progresso=lambda etapa: None):
    chave = _chave(sessao)
    with _guarda:
        if chave in _ativas:
            raise OperacaoEmCurso("Já existe um documento em elaboração neste processo.")
        if request_id == sessao.get("_ultima_geracao_concluida"):
            raise OperacaoEmCurso("Esta solicitação já foi concluída.")
        _ativas.add(chave)
    base = versao(sessao)
    op = {"chave": chave, "documento": documento, "request_id": request_id,
          "etapa": "PREPARANDO", "base": base}
    sessao["_operacao_documento"] = op

    def etapa(nome):
        if nome not in ESTAGIOS or ESTAGIOS.index(nome) < ESTAGIOS.index(op["etapa"]):
            raise ValueError("Transição de geração inválida")
        op["etapa"] = nome
        progresso(nome)

    try:
        progresso("PREPARANDO")
        yield etapa, base
        sessao["_ultima_geracao_concluida"] = request_id
    except BaseException:
        op["etapa"] = "ERRO"
        raise
    finally:
        with _guarda:
            _ativas.discard(chave)


def confirmar_versao(sessao, base):
    if versao(sessao) != base:
        raise ContextoAlterado("O processo foi alterado durante a elaboração. Revise antes de tentar novamente.")
