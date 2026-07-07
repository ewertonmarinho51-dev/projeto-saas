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

import os
import time

import streamlit as st

from .config import (
    API_BACKOFF_BASE,
    API_TENTATIVAS,
    API_TIMEOUT_SEGUNDOS,
    DOCUMENTOS,
    GEMINI_MODEL_PADRAO,
    OPENAI_MODEL_PADRAO,
)
from .prompts import formatar_dados_formulario, montar_prompt


class ErroGeracaoIA(Exception):
    """Erro de geração já traduzido em mensagem amigável para a interface."""


def _ler_chave(nome_secret: str, chave_sidebar: str) -> str:
    """
    Busca uma chave na ordem:
    painel do administrador (banco) > sessão > secrets.toml > ambiente.
    """
    from . import db

    valor = db.obter_config(nome_secret)
    if valor:
        return valor
    valor = st.session_state.get(chave_sidebar, "").strip()
    if valor:
        return valor
    try:
        if nome_secret in st.secrets:
            return str(st.secrets[nome_secret]).strip()
    except Exception:
        pass  # sem arquivo secrets.toml — segue para a variável de ambiente
    return os.getenv(nome_secret, "").strip()


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


def _traduzir_erro(exc: Exception) -> str:
    """Converte exceções técnicas da API em mensagens amigáveis."""
    texto = f"{type(exc).__name__}: {exc}".lower()
    if "deadline" in texto or "timeout" in texto or "timed out" in texto:
        return (
            "A IA demorou demais para responder (timeout). "
            "Tente novamente em instantes — seus dados não foram perdidos."
        )
    if "api key" in texto or "api_key" in texto or "permission" in texto or "401" in texto or "403" in texto:
        return (
            "Chave de API inválida ou sem permissão. Verifique a chave em "
            ".streamlit/secrets.toml, na variável GOOGLE_API_KEY ou na barra lateral."
        )
    if "quota" in texto or "resource" in texto and "exhausted" in texto or "429" in texto:
        return (
            "Limite de uso da API atingido (cota/quota). "
            "Aguarde alguns minutos ou verifique seu plano no Google AI Studio."
        )
    if "safety" in texto or "blocked" in texto:
        return (
            "A resposta foi bloqueada pelos filtros de segurança do modelo. "
            "Revise o texto informado no formulário e tente novamente."
        )
    if "not found" in texto or "404" in texto:
        return (
            "Modelo de IA não encontrado. Ajuste GEMINI_MODEL em "
            ".streamlit/secrets.toml para um modelo disponível na sua conta."
        )
    return f"Falha na comunicação com a IA: {exc}"


def _chamar_openai(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """Motor principal: OpenAI, com retentativas e backoff exponencial."""
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from openai import OpenAI

    cliente = OpenAI(api_key=api_key, timeout=API_TIMEOUT_SEGUNDOS, max_retries=0)

    ultima_excecao: Exception | None = None
    for tentativa in range(1, API_TENTATIVAS + 1):
        try:
            resposta = cliente.chat.completions.create(
                model=_obter_modelo_openai(),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=8192,
            )
            texto = (resposta.choices[0].message.content or "").strip()
            if not texto:
                raise RuntimeError("resposta vazia do modelo")
            return texto
        except Exception as exc:  # noqa: BLE001 — traduzimos qualquer falha
            ultima_excecao = exc
            if tentativa < API_TENTATIVAS:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ErroGeracaoIA(_traduzir_erro(ultima_excecao))


def _chamar_gemini(system_prompt: str, user_prompt: str, api_key: str) -> str:
    """Chamada ao Gemini com retentativas e backoff exponencial (2s, 4s, 8s)."""
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from google import genai
    from google.genai import types

    cliente = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(timeout=API_TIMEOUT_SEGUNDOS * 1000),  # ms
    )

    ultima_excecao: Exception | None = None
    for tentativa in range(1, API_TENTATIVAS + 1):
        try:
            resposta = cliente.models.generate_content(
                model=_obter_modelo(),
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=8192,
                ),
            )
            texto = (resposta.text or "").strip()
            if not texto:
                raise RuntimeError("resposta vazia do modelo")
            return texto
        except Exception as exc:  # noqa: BLE001 — traduzimos qualquer falha
            ultima_excecao = exc
            if tentativa < API_TENTATIVAS:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ErroGeracaoIA(_traduzir_erro(ultima_excecao))


def gerar_documento(doc_key: str, dados: dict, contexto_anterior: str | None) -> str:
    """
    Gera o documento `doc_key` ('dfd' | 'etp' | 'tr' | 'edital').

    Com chave de API configurada, usa o Gemini; sem chave (ou com o modo
    demonstração ativado), devolve uma minuta-esqueleto offline.
    Levanta ErroGeracaoIA com mensagem amigável em caso de falha.
    """
    if st.session_state.get("modo_demo", False):
        return _gerar_demo(doc_key, dados)

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

    # Motor principal: OpenAI; fallback automático: Gemini
    if chave_openai:
        try:
            return _chamar_openai(system_prompt, user_prompt, chave_openai)
        except ErroGeracaoIA as erro:
            if not chave_gemini:
                raise
            st.warning(
                f"Motor principal (OpenAI) indisponível — usando Gemini. Detalhe: {erro}",
            )
    return _chamar_gemini(system_prompt, user_prompt, chave_gemini)


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
