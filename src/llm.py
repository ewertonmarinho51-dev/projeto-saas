"""
Camada de integração com a IA.

Motores, em ordem de prioridade:
  1. OpenAI (PRINCIPAL) — chave em OPENAI_API_KEY (secrets/env/sidebar);
  2. Google Gemini (fallback) — chave em GOOGLE_API_KEY;
  3. Modo Demonstração — minutas-esqueleto offline, sem chave alguma.

Se o motor principal falhar após as retentativas e houver chave do
Gemini, a geração cai automaticamente para o fallback (com aviso na
interface). Todos os erros de API (timeout, chave inválida, cota,
bloqueio de conteúdo) viram mensagens amigáveis.
"""

import logging
import os
import time
from datetime import datetime

import streamlit as st

from .config import (
    API_BACKOFF_BASE,
    API_TENTATIVAS,
    API_TIMEOUT_SEGUNDOS,
    DOCUMENTOS,
    GEMINI_MODEL_PADRAO,
    GEMINI_MODELOS_FALLBACK,
    OPENAI_MODEL_PADRAO,
    OPENAI_MODELOS_FALLBACK,
)
from .prompts import formatar_dados_formulario, montar_prompt


class ErroGeracaoIA(Exception):
    """Erro de geração já traduzido em mensagem amigável para a interface.

    `detalhe` guarda o erro técnico bruto da API (motor + tipo + mensagem)
    para exibição opcional na interface — é o que permite diagnosticar a
    causa real (401, 404, 429, região bloqueada etc.).
    """

    def __init__(self, mensagem: str, detalhe: str = ""):
        super().__init__(mensagem)
        self.detalhe = detalhe


# ---------------------------------------------------------------------------
# Registro técnico de geração (auditoria) — NUNCA grava chave de API nem o
# conteúdo dos documentos; apenas metadados sanitizados.
# ---------------------------------------------------------------------------
_log = logging.getLogger("govdocs.geracao")

# metadados da última chamada bem-sucedida (tokens/modelo/id), preenchidos
# pelos executores de chamada de cada motor
_ultimo_uso: dict = {}


def registrar_geracao(doc_key: str, motor: str, inicio: float, status: str,
                      erro: str = "", fallback: bool = False,
                      processo_id: str | None = None) -> dict:
    """Grava o registro no log do servidor e no histórico da sessão."""
    registro = {
        "quando": datetime.now().isoformat(timespec="seconds"),
        "processo": processo_id or st.session_state.get("processo_id") or "(novo)",
        "documento": doc_key,
        "motor": motor,
        "modelo": _ultimo_uso.get("modelo", ""),
        "duracao_s": round(time.time() - inicio, 1),
        "tokens_entrada": _ultimo_uso.get("tokens_entrada"),
        "tokens_saida": _ultimo_uso.get("tokens_saida"),
        "request_id": _ultimo_uso.get("request_id", ""),
        "status": status,                      # "ok" | "falha"
        "erro": (erro or "")[:300],            # sanitizado (sem chave/conteúdo)
        "fallback": fallback,
    }
    _log.info("geracao %s", registro)
    historico = st.session_state.setdefault("registro_geracoes", [])
    historico.append(registro)
    del historico[:-40]  # guarda os 40 últimos
    # Persistência (tabela `geracoes`, migração 0006) — best-effort: a
    # auditoria nunca pode derrubar a geração.
    from . import db

    db.registrar_geracao_bd(registro)
    return registro


def _ler_chave(nome_secret: str, chave_sidebar: str) -> str:
    """
    Busca uma chave na ordem:
    painel do administrador (banco) > sessão > secrets.toml > ambiente.
    """
    from . import db

    valor = db.obter_config(nome_secret)
    if valor:
        return valor
    # chave_sidebar vazio (ex.: OPENAI_MODEL/GEMINI_MODEL não têm campo na
    # barra lateral) — pular a sessão. st.session_state.get("") lança
    # StreamlitAPIException, o que fazia AS DUAS engines falharem ao ler o modelo.
    valor = st.session_state.get(chave_sidebar, "").strip() if chave_sidebar else ""
    if valor:
        return valor
    try:
        if nome_secret in st.secrets:
            return str(st.secrets[nome_secret]).strip()
    except Exception:
        pass  # sem arquivo secrets.toml — segue para a variável de ambiente
    return os.getenv(nome_secret, "").strip()


def origem_chave(nome_secret: str, chave_sidebar: str) -> str:
    """
    De ONDE vem a chave ativa (mesma ordem de prioridade de _ler_chave):
    'painel do administrador' | 'barra lateral' | 'secrets.toml' |
    'variável de ambiente' | '' (não configurada). Usado no diagnóstico do
    painel admin — uma chave antiga salva no painel sobrepõe o secrets.toml.
    """
    from . import db

    if db.obter_config(nome_secret):
        return "painel do administrador"
    if chave_sidebar and st.session_state.get(chave_sidebar, "").strip():
        return "barra lateral"
    try:
        if nome_secret in st.secrets and str(st.secrets[nome_secret]).strip():
            return "secrets.toml"
    except Exception:
        pass
    if os.getenv(nome_secret, "").strip():
        return "variável de ambiente"
    return ""


def obter_openai_key() -> str:
    """Chave do motor principal (OpenAI)."""
    return _ler_chave("OPENAI_API_KEY", "openai_key_manual")


def obter_api_key() -> str:
    """Chave do fallback (Google Gemini) — também usada nos embeddings."""
    return _ler_chave("GOOGLE_API_KEY", "api_key_manual")


def motor_ativo() -> str:
    """'openai' | 'gemini' | '' — qual motor será usado na próxima geração."""
    if obter_openai_key():
        return "openai"
    if obter_api_key():
        return "gemini"
    return ""


def _obter_modelo() -> str:
    return _ler_chave("GEMINI_MODEL", "") or GEMINI_MODEL_PADRAO


def _obter_modelo_openai() -> str:
    return _ler_chave("OPENAI_MODEL", "") or OPENAI_MODEL_PADRAO


def _dedup(modelos: list[str]) -> list[str]:
    vistos, saida = set(), []
    for m in modelos:
        m = (m or "").strip()
        if m and m not in vistos:
            vistos.add(m)
            saida.append(m)
    return saida


def _modelos_openai() -> list[str]:
    """Modelo configurado + alternativas amplamente disponíveis."""
    return _dedup([_obter_modelo_openai(), *OPENAI_MODELOS_FALLBACK])


def _modelos_gemini() -> list[str]:
    return _dedup([_obter_modelo(), *GEMINI_MODELOS_FALLBACK])


def _e_erro_de_modelo(exc: Exception) -> bool:
    """True quando o modelo não existe/sem acesso — vale tentar outro modelo."""
    t = f"{type(exc).__name__}: {exc}".lower()
    return (
        "model_not_found" in t or "does not exist" in t or "not found" in t
        or "unsupported" in t or "unknown model" in t
        or ("model" in t and "404" in t)
    )


def _traduzir_erro(exc: Exception, motor: str = "") -> str:
    """
    Converte exceções técnicas da API em mensagens amigáveis.

    `motor` ('openai' | 'gemini') deixa a mensagem apontar a variável e o
    modelo corretos de cada engine.
    """
    texto = f"{type(exc).__name__}: {exc}".lower()
    if motor == "openai":
        rotulo, var_chave, var_modelo, painel = (
            "OpenAI", "OPENAI_API_KEY", "OPENAI_MODEL",
            "platform.openai.com (chave, faturamento/billing e modelo)")
    elif motor == "gemini":
        rotulo, var_chave, var_modelo, painel = (
            "Google Gemini", "GOOGLE_API_KEY", "GEMINI_MODEL",
            "aistudio.google.com (chave e cota)")
    else:
        rotulo, var_chave, var_modelo, painel = (
            "IA", "OPENAI_API_KEY/GOOGLE_API_KEY", "OPENAI_MODEL/GEMINI_MODEL",
            "o painel do provedor")

    if "deadline" in texto or "timeout" in texto or "timed out" in texto:
        return (
            f"{rotulo}: demorou demais para responder (timeout). "
            "Tente novamente em instantes — seus dados não foram perdidos."
        )
    if ("api key" in texto or "api_key" in texto or "invalid_api_key" in texto
            or "incorrect api key" in texto or "unauthorized" in texto
            or "permission" in texto or "401" in texto or "403" in texto):
        return (
            f"{rotulo}: chave de API inválida, expirada ou sem permissão "
            f"(verifique {var_chave} no painel do administrador, em "
            f".streamlit/secrets.toml ou na barra lateral)."
        )
    if ("quota" in texto or "insufficient_quota" in texto or "billing" in texto
            or ("resource" in texto and "exhausted" in texto) or "429" in texto
            or "rate limit" in texto):
        return (
            f"{rotulo}: limite de uso/cota atingido ou sem crédito de "
            f"faturamento. Verifique {painel}."
        )
    if "vazi" in texto or "finish_reason=length" in texto:
        return (
            f"{rotulo}: o modelo devolveu resposta vazia (provável limite de "
            "tokens ou raciocínio consumindo o orçamento). Tente um modelo "
            f"não-raciocínio em {var_modelo} (ex.: gpt-4o-mini) ou reduza o "
            "tamanho da planilha/prompt."
        )
    if "safety" in texto or "blocked" in texto:
        return (
            f"{rotulo}: a resposta foi bloqueada pelos filtros de segurança "
            "do modelo. Revise o texto do formulário e tente novamente."
        )
    if ("not found" in texto or "does not exist" in texto or "model_not_found" in texto
            or "unsupported" in texto or "404" in texto):
        return (
            f"{rotulo}: modelo não encontrado ou sem acesso na sua conta. "
            f"Ajuste {var_modelo} para um modelo disponível "
            "(ex.: gpt-4o-mini / gemini-1.5-flash)."
        )
    return f"{rotulo}: falha na comunicação — {type(exc).__name__}: {exc}"


class _RespostaVazia(Exception):
    """O modelo respondeu sem conteúdo (ex.: raciocínio consumiu os tokens).
    Sinaliza que vale a pena tentar o próximo modelo da lista."""


def _params_modelo_openai(modelo: str) -> dict:
    """
    Parâmetros extras por família de modelo. Modelos de raciocínio consomem
    tokens 'pensando' antes de escrever — com prompt grande podem gastar todo
    o orçamento no raciocínio e devolver conteúdo VAZIO. Usamos esforço baixo
    (qualidade com orçamento p/ texto); se ainda vier vazio, a troca de
    modelo automática assume.
    """
    ml = modelo.lower()
    if ml.startswith("gpt-5"):
        return {"reasoning_effort": "low"}
    if ml.startswith(("o1", "o3", "o4")):
        return {"reasoning_effort": "low"}
    return {}


def _trocar_de_modelo(exc: Exception) -> bool:
    """Erros em que vale tentar o próximo modelo: inexistente/sem acesso, ou
    resposta vazia (típico de modelo de raciocínio sem tokens p/ o texto)."""
    return isinstance(exc, _RespostaVazia) or _e_erro_de_modelo(exc)


def _openai_uma_chamada(cliente, modelo: str, system_prompt: str,
                        user_prompt: str) -> str:
    """Uma chamada ao modelo indicado, com retentativas/backoff em falhas."""
    ultima_excecao: Exception | None = None
    extra = _params_modelo_openai(modelo)
    for tentativa in range(1, API_TENTATIVAS + 1):
        try:
            resposta = cliente.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=16384,
                **extra,
            )
            escolha = resposta.choices[0]
            texto = (escolha.message.content or "").strip()
            if not texto:
                motivo = getattr(escolha, "finish_reason", "?")
                raise _RespostaVazia(f"conteúdo vazio (finish_reason={motivo})")
            uso = getattr(resposta, "usage", None)
            _ultimo_uso.update(
                modelo=modelo,
                tokens_entrada=getattr(uso, "prompt_tokens", None),
                tokens_saida=getattr(uso, "completion_tokens", None),
                request_id=getattr(resposta, "id", "") or "",
            )
            return texto
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            # Erro de modelo / resposta vazia não melhoram com retry no mesmo
            # modelo — sobe já para trocar de modelo.
            if _trocar_de_modelo(exc):
                raise
            if tentativa < API_TENTATIVAS:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ultima_excecao  # type: ignore[misc]


def _chamar_openai(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """
    Motor principal: OpenAI. Tenta o modelo configurado e, se ele não existir,
    não tiver acesso, ou devolver resposta vazia (comum em modelos de
    raciocínio), cai automaticamente para modelos alternativos amplamente
    disponíveis (gpt-4o-mini etc.).
    """
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from openai import OpenAI

    cliente = OpenAI(api_key=api_key, timeout=API_TIMEOUT_SEGUNDOS, max_retries=0)
    modelos = _modelos_openai()
    ultima_excecao: Exception | None = None
    tentados: list[str] = []
    for i, modelo in enumerate(modelos):
        tentados.append(modelo)
        try:
            return _openai_uma_chamada(cliente, modelo, system_prompt, user_prompt)
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            # Troca de modelo em erro de modelo OU resposta vazia. Chave
            # inválida/cota falha igual em qualquer modelo → aborta.
            if _trocar_de_modelo(exc) and i < len(modelos) - 1:
                continue
            break
    raise ErroGeracaoIA(
        _traduzir_erro(ultima_excecao, "openai"),
        detalhe=f"[OpenAI · tentados: {', '.join(tentados)}] "
                f"{type(ultima_excecao).__name__}: {ultima_excecao}",
    )


def _gemini_uma_chamada(cliente, types, modelo: str, system_prompt: str,
                        user_prompt: str) -> str:
    """Uma chamada ao modelo indicado, com retentativas/backoff em falhas."""
    ultima_excecao: Exception | None = None
    for tentativa in range(1, API_TENTATIVAS + 1):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=16384,
                ),
            )
            texto = (resposta.text or "").strip()
            if not texto:
                raise _RespostaVazia("conteúdo vazio")
            uso = getattr(resposta, "usage_metadata", None)
            _ultimo_uso.update(
                modelo=modelo,
                tokens_entrada=getattr(uso, "prompt_token_count", None),
                tokens_saida=getattr(uso, "candidates_token_count", None),
                request_id=getattr(resposta, "response_id", "") or "",
            )
            return texto
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            if _trocar_de_modelo(exc):
                raise
            if tentativa < API_TENTATIVAS:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ultima_excecao  # type: ignore[misc]


def _chamar_gemini(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """
    Fallback: Gemini. Tenta o modelo configurado e, se não existir/sem
    acesso, cai para modelos alternativos (gemini-1.5-flash etc.).
    """
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from google import genai
    from google.genai import types

    cliente = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=API_TIMEOUT_SEGUNDOS * 1000),  # ms
    )
    modelos = _modelos_gemini()
    ultima_excecao: Exception | None = None
    tentados: list[str] = []
    for i, modelo in enumerate(modelos):
        tentados.append(modelo)
        try:
            return _gemini_uma_chamada(cliente, types, modelo, system_prompt,
                                       user_prompt)
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            if _trocar_de_modelo(exc) and i < len(modelos) - 1:
                continue
            break
    raise ErroGeracaoIA(
        _traduzir_erro(ultima_excecao, "gemini"),
        detalhe=f"[Gemini · tentados: {', '.join(tentados)}] "
                f"{type(ultima_excecao).__name__}: {ultima_excecao}",
    )


def gerar_documento(doc_key: str, dados: dict, contexto_anterior: str | None) -> str:
    """
    Gera o documento `doc_key` ('dfd' | 'etp' | 'tr' | 'edital').

    Com chave de API configurada, usa o Gemini; sem chave (ou com o modo
    demonstração ativado), devolve uma minuta-esqueleto offline.
    Levanta ErroGeracaoIA com mensagem amigável em caso de falha.
    """
    from . import planilha

    if st.session_state.get("modo_demo", False):
        # Fallback EXPLÍCITO (nunca silencioso): só ocorre com o toggle
        # "Modo Demonstração" ligado pelo usuário; registrado como tal.
        inicio = time.time()
        texto = planilha.injetar_tabela(_gerar_demo(doc_key, dados),
                                        dados.get("itens"))
        registrar_geracao(doc_key, "demo", inicio, "ok", fallback=True)
        return texto

    chave_openai = obter_openai_key()
    chave_gemini = obter_api_key()
    if not chave_openai and not chave_gemini:
        raise ErroGeracaoIA(
            "Nenhuma chave de API configurada. Informe a chave da OpenAI "
            "(motor principal) ou do Google AI Studio na barra lateral / "
            ".streamlit/secrets.toml — ou ative o Modo Demonstração."
        )
    system_prompt, user_prompt = montar_prompt(doc_key, dados, contexto_anterior)

    # RAG: anexa trechos relevantes da Base de Conhecimento (leis, acórdãos,
    # entendimentos de TCs, processos anteriores). Falha de RAG nunca
    # bloqueia a geração — o bloco simplesmente fica vazio.
    from . import rag

    user_prompt += rag.montar_bloco_referencias(dados, doc_key)

    # Motor principal: OpenAI; fallback automático (e AVISADO): Gemini.
    # Toda geração — sucesso ou falha — entra no registro técnico.
    texto = ""
    if chave_openai:
        inicio = time.time()
        try:
            texto = _chamar_openai(system_prompt, user_prompt, chave_openai)
            registrar_geracao(doc_key, "openai", inicio, "ok")
        except ErroGeracaoIA as erro:
            registrar_geracao(doc_key, "openai", inicio, "falha",
                              erro=getattr(erro, "detalhe", "") or str(erro))
            if not chave_gemini:
                raise
            st.warning(
                f"Motor principal (OpenAI) indisponível — tentando Gemini. "
                f"{erro}\n\n`{getattr(erro, 'detalhe', '')}`",
            )
    if not texto:
        inicio = time.time()
        try:
            texto = _chamar_gemini(system_prompt, user_prompt, chave_gemini)
            registrar_geracao(doc_key, "gemini", inicio, "ok",
                              fallback=bool(chave_openai))
        except ErroGeracaoIA as erro:
            registrar_geracao(doc_key, "gemini", inicio, "falha",
                              erro=getattr(erro, "detalhe", "") or str(erro),
                              fallback=bool(chave_openai))
            raise
    # Injeta a tabela real da planilha (grande) no lugar da marca [[TABELA_ITENS]].
    return planilha.injetar_tabela(texto, dados.get("itens"))


def chamar_ia_texto(system_prompt: str, user_prompt: str,
                    finalidade: str = "revisao") -> str:
    """
    Chamada genérica de IA para a correção automática (auditor/corretor):
    mesma ordem de motores, fallback e registro técnico da geração de
    documentos — sem RAG, sem modo demo e sem pós-processamento.
    `finalidade` identifica a chamada no registro (ex.: 'corretor').
    """
    chave_openai = obter_openai_key()
    chave_gemini = obter_api_key()
    if not chave_openai and not chave_gemini:
        raise ErroGeracaoIA(
            "Nenhuma chave de API configurada para a revisão com IA. "
            "Informe a chave da OpenAI ou do Gemini no painel do "
            "administrador."
        )
    if chave_openai:
        inicio = time.time()
        try:
            texto = _chamar_openai(system_prompt, user_prompt, chave_openai)
            registrar_geracao(finalidade, "openai", inicio, "ok")
            return texto
        except ErroGeracaoIA as erro:
            registrar_geracao(finalidade, "openai", inicio, "falha",
                              erro=getattr(erro, "detalhe", "") or str(erro))
            if not chave_gemini:
                raise
    inicio = time.time()
    try:
        texto = _chamar_gemini(system_prompt, user_prompt, chave_gemini)
        registrar_geracao(finalidade, "gemini", inicio, "ok",
                          fallback=bool(chave_openai))
        return texto
    except ErroGeracaoIA as erro:
        registrar_geracao(finalidade, "gemini", inicio, "falha",
                          erro=getattr(erro, "detalhe", "") or str(erro),
                          fallback=bool(chave_openai))
        raise


def testar_conexao(motor: str) -> tuple[bool, str]:
    """
    Faz uma chamada mínima ao motor ('openai' | 'gemini') e devolve
    (ok, mensagem). Usado pelo botão "Testar conexão" do painel admin para
    diagnosticar chave/modelo com o erro técnico exato.
    """
    system = "Responda apenas com a palavra OK."
    user = "Responda: OK"
    try:
        if motor == "openai":
            chave = obter_openai_key()
            if not chave:
                return False, "OPENAI_API_KEY não configurada."
            _chamar_openai(system, user, chave)
            return True, f"OpenAI respondeu. Modelos tentados: {', '.join(_modelos_openai())}."
        chave = obter_api_key()
        if not chave:
            return False, "GOOGLE_API_KEY não configurada."
        _chamar_gemini(system, user, chave)
        return True, f"Gemini respondeu. Modelos tentados: {', '.join(_modelos_gemini())}."
    except ErroGeracaoIA as erro:
        detalhe = getattr(erro, "detalhe", "")
        return False, f"{erro}\n\n{detalhe}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Modo demonstração (offline) — minutas-esqueleto a partir do formulário
# ---------------------------------------------------------------------------
def _gerar_demo(doc_key: str, dados: dict) -> str:
    doc = DOCUMENTOS[doc_key]
    dados_fmt = formatar_dados_formulario(dados)
    cabecalho = (
        f"# {doc['titulo'].upper()}\n\n"
        f"*Minuta-esqueleto gerada em Modo Demonstração (sem IA) — "
        f"base legal: {doc['base_legal']}.*\n\n"
        f"## 1. Identificação\n\n- Órgão requisitante: {dados.get('orgao') or '[PREENCHER]'}\n"
        f"- Responsável: {dados.get('responsavel') or '[PREENCHER]'}\n\n"
        f"## 2. Objeto\n\n{dados.get('objeto') or '[PREENCHER: objeto]'}\n\n"
        f"## 3. Justificativa da Necessidade\n\n{dados.get('justificativa') or '[PREENCHER]'}\n\n"
    )
    corpo = {
        "dfd": (
            f"## 4. Alinhamento ao Planejamento\n\n{dados.get('alinhamento') or '[PREENCHER: PCA]'}\n\n"
            "## 5. Estimativa Preliminar de Valor\n\nConforme dados informados:\n\n"
            f"{dados_fmt}\n\n"
            f"## 6. Previsão e Prioridade\n\n{dados.get('prazo') or '[PREENCHER: prazo]'}\n\n"
            "## 7. Encaminhamento\n\nEncaminha-se para autorização da autoridade "
            "competente, nos termos do art. 12, VII, da Lei nº 14.133/2021.\n\n"
            "Local e data: [PREENCHER]\n\nAssinatura: ________________________"
        ),
        "etp": (
            f"## 4. Requisitos da Contratação (art. 18, §1º, III)\n\n{dados.get('requisitos') or '[PREENCHER]'}\n\n"
            "## 5. Levantamento de Mercado (art. 18, §1º, V)\n\n[PREENCHER: pesquisa de mercado]\n\n"
            "## 6. Justificativa do Parcelamento (art. 18, §1º, VIII)\n\n"
            f"Modelo de execução informado: {dados.get('modelo_execucao') or '[PREENCHER]'}. [PREENCHER: análise]\n\n"
            "## 7. Matriz de Riscos\n\n"
            "| Risco | Probabilidade | Impacto | Mitigação | Responsável |\n"
            "|---|---|---|---|---|\n"
            f"| {dados.get('riscos') or '[PREENCHER]'} | [PREENCHER] | [PREENCHER] | [PREENCHER] | [PREENCHER] |\n\n"
            "## 8. Declaração de Viabilidade (art. 18, §1º, XIII)\n\n[PREENCHER: conclusão]"
        ),
        "tr": (
            f"## 4. Requisitos e Especificações (art. 6º, XXIII, 'd')\n\n{dados.get('requisitos') or '[PREENCHER]'}\n\n"
            "## 5. Modelo de Execução e Fiscalização\n\n"
            f"{dados.get('modelo_execucao') or '[PREENCHER]'} — gestor e fiscal do contrato a designar (art. 117).\n\n"
            "## 6. Recebimento e Pagamento (art. 140)\n\n[PREENCHER: critérios de medição e recebimento]\n\n"
            "## 7. Sanções\n\nAplicam-se os arts. 155 a 163 da Lei nº 14.133/2021."
        ),
        "edital": (
            "## 4. Da Participação e Habilitação\n\n[PREENCHER: condições — arts. 14 e 62 a 70]\n\n"
            "## 5. Do Julgamento\n\n[PREENCHER: critério — art. 33]\n\n"
            "## 6. Das Sanções\n\nArts. 155 a 163 da Lei nº 14.133/2021.\n\n"
            + (
                "## 7. Minuta da Ata de Registro de Preços\n\n[PREENCHER: vigência (art. 84), adesões e cancelamento]"
                if "SRP" in (dados.get("modelo_execucao") or "")
                else "## 7. Da Contratação\n\n[PREENCHER: condições de assinatura]"
            )
        ),
    }
    return cabecalho + corpo[doc_key]
