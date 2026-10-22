"""
Onde o arquivo gerado espera o download: Redis da rede interna, 30 min.

ADR-003, revisada no P04d. O relatório é REPRODUTÍVEL (o mesmo resultado
gera o mesmo identificador decisório) e a prova permanente da emissão já
mora no banco (`pesquisa_preco_emissoes`, 0029: hash do conteúdo e hash
do arquivo). O arquivo só precisa viver até a pessoa baixá-lo — que é o
que o Streamlit faz hoje, sem guardar nada. Um bucket privado traria uma
política de RLS a mais em `storage.objects`, uma URL assinada que pode
vazar em log, e retenção a decidir; fica para quando houver arquivo que
PRECISE ser guardado (P05, documentos).

Os metadados do download (nome, mimetype, hash) moram AQUI, gravados pelo
worker, e não em `api_jobs.resultado`, que o dono do job consegue
reescrever pelo PostgREST: quem baixa recebe o tipo e o nome que o worker
deu, nunca um que o usuário escolheu.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Protocol

VALIDADE_S = 30 * 60
# Teto do que se guarda: o analítico integral é o maior, e acima do
# LIMITE_DO_ANALITICO nem é gerado. Passou disto: o job falha com código,
# em vez de encher a memória do Redis.
LIMITE_BYTES = 50 * 1024 * 1024

# Só estes tipos saem pelo download, com estes nomes de extensão.
MIME_POR_EXTENSAO = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "zip": "application/zip",
}


class ArtefatoGrandeDemais(Exception):
    pass


@dataclass(frozen=True)
class Artefato:
    nome: str
    mimetype: str
    sha256: str
    conteudo: bytes

    @property
    def tamanho(self) -> int:
        return len(self.conteudo)


def montar(nome: str, conteudo: bytes) -> Artefato:
    """O artefato com mimetype decidido pela EXTENSÃO, de uma lista fechada."""
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if extensao not in MIME_POR_EXTENSAO:
        raise ValueError(f"extensão não servida: {extensao!r}")
    if len(conteudo) > LIMITE_BYTES:
        raise ArtefatoGrandeDemais(len(conteudo))
    return Artefato(nome=nome, mimetype=MIME_POR_EXTENSAO[extensao],
                    sha256=hashlib.sha256(conteudo).hexdigest(), conteudo=conteudo)


class Deposito(Protocol):
    def guardar(self, job_id: str, artefato: Artefato) -> float:
        """Guarda e devolve o instante (epoch) em que expira."""

    def ler(self, job_id: str) -> Artefato | None:
        """None se não existe ou já expirou."""


def _chave(job_id: str) -> tuple[str, str]:
    return f"govconect:artefato:{job_id}:meta", f"govconect:artefato:{job_id}:bytes"


class DepositoRedis:
    def __init__(self, redis_url: str, validade_s: int = VALIDADE_S) -> None:
        import redis

        self._r = redis.Redis.from_url(redis_url, socket_timeout=10)
        self._validade = validade_s

    def guardar(self, job_id: str, artefato: Artefato) -> float:
        meta, dados = _chave(job_id)
        corpo = json.dumps({"nome": artefato.nome, "mimetype": artefato.mimetype,
                            "sha256": artefato.sha256})
        with self._r.pipeline(transaction=True) as p:
            p.set(dados, artefato.conteudo, ex=self._validade)
            p.set(meta, corpo, ex=self._validade)
            p.execute()
        return time.time() + self._validade

    def ler(self, job_id: str) -> Artefato | None:
        meta, dados = _chave(job_id)
        corpo, conteudo = self._r.mget(meta, dados)
        if corpo is None or conteudo is None:
            return None
        m = json.loads(corpo)
        if hashlib.sha256(conteudo).hexdigest() != m["sha256"]:
            return None          # par incompleto ou corrompido: não entrega
        return Artefato(nome=m["nome"], mimetype=m["mimetype"], sha256=m["sha256"],
                        conteudo=conteudo)


class DepositoMemoria:
    """Para as provas sem Redis. Mesma validade, mesmo contrato."""

    def __init__(self, validade_s: int = VALIDADE_S, agora=time.time) -> None:
        self._itens: dict[str, tuple[float, Artefato]] = {}
        self._validade, self._agora = validade_s, agora

    def guardar(self, job_id: str, artefato: Artefato) -> float:
        expira = self._agora() + self._validade
        self._itens[job_id] = (expira, artefato)
        return expira

    def ler(self, job_id: str) -> Artefato | None:
        guardado = self._itens.get(job_id)
        if guardado is None or guardado[0] <= self._agora():
            return None
        return guardado[1]
