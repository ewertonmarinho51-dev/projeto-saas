"""
Logs estruturados e métricas RED (ADR-005, P06).

**Log**: uma linha JSON por evento, com `request_id`. Por requisição:
método, ROTA (o modelo, `/api/v1/precos/pesquisas/{pesquisa_id}`, nunca
o caminho com ids nem a query), status, duração e o município
PSEUDONIMIZADO. Nunca corpo, token, cabeçalho ou texto de exceção (P01
já registrava só o tipo da exceção).

**Métricas**: contadores em memória, no formato de texto do Prometheus,
em `GET /health/metrics`. A API não é pública (o Caddy não tem rota para
ela), então só a rede interna lê. Sem dependência nova: são poucos
contadores, e um processo (ADR-007).

    govconect_requisicoes_total{metodo,rota,classe}   taxa e erros (R, E)
    govconect_duracao_segundos_bucket{rota,le}         duração (D)
    govconect_jobs_total{tipo,estado}                  fim de cada job
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from datetime import datetime, timezone

_PADRAO = logging.LogRecord("x", 0, "", 0, "", None, None).__dict__.keys()
LIMITES_S = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def pseudonimo(tenant_id: str | None) -> str:
    """Município no log sem o id: o suficiente para agrupar, não para juntar
    com outra base sem a tabela de tenants."""
    if not tenant_id:
        return ""
    return hashlib.sha256(f"govconect:{tenant_id}".encode()).hexdigest()[:12]


class FormatoJson(logging.Formatter):
    """Uma linha JSON. Campos extras vêm de `extra={...}` e passam por uma
    lista fechada de tipos simples — objeto arbitrário não vai ao log."""

    def format(self, registro: logging.LogRecord) -> str:
        linha = {
            "ts": datetime.fromtimestamp(registro.created, timezone.utc).isoformat(timespec="milliseconds"),
            "nivel": registro.levelname.lower(),
            "logger": registro.name,
            "msg": registro.getMessage()[:2000],
        }
        for chave, valor in registro.__dict__.items():
            if chave not in _PADRAO and not chave.startswith("_") and \
                    isinstance(valor, (str, int, float, bool)) and chave not in linha:
                linha[chave] = valor[:500] if isinstance(valor, str) else valor
        if registro.exc_info and registro.exc_info[0] is not None:
            # O TIPO, nunca o texto: mensagem de exceção do PostgREST e do
            # httpx carrega URL, chave e corpo.
            linha["excecao"] = registro.exc_info[0].__name__
        return json.dumps(linha, ensure_ascii=False)


def configurar_logs(nivel: str = "INFO") -> None:
    """Raiz em JSON no stdout. Idempotente (a API e o worker chamam)."""
    raiz = logging.getLogger()
    if any(getattr(h, "_govconect", False) for h in raiz.handlers):
        return
    saida = logging.StreamHandler()
    saida.setFormatter(FormatoJson())
    saida._govconect = True  # type: ignore[attr-defined]
    raiz.handlers = [saida]
    raiz.setLevel(nivel)
    # O log de acesso do uvicorn repete o caminho com ids e query; o nosso
    # (`requisicao`) substitui.
    logging.getLogger("uvicorn.access").disabled = True


class Metricas:
    def __init__(self) -> None:
        self._trava = threading.Lock()
        self._requisicoes: dict[tuple[str, str, str], int] = {}
        self._buckets: dict[tuple[str, float], int] = {}
        self._soma: dict[str, float] = {}
        self._contagem: dict[str, int] = {}
        self._jobs: dict[tuple[str, str], int] = {}

    def requisicao(self, *, metodo: str, rota: str, status: int, duracao_s: float) -> None:
        classe = f"{status // 100}xx"
        with self._trava:
            chave = (metodo, rota, classe)
            self._requisicoes[chave] = self._requisicoes.get(chave, 0) + 1
            for limite in LIMITES_S:
                if duracao_s <= limite:
                    self._buckets[(rota, limite)] = self._buckets.get((rota, limite), 0) + 1
            self._soma[rota] = self._soma.get(rota, 0.0) + duracao_s
            self._contagem[rota] = self._contagem.get(rota, 0) + 1

    def job(self, *, tipo: str, estado: str) -> None:
        with self._trava:
            self._jobs[(tipo, estado)] = self._jobs.get((tipo, estado), 0) + 1

    def texto(self) -> str:
        def rotulos(**r) -> str:
            return "{" + ",".join(f'{k}="{_escapar(v)}"' for k, v in r.items()) + "}"

        linhas = ["# TYPE govconect_requisicoes_total counter"]
        with self._trava:
            for (metodo, rota, classe), n in sorted(self._requisicoes.items()):
                linhas.append(f"govconect_requisicoes_total{rotulos(metodo=metodo, rota=rota, classe=classe)} {n}")
            linhas.append("# TYPE govconect_duracao_segundos histogram")
            for rota in sorted(self._contagem):
                for limite in LIMITES_S:
                    n = self._buckets.get((rota, limite), 0)
                    linhas.append(f"govconect_duracao_segundos_bucket{rotulos(rota=rota, le=limite)} {n}")
                linhas.append(f"govconect_duracao_segundos_bucket{rotulos(rota=rota, le='+Inf')} {self._contagem[rota]}")
                linhas.append(f"govconect_duracao_segundos_sum{rotulos(rota=rota)} {self._soma[rota]:.6f}")
                linhas.append(f"govconect_duracao_segundos_count{rotulos(rota=rota)} {self._contagem[rota]}")
            linhas.append("# TYPE govconect_jobs_total counter")
            for (tipo, estado), n in sorted(self._jobs.items()):
                linhas.append(f"govconect_jobs_total{rotulos(tipo=tipo, estado=estado)} {n}")
        return "\n".join(linhas) + "\n"


def _escapar(valor) -> str:
    return str(valor).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


# Uma por processo: a API e o worker são processos separados, e cada um
# conta o que é seu (o worker loga seus jobs; a API, suas requisições).
METRICAS = Metricas()
