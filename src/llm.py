"""
Camada de integração com a IA.

DOIS MODOS DE ESCOLHER O PROVEDOR

1. **Provedor único** (`IA_PROVEDOR` = openai | gemini | openrouter):
   a geração usa SÓ aquele, mesmo havendo chave dos outros. É o modo de
   quem quer uma fatura só. Não há queda para outro provedor: a
   resiliência é a lista de modelos do provedor escolhido.

2. **Cascata** (`IA_PROVEDOR` vazio — o padrão): OpenAI, depois Gemini,
   depois OpenRouter, na ordem, filtrada por quem tem chave. O motor que
   falha depois das retentativas cai para o seguinte, com aviso na tela.

Sem chave alguma, a geração só acontece com o **Modo Demonstração**
ligado explicitamente, e o que sai é minuta-esqueleto offline.

O ÍNDICE VETORIAL NÃO SEGUE ESSA ESCOLHA

Os embeddings exigem a OpenAI e não têm substituto (ver
`obter_chave_de_embeddings` e `rag._gerar_embeddings`). A chave deles
tem nome próprio — `OPENAI_EMBEDDINGS_KEY` — justamente para poder
existir sem arrastar a GERAÇÃO de volta para a OpenAI.

Todos os erros de API (timeout, chave inválida, cota, bloqueio de
conteúdo) viram mensagens amigáveis, e a chave nunca aparece em
nenhuma delas.
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
    OPENROUTER_BASE_URL,
    OPENROUTER_MODEL_PADRAO,
    OPENROUTER_MODELOS_FALLBACK,
    PROVEDORES_DE_IA,
)
from . import ai_gateway, templates_gov
from .prompts import dados_objetivos_do_formulario, montar_prompt


class ErroGeracaoIA(Exception):
    """Erro de geração já traduzido em mensagem amigável para a interface.

    `detalhe` guarda o erro técnico da API (motor + tipo + mensagem)
    para exibição opcional na interface — é o que permite diagnosticar a
    causa real (401, 404, 429, região bloqueada etc.).

    O detalhe é SANITIZADO na construção: exceções de 401 do OpenAI e do
    Gemini ecoam a própria chave, e este texto vai tanto para a tela
    quanto para a coluna de auditoria de `registrar_geracao`.
    """

    def __init__(self, mensagem: str, detalhe: str = ""):
        from . import db   # import tardio: mesmo padrão do resto do módulo

        super().__init__(db.redigir(mensagem))
        self.detalhe = db.redigir(detalhe)


# ---------------------------------------------------------------------------
# Registro técnico de geração (auditoria) — NUNCA grava chave de API nem o
# conteúdo dos documentos; apenas metadados sanitizados.
# ---------------------------------------------------------------------------
_log = logging.getLogger("govdocs.geracao")

# metadados da última chamada bem-sucedida (tokens/modelo/id), preenchidos
# pelos executores de chamada de cada motor
_ultimo_uso: dict = {}


def _telemetria_de_roteamento(rotulo: str, motor: str) -> dict:
    """
    Sob QUAL política a tarefa correu — ou `{}` se nem isso deu para saber.

    Blindado de propósito: este campo é auditoria, e auditoria não pode
    derrubar uma geração. Se `telemetria` levantar por qualquer motivo,
    o registro sai sem ele em vez de o documento não sair.
    """
    try:
        return dict(ai_gateway.telemetria(rotulo, motor))
    except Exception:  # noqa: BLE001 — ver a docstring
        return {}


# Rótulos que NÃO são documento: são trabalho sobre os documentos. A
# lista é declarada para que uma tarefa nova apareça como "documento"
# por omissão e alguém tenha de decidir — em vez de se esconder numa
# heurística de nome.
OPERACOES_DE_APOIO = {
    "auditor": "auditoria",
    "corretor": "correcao",
    "revisao": "revisao",
    "analista_parecer": "parecer",
    "govbot": "assistente",
    "pesquisa_precos": "pesquisa_precos",
    "semantica_precos": "pesquisa_precos",
}


def _operacao_da_tarefa(tarefa: str) -> str:
    return OPERACOES_DE_APOIO.get(tarefa, "documento")


def _custo_do_registro(cache_hit: bool) -> float | None:
    """
    Custo em reais desta chamada, ou None quando o preço do modelo não
    foi configurado. Acerto de cache custa zero, e zero é medida.
    """
    if cache_hit:
        return 0.0
    try:
        from . import politica_ia

        return politica_ia.custo_estimado(
            _ultimo_uso.get("modelo", ""),
            _ultimo_uso.get("tokens_entrada"),
            _ultimo_uso.get("tokens_saida"))
    except Exception:  # noqa: BLE001 — auditoria não derruba geração
        return None


def _identidade_para_o_registro() -> dict:
    """
    Quem gastou: tenant, secretaria e usuário.

    Sai do CONTEXTO INSTITUCIONAL, que deriva da sessão autenticada —
    nunca de campo do formulário. Sem isto, o controle de consumo
    responde "quanto se gastou" e não responde "quem gastou", que é
    metade da pergunta de quem administra o orçamento.

    Blindado: o registro de consumo não pode derrubar a geração.
    """
    try:
        from . import contexto

        institucional = contexto.contexto_institucional()
        return {
            "tenant_id": institucional.get("tenant_id"),
            "secretaria_id": institucional.get("secretaria_id"),
            "usuario_id": institucional.get("usuario_id"),
        }
    except Exception:  # noqa: BLE001 — ver a docstring
        return {}


def registrar_geracao(doc_key: str, motor: str, inicio: float, status: str,
                      erro: str = "", fallback: bool = False,
                      processo_id: str | None = None,
                      rag_trace: dict | None = None,
                      cache_hit: bool = False,
                      tokens_evitados_entrada: int | None = None,
                      tokens_evitados_saida: int | None = None) -> dict:
    """
    Grava o registro no log do servidor e no histórico da sessão.

    `rag_trace` (P1) responde "por que o sistema citou este artigo?":
    consultas/temas feitos à base, fontes recuperadas com título,
    categoria e score. Guarda IDENTIFICAÇÃO da fonte — nunca chaves de
    API, nunca o documento inteiro.

    `roteamento` responde a outra pergunta, que até aqui não tinha
    resposta: SOB QUAL POLÍTICA este documento foi gerado.
    """
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
        "rag_trace": rag_trace or {},
        # `ai_gateway.telemetria` já devolvia exatamente estes campos e
        # NÃO era chamada em lugar nenhum do sistema — foi escrita e
        # nunca ligada. Ligá-la é o oposto de criar um segundo
        # mecanismo: é usar o que já existia. Sem conteúdo dentro:
        # nada de prompt, resposta ou chave, e há prova disso.
        "roteamento": _telemetria_de_roteamento(doc_key, motor),
        # ------------------------------------------------------------
        # Controle de consumo (ETAPA 10). Toda chamada de IA passa por
        # aqui — é o ponto único, e é por isso que ele responde às
        # perguntas todas de uma vez: quem, em que processo, para qual
        # documento, com qual operação, em que modelo, quanto gastou, se
        # foi acerto de cache e quanto isso evitou.
        #
        # `operacao` distingue a REDAÇÃO do documento do trabalho de
        # auditoria e correção sobre ele. Sem essa coluna, `documento`
        # misturava "gerei o TR" com "auditei o bundle", e o custo por
        # documento não podia ser apurado — em produção, 65 das 90
        # chamadas bem-sucedidas eram de auditor e corretor.
        # ------------------------------------------------------------
        **_identidade_para_o_registro(),
        "operacao": _operacao_da_tarefa(doc_key),
        "cache_hit": bool(cache_hit),
        "tokens_evitados_entrada": tokens_evitados_entrada,
        "tokens_evitados_saida": tokens_evitados_saida,
        "custo": _custo_do_registro(cache_hit),
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
    """Chave do fallback (Google Gemini)."""
    return _ler_chave("GOOGLE_API_KEY", "api_key_manual")


def obter_openrouter_key() -> str:
    """Chave do terceiro motor (OpenRouter)."""
    return _ler_chave("OPENROUTER_API_KEY", "openrouter_key_manual")


def obter_chave_de_embeddings() -> str:
    """
    Chave do ÍNDICE VETORIAL, que é outra coisa que a chave de geração.

    O índice exige a OpenAI: `EMBEDDING_V2_PROVEDOR` está fixado nela,
    e trocar de provedor de embedding invalida todos os vetores já
    gravados (reindexar a base inteira). O OpenRouter não é alternativa
    — ele não serve embedding nenhum.

    Por isso a chave do índice ganhou NOME PRÓPRIO. Enquanto ela se
    chamava `OPENAI_API_KEY`, mantê-la para o índice colocava a OpenAI
    de volta na cascata de GERAÇÃO sem que ninguém tivesse pedido: quem
    escolhesse o OpenRouter como provedor continuaria gerando documento
    na OpenAI por efeito colateral de uma chave que existia para a
    busca.

    `OPENAI_API_KEY` continua valendo como fonte, atrás da nova, para
    que nenhuma instalação pare de indexar por causa desta mudança. A
    compatibilidade passa por `obter_openai_key()` e não por uma
    segunda leitura de `OPENAI_API_KEY`: duas leituras da mesma chave
    divergiriam na primeira vez que alguém mexesse em uma só — e a
    daquela função já cobre a barra lateral, que a outra esqueceria.
    """
    return _ler_chave("OPENAI_EMBEDDINGS_KEY", "") or obter_openai_key()


def provedor_declarado() -> str:
    """
    O provedor ESCOLHIDO para a geração, ou '' para a cascata de sempre.

    Nome fora de `PROVEDORES_DE_IA` é tratado como vazio: um erro de
    digitação em `IA_PROVEDOR` não pode deixar o sistema sem provedor
    nenhum e com a tela dizendo "nenhuma chave configurada".
    """
    nome = _ler_chave("IA_PROVEDOR", "").strip().lower()
    return nome if nome in PROVEDORES_DE_IA else ""


# Ordem de precedência dos motores. É a ÚNICA fonte da ordem: quem
# adiciona motor mexe aqui, e `motor_ativo`, a geração de documento e a
# revisão passam a enxergá-lo sem uma terceira cópia do mesmo try/except.
def motores_disponiveis() -> list[tuple[str, str]]:
    """
    [(motor, chave)] dos motores a usar, do primeiro ao último.

    Com `IA_PROVEDOR` declarado, a lista tem no máximo UM item: o
    provedor escolhido. Sem ele, a cascata histórica — OpenAI, Gemini,
    OpenRouter, nessa ordem, filtrada por quem tem chave. OpenRouter
    vem por último na cascata de propósito: ver o comentário da escolha
    em `config.py`.
    """
    chaves = {
        "openai": obter_openai_key,
        "gemini": obter_api_key,
        "openrouter": obter_openrouter_key,
    }
    escolhido = provedor_declarado()
    ordem = (escolhido,) if escolhido else PROVEDORES_DE_IA
    return [(motor, chaves[motor]()) for motor in ordem if chaves[motor]()]


def motor_ativo() -> str:
    """'openai' | 'gemini' | 'openrouter' | '' — motor da próxima geração."""
    disponiveis = motores_disponiveis()
    return disponiveis[0][0] if disponiveis else ""


def _sem_motor() -> str:
    """
    A mensagem de "não há motor", que depende de POR QUE não há.

    Declarar um provedor e esquecer a chave dele é um estado diferente
    de não ter configurado nada, e mandar o servidor procurar a chave
    errada é o que uma mensagem genérica faria.
    """
    escolhido = provedor_declarado()
    if escolhido:
        rotulo = ROTULOS_MOTOR.get(escolhido, escolhido)
        return (
            f"O provedor de IA escolhido é o {rotulo} (IA_PROVEDOR="
            f"{escolhido}) e a chave dele não está configurada. Informe a "
            f"chave do {rotulo} no painel do administrador, escolha outro "
            "provedor, ou deixe IA_PROVEDOR vazio para voltar à cascata "
            "automática entre os provedores configurados."
        )
    return (
        "Nenhuma chave de API configurada. Informe a chave da OpenAI "
        "(motor principal), do Google AI Studio ou do OpenRouter na "
        "barra lateral / .streamlit/secrets.toml — ou ative o Modo "
        "Demonstração."
    )


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


def _obter_modelo_openrouter() -> str:
    return _ler_chave("OPENROUTER_MODEL", "") or OPENROUTER_MODEL_PADRAO


def _modelos_openrouter() -> list[str]:
    return _dedup([_obter_modelo_openrouter(), *OPENROUTER_MODELOS_FALLBACK])


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
    elif motor == "openrouter":
        rotulo, var_chave, var_modelo, painel = (
            "OpenRouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL",
            "openrouter.ai (chave, créditos e limite diário do plano "
            "gratuito)")
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
    from . import db   # import tardio: mesmo padrão do resto do módulo

    # Categoria desconhecida: mensagem genérica com referência. O texto
    # bruto da API costuma trazer a chave no cabeçalho ecoado.
    return (f"{rotulo}: falha na comunicação. Referência: "
            f"{db.registrar_incidente(exc, f'llm: {motor or rotulo}')}.")


class _RespostaVazia(Exception):
    """O modelo respondeu sem conteúdo (ex.: raciocínio consumiu os tokens).
    Sinaliza que vale a pena tentar o próximo modelo da lista."""


# ---------------------------------------------------------------------------
# Classificação do erro — o que a retentativa pode e o que ela não pode
# ---------------------------------------------------------------------------
# Até aqui QUALQUER falha que não fosse de modelo era repetida
# `API_TENTATIVAS` vezes, com espera de 2s e 4s entre elas. Chave
# inválida era repetida três vezes. Requisição malformada, três vezes.
# Crédito esgotado, três vezes. Nenhuma delas melhora por repetição:
# o resultado é a mesma recusa, três vezes o tempo de tela e — quando o
# provedor cobra a requisição recusada — três vezes a conta.
#
# A classificação abaixo é por TEXTO do erro porque é o que os três
# SDKs têm em comum; `_traduzir_erro` já lia o erro assim, e criar uma
# segunda forma de lê-lo faria as duas divergirem.
CLASSE_AUTENTICACAO = "autenticacao"   # 401/403 — chave inválida ou sem permissão
CLASSE_CREDITO = "credito"             # cota/faturamento esgotado
CLASSE_LIMITE = "limite"               # 429 de ritmo — passa com espera
CLASSE_MODELO = "modelo"               # modelo inexistente/sem acesso
CLASSE_VALIDACAO = "validacao"         # requisição malformada, contexto excedido
CLASSE_VAZIA = "vazia"                 # respondeu sem conteúdo
CLASSE_REDE = "rede"                   # timeout, conexão — transitório
CLASSE_DESCONHECIDA = "desconhecida"

# Só estas melhoram com repetir a MESMA requisição no MESMO modelo.
CLASSES_QUE_VALEM_RETENTATIVA = (CLASSE_LIMITE, CLASSE_REDE,
                                 CLASSE_DESCONHECIDA)


def classificar_erro(exc: Exception) -> str:
    """
    Em que categoria cai esta falha. Decide retentativa e troca de modelo.

    A ordem das perguntas importa: `insufficient_quota` também carrega
    "429" na mensagem, e tratá-lo como limite de ritmo faria o sistema
    esperar e repetir três vezes uma conta sem crédito — que só volta a
    funcionar quando alguém pagar.
    """
    if isinstance(exc, _RespostaVazia):
        return CLASSE_VAZIA
    texto = f"{type(exc).__name__}: {exc}".lower()
    if ("insufficient_quota" in texto or "billing" in texto
            or "exceeded your current quota" in texto
            or "credit" in texto and "insufficient" in texto):
        return CLASSE_CREDITO
    if ("invalid_api_key" in texto or "incorrect api key" in texto
            or "api key" in texto or "api_key" in texto
            or "unauthorized" in texto or "401" in texto
            or "permission" in texto or "403" in texto):
        return CLASSE_AUTENTICACAO
    if _e_erro_de_modelo(exc):
        return CLASSE_MODELO
    # "400" solto NÃO entra: ele aparece em contagem de token e em id de
    # requisição, e classificar por acidente uma falha de rede como
    # requisição malformada tiraria dela a única retentativa que ajuda.
    if ("context_length_exceeded" in texto or "maximum context" in texto
            or "invalid_request_error" in texto
            or "badrequest" in texto or "bad request" in texto
            or "too many tokens" in texto):
        return CLASSE_VALIDACAO
    if ("rate limit" in texto or "429" in texto
            or ("resource" in texto and "exhausted" in texto)
            or "overloaded" in texto or "503" in texto):
        return CLASSE_LIMITE
    if ("timeout" in texto or "timed out" in texto or "deadline" in texto
            or "connection" in texto or "connect" in texto):
        return CLASSE_REDE
    return CLASSE_DESCONHECIDA


def vale_retentar(exc: Exception) -> bool:
    """Repetir a MESMA requisição no MESMO modelo pode dar outro resultado?"""
    return classificar_erro(exc) in CLASSES_QUE_VALEM_RETENTATIVA


# Modelos que PENSAM antes de escrever, por família.
#
# A lista é declarada porque a consequência de errar é assimétrica: um
# modelo de raciocínio tratado como comum gasta o orçamento inteiro
# pensando e devolve conteúdo VAZIO, e o documento não sai. O contrário
# — um modelo comum receber `reasoning_effort` — é ignorado pelo
# provedor.
#
# `nemotron-3` entrou quando o OpenRouter passou a ser provedor de
# verdade e não terceiro na fila. Ela é modelo de raciocínio, aceita
# `reasoning_effort` (conferido no catálogo do provedor em 08/10/2026,
# campo `supported_parameters`), e sem o esforço baixo era a candidata
# mais provável a devolver vazio num prompt de Termo de Referência.
_FAMILIAS_DE_RACIOCINIO = ("gpt-5", "o1", "o3", "o4")
_MARCAS_DE_RACIOCINIO = ("nemotron-3",)


def e_modelo_de_raciocinio(modelo: str) -> bool:
    """
    Este modelo gasta orçamento de saída PENSANDO?

    Casa por prefixo nas famílias da OpenAI e por marca no identificador
    do OpenRouter, que vem com fornecedor na frente
    (`nvidia/nemotron-3-ultra-550b-a55b:free`) e nunca casaria por
    prefixo.

    Fonte única: `politica_ia` lê daqui para calcular o teto de saída, e
    `_params_modelo_openai` lê daqui para pedir esforço baixo. Duas
    listas divergiriam, e a divergência apareceria como documento vazio.
    """
    ml = (modelo or "").lower()
    return (ml.startswith(_FAMILIAS_DE_RACIOCINIO)
            or any(marca in ml for marca in _MARCAS_DE_RACIOCINIO))


def _params_modelo_openai(modelo: str) -> dict:
    """
    Parâmetros extras por família de modelo. Modelos de raciocínio consomem
    tokens 'pensando' antes de escrever — com prompt grande podem gastar todo
    o orçamento no raciocínio e devolver conteúdo VAZIO. Usamos esforço baixo
    (qualidade com orçamento p/ texto); se ainda vier vazio, a troca de
    modelo automática assume.

    Vale para a OpenAI e para o OpenRouter, que documenta
    `reasoning_effort` com a mesma semântica — é o que permite aos dois
    motores reusarem `_openai_uma_chamada` sem um segundo conjunto de
    parâmetros.
    """
    if e_modelo_de_raciocinio(modelo):
        return {"reasoning_effort": "low"}
    return {}


def _trocar_de_modelo(exc: Exception) -> bool:
    """Erros em que vale tentar o próximo modelo: inexistente/sem acesso, ou
    resposta vazia (típico de modelo de raciocínio sem tokens p/ o texto)."""
    return isinstance(exc, _RespostaVazia) or _e_erro_de_modelo(exc)


def _cabecalhos_de_idempotencia(system_prompt: str, user_prompt: str,
                                modelo: str) -> dict:
    """
    `Idempotency-Key` derivada do próprio pedido.

    Fecha o único caminho de cobrança duplicada que o cache local não
    alcança: a resposta que o provedor GEROU e que não chegou até aqui
    (timeout de leitura, conexão cortada). Do lado de cá parece que nada
    aconteceu, e a retentativa pede a geração de novo — a segunda
    cobrança de um documento que já existe do lado de lá.

    Com a chave, a repetição devolve a resposta original. A chave cobre
    o pedido inteiro, então um pedido DIFERENTE nunca é confundido com a
    repetição de outro.
    """
    import hashlib

    material = "\u0000".join((modelo or "", system_prompt or "",
                              user_prompt or ""))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return {"Idempotency-Key": f"govdocs-{digest[:48]}"}


def _openai_uma_chamada(cliente, modelo: str, system_prompt: str,
                        user_prompt: str,
                        tentativas: int = API_TENTATIVAS,
                        tarefa: str = "") -> str:
    """Uma chamada ao modelo indicado, com retentativas/backoff em falhas."""
    from . import politica_ia

    ultima_excecao: Exception | None = None
    extra = _params_modelo_openai(modelo)
    teto = politica_ia.teto_de_saida(tarefa, modelo)
    cabecalhos = _cabecalhos_de_idempotencia(system_prompt, user_prompt,
                                             modelo)
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = cliente.chat.completions.create(
                model=modelo,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                max_completion_tokens=teto,
                extra_headers=cabecalhos,
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
            # Repetir só o que pode dar outro resultado. Chave inválida,
            # crédito esgotado, requisição malformada, modelo inexistente
            # e resposta vazia devolvem exatamente a mesma coisa na
            # segunda e na terceira vez — e cada uma delas ainda é uma
            # requisição, com o tempo de tela e a conta que vêm junto.
            if not vale_retentar(exc):
                raise
            if tentativa < tentativas:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ultima_excecao  # type: ignore[misc]


def _chamar_openai(system_prompt: str, user_prompt: str, api_key: str,
                   timeout: float | None = None,
                   tentativas: int = API_TENTATIVAS,
                   tarefa: str = "") -> str:
    """
    Motor principal: OpenAI. Tenta o modelo configurado e, se ele não existir,
    não tiver acesso, ou devolver resposta vazia (comum em modelos de
    raciocínio), cai automaticamente para modelos alternativos amplamente
    disponíveis (gpt-4o-mini etc.).
    `timeout`/`tentativas` permitem às tarefas rápidas (auditor/corretor)
    desistir bem antes do teto de geração de documentos longos — inclui
    o loop de retentativa por modelo de `_openai_uma_chamada`.
    """
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from openai import OpenAI

    # `base_url=None` é o padrão do SDK — é o caminho direto de sempre. O
    # gateway só entra quando alguém liga `OMNIROUTE_ENABLED` E configura
    # `OMNIROUTE_BASE_URL`; sem as duas, esta linha não muda nada.
    cliente = OpenAI(api_key=api_key,
                     base_url=ai_gateway.base_url_para("openai"),
                     timeout=timeout or API_TIMEOUT_SEGUNDOS, max_retries=0)
    from . import politica_ia

    modelos = politica_ia.modelos_para(tarefa, _modelos_openai(), "openai")
    ultima_excecao: Exception | None = None
    tentados: list[str] = []
    for i, modelo in enumerate(modelos):
        tentados.append(modelo)
        try:
            return _openai_uma_chamada(cliente, modelo, system_prompt,
                                       user_prompt, tentativas, tarefa)
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


def _chamar_openrouter(system_prompt: str, user_prompt: str, api_key: str,
                       timeout: float | None = None,
                       tentativas: int = API_TENTATIVAS,
                       tarefa: str = "") -> str:
    """
    Terceiro motor: OpenRouter, pela API compatível com a da OpenAI.

    O corpo é o MESMO de `_chamar_openai`, e isso é intencional: muda a
    base e a lista de modelos, não o protocolo. Reescrever o laço de
    retentativa aqui criaria duas implementações do mesmo contrato que
    divergiriam na primeira correção feita só de um lado.

    `_params_modelo_openai` devolve `{}` para estes identificadores
    (`nvidia/...`, `google/gemma-...`), então nenhum parâmetro específico
    da OpenAI é enviado. Vale notar que a Nemotron Ultra é modelo de
    raciocínio: se ela gastar o orçamento pensando e devolver vazio, o
    `_RespostaVazia` já existente troca de modelo sozinho.
    """
    from openai import OpenAI

    cliente = OpenAI(
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        timeout=timeout or API_TIMEOUT_SEGUNDOS,
        max_retries=0,
        # Cabeçalhos de atribuição do OpenRouter. Identificam a aplicação
        # no painel do provedor; não carregam dado de processo.
        default_headers={
            "HTTP-Referer": "https://github.com/ewertonmarinho51-dev/projeto-saas",
            "X-Title": "GovDocs Wizard",
        },
    )
    modelos = _modelos_openrouter()
    ultima_excecao: Exception | None = None
    tentados: list[str] = []
    for i, modelo in enumerate(modelos):
        tentados.append(modelo)
        try:
            return _openai_uma_chamada(cliente, modelo, system_prompt,
                                       user_prompt, tentativas, tarefa)
        except Exception as exc:  # noqa: BLE001
            ultima_excecao = exc
            if _trocar_de_modelo(exc) and i < len(modelos) - 1:
                continue
            break
    raise ErroGeracaoIA(
        _traduzir_erro(ultima_excecao, "openrouter"),
        detalhe=f"[OpenRouter · tentados: {', '.join(tentados)}] "
                f"{type(ultima_excecao).__name__}: {ultima_excecao}",
    )


# Despacho por motor. Mantido junto das implementações para que um motor
# novo não possa ser adicionado sem aparecer aqui.
_CHAMADAS = {
    "openai": lambda *a, **k: _chamar_openai(*a, **k),
    "gemini": lambda *a, **k: _chamar_gemini(*a, **k),
    "openrouter": lambda *a, **k: _chamar_openrouter(*a, **k),
}


def _chamar_motor(motor: str, system_prompt: str, user_prompt: str,
                  api_key: str, timeout: float | None = None,
                  tentativas: int = API_TENTATIVAS,
                  tarefa: str = "") -> str:
    """Chama o motor nomeado. Indireção tardia para o teste poder trocar
    `_chamar_openai` por um dublê com `monkeypatch.setattr`."""
    return _CHAMADAS[motor](system_prompt, user_prompt, api_key,
                            timeout=timeout, tentativas=tentativas,
                            tarefa=tarefa)


def _gemini_uma_chamada(cliente, types, modelo: str, system_prompt: str,
                        user_prompt: str, tentativas: int = API_TENTATIVAS,
                        tarefa: str = "") -> str:
    """Uma chamada ao modelo indicado, com retentativas/backoff em falhas."""
    from . import politica_ia

    ultima_excecao: Exception | None = None
    teto = politica_ia.teto_de_saida(tarefa, modelo)
    for tentativa in range(1, tentativas + 1):
        try:
            resposta = cliente.models.generate_content(
                model=modelo,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,
                    max_output_tokens=teto,
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
            if not vale_retentar(exc):
                raise
            if tentativa < tentativas:
                time.sleep(API_BACKOFF_BASE**tentativa)  # 2s, 4s...
    raise ultima_excecao  # type: ignore[misc]


def _chamar_gemini(system_prompt: str, user_prompt: str, api_key: str,
                   timeout: float | None = None,
                   tentativas: int = API_TENTATIVAS,
                   tarefa: str = "") -> str:
    """
    Fallback: Gemini. Tenta o modelo configurado e, se não existir/sem
    acesso, cai para modelos alternativos (gemini-1.5-flash etc.).
    `timeout`/`tentativas` deixam tarefas rápidas (auditor) desistir cedo.
    """
    # Import tardio: a interface abre mesmo sem a biblioteca instalada
    from google import genai
    from google.genai import types

    cliente = genai.Client(
        api_key=api_key,
        http_options=types.HttpOptions(
            timeout=int((timeout or API_TIMEOUT_SEGUNDOS) * 1000)),  # ms
    )
    modelos = _modelos_gemini()
    ultima_excecao: Exception | None = None
    tentados: list[str] = []
    for i, modelo in enumerate(modelos):
        tentados.append(modelo)
        try:
            return _gemini_uma_chamada(cliente, types, modelo, system_prompt,
                                       user_prompt, tentativas, tarefa)
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


def gerar_instrumento_oficial(doc_key: str, dados: dict) -> str:
    """
    Edital / Ata de Registro de Preços montados DETERMINISTICAMENTE.

    A redação jurídica destes instrumentos não é livre: vem do catálogo
    de cláusulas versionado (templates_gov), com a tabela oficial de
    itens injetada no lugar do marcador. Dado ausente aparece como
    [PREENCHER: …] e bloqueia a emissão — jamais é preenchido por
    plausibilidade, que foi como o edital auditado ganhou pregão fundado
    no art. 109 e garantia sem base legal.
    """
    from . import planilha

    inicio = time.time()
    montado = templates_gov.montar_oficial(doc_key, dados)
    texto = planilha.injetar_tabela(montado["texto"], dados.get("itens"))
    registrar_geracao(doc_key, "template", inicio, "ok")
    # instrumento determinístico não consulta a base de conhecimento: o
    # rastro fica explicitamente vazio (e não herda o do documento anterior)
    _associar_rag_trace(doc_key, {"modo": "template", "consultas": [],
                                  "referencias": []}, texto)
    return texto


def gerar_documento(doc_key: str, dados: dict,
                    contexto_anterior: str | None,
                    instrucoes_extra: str = "", *, progresso=None) -> str:
    """
    Gera o documento `doc_key` ('dfd' | 'etp' | 'tr' | 'edital' | 'arp').

    Três caminhos, nesta ordem:

    1. **`edital` e `arp` nunca passam por IA.** São instrumentos de
       conteúdo obrigatório (art. 25 e arts. 82 a 86), montados por
       código a partir do catálogo versionado de cláusulas — o que falta
       neles vira [PREENCHER: …] visível, nunca texto plausível;
    2. **Modo Demonstração ligado** (toggle explícito do administrador):
       devolve a minuta-esqueleto offline de `_gerar_demo`, com os dados
       objetivos do formulário e a tabela oficial;
    3. **caso contrário**: OpenAI como motor principal, Gemini como
       fallback avisado.

    **Sem chave de API e sem Modo Demonstração, levanta `ErroGeracaoIA`**
    — não existe queda silenciosa para o esqueleto offline. Um documento
    de fase preparatória produzido sem IA, sem que ninguém tenha pedido,
    seria entregue como se fosse a redação encomendada.

    `instrucoes_extra` (V6): diretrizes adicionais da família de modelo
    resolvida — aditivas ao perfil institucional. Qualquer falha de
    geração vira `ErroGeracaoIA` com mensagem amigável.
    """
    from . import planilha

    if doc_key in templates_gov.TEMPLATES_OFICIAIS:
        if progresso:
            progresso("GERANDO")
        return gerar_instrumento_oficial(doc_key, dados)

    if st.session_state.get("modo_demo", False):
        if progresso:
            progresso("GERANDO")
        # Fallback EXPLÍCITO (nunca silencioso): só ocorre com o toggle
        # "Modo Demonstração" ligado pelo usuário; registrado como tal.
        inicio = time.time()
        if doc_key == "mapa_riscos":
            from .mapa_riscos import minuta_demo
            texto = minuta_demo(dados)
        else:
            texto = planilha.injetar_tabela(_gerar_demo(doc_key, dados),
                                            dados.get("itens"))
        registrar_geracao(doc_key, "demo", inicio, "ok", fallback=True)
        # esqueleto offline não consulta a base: rastro vazio, mas do
        # documento certo (o anterior não pode ficar valendo)
        _associar_rag_trace(doc_key, {"modo": "demo", "consultas": [],
                                      "referencias": []}, texto)
        return texto

    # A guarda continua AQUI, e não só dentro de `_percorrer_motores`: ela
    # precisa vir antes de montar o prompt e de consultar o RAG. Sem chave
    # nenhuma, esse trabalho todo seria jogado fora, e a mensagem certa é
    # a desta tela — que menciona o Modo Demonstração como saída.
    if not motores_disponiveis():
        raise ErroGeracaoIA(_sem_motor())
    system_prompt, user_prompt = montar_prompt(doc_key, dados, contexto_anterior)

    # RAG: anexa trechos relevantes da Base de Conhecimento (leis, acórdãos,
    # entendimentos de TCs, processos anteriores). Falha de RAG nunca
    # bloqueia a geração — o bloco simplesmente fica vazio.
    from . import rag

    contexto_rag = rag.montar_contexto(dados, doc_key)
    user_prompt += contexto_rag["bloco"]
    rag_trace = contexto_rag["trace"]

    # P1: cláusulas condicionais resolvidas pelo MOTOR DE CONHECIMENTO
    # (mesmas regras, fatos e trilha exibidos na tela final). Com o motor
    # inativo devolve "" — o prompt fica idêntico ao de hoje.
    from . import conhecimento

    user_prompt += conhecimento.diretrizes_para_prompt(
        dados, st.session_state.get("processo_id"),
        documentos=st.session_state.get("documentos") or {}, doc_key=doc_key)
    if instrucoes_extra:
        user_prompt += instrucoes_extra

    # Conteúdo determinístico sai do modelo: a equipe de planejamento
    # vem da portaria cadastrada, como o bloco de assinaturas já vinha.
    # A instrução custa algumas dezenas de tokens de ENTRADA e poupa a
    # cláusula inteira de SAÍDA — a troca certa, porque saída é mais
    # cara que entrada em todo provedor em uso.
    from . import clausulas_deterministicas

    user_prompt += clausulas_deterministicas.instrucao_para_o_prompt(doc_key)

    # Cache: a mesma pergunta não se paga duas vezes.
    #
    # A chave é o hash dos DOIS PROMPTS já montados — formulário,
    # planilha calculada, cadeia aprovada, RAG e diretrizes já estão
    # dentro deles. É o que torna impossível o erro clássico deste tipo
    # de cache: acrescentar uma fonte ao prompt e esquecer de somá-la à
    # chave, passando a servir documento montado com contexto velho.
    #
    # A consulta vem ANTES de o `progresso` anunciar "GERANDO": um
    # acerto de cache não gera coisa nenhuma, e anunciar geração seria
    # mentir para quem está olhando a tela.
    from . import cache_geracao

    chave_cache = _chave_de_cache(system_prompt, user_prompt)
    processo_id = st.session_state.get("processo_id")
    guardado = cache_geracao.buscar(chave_cache, processo_id)
    if guardado:
        inicio = time.time()
        _ultimo_uso.update(modelo=guardado.get("modelo", ""),
                           tokens_entrada=0, tokens_saida=0, request_id="")
        registrar_geracao(doc_key, guardado.get("motor", ""), inicio, "ok",
                          rag_trace=rag_trace, cache_hit=True,
                          tokens_evitados_entrada=guardado.get(
                              "tokens_entrada"),
                          tokens_evitados_saida=guardado.get("tokens_saida"))
        _associar_rag_trace(doc_key, rag_trace, guardado["texto"])
        if progresso:
            progresso("GERANDO")
        return guardado["texto"]

    # Motores em ordem de precedência, com queda AVISADA para o seguinte.
    # Toda geração — sucesso ou falha — entra no registro técnico.
    #
    # O laço substituiu duas cópias do mesmo try/except. Com três motores
    # seriam três, e a terceira já nasceria divergindo: era na cópia do
    # Gemini que `fallback=` estava preenchido, e na da OpenAI não.
    if progresso:
        progresso("GERANDO")
    texto = _percorrer_motores(doc_key, system_prompt, user_prompt,
                               rag_trace=rag_trace, avisar=progresso is None)
    # Injeta a tabela real da planilha (grande) no lugar da marca [[TABELA_ITENS]].
    texto = clausulas_deterministicas.injetar(texto, doc_key)
    final = (texto if doc_key == "mapa_riscos" else
             planilha.injetar_tabela(texto, dados.get("itens")))
    # Guarda o texto FINAL (com a tabela já injetada), que é o que o
    # acerto de cache devolve. Guardar o texto cru faria a tabela ser
    # injetada uma vez no caminho normal e nenhuma no caminho do cache.
    cache_geracao.guardar(chave_cache, processo_id, doc_key, {
        "texto": final,
        "motor": _ultimo_uso.get("motor", motor_ativo()),
        "modelo": _ultimo_uso.get("modelo", ""),
        "tokens_entrada": _ultimo_uso.get("tokens_entrada"),
        "tokens_saida": _ultimo_uso.get("tokens_saida"),
    })
    _associar_rag_trace(doc_key, rag_trace, final)
    return final


def regenerar_clausulas(doc_key: str, dados: dict,
                        contexto_anterior: str | None, texto_atual: str,
                        pedidas: set[int], campos: list[str],
                        instrucoes_extra: str = "", *,
                        progresso=None) -> str:
    """
    Reescreve APENAS as cláusulas `pedidas` do documento vigente.

    Levanta `regeneracao.RecorteRejeitado` quando a resposta não passa
    na conferência — e o chamador então gera o documento inteiro, que é
    o comportamento de hoje. Documento pela metade nunca sai daqui.

    O ganho está na SAÍDA, que é onde a regeneração por blocos economiza
    de verdade: o modelo escreve duas cláusulas em vez de dezessete. A
    entrada cai menos, porque o documento vigente viaja como referência
    de coerência — sem ele, as cláusulas novas contradiriam as antigas,
    que é o defeito que esta função existe para não criar.
    """
    from . import clausulas_deterministicas, planilha, regeneracao

    if doc_key in templates_gov.TEMPLATES_OFICIAIS:
        raise regeneracao.RecorteRejeitado(
            "instrumento determinístico não tem regeneração parcial")
    if not motores_disponiveis():
        raise ErroGeracaoIA(_sem_motor())

    system_prompt, user_prompt = montar_prompt(doc_key, dados,
                                               contexto_anterior)
    from . import rag

    contexto_rag = rag.montar_contexto(dados, doc_key)
    user_prompt += contexto_rag["bloco"]
    if instrucoes_extra:
        user_prompt += instrucoes_extra
    # A mesma instrução da geração inteira: se a cláusula de equipe
    # estiver entre as reescritas, ela continua vindo do cadastro. Sem
    # isto, a atualização parcial desfaria a cláusula determinística e
    # o documento voltaria a ter `[PREENCHER]` onde já tinha o nome.
    user_prompt += clausulas_deterministicas.instrucao_para_o_prompt(doc_key)
    user_prompt += regeneracao.instrucoes_de_recorte(
        doc_key, pedidas, campos, texto_atual)

    from . import cache_geracao

    chave_cache = _chave_de_cache(system_prompt, user_prompt)
    processo_id = st.session_state.get("processo_id")
    guardado = cache_geracao.buscar(chave_cache, processo_id)
    if guardado:
        inicio = time.time()
        _ultimo_uso.update(modelo=guardado.get("modelo", ""),
                           tokens_entrada=0, tokens_saida=0, request_id="")
        registrar_geracao(doc_key, guardado.get("motor", ""), inicio, "ok",
                          cache_hit=True)
        return guardado["texto"]

    if progresso:
        progresso("GERANDO")
    resposta = _percorrer_motores(doc_key, system_prompt, user_prompt,
                                  rag_trace=contexto_rag["trace"],
                                  avisar=progresso is None)
    # A conferência acontece ANTES da injeção da tabela: o marcador
    # [[TABELA_ITENS]] pertence ao texto do modelo, e comparar cláusulas
    # já com a tabela dentro compararia a planilha, não a redação.
    recomposto = clausulas_deterministicas.injetar(
        regeneracao.aplicar(texto_atual, resposta, pedidas), doc_key)
    final = (recomposto if doc_key == "mapa_riscos" else
             planilha.injetar_tabela(recomposto, dados.get("itens")))
    cache_geracao.guardar(chave_cache, processo_id, doc_key, {
        "texto": final,
        "motor": _ultimo_uso.get("motor", motor_ativo()),
        "modelo": _ultimo_uso.get("modelo", ""),
        "tokens_entrada": _ultimo_uso.get("tokens_entrada"),
        "tokens_saida": _ultimo_uso.get("tokens_saida"),
    })
    return final


def _chave_de_cache(system_prompt: str, user_prompt: str) -> str:
    """
    Chave do cache para o pedido montado.

    O motor e a LISTA de modelos candidatos entram porque a resposta
    depende deles: o mesmo prompt no Gemini e na OpenAI produz textos
    diferentes, e servir um pelo outro seria trocar o autor do documento
    sem dizer a ninguém.
    """
    from . import cache_geracao

    motor = motor_ativo()
    candidatos = {"openai": _modelos_openai, "gemini": _modelos_gemini,
                  "openrouter": _modelos_openrouter}.get(motor)
    modelos = ",".join(candidatos()) if candidatos else ""
    return cache_geracao.chave(motor, modelos, system_prompt, user_prompt)


ROTULOS_MOTOR = {
    "openai": "OpenAI",
    "gemini": "Gemini",
    "openrouter": "OpenRouter",
}


def _percorrer_motores(rotulo_registro: str, system_prompt: str,
                       user_prompt: str, *, rag_trace: dict | None = None,
                       avisar: bool = False,
                       timeout: float | None = None,
                       tentativas: int = API_TENTATIVAS) -> str:
    """
    Tenta cada motor configurado, em ordem, até um responder.

    Devolve o texto do primeiro que responder. Se todos falharem, propaga
    o erro do ÚLTIMO — que é o que o operador precisa ver para agir, já
    que os anteriores ele acabou de ver na tela como aviso.

    `avisar` liga o `st.warning` de queda de motor, que faz sentido na
    geração de documento (o usuário está esperando) e não na revisão
    automática, que roda em segundo plano.
    """
    disponiveis = motores_disponiveis()
    if not disponiveis:
        raise ErroGeracaoIA(_sem_motor())

    # A política de roteamento entra AQUI, e só aqui: este é o único
    # lugar do sistema onde a cascata de motores é decidida. Com
    # `OMNIROUTE_ROUTING_ENABLED` desligado — o padrão — a lista volta
    # intacta e a ordem é a de sempre.
    #
    # Com ela ligada, a geração de um edital deixa de poder cair para um
    # motor não homologado só porque o principal ficou indisponível. Era
    # esse o buraco: a cascata é irrestrita, então uma queda da OpenAI no
    # meio de um edital descia para o motor seguinte sem que ninguém
    # tivesse homologado aquele modelo para documento que vira ato
    # administrativo.
    disponiveis = ai_gateway.motores_para(rotulo_registro, disponiveis)

    extras = {"rag_trace": rag_trace} if rag_trace is not None else {}
    for indice, (motor, chave) in enumerate(disponiveis):
        inicio = time.time()
        # `_ultimo_uso` é global e só era ESCRITO por chamada
        # bem-sucedida. Uma chamada que falhava registrava o modelo e os
        # tokens da anterior — e agora que o registro tem uma coluna de
        # CUSTO, isso deixaria de ser um metadado errado e passaria a ser
        # dinheiro cobrado de uma chamada que não aconteceu.
        _ultimo_uso.clear()
        try:
            texto = _chamar_motor(motor, system_prompt, user_prompt, chave,
                                  timeout=timeout, tentativas=tentativas,
                                  tarefa=rotulo_registro)
            # Qual motor respondeu de fato — o cache precisa saber, e
            # `_ultimo_uso` é onde os executores já depositam o que a
            # chamada revelou (modelo, tokens, request_id).
            _ultimo_uso["motor"] = motor
            registrar_geracao(rotulo_registro, motor, inicio, "ok",
                              fallback=indice > 0, **extras)
            return texto
        except ErroGeracaoIA as erro:
            registrar_geracao(rotulo_registro, motor, inicio, "falha",
                              erro=getattr(erro, "detalhe", "") or str(erro),
                              fallback=indice > 0, **extras)
            ultimo = indice == len(disponiveis) - 1
            if ultimo:
                raise
            if avisar:
                proximo = ROTULOS_MOTOR.get(disponiveis[indice + 1][0],
                                            disponiveis[indice + 1][0])
                st.warning(
                    f"Motor {ROTULOS_MOTOR.get(motor, motor)} indisponível "
                    f"— tentando {proximo}. {erro}\n\n"
                    f"`{getattr(erro, 'detalhe', '')}`")
    raise AssertionError("inalcançável: o último motor propaga ou retorna")


def _associar_rag_trace(doc_key: str, rag_trace: dict, texto: str) -> None:
    """
    Vincula o rastro do RAG ao documento SOMENTE após uma geração bem
    sucedida — e ao texto que ela produziu.

    Se todos os motores falharem, a função não é chamada: o rastro do
    documento anterior permanece intacto. Sem isso, uma tentativa
    fracassada de regerar substituiria a evidência e o documento vigente
    passaria a ser auditado com o rastro de outra geração.
    """
    import hashlib

    st.session_state.setdefault("_rag_trace", {})[doc_key] = {
        **rag_trace,
        "hash_texto": hashlib.sha256(texto.encode("utf-8")).hexdigest()[:16],
        "request_id": _ultimo_uso.get("request_id", ""),
        "modelo": _ultimo_uso.get("modelo", ""),
    }


def chamar_ia_texto(system_prompt: str, user_prompt: str,
                    finalidade: str = "revisao",
                    timeout: float | None = None,
                    tentativas: int = API_TENTATIVAS) -> str:
    """
    Chamada genérica de IA para a correção automática (auditor/corretor):
    mesma ordem de motores, fallback e registro técnico da geração de
    documentos — sem RAG, sem modo demo e sem pós-processamento.
    `finalidade` identifica a chamada no registro (ex.: 'corretor').
    `timeout`/`tentativas` deixam tarefas rápidas (auditor) desistir bem
    antes do teto de geração — sem esperar minutos por um motor lento.
    """
    return _percorrer_motores(finalidade, system_prompt, user_prompt,
                              avisar=False, timeout=timeout,
                              tentativas=tentativas)


def testar_conexao(motor: str) -> tuple[bool, str]:
    """
    Faz uma chamada mínima ao motor ('openai' | 'gemini' | 'openrouter') e
    devolve (ok, mensagem). Usado pelo botão "Testar conexão" do painel
    admin para diagnosticar chave/modelo com o erro técnico exato.

    Motor desconhecido é RECUSADO por nome. A versão anterior tratava
    qualquer coisa diferente de 'openai' como Gemini — com três motores,
    isso faria um "testar OpenRouter" reportar o Gemini como se fosse ele.
    """
    system = "Responda apenas com a palavra OK."
    user = "Responda: OK"
    chaves = {
        "openai": (obter_openai_key, "OPENAI_API_KEY", _modelos_openai,
                   "OpenAI"),
        "gemini": (obter_api_key, "GOOGLE_API_KEY", _modelos_gemini,
                   "Gemini"),
        "openrouter": (obter_openrouter_key, "OPENROUTER_API_KEY",
                       _modelos_openrouter, "OpenRouter"),
    }
    if motor not in chaves:
        return False, (f"Motor desconhecido: {motor!r}. "
                       f"Use um de: {', '.join(sorted(chaves))}.")
    obter, nome_var, listar_modelos, rotulo = chaves[motor]
    try:
        chave = obter()
        if not chave:
            return False, f"{nome_var} não configurada."
        _chamar_motor(motor, system, user, chave)
        return True, (f"{rotulo} respondeu. Modelos tentados: "
                      f"{', '.join(listar_modelos())}.")
    except ErroGeracaoIA as erro:
        # `detalhe` já sai sanitizado de ErroGeracaoIA.__init__
        detalhe = getattr(erro, "detalhe", "")
        return False, f"{erro}\n\n{detalhe}"
    except Exception as exc:  # noqa: BLE001
        from . import db

        return False, (
            "Falha inesperada ao testar o motor. Referência: "
            f"{db.registrar_incidente(exc, 'llm: teste de motor')}.")


# ---------------------------------------------------------------------------
# Modo demonstração (offline) — minutas-esqueleto a partir do formulário
# ---------------------------------------------------------------------------
def _gerar_demo(doc_key: str, dados: dict) -> str:
    """
    Minuta-esqueleto offline do Modo Demonstração.

    Escreve apenas DADOS OBJETIVOS do formulário e a tabela oficial. Não
    reutiliza o bloco destinado ao modelo: era daí que "PROIBIDO escrever
    a lista de itens", "EXATAMENTE UMA VEZ" e "para você compreender o
    que se contrata" chegavam ao corpo de um documento administrativo.
    """
    doc = DOCUMENTOS[doc_key]
    dados_fmt = dados_objetivos_do_formulario(dados)
    cabecalho = (
        f"# {doc['titulo'].upper()}\n\n"
        f"*Minuta-esqueleto gerada em Modo Demonstração (sem IA) — "
        f"base legal: {doc['base_legal']}.*\n\n"
        f"## 1. Identificação\n\n- Órgão requisitante: "
        f"{dados.get('orgao') or '[PREENCHER: órgão requisitante]'}\n"
        f"- Responsável: "
        f"{dados.get('responsavel') or '[PREENCHER: responsável pela demanda]'}\n\n"
        f"## 2. Objeto\n\n{dados.get('objeto') or '[PREENCHER: objeto]'}\n\n"
        f"## 3. Justificativa da Necessidade\n\n"
        f"{dados.get('justificativa') or '[PREENCHER: justificativa da necessidade]'}\n\n"
    )
    corpo = {
        "dfd": (
            f"## 4. Alinhamento ao Planejamento\n\n{dados.get('alinhamento') or '[PREENCHER: PCA]'}\n\n"
            "## 5. Estimativa Preliminar de Valor\n\nConforme dados informados:\n\n"
            f"{dados_fmt}\n\n"
            f"## 6. Previsão e Prioridade\n\n{dados.get('prazo') or '[PREENCHER: prazo]'}\n\n"
            "## 7. Encaminhamento\n\nEncaminha-se para autorização da autoridade "
            "competente, nos termos do art. 12, VII, da Lei nº 14.133/2021.\n\n"
            "Local e data: [PREENCHER: local e data de assinatura]\n\n"
            "Assinatura: ________________________"
        ),
        "etp": (
            f"## 4. Requisitos da Contratação (art. 18, §1º, III)\n\n"
            f"{dados.get('requisitos') or '[PREENCHER: requisitos da contratação]'}\n\n"
            "## 5. Levantamento de Mercado (art. 18, §1º, V)\n\n[PREENCHER: pesquisa de mercado]\n\n"
            "## 6. Justificativa do Parcelamento (art. 18, §1º, VIII)\n\n"
            f"Modelo de execução informado: "
            f"{dados.get('modelo_execucao') or '[PREENCHER: modelo de execução]'}. "
            "[PREENCHER: análise do parcelamento]\n\n"
            # Células da matriz ficam SEM descrição de propósito: na
            # revisão o nome do campo vem do cabeçalho da coluna e a
            # lacuna é tratada como posicional (a "Mitigação" da linha A
            # não é a da linha B). Um marcador descrito seria idêntico
            # entre linhas e as respostas se sobreporiam.
            "## 7. Matriz de Riscos\n\n"
            "| Risco | Probabilidade | Impacto | Mitigação | Responsável |\n"
            "|---|---|---|---|---|\n"
            f"| {dados.get('riscos') or '[PREENCHER]'} | [PREENCHER] | [PREENCHER] | [PREENCHER] | [PREENCHER] |\n\n"
            "## 8. Declaração de Viabilidade (art. 18, §1º, XIII)\n\n[PREENCHER: conclusão]"
        ),
        "tr": (
            f"## 4. Requisitos e Especificações (art. 6º, XXIII, 'd')\n\n"
            f"{dados.get('requisitos') or '[PREENCHER: requisitos e especificações]'}\n\n"
            "## 5. Modelo de Execução e Fiscalização\n\n"
            f"{dados.get('modelo_execucao') or '[PREENCHER: modelo de execução]'} "
            "— gestor e fiscal do contrato a designar (art. 117).\n\n"
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
