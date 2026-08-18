"""
Persistência dos processos no Supabase (PostgreSQL).

Cada "processo" é uma linha na tabela public.processos contendo o
Formulário Matriz (jsonb), os documentos gerados/editados (jsonb), a
lista de aprovados e a etapa atual — permitindo salvar o andamento e
retomá-lo depois, de qualquer máquina.

Configuração:
    .streamlit/secrets.toml  ➜  SUPABASE_URL e SUPABASE_SECRET_KEY
    ou as variáveis de ambiente equivalentes.

Em DESENVOLVIMENTO, sem Supabase, a aplicação roda sem persistência e o
painel "Processos salvos" fica desativado.

Em PRODUÇÃO isso não vale: com GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR=1, a
ausência da credencial de servidor coloca o app em MANUTENÇÃO — nada de
login, persistência, aprovação, geração oficial ou emissão, e nenhum
fallback para a chave publicável.
"""

import base64
import binascii
import hashlib
import json
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import streamlit as st

from . import trilha

_log = logging.getLogger(__name__)


class ErroBanco(Exception):
    """Erro de banco já traduzido em mensagem amigável para a interface."""


# ---------------------------------------------------------------------------
# Credencial de banco — achado P0 de 14/08/2026 (preventivo)
#
# O app roda INTEIRO no servidor (Streamlit): o navegador recebe a
# interface renderizada, nunca a credencial. Ainda assim a chave
# publicável DEVE ser tratada como pública — é a premissa do modelo do
# Supabase, que coloca a autorização no RLS. Como hoje não há RLS
# efetivo, o app passa a exigir uma credencial de servidor.
#
# Chave atual: SUPABASE_SECRET_KEY, no formato `sb_secret_...`.
# A `service_role` legada (JWT) é aceita apenas para TRANSIÇÃO, com
# aviso de descontinuação — ver `avisos_de_credencial()`.
#
# Origem: Streamlit Secrets ou variável de ambiente. NUNCA o banco (a
# credencial do banco não pode depender do banco), nunca log, nunca
# mensagem de erro, nunca frontend.
# ---------------------------------------------------------------------------
NOME_CHAVE_SERVIDOR = "SUPABASE_SECRET_KEY"
NOME_CHAVE_SERVIDOR_LEGADA = "SUPABASE_SERVICE_KEY"
NOME_CHAVE_PUBLICA = "SUPABASE_KEY"
FLAG_EXIGIR_SERVIDOR = "GOVDOCS_EXIGIR_CREDENCIAL_SERVIDOR"

PREFIXO_CHAVE_ATUAL = "sb_secret_"


def _segredo(nome: str) -> str:
    """
    Lê de Streamlit Secrets, com o ambiente como origem alternativa.

    NUNCA consulta o banco e nunca devolve o valor para log ou mensagem:
    quem chama usa o valor apenas para abrir a conexão.
    """
    valor = os.getenv(nome, "")
    try:
        valor = str(st.secrets.get(nome, valor))
    except Exception:
        pass  # sem arquivo secrets.toml — usa apenas o ambiente
    return valor.strip()


def exigir_credencial_servidor() -> bool:
    """Falha fechada ligada? Produção deve manter ligada."""
    return _segredo(FLAG_EXIGIR_SERVIDOR).lower() in ("1", "true", "on", "sim")


def _credencial_de_servidor() -> tuple[str, str]:
    """(valor, origem) — origem em {'atual', 'legada', ''}."""
    atual = _segredo(NOME_CHAVE_SERVIDOR)
    if atual:
        return atual, "atual"
    legada = _segredo(NOME_CHAVE_SERVIDOR_LEGADA)
    if legada:
        return legada, "legada"
    return "", ""


def credencial_de_servidor_presente() -> bool:
    """Diagnóstico booleano — jamais expõe o valor."""
    return bool(_credencial_de_servidor()[0])


# Formato das credenciais aceitas como sendo DE SERVIDOR.
#
# `sb_secret_…` é a chave secreta atual. A `service_role` legada é um
# JWT cujo payload DECLARA o papel — e é o papel declarado, não a
# forma, que decide se ela serve. A assinatura não é verificada aqui:
# validá-la é trabalho do Supabase, e nós não temos o segredo.
PREFIXO_CHAVE_PUBLICA = "sb_publishable_"
_RE_JWT = re.compile(r"^ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\."
                     r"[A-Za-z0-9_-]{10,}$")
_TAMANHO_MINIMO_SECRETA = len(PREFIXO_CHAVE_ATUAL) + 16

PAPEL_DE_SERVIDOR = "service_role"


def _papel_do_jwt(valor: str) -> str:
    """
    Papel declarado no payload do JWT — "" quando não dá para saber.

    Decodifica LOCALMENTE, sem rede e sem verificar assinatura: a
    assinatura é problema do Supabase, e nós não temos o segredo para
    conferi-la. O que se apura aqui é outra coisa, e é o que importa
    para a falha fechada: *qual papel esta chave carrega*.

    Sem isto, `role: anon` num JWT bem formado passava como credencial
    de servidor — a forma estava certa, e a forma era tudo que se
    conferia. O app subiria com privilégio de anônimo acreditando ser
    servidor, que é exatamente o estado que a falha fechada existe para
    impedir.

    NUNCA registra nem devolve o payload: só o papel.
    """
    partes = valor.split(".")
    if len(partes) != 3:
        return ""
    corpo = partes[1]
    corpo += "=" * (-len(corpo) % 4)          # padding base64url
    try:
        bruto = base64.urlsafe_b64decode(corpo.encode("ascii"))
        conteudo = json.loads(bruto)
    except (ValueError, binascii.Error, UnicodeDecodeError):
        return ""
    if not isinstance(conteudo, dict):
        return ""
    papel = conteudo.get("role")
    return papel if isinstance(papel, str) else ""


def credencial_invalida(valor: str, origem: str) -> str:
    """
    Motivo pelo qual o valor NÃO serve como credencial de servidor —
    "" quando serve.

    Descreve o problema pelo FORMATO; nunca ecoa o valor.

    Isto existe porque "presente" não é "válida". Uma chave publicável
    colada no campo errado é uma credencial presente, e o app subia com
    ela: conectava como `anon`, sem privilégio de servidor, e a falha
    fechada — que existe justamente para impedir isso — dava por
    satisfeita. O erro chegaria depois, disfarçado de "permissão
    negada" no meio de uma operação de negócio.
    """
    if not valor:
        return "ausente"
    if valor.startswith(PREFIXO_CHAVE_PUBLICA):
        return (f"{NOME_CHAVE_SERVIDOR} contém uma chave PUBLICÁVEL "
                f"(`{PREFIXO_CHAVE_PUBLICA}…`). Essa chave não tem "
                "privilégio de servidor: usá-la equivale a operar como "
                "anônimo.")
    if origem == "legada":
        if not _RE_JWT.match(valor):
            return (f"{NOME_CHAVE_SERVIDOR_LEGADA} não tem o formato de um "
                    "JWT.")
        papel = _papel_do_jwt(valor)
        if not papel:
            return (f"{NOME_CHAVE_SERVIDOR_LEGADA} não declara `role` em um "
                    "payload JSON legível. Forma de JWT não é credencial de "
                    "servidor.")
        if papel != PAPEL_DE_SERVIDOR:
            # A mensagem nomeia o papel encontrado, que NÃO é segredo —
            # é justamente o diagnóstico de que se precisa. O valor da
            # chave e o payload continuam fora daqui.
            return (f"{NOME_CHAVE_SERVIDOR_LEGADA} carrega `role={papel}`, "
                    f"não `{PAPEL_DE_SERVIDOR}`. Essa chave não tem "
                    "privilégio de servidor.")
        return ""
    if not valor.startswith(PREFIXO_CHAVE_ATUAL):
        return (f"{NOME_CHAVE_SERVIDOR} não começa com "
                f"`{PREFIXO_CHAVE_ATUAL}`. Chaves de servidor atuais têm "
                "esse prefixo; um valor arbitrário aqui não é credencial.")
    if len(valor) < _TAMANHO_MINIMO_SECRETA:
        return (f"{NOME_CHAVE_SERVIDOR} tem o prefixo correto mas é curta "
                "demais para ser uma chave real — parece um placeholder.")
    return ""


def credencial_de_servidor_valida() -> bool:
    """Presente E com formato de credencial de servidor."""
    valor, origem = _credencial_de_servidor()
    return not credencial_invalida(valor, origem)


def avisos_de_credencial() -> list[str]:
    """
    Avisos operacionais sobre a credencial em uso. Descrevem FORMATO e
    ORIGEM; nunca o valor.
    """
    valor, origem = _credencial_de_servidor()
    avisos = []
    if origem == "legada" and not credencial_invalida(valor, origem):
        avisos.append(
            f"{NOME_CHAVE_SERVIDOR_LEGADA} (service_role legada) está em "
            f"uso. Aceita apenas para transição — migre para "
            f"{NOME_CHAVE_SERVIDOR} (`{PREFIXO_CHAVE_ATUAL}…`), que pode "
            "ser rotacionada isoladamente."
        )
    return avisos


def motivo_de_manutencao() -> str:
    """
    Por que o app deve entrar em MANUTENÇÃO — "" quando pode operar.

    Falha FECHADA de verdade: sem a credencial de servidor obrigatória,
    o app não opera em modo degradado nem cai para a chave publicável.
    Login, persistência, aprovação, geração oficial e emissão ficam
    todos bloqueados.
    """
    if not exigir_credencial_servidor():
        return ""
    valor, origem = _credencial_de_servidor()
    problema = credencial_invalida(valor, origem)
    if not problema:
        # Formato aprovado. Falta a única prova que vale: o banco
        # aceitar a credencial com privilégio de servidor.
        return problema_de_capacidade()
    if problema == "ausente":
        problema = (f"{NOME_CHAVE_SERVIDOR} não está configurada nos "
                    "Secrets do servidor.")
    return (
        f"Credencial de servidor inválida. {problema} Enquanto isso, a "
        "aplicação permanece em manutenção: nenhuma operação é executada "
        "com a chave publicável."
    )


# ---------------------------------------------------------------------------
# Sonda remota de capacidade privilegiada
#
# Formato não é validade. Uma chave `sb_secret_…` perfeitamente bem
# formada pode estar REVOGADA, ter sido copiada errada, ou pertencer a
# outro projeto — e nada disso aparece olhando a string. O único jeito
# de saber se a credencial tem privilégio de servidor é PEDIR ao
# servidor.
#
# A sonda é deliberadamente mínima: lê ZERO linhas de um objeto que,
# depois da 0019, está fechado a `anon` e autorizado ao papel de
# servidor. Se a resposta vier, o privilégio existe. Nada de conteúdo
# trafega, nada é registrado além do sucesso ou do fracasso.
# ---------------------------------------------------------------------------
FLAG_SONDAR_CREDENCIAL = "GOVDOCS_SONDAR_CREDENCIAL"
TABELA_DA_SONDA = "config_app"
_TTL_DA_SONDA = 300          # segundos


def sondar_credencial_ativa() -> bool:
    """
    A sonda remota está ativa?

    OBRIGATÓRIA sempre que a credencial de servidor for exigida — ou
    seja, em produção. Enquanto era opcional, a falha fechada só
    conferia o FORMATO: uma `sb_secret_…` revogada tinha forma
    impecável e passava, e o app subia achando que tinha privilégio.
    Deixar isso ligado por configuração significa que basta esquecer a
    variável para a validação mais importante sumir sem aviso.

    `GOVDOCS_SONDAR_CREDENCIAL=0` DESLIGA explicitamente — existe para
    diagnóstico e para ambiente sem rede, e é uma decisão registrada,
    não um esquecimento.
    """
    escolha = _segredo(FLAG_SONDAR_CREDENCIAL).lower()
    if escolha in ("0", "false", "off", "nao", "não"):
        return False
    if escolha in ("1", "true", "on", "sim"):
        return True
    return exigir_credencial_servidor()   # produção: ligada por padrão


def impressao_da_credencial(valor: str) -> str:
    """
    Impressão digital da credencial. Nunca é registrada nem exibida —
    existe só para CHAVEAR o cache da sonda.
    """
    return hashlib.sha256(valor.encode()).hexdigest()[:16]


@st.cache_resource(show_spinner=False, ttl=_TTL_DA_SONDA)
def _sonda_bem_sucedida(impressao_da_credencial: str) -> bool:
    """
    Sonda cacheada, chaveada pela IMPRESSÃO DA CREDENCIAL.

    O nome do parâmetro importa: no Streamlit, argumento com underscore
    à frente é EXCLUÍDO da chave de cache. Chamava-se
    `_impressao_da_credencial`, então a impressão não participava da
    chave — e o cache de uma credencial válida sobrevivia à rotação e à
    revogação. Trocar a chave em produção manteria o app operando por
    todo o TTL com o resultado da chave ANTIGA, que é exatamente o
    contrário do que a sonda existe para fazer.

    Levanta a exceção original em caso de falha, de propósito: o
    Streamlit não cacheia exceção, então falha transitória de rede é
    retentada na execução seguinte em vez de prender o app em
    manutenção pelo TTL inteiro.
    """
    from supabase import create_client

    url, chave = _config()
    cliente = create_client(url, chave)
    cliente.table(TABELA_DA_SONDA).select("*").limit(0).execute()
    return True


def problema_de_capacidade() -> str:
    """
    Motivo pelo qual a credencial NÃO comprova privilégio de servidor —
    "" quando comprova ou quando a sonda está desligada.
    """
    if not sondar_credencial_ativa():
        return ""
    valor, origem = _credencial_de_servidor()
    if not valor or credencial_invalida(valor, origem):
        return ""            # o formato já reprovou; não há o que sondar
    try:
        _sonda_bem_sucedida(impressao_da_credencial(valor))
    except Exception as exc:  # noqa: BLE001
        correlacao = registrar_incidente(exc, "sonda de credencial")
        return (
            "A credencial de servidor não comprovou privilégio no banco. "
            "Ela pode estar revogada, ter sido copiada incorretamente ou "
            "pertencer a outro projeto. O detalhe técnico ficou registrado "
            f"no servidor. Referência: {correlacao}.")
    return ""


def em_manutencao() -> bool:
    return bool(motivo_de_manutencao())


def exigir_operacional() -> None:
    """
    Barreira única de manutenção. Levanta ErroBanco quando o app não
    pode operar.

    Chamada em TODOS os caminhos que a manutenção precisa fechar —
    login, persistência, aprovação, geração oficial e emissão — para
    que a proteção não dependa de a interface ter sido renderizada na
    ordem certa.
    """
    if motivo := motivo_de_manutencao():
        raise ErroBanco(motivo)


def _config() -> tuple[str, str]:
    """
    (url, chave). Prefere a credencial de servidor. Com a falha fechada
    ligada e sem essa credencial, levanta ErroBanco — jamais cai para a
    chave publicável.
    """
    url = _segredo("SUPABASE_URL")
    servidor, origem = _credencial_de_servidor()
    # Em produção, uma credencial MAL FORMADA não vale como credencial:
    # com `sb_publishable_…` no campo errado, o app conectaria como
    # anônimo achando que é servidor.
    if servidor and not (exigir_credencial_servidor()
                         and credencial_invalida(servidor, origem)):
        return url, servidor
    if exigir_credencial_servidor():
        raise ErroBanco(motivo_de_manutencao())
    return url, _segredo(NOME_CHAVE_PUBLICA)


def disponivel() -> bool:
    """
    True se há credencial utilizável. Em manutenção devolve False — mas
    o app NÃO segue "sem persistência": `em_manutencao()` bloqueia a
    interface inteira antes disso (ver app.py).

    A checagem de manutenção vem PRIMEIRO e é o que traz o veredito da
    sonda remota: `_config()` sozinho só sabe do formato, e uma chave
    de formato impecável mas revogada passaria por ele.
    """
    if em_manutencao():
        return False
    try:
        url, chave = _config()
    except ErroBanco:
        return False
    return bool(url and chave)


@st.cache_resource(show_spinner=False)
def _cliente():
    """
    Cliente de SERVIDOR. Carrega a credencial secreta e, portanto,
    ATRAVESSA o RLS: toda linha é visível e gravável para ele.

    Não é o cliente das operações de usuário. Ver `cliente_do_usuario()`
    e `docs/etapa-e-credencial-de-servidor.md`.
    """
    from supabase import create_client  # import tardio: app abre sem a lib

    exigir_operacional()
    url, chave = _config()
    return create_client(url, chave)


# ---------------------------------------------------------------------------
# Etapa E — a operação do USUÁRIO tem de ir com o JWT do usuário
#
# Enquanto tudo passa por `_cliente()`, o RLS da 0020 não é exercido em
# lugar nenhum: a credencial de servidor o atravessa por definição. Uma
# política que nunca é avaliada não protege nada — ela só parece
# proteger, o que é pior, porque a matriz de 28 tabelas passa a ser
# lida como garantia.
#
# O token vem da sessão do Supabase Auth, gravado no login. Enquanto a
# 0020 não for aplicada não existe login de Supabase Auth neste app (a
# autenticação é a própria tabela `usuarios`, com `senha_hash`), então
# `sessao_do_usuario()` devolve None e quem exige JWT recusa. É
# deliberado: a alternativa seria cair no servidor em silêncio, que é
# exatamente o defeito.
# ---------------------------------------------------------------------------
CHAVE_DA_SESSAO = "supabase_access_token"


def sessao_do_usuario() -> str | None:
    """Access token do Supabase Auth desta sessão, se houver."""
    token = st.session_state.get(CHAVE_DA_SESSAO)
    return token if isinstance(token, str) and token else None


def cliente_do_usuario():
    """
    Cliente ligado ao JWT do USUÁRIO — o único em que o RLS vale.

    Devolve None quando não há sessão do Supabase Auth. NÃO cai para o
    cliente de servidor: quem chama decide o que fazer com a ausência,
    e a decisão fica visível no ponto de chamada em vez de escondida
    aqui dentro.

    Sem cache: o token expira e roda. Um `cache_resource` guardaria o
    primeiro token para sempre — e, num app multiusuário, o token de
    quem chegou primeiro para todo mundo.
    """
    from supabase import create_client

    token = sessao_do_usuario()
    if not token:
        return None
    exigir_operacional()
    url = _segredo("SUPABASE_URL")
    publica = _segredo(NOME_CHAVE_PUBLICA)
    if not (url and publica):
        return None
    cliente = create_client(url, publica)
    cliente.postgrest.auth(token)
    return cliente


# ---------------------------------------------------------------------------
# Redação de segredos e identificador de correlação
#
# Erros de API trazem a credencial dentro da própria mensagem: cabeçalho
# `apikey`, querystring, corpo devolvido pelo PostgREST, corpo JSON do
# httpx, traceback multilinha. O caminho genérico de `_traduzir_erro`
# repassava esse texto para a tela e para o log.
#
# A regra passou a ser dupla, porque expressão regular sozinha não é
# defesa suficiente contra um formato de credencial que ainda não
# conhecemos:
#
#   1. a INTERFACE nunca recebe o texto original — recebe uma mensagem
#      genérica e um identificador de correlação;
#   2. o LOG recebe o texto já sanitizado, e só o log.
#
# Assim, um segredo em formato novo — que escape de todos os padrões
# abaixo — ainda assim não chega à tela: no máximo fica no log do
# servidor, que já é área restrita.
# ---------------------------------------------------------------------------
_REDIGIDO = "[REDIGIDO]"

# Formatos conhecidos de credencial. Sem âncora de início/fim: precisam
# casar no meio de URL, JSON, cabeçalho e texto colado.
_RE_TOKEN = re.compile(
    r"(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}(?:\.[A-Za-z0-9_-]+)?"  # JWT
    r"|sb_(?:publishable|secret)_[A-Za-z0-9_-]{8,}"    # chaves Supabase novas
    r"|sk-[A-Za-z0-9_-]{16,}"                          # OpenAI
    r"|AIza[A-Za-z0-9_-]{20,}"                         # Google
    r"|gh[pousr]_[A-Za-z0-9]{16,}"                     # GitHub
    r"|pbkdf2_[a-z0-9]+\$[^\s\"',}\]]+)")              # hash de senha

# Parâmetro nomeado, em qualquer sintaxe: `apikey=…`, `"apikey": "…"`,
# `apikey: …`, e as formas percent-encoded (`apikey%3D…`) que aparecem
# quando a URL inteira vem escapada dentro da mensagem.
_NOMES_SENSIVEIS = (
    r"apikey|api[_-]?key|authorization|bearer|token|access[_-]?token|"
    r"refresh[_-]?token|senha|senha_hash|password|secret|service[_-]?role|"
    r"anon[_-]?key|supabase[_-]?(?:key|secret[_-]?key|service[_-]?key)"
)
_RE_PARAMETRO = re.compile(
    rf"((?:{_NOMES_SENSIVEIS})\s*(?:=|:|%3[AD])\s*[\"']?)"
    r"[^\s\"',&}\]]+",
    re.IGNORECASE)

# Credencial embutida na própria URL (`https://usuario:senha@host`).
_RE_USERINFO = re.compile(r"(//)[^/\s:@]+:[^/\s@]+(@)")

# A referência do projeto identifica a instalação e não ajuda o usuário.
_RE_PROJETO = re.compile(
    r"https?://[a-z0-9-]+\.(supabase\.(?:co|in)|supabase\.co)",
    re.IGNORECASE)

# Sobra opaca longa: base64/hex sem rótulo algum. Último recurso, com
# limiar alto para não engolir mensagem útil.
_RE_OPACO = re.compile(r"\b[A-Za-z0-9+/]{40,}={0,2}\b")


def redigir(texto: str) -> str:
    """
    Remove credenciais de qualquer texto antes de registrar em log.

    Trabalha sobre URL, querystring, cabeçalho, JSON, texto multilinha e
    valores percent-encoded. NÃO é a única barreira: a interface recebe
    mensagem genérica, nunca este texto (ver `_traduzir_erro`).
    """
    texto = _RE_TOKEN.sub(_REDIGIDO, texto or "")
    texto = _RE_PARAMETRO.sub(rf"\1{_REDIGIDO}", texto)
    texto = _RE_USERINFO.sub(rf"\1{_REDIGIDO}\2", texto)
    texto = _RE_PROJETO.sub("https://[PROJETO].supabase.co", texto)
    return _RE_OPACO.sub(_REDIGIDO, texto)


_redigir = redigir   # nome anterior, mantido para não quebrar chamadas


def registrar_incidente(exc: Exception, contexto: str = "banco") -> str:
    """
    Registra a falha SANITIZADA no log do servidor e devolve um
    identificador de correlação para mostrar ao usuário.

    O identificador não carrega informação: é aleatório e serve só para
    casar a reclamação ("deu erro FA3C91B2") com a linha do log.
    """
    correlacao = uuid.uuid4().hex[:8].upper()
    _log.error("[%s] falha em %s: %s",
               correlacao, contexto, redigir(f"{type(exc).__name__}: {exc}"))
    return correlacao


def _traduzir_erro(exc: Exception) -> ErroBanco:
    """
    Converte a exceção em mensagem para a tela.

    As categorias reconhecidas viram orientação acionável; o resto vira
    mensagem genérica com identificador de correlação. Em nenhum caso o
    texto original da exceção chega à interface.
    """
    texto = str(exc).lower()
    correlacao = registrar_incidente(exc)
    if "connection" in texto or "timeout" in texto or "resolve" in texto:
        return ErroBanco(
            "Não foi possível conectar ao Supabase. Verifique sua internet "
            "e se o projeto está ativo (projetos gratuitos pausam por "
            f"inatividade). Referência: {correlacao}."
        )
    if "jwt" in texto or "api key" in texto or "invalid" in texto and "key" in texto:
        return ErroBanco(
            "Credenciais do Supabase inválidas. Confira SUPABASE_URL e a "
            f"credencial de servidor nos Secrets. Referência: {correlacao}."
        )
    return ErroBanco(
        "Falha ao acessar o banco de dados. O detalhe técnico ficou "
        "registrado no servidor; informe a referência ao suporte. "
        f"Referência: {correlacao}."
    )


def salvar_processo(
    processo_id: str | None,
    dados: dict,
    documentos: dict,
    aprovados: set,
    etapa: int,
    usuario_id: str | None = None,
    secretaria_id: str | None = None,
    auth_user_id: str | None = None,
) -> str:
    """
    Cria ou atualiza o processo e retorna seu id (uuid).

    `auth_user_id` é o dono no Supabase Auth, e é o que a 0020 usa nas
    políticas (`auth.uid()`). `usuario_id` guarda `usuarios.id`, da
    tabela própria do app — os dois identificadores são DIFERENTES, e
    confundi-los trancaria cada servidor para fora dos próprios
    processos.

    Preenchê-lo desde já encolhe o backfill da 0020: só os processos
    anteriores à transição precisarão de conversão.
    """
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
    if auth_user_id:
        # Só grava quando a coluna existe (ETAPA C da 0020). Antes
        # disso o PostgREST recusaria a coluna desconhecida.
        registro["auth_user_id"] = auth_user_id
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
# Centro de Governança (migração 0010 — pacote V6)
# ---------------------------------------------------------------------------
def obter_ou_criar_artefato(tipo_artefato: str, chave_estavel: str,
                            plataforma: bool = False,
                            secretaria_id: str | None = None) -> dict:
    """
    Artefato do escopo pedido (plataforma = tenant NULL; senão, tenant
    da sessão). Idempotente: devolve o existente se já houver.
    """
    tenant = None if plataforma else tenant_atual()
    try:
        tabela = _cliente().table("governanca_artefatos")
        consulta = (tabela.select("*")
                    .eq("tipo_artefato", tipo_artefato)
                    .eq("chave_estavel", chave_estavel))
        consulta = (consulta.is_("tenant_id", "null") if tenant is None
                    else consulta.eq("tenant_id", tenant))
        existentes = consulta.limit(1).execute().data
        if existentes:
            return existentes[0]
        registro = {"tipo_artefato": tipo_artefato,
                    "chave_estavel": chave_estavel,
                    "tenant_id": tenant, "secretaria_id": secretaria_id}
        return tabela.insert(registro).execute().data[0]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_artefatos(tipo_artefato: str | None = None) -> list[dict]:
    """Artefatos visíveis: plataforma (tenant NULL) + tenant da sessão."""
    try:
        consulta = _cliente().table("governanca_artefatos").select("*")
        if tipo_artefato:
            consulta = consulta.eq("tipo_artefato", tipo_artefato)
        registros = consulta.order("chave_estavel").execute().data or []
        atual = tenant_atual()
        return [r for r in registros
                if r.get("tenant_id") in (None, atual)]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def criar_versao_governanca(artefato_id: str, registro: dict) -> dict:
    campos = {k: registro[k] for k in
              ("versao", "status", "vigencia_inicio", "vigencia_fim",
               "payload", "hash") if k in registro}
    campos["artefato_id"] = artefato_id
    if registro.get("autor"):
        campos["autor"] = registro["autor"]
    try:
        resposta = _cliente().table("governanca_versoes").insert(
            campos).execute()
        return resposta.data[0]
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def listar_versoes_governanca(artefato_id: str) -> list[dict]:
    try:
        resposta = (
            _cliente().table("governanca_versoes").select("*")
            .eq("artefato_id", artefato_id)
            .order("versao", desc=True).execute()
        )
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def atualizar_versao_governanca(versao_id: str, **campos) -> dict:
    """
    Atualiza uma versão EDITÁVEL (DRAFT/UNDER_REVIEW) ou aplica uma
    transição de status. Versão publicada é imutável: qualquer outra
    alteração exige derivar nova versão.
    """
    try:
        tabela = _cliente().table("governanca_versoes")
        atual = tabela.select("status").eq("id", versao_id).limit(1)\
            .execute()
        status_atual = atual.data[0]["status"] if atual.data else ""
        so_transicao = set(campos) <= {"status", "revisor", "aprovador",
                                       "vigencia_inicio", "vigencia_fim"}
        if status_atual not in ("DRAFT", "UNDER_REVIEW") and \
                not so_transicao:
            raise ErroBanco(
                "Versão publicada é imutável — derive uma nova versão.")
        campos["atualizado_em"] = datetime.now(timezone.utc).isoformat()
        resposta = tabela.update(campos).eq("id", versao_id).execute()
        if not resposta.data:
            raise ErroBanco("Versão não encontrada para atualizar.")
        return resposta.data[0]
    except ErroBanco:
        raise
    except Exception as exc:  # noqa: BLE001
        raise _traduzir_erro(exc) from exc


def registrar_evento_governanca(tipo_evento: str, entidade_tipo: str,
                                entidade_id: str | None,
                                payload: dict | None = None) -> None:
    """
    Trilha de auditoria do Centro. ÚNICO caminho: a RPC.

    O que mudou, e por quê
    ----------------------
    Antes isto era um `insert` direto em `governanca_eventos`, com
    `ator` vindo como PARÂMETRO, feito pelo cliente de SERVIDOR. Três
    defeitos numa linha só:

      * `ator` de parâmetro é assinatura de quem o chamador quiser. A
        trilha ficava com o nome certo só enquanto ninguém quisesse o
        contrário;
      * o cliente de servidor atravessa o RLS, então nenhuma política
        de `governanca_eventos` era exercida;
      * `insert` direto não passa por autorização nenhuma: estar
        autenticado bastava para registrar um ato de governança.

    A RPC da 0020 resolve os três de uma vez: `ator` sai de
    `auth.uid()` dentro da função, o papel é conferido contra a matriz,
    e a entidade é resolvida até o objeto governado.

    `ator` deixou de ser parâmetro AQUI também, e não por simetria: um
    parâmetro que o servidor ignora ainda ensina quem lê o código que a
    identidade é do chamador.
    """
    trilha.exigir_evento_valido(tipo_evento, entidade_tipo)
    cliente = cliente_do_usuario()
    if cliente is None:
        raise ErroBanco(
            "Trilha de governança exige sessão autenticada: o ato não foi "
            "registrado e, portanto, não pode ser dado como praticado. "
            "(Requer a migração 0020 aplicada e login por Supabase Auth.)")
    try:
        cliente.rpc("registrar_evento_governanca", {
            "p_tipo_evento": tipo_evento,
            "p_entidade_tipo": entidade_tipo,
            "p_entidade_id": entidade_id,
            "p_payload": payload or {},
        }).execute()
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
    linha = {
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
    }
    # P1: rastro do RAG (coluna `rag_trace`, migração 0011). Antes dela a
    # coluna não existe — o insert é refeito sem o campo, preservando a
    # compatibilidade com bancos ainda não migrados.
    trace = registro.get("rag_trace") or {}
    try:
        _cliente().table("geracoes").insert(
            {**linha, "rag_trace": trace} if trace else linha).execute()
    except Exception:  # noqa: BLE001
        if not trace:
            return
        try:
            _cliente().table("geracoes").insert(linha).execute()
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
