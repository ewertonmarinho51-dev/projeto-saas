"""
Limite de requisições por usuário — em memória, por processo.

É o limite INICIAL (matriz 111, item 1). Vale enquanto a API roda num
processo só, que é o desenho do VPS (ADR-007). Com réplicas, cada uma
contaria a sua parte e o limite efetivo multiplicaria; aí ele vai para o
Redis, que entra com a fila no P04. Escrito para essa troca não mexer em
quem chama: `Limitador.consumir(chave)` é a interface inteira.
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import Request

from .erros import ErroApi

JANELA_S = 60.0


class Limitador:
    def __init__(self, por_minuto: int, relogio=time.monotonic) -> None:
        self._limite = por_minuto
        self._relogio = relogio
        self._eventos: dict[str, deque[float]] = {}
        self._trava = threading.Lock()

    def consumir(self, chave: str) -> float:
        """0 se cabe; senão, segundos até caber (vai no Retry-After)."""
        agora = self._relogio()
        with self._trava:
            fila = self._eventos.setdefault(chave, deque())
            while fila and fila[0] <= agora - JANELA_S:
                fila.popleft()
            if len(fila) >= self._limite:
                return fila[0] + JANELA_S - agora
            fila.append(agora)
            # Varredura barata das chaves ociosas: sem ela, cada usuário
            # que passou um dia por aqui ficaria na memória para sempre.
            if len(self._eventos) > 10_000:
                for k in [k for k, f in self._eventos.items()
                          if not f or f[-1] <= agora - JANELA_S]:
                    del self._eventos[k]
            return 0.0


def aplicar_limite(request: Request) -> None:
    """Dependência do roteador v1, DEPOIS da identidade: a chave é o
    usuário verificado, não o IP — atrás do Caddy todo mundo teria o IP
    do proxy, e um município inteiro dividiria a mesma cota."""
    identidade = getattr(request.state, "identidade", None)
    limitador: Limitador | None = getattr(request.app.state, "limitador", None)
    if identidade is None or limitador is None:
        return
    espera = limitador.consumir(identidade.auth_user_id)
    if espera > 0:
        raise ErroApi(429, "RATE_LIMITED", "Limite de requisições excedido",
                      {"Retry-After": str(max(1, math.ceil(espera)))})
