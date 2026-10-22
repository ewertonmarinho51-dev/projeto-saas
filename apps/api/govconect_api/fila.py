"""
Fila das tarefas longas: Celery sobre Redis (ADR-004).

    celery -A govconect_api.fila:celery worker --concurrency=1 --loglevel=INFO

* `acks_late` + `reject_on_worker_lost`: worker que morre no meio devolve
  o aviso à fila; o próximo retoma do estado dos itens no banco.
* `prefetch=1`, concorrência 1 no VPS (ADR-007): medir antes de subir.
* Retry só para erro transitório (banco/rede), com backoff e jitter, no
  máximo 3; depois disso o job fica `failed` com código — é a "fila de
  mortos" lógica, consultável e reprocessável com um novo pedido.
* O token do usuário nunca aparece em log nem em painel (`argsrepr`), e o
  aviso expira junto com ele (`expires`): aviso velho não acorda worker
  com credencial vencida.
"""

from __future__ import annotations

import logging
import random
import time

from celery import Celery

from .coleta import (ErroTransitorio, atualizar_job, expiracao_do_token,
                     processar_job, _agora_iso)
from .config import carregar
from .erros import ErroApi
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

NOME_TAREFA = "govconect.coletar_precos"
NOME_TAREFA_RELATORIO = "govconect.emitir_relatorio"
TAREFAS = {"coleta": NOME_TAREFA, "relatorio": NOME_TAREFA_RELATORIO}
MAX_TENTATIVAS = 3


def _criar_celery(redis_url: str) -> Celery:
    app = Celery("govconect", broker=redis_url or "redis://indisponivel.invalid:6379/0")
    app.conf.update(
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_time_limit=3600,
        task_soft_time_limit=3540,
        task_serializer="json",
        accept_content=["json"],
        task_ignore_result=True,          # o resultado é o job no banco
        broker_connection_retry_on_startup=True,
        broker_transport_options={"visibility_timeout": 3700},
        worker_hijack_root_logger=False,
    )
    return app


_config = carregar()
celery = _criar_celery(_config.redis_url)


class FilaCelery:
    def __init__(self, app: Celery = celery) -> None:
        self._app = app

    def enfileirar(self, *, job_id: str, token: str, tenant_id: str,
                   auth_user_id: str, secretaria_id: str | None,
                   usuario_id: str = "", tarefa: str = "coleta") -> None:
        expira = expiracao_do_token(token)
        validade = max(1, int(expira - time.time())) if expira else 600
        args = [job_id, token, tenant_id, auth_user_id, secretaria_id]
        if tarefa == "relatorio":
            args.append(usuario_id)
        self._app.send_task(
            TAREFAS[tarefa], args=args,
            argsrepr=f"('{job_id}', '<token>', '{tenant_id}')", kwargsrepr="{}",
            expires=validade)


def _espera(tentativa: int) -> int:
    return min(60, 2 ** tentativa * 5) + random.randint(0, 5)


@celery.task(name=NOME_TAREFA, bind=True, max_retries=MAX_TENTATIVAS)
def coletar_precos(self, job_id: str, token: str, tenant_id: str, auth_user_id: str,
                   secretaria_id: str | None) -> str:
    config = carregar()
    from src.streamlit_opcional import configurar_supabase

    configurar_supabase(config.supabase_url, config.supabase_chave_publica)
    rest = ClienteRest(config.supabase_url, config.supabase_chave_publica)
    fontes = [] if config.fontes_coleta == "nenhuma" else None
    try:
        return processar_job(job_id=job_id, token=token, tenant_id=tenant_id,
                             auth_user_id=auth_user_id, secretaria_id=secretaria_id,
                             rest=rest, fontes=fontes)
    except (ErroTransitorio, ErroApi) as exc:
        if isinstance(exc, ErroApi) and exc.status == 401:
            # Token vencido no caminho: não há com que escrever no job.
            _log.warning("job_token_vencido job=%s", job_id)
            return "failed"
        if self.request.retries >= MAX_TENTATIVAS:
            try:
                atualizar_job(rest, token, job_id, estado="failed",
                              erro_codigo="DATABASE_UNAVAILABLE", concluido_em=_agora_iso())
            except Exception:  # noqa: BLE001
                _log.error("job_sem_registro_de_falha job=%s", job_id)
            return "failed"
        raise self.retry(exc=exc, countdown=_espera(self.request.retries)) from None
    finally:
        rest.fechar()


@celery.task(name=NOME_TAREFA_RELATORIO, bind=True, max_retries=MAX_TENTATIVAS)
def emitir_relatorio(self, job_id: str, token: str, tenant_id: str, auth_user_id: str,
                     secretaria_id: str | None, usuario_id: str = "") -> str:
    """Gera um relatório (P04d). O arquivo fica no MESMO Redis da fila,
    30 min; a prova da emissão fica no banco (0029)."""
    from .artefatos import DepositoRedis
    from .relatorios import processar_relatorio
    from src.streamlit_opcional import configurar_supabase

    config = carregar()
    configurar_supabase(config.supabase_url, config.supabase_chave_publica)
    rest = ClienteRest(config.supabase_url, config.supabase_chave_publica)
    try:
        return processar_relatorio(job_id=job_id, token=token, tenant_id=tenant_id,
                                   auth_user_id=auth_user_id, secretaria_id=secretaria_id,
                                   usuario_id=usuario_id, rest=rest,
                                   deposito=DepositoRedis(config.redis_url))
    except (ErroTransitorio, ErroApi) as exc:
        if isinstance(exc, ErroApi) and exc.status == 401:
            _log.warning("job_token_vencido job=%s", job_id)
            return "failed"
        if self.request.retries >= MAX_TENTATIVAS:
            try:
                atualizar_job(rest, token, job_id, estado="failed",
                              erro_codigo="DATABASE_UNAVAILABLE", concluido_em=_agora_iso())
            except Exception:  # noqa: BLE001
                _log.error("job_sem_registro_de_falha job=%s", job_id)
            return "failed"
        raise self.retry(exc=exc, countdown=_espera(self.request.retries)) from None
    finally:
        rest.fechar()
