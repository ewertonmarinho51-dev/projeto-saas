"""
Persistência dos processos no Supabase (PostgreSQL).

Cada "processo" é uma linha na tabela public.processos contendo o
Formulário Matriz (jsonb), os documentos gerados/editados (jsonb), a
lista de aprovados e a etapa atual — permitindo salvar o andamento e
retomá-lo depois, de qualquer máquina.

Configuração (obrigatória apenas se quiser persistência):
    .streamlit/secrets.toml  ➜  SUPABASE_URL e SUPABASE_KEY
    ou variáveis de ambiente SUPABASE_URL / SUPABASE_KEY
A aplicação funciona normalmente sem Supabase — o painel "Processos
salvos" apenas fica desativado.
"""

import os
from datetime import datetime, timezone

import streamlit as st


class ErroBanco(Exception):
    """Erro de banco já traduzido em mensagem amigável para a interface."""


def _config() -> tuple[str, str]:
    url = os.getenv("SUPABASE_URL", "")
    chave = os.getenv("SUPABASE_KEY", "")
    try:
        url = str(st.secrets.get("SUPABASE_URL", url))
        chave = str(st.secrets.get("SUPABASE_KEY", chave))
    except Exception:
        pass  # sem arquivo secrets.toml — usa apenas o ambiente
    return url.strip(), chave.strip()


def disponivel() -> bool:
    """True se as credenciais do Supabase estiverem configuradas."""
    url, chave = _config()
    return bool(url and chave)


@st.cache_resource(show_spinner=False)
def _cliente():
    from supabase import create_client  # import tardio: app abre sem a lib

    url, chave = _config()
    return create_client(url, chave)


def _traduzir_erro(exc: Exception) -> ErroBanco:
    texto = str(exc).lower()
    if "connection" in texto or "timeout" in texto or "resolve" in texto:
        return ErroBanco(
            "Não foi possível conectar ao Supabase. Verifique sua internet "
            "e se o projeto está ativo (projetos gratuitos pausam por inatividade)."
        )
    if "jwt" in texto or "api key" in texto or "invalid" in texto and "key" in texto:
        return ErroBanco(
            "Credenciais do Supabase inválidas. Confira SUPABASE_URL e "
            "SUPABASE_KEY em .streamlit/secrets.toml."
        )
    return ErroBanco(f"Falha ao acessar o banco de dados: {exc}")


def salvar_processo(
    processo_id: str | None,
    dados: dict,
    documentos: dict,
    aprovados: set,
    etapa: int,
    usuario_id: str | None = None,
    secretaria_id: str | None = None,
) -> str:
    """Cria ou atualiza o processo e retorna seu id (uuid)."""
    registro = {
        "orgao": dados.get("orgao") or "",
        "objeto": dados.get("objeto") or "",
        "etapa": etapa,
        "dados": dados,
        "documentos": documentos,
        "aprovados": sorted(aprovados),
    }
    if usuario_id:
        registro["usuario_id"] = usuario_id
    if secretaria_id:
        # Fase 2 (flag_secretarias): vínculo institucional do processo.
        # Só chega preenchido com a flag ligada — que pressupõe a
        # migração 0007 aplicada (coluna existente).
        registro["secretaria_id"] = secretaria_id
    try:
        tabela = _cliente().table("processos")
        if processo_id:
            resposta = tabela.update(registro).eq("id", processo_id).execute()
            if resposta.data:
                return processo_id
            # id não encontrado (ex.: excluído em outra sessão) — insere novo
        resposta = tabela.insert(registro).execute()
        return resposta.data[0]["id"]
    except Exception as exc:  # noqa: BLE001 — traduzimos qualquer falha
        raise _traduzir_erro(exc) from exc


def listar_processos(limite: int = 20, usuario_id: str | None = None) -> list[dict]:
    """Processos mais recentes; com usuario_id, apenas os daquele usuário."""
    try:
        consulta = (
            _cliente()
            .table("processos")
            .select("id, orgao, objeto, etapa, atualizado_em")
        )
        if usuario_id:
            consulta = consulta.eq("usuario_id", usuario_id)
        resposta = (
            consulta.order("atualizado_em", desc=True).limit(limite).execute()
        )
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


# ---------------------------------------------------------------------------
# Revisões — ciclo de correção automática (migração 0008)
# ---------------------------------------------------------------------------
def criar_revisao(processo_id: str | None, snapshot: dict, relatorio: dict,
                  idempotency_key: str = "") -> dict:
    """
    Cria o job de revisão/correção com a versão 1 do bundle e o primeiro
    audit-report. Reexecução com a MESMA idempotency_key não cria novo
    job — devolve o existente (inclusive na corrida entre duas sessões,
    resolvida pelo índice único da migração 0008).
    """
    if idempotency_key:
        existente = obter_revisao_por_chave(idempotency_key)
        if existente:
            return existente
    registro = {
        "tenant_id": tenant_atual(),
        "processo_id": processo_id,
        "status": "REVIEW_QUEUED",
        "ciclo": 0,
        "versao_atual": snapshot.get("versao", 1),
        "bundle_hash": snapshot.get("hash", ""),
        "snapshots": [snapshot],
        "relatorios": [relatorio] if relatorio else [],
        "idempotency_key": idempotency_key,
    }
    try:
        resposta = _cliente().table("revisoes").insert(registro).execute()
        return resposta.data[0]
    except Exception as exc:  # noqa: BLE001
        texto = str(exc).lower()
        if idempotency_key and ("duplicate" in texto or "unique" in texto):
            existente = obter_revisao_por_chave(idempotency_key)
            if existente:
                return existente
        raise _traduzir_erro(exc) from exc


def obter_revisao_por_chave(idempotency_key: str) -> dict | None:
    try:
        resposta = (
            _cliente().table("revisoes").select("*")
            .eq("idempotency_key", idempotency_key).limit(1).execute()
        )
        return resposta.data[0] if resposta.data else None
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def obter_revisao(processo_id: str) -> dict | None:
    """Job de revisão mais recente do processo (para retomar a tela)."""
    try:
        resposta = (
            _cliente().table("revisoes").select("*")
            .eq("processo_id", processo_id)
            .order("criado_em", desc=True).limit(1).execute()
        )
        return resposta.data[0] if resposta.data else None
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def atualizar_revisao(revisao_id: str, **campos) -> dict:
    """Atualiza o job (status, ciclo, snapshots…) e carimba atualizado_em."""
    campos["atualizado_em"] = datetime.now(timezone.utc).isoformat()
    try:
        resposta = (
            _cliente().table("revisoes").update(campos)
            .eq("id", revisao_id).execute()
        )
        if not resposta.data:
            raise ErroBanco("Revisão não encontrada para atualizar.")
        return resposta.data[0]
    except ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


# ---------------------------------------------------------------------------
# Governança e qualidade documental (migração 0009 — pacote V5)
# ---------------------------------------------------------------------------
def salvar_fatos(fatos: list[dict]) -> list[dict]:
    """Insere fatos canônicos (novas versões; nunca sobrescreve)."""
    if not fatos:
        return []
    registros = [{**f, "tenant_id": tenant_atual()} for f in fatos]
    try:
        resposta = (
            _cliente().table("fatos_canonicos").insert(registros).execute()
        )
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_fatos(processo_id: str, apenas_vigentes: bool = True) -> list[dict]:
    try:
        consulta = (
            _cliente().table("fatos_canonicos").select("*")
            .eq("processo_id", processo_id)
        )
        if apenas_vigentes:
            consulta = consulta.neq("status", "substituido")
        resposta = consulta.order("path").order(
            "versao", desc=True).execute()
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def atualizar_fato(fato_id: str, **campos) -> None:
    """Transição de status (confirmar/disputar/substituir) — só isso."""
    permitidos = {"status", "confirmado_por", "confianca"}
    if extras := set(campos) - permitidos:
        raise ErroBanco(f"Campos de fato não atualizáveis: {sorted(extras)} "
                        "(mudar valor = nova versão, nunca edição).")
    try:
        _cliente().table("fatos_canonicos").update(campos).eq(
            "id", fato_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def registrar_decisao(registro: dict) -> dict:
    """Decisão é APPEND-ONLY: só insert (a 0009 não tem policy de update)."""
    try:
        resposta = _cliente().table("decisoes").insert(
            {**registro, "tenant_id": tenant_atual()}).execute()
        return resposta.data[0]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_decisoes(processo_id: str, limite: int = 50) -> list[dict]:
    try:
        resposta = (
            _cliente().table("decisoes").select("*")
            .eq("processo_id", processo_id)
            .order("criado_em", desc=True).limit(limite).execute()
        )
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_regras(apenas_publicadas: bool = True) -> list[dict]:
    """Regras do tenant atual + camada plataforma/nacional (tenant NULL)."""
    try:
        consulta = _cliente().table("regras_conhecimento").select("*")
        if apenas_publicadas:
            consulta = consulta.eq("status", "PUBLISHED")
        resposta = consulta.order("prioridade", desc=True).execute()
        registros = resposta.data or []
        # isolamento: só o próprio tenant ou regras de plataforma (NULL)
        atual = tenant_atual()
        return [r for r in registros
                if r.get("tenant_id") in (None, atual)]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def salvar_regra(registro: dict, regra_id: str | None = None) -> dict:
    """Insere regra nova ou atualiza um RASCUNHO (nunca publicada)."""
    try:
        tabela = _cliente().table("regras_conhecimento")
        if regra_id:
            atual = tabela.select("status").eq("id", regra_id).limit(1)\
                .execute()
            status = (atual.data[0]["status"] if atual.data else "")
            if status not in ("DRAFT", "UNDER_REVIEW"):
                raise ErroBanco(
                    "Versão publicada é imutável — derive uma nova versão.")
            resposta = tabela.update(registro).eq("id", regra_id).execute()
            return resposta.data[0]
        registro = {**registro, "tenant_id": registro.get(
            "tenant_id", tenant_atual())}
        resposta = tabela.insert(registro).execute()
        return resposta.data[0]
    except ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def salvar_score(registro: dict) -> None:
    """Score de qualidade — best-effort (observabilidade nunca derruba)."""
    if not disponivel():
        return
    try:
        _cliente().table("qualidade_scores").insert(
            {**registro, "tenant_id": tenant_atual()}).execute()
    except Exception:  # noqa: BLE001
        pass


def salvar_feedback(registro: dict) -> dict:
    try:
        resposta = _cliente().table("aprendizado_feedback").insert(
            {**registro, "tenant_id": tenant_atual()}).execute()
        return resposta.data[0]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_feedbacks(status: str | None = None,
                     limite: int = 100) -> list[dict]:
    """Feedbacks do tenant atual (curadoria) — isolamento aplicado."""
    try:
        consulta = _cliente().table("aprendizado_feedback").select("*")
        if status:
            consulta = consulta.eq("status", status)
        registros = (consulta.order("criado_em", desc=True)
                     .limit(limite).execute()).data or []
        atual = tenant_atual()
        return [r for r in registros if r.get("tenant_id") == atual]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def atualizar_feedback(feedback_id: str, **campos) -> None:
    """Transição de curadoria (status/curador/versão publicada)."""
    permitidos = {"status", "curador", "versao_publicada"}
    if extras := set(campos) - permitidos:
        raise ErroBanco(
            f"Campos de feedback não atualizáveis: {sorted(extras)} "
            "(conteúdo e evidências são imutáveis após a captura).")
    campos["atualizado_em"] = datetime.now(timezone.utc).isoformat()
    try:
        _cliente().table("aprendizado_feedback").update(campos).eq(
            "id", feedback_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


# ---------------------------------------------------------------------------
# Multi-tenant (Fase 1 — fundação; ver docs/matriz-compatibilidade.md)
# ---------------------------------------------------------------------------
# Tenant padrão = município atual (uuid fixo da migração 0006).
TENANT_PADRAO = "11111111-1111-1111-1111-111111111111"


def tenant_atual() -> str:
    """
    Tenant do contexto da sessão: derivado do VÍNCULO do usuário
    autenticado no login (auth.entrar) — nunca de campo livre vindo do
    frontend. Sem vínculo/login (modo aberto, CI): tenant padrão.
    """
    return st.session_state.get("tenant_id") or TENANT_PADRAO


def registrar_geracao_bd(registro: dict) -> None:
    """
    Persiste o registro técnico de geração em `geracoes` (migração 0006).
    Best-effort: auditoria NUNCA pode derrubar uma geração — sem banco ou
    sem a tabela (migração ainda não aplicada), falha em silêncio.
    """
    if not disponivel():
        return
    processo = registro.get("processo") or ""
    try:
        _cliente().table("geracoes").insert({
            "tenant_id": tenant_atual(),
            "processo_id": processo if "-" in str(processo) else None,
            "documento": registro.get("documento", ""),
            "motor": registro.get("motor", ""),
            "modelo": registro.get("modelo", ""),
            "duracao_s": registro.get("duracao_s"),
            "tokens_entrada": registro.get("tokens_entrada"),
            "tokens_saida": registro.get("tokens_saida"),
            "request_id": registro.get("request_id", ""),
            "status": registro.get("status", ""),
            "erro": registro.get("erro", ""),
            "fallback": bool(registro.get("fallback")),
        }).execute()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Configurações do aplicativo (chaves de IA definidas pelo administrador)
# ---------------------------------------------------------------------------
@st.cache_data(ttl=60, show_spinner=False)
def obter_config(chave: str) -> str:
    """Valor de config_app (cache 60s). Vazio se ausente/indisponível."""
    if not disponivel():
        return ""
    try:
        resposta = (
            _cliente().table("config_app").select("valor")
            .eq("chave", chave).limit(1).execute()
        )
        return (resposta.data[0]["valor"] if resposta.data else "").strip()
    except Exception:  # noqa: BLE001 — tabela ausente/erro: segue sem config
        return ""


def salvar_config(chave: str, valor: str) -> None:
    try:
        _cliente().table("config_app").upsert(
            {"chave": chave, "valor": valor.strip()}
        ).execute()
        obter_config.clear()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def flag_ativa(nome: str) -> bool:
    """
    Feature flag da matriz de compatibilidade: chave `flag_<nome>` em
    config_app. Default OFF (sem banco, sem registro ou valor falso);
    rollback de uma fase = desligar a flag.
    """
    return obter_config(f"flag_{nome}").lower() in ("1", "true", "on", "sim")


# ---------------------------------------------------------------------------
# Identidade visual por órgão (cabeçalho, rodapé, marca d'água)
# ---------------------------------------------------------------------------
def listar_orgaos() -> list[dict]:
    try:
        return (
            _cliente().table("config_orgaos").select("*")
            .order("padrao", desc=True).order("orgao").execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def salvar_orgao(registro: dict, orgao_id: str | None = None) -> None:
    """Cria/atualiza identidade visual; se padrao=True, desmarca as demais."""
    try:
        tabela = _cliente().table("config_orgaos")
        if registro.get("padrao"):
            tabela.update({"padrao": False}).neq(
                "id", orgao_id or "00000000-0000-0000-0000-000000000000"
            ).execute()
        if orgao_id:
            tabela.update(registro).eq("id", orgao_id).execute()
        else:
            resposta = tabela.insert(registro).execute()
            orgao_id = ((resposta.data or [{}])[0]).get("id")
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc
    _espelhar_orgao_em_secretaria(registro, orgao_id)


def _espelhar_orgao_em_secretaria(registro: dict, orgao_id: str | None) -> None:
    """
    Fase 2: mantém `secretarias` sincronizada com o legado `config_orgaos`
    (a aba Identidade visual continua sendo o único ponto de captura).
    Best-effort: antes da migração 0007 a tabela não existe e o espelho é
    silenciosamente ignorado — o fluxo antigo nunca quebra por causa dele.
    """
    if not orgao_id:
        return
    campos_visuais = (
        "cabecalho", "rodape", "marca_dagua", "cabecalho_img",
        "rodape_img", "marca_img", "cabecalho_pct", "rodape_pct",
    )
    espelho = {k: v for k, v in registro.items() if k in campos_visuais}
    if registro.get("orgao"):
        espelho["nome"] = registro["orgao"]
    if "padrao" in registro:
        espelho["padrao"] = bool(registro["padrao"])
    try:
        tabela = _cliente().table("secretarias")
        if espelho.get("padrao"):
            tabela.update({"padrao": False}).eq(
                "tenant_id", tenant_atual()
            ).execute()
        existentes = (
            tabela.select("id").eq("origem_orgao_id", orgao_id).limit(1).execute()
        )
        if existentes.data:
            tabela.update(espelho).eq("id", existentes.data[0]["id"]).execute()
        else:
            tabela.insert({
                **espelho,
                "nome": espelho.get("nome") or "Identidade sem nome",
                "tenant_id": tenant_atual(),
                "origem_orgao_id": orgao_id,
            }).execute()
    except Exception:  # noqa: BLE001 — migração 0007 ausente: segue sem espelho
        pass


# ---------------------------------------------------------------------------
# Secretarias (Fase 2 — unidades do município; ver src/contexto.py)
# ---------------------------------------------------------------------------
def listar_secretarias(incluir_inativas: bool = False) -> list[dict]:
    """Secretarias do tenant atual (padrão primeiro, depois por nome)."""
    try:
        consulta = (
            _cliente().table("secretarias").select("*")
            .eq("tenant_id", tenant_atual())
        )
        if not incluir_inativas:
            consulta = consulta.eq("ativo", True)
        return (
            consulta.order("padrao", desc=True).order("nome").execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def salvar_secretaria(registro: dict, secretaria_id: str | None = None) -> None:
    """Cria/atualiza secretaria; padrao=True desmarca as demais do tenant."""
    try:
        tabela = _cliente().table("secretarias")
        registro = dict(registro)
        if not secretaria_id:
            registro.setdefault("tenant_id", tenant_atual())
        if registro.get("padrao"):
            tabela.update({"padrao": False}).eq(
                "tenant_id", tenant_atual()
            ).execute()
        if secretaria_id:
            tabela.update(registro).eq("id", secretaria_id).execute()
        else:
            tabela.insert(registro).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def excluir_orgao(orgao_id: str) -> None:
    try:
        _cliente().table("config_orgaos").delete().eq("id", orgao_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def carregar_processo(processo_id: str) -> dict | None:
    try:
        resposta = (
            _cliente().table("processos").select("*").eq("id", processo_id).execute()
        )
        return resposta.data[0] if resposta.data else None
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def excluir_processo(processo_id: str) -> None:
    try:
        _cliente().table("processos").delete().eq("id", processo_id).execute()
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def rotulo_processo(proc: dict) -> str:
    """Rótulo curto e legível para o seletor de processos salvos."""
    quando = (proc.get("atualizado_em") or "")[:16].replace("T", " ")
    try:
        quando = datetime.fromisoformat(proc["atualizado_em"]).strftime("%d/%m/%Y %H:%M")
    except Exception:
        pass
    orgao = (proc.get("orgao") or "sem órgão")[:35]
    objeto = (proc.get("objeto") or "sem objeto")[:45]
    return f"{quando} — {orgao} — {objeto}"
