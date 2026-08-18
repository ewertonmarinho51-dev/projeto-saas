#!/usr/bin/env python3
"""
Ensaio da contenção P0 — ANTES e DEPOIS, com rollback.

NÃO aplica nada em produção. Exige um projeto de ENSAIO próprio e
recusa-se a rodar se a URL apontar para o projeto de produção conhecido.

    export GOVDOCS_ENSAIO_URL=...            # projeto de ensaio
    export GOVDOCS_ENSAIO_ANON_KEY=...       # chave publicável do ensaio
    export GOVDOCS_ENSAIO_SECRET_KEY=...     # credencial de servidor
    export GOVDOCS_ENSAIO_EMAIL=...          # conta comum do Auth (ensaio)
    export GOVDOCS_ENSAIO_SENHA=...          # senha dessa conta

    python scripts/ensaio_seguranca.py --sondar     # mede tudo
    python scripts/ensaio_seguranca.py --instrucoes # imprime o SQL a rodar

O ensaio prova QUATRO coisas, não uma:

  1. `anon` é NEGADO em toda tabela, sequence e RPC;
  2. `authenticated` sem política de titularidade também é NEGADO —
     fechar só o `anon` apenas move o problema para quem se cadastra;
  3. as operações legítimas do SERVIDOR continuam funcionando — é o
     que separa "contido" de "quebrado";
  4. um objeto NOVO nasce fechado — prova de que os default privileges
     foram revogados e a vulnerabilidade não volta na próxima migração.

O relatório imprime APENAS: objeto, operação, papel e veredito. Nunca
valores de linha, credenciais, hashes ou dados pessoais.
"""

import argparse
import hashlib
import os
import re
import sys
import urllib.parse
import uuid
from pathlib import Path

# Guarda contra produção, por HASH da referência do projeto.
#
# A referência não é segredo — vai na URL de toda requisição — mas este
# repositório é PÚBLICO, e gravar aqui o identificador da instalação da
# Prefeitura entrega de graça o alvo a quem varrer o GitHub. O hash
# cumpre a mesma função de guarda sem publicar o nome.
_HASH_PROJETO_PRODUCAO = (
    "d240cf6096d9560448f2a4d6236b46dfae0bf56218ac841b2069151100537de3")


class ProducaoRecusada(RuntimeError):
    """
    A URL não foi comprovada como de ENSAIO. Nenhuma operação pode ser
    executada.

    O nome é histórico: hoje a exceção cobre todo caso em que a
    identidade do projeto não fica PROVADA — produção, domínio
    desconhecido, URL malformada, porta, identidade fora da allowlist.
    Recusar por não saber é o comportamento correto de uma guarda.
    """


# Domínios em que a REFERÊNCIA do projeto é o primeiro rótulo do host e,
# portanto, pode ser provada a partir da URL. Qualquer outro domínio —
# inclusive um custom domain legítimo — não permite provar identidade a
# partir da URL, e por isso é recusado.
DOMINIOS_COM_REFERENCIA = ("supabase.co", "supabase.in")

NOME_ALLOWLIST = "GOVDOCS_ENSAIO_PROJETO"


def _canonicalizar_host(host: str) -> str:
    """
    Host canônico: minúsculas e IDNA.

    `casefold()` antes do IDNA porque `NXIB….SUPABASE.CO` e
    `nxib….supabase.co` são o MESMO host, e a comparação anterior era
    sensível à caixa: bastava digitar a URL de produção em maiúsculas
    para a guarda deixar passar.

    O ponto final ("trailing dot") é sintaticamente válido em DNS e
    designa o mesmo host, mas é recusado adiante — não há motivo
    legítimo para ele aqui, e aceitá-lo é mais uma grafia a conferir.
    """
    host = host.strip().casefold()
    if not host:
        return ""
    try:
        # idna via encode/decode normaliza rótulos unicode (homográficos
        # tipo `ѕupabase.co` com "s" cirílico não sobrevivem a isto)
        return host.encode("idna").decode("ascii").casefold()
    except (UnicodeError, UnicodeDecodeError):
        return ""


def _e_producao(referencia: str) -> bool:
    """Verdadeiro se a referência é a do projeto de produção."""
    return (hashlib.sha256(referencia.encode()).hexdigest()
            == _HASH_PROJETO_PRODUCAO)


def referencia_do_projeto(url: str) -> str:
    """
    Referência do projeto extraída da URL, ou "" quando NÃO é possível
    prová-la.

    Recusa por construção: esquema diferente de https, credencial
    embutida, porta, ponto final, domínio fora dos que expõem a
    referência no host, e qualquer coisa que não seja
    `<referencia>.supabase.co`.
    """
    try:
        partes = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if partes.scheme.casefold() != "https":
        return ""
    if partes.username or partes.password:
        return ""
    try:
        if partes.port is not None:          # porta explícita: recusada
            return ""
    except ValueError:                       # porta não numérica
        return ""
    if partes.path not in ("", "/") or partes.query or partes.fragment:
        return ""

    host_bruto = (partes.hostname or "")
    if host_bruto.endswith("."):             # trailing dot: recusado
        return ""
    host = _canonicalizar_host(host_bruto)
    if not host:
        return ""

    for dominio in DOMINIOS_COM_REFERENCIA:
        sufixo = "." + dominio
        if host.endswith(sufixo):
            referencia = host[: -len(sufixo)]
            # exatamente UM rótulo antes do domínio
            if referencia and "." not in referencia:
                return referencia
    return ""                                # custom domain ou desconhecido


def _allowlist_de_ensaio() -> frozenset[str]:
    """
    Allowlist POSITIVA das referências de ensaio, declarada pelo
    operador em GOVDOCS_ENSAIO_PROJETO (uma ou mais, separadas por
    vírgula).

    Negar produção é necessário mas não suficiente: existe um universo
    de projetos que não são o de produção e também não são o ensaio
    pretendido — o de outro município, o de outro cliente. A allowlist
    inverte o ônus: em vez de listar o que é proibido, declara-se o que
    é permitido.
    """
    bruto = os.getenv(NOME_ALLOWLIST, "")
    return frozenset(
        p.strip().casefold() for p in bruto.split(",") if p.strip())


def exigir_ensaio(url: str | None = None) -> str:
    """
    Porta única de entrada do ensaio: devolve a URL só quando a
    identidade do projeto está PROVADA e é de ensaio.

    Toda leitura de GOVDOCS_ENSAIO_URL — no script E nos testes — passa
    por aqui. Antes, a guarda existia apenas no script: os testes liam a
    variável direto e, apontada para produção, teriam executado contra
    ela as mesmas operações destrutivas.

    Levanta ProducaoRecusada em vez de `sys.exit` para que o teste possa
    FALHAR (e não passar silenciosamente).
    """
    url = os.getenv("GOVDOCS_ENSAIO_URL", "") if url is None else url
    url = (url or "").strip()
    if not url:
        raise ProducaoRecusada("GOVDOCS_ENSAIO_URL não definida.")

    referencia = referencia_do_projeto(url)
    if not referencia:
        raise ProducaoRecusada(
            "RECUSADO: não foi possível PROVAR a identidade do projeto a "
            "partir da URL. Use `https://<referencia>.supabase.co`, sem "
            "porta, sem caminho e sem ponto final. Nenhuma operação foi "
            "executada.")

    if _e_producao(referencia):
        raise ProducaoRecusada(
            "RECUSADO: a URL aponta para PRODUÇÃO. Use um projeto de "
            "ensaio. Nenhuma operação foi executada.")

    permitidas = _allowlist_de_ensaio()
    if not permitidas:
        # OBRIGATÓRIA. Enquanto era opcional, a proteção real era só a
        # negação de produção — e "não é produção" inclui o projeto de
        # outro município, o de outro cliente e o que o operador digitou
        # errado. Exigir a declaração transforma a guarda de "recuso o
        # que reconheço" em "só aceito o que foi declarado".
        raise ProducaoRecusada(
            f"RECUSADO: {NOME_ALLOWLIST} não declarada. Informe a(s) "
            "referência(s) do projeto de ensaio antes de qualquer "
            "operação. Nenhuma operação foi executada.")
    if referencia not in permitidas:
        raise ProducaoRecusada(
            f"RECUSADO: o projeto da URL não está em {NOME_ALLOWLIST}. "
            "Declare explicitamente a referência do ensaio. Nenhuma "
            "operação foi executada.")
    return url


def allowlist_declarada() -> bool:
    """A allowlist positiva foi declarada? O script exige; o teste não."""
    return bool(_allowlist_de_ensaio())


RAIZ = Path(__file__).resolve().parent.parent
MIGRACOES = RAIZ / "supabase" / "migrations"

OPERACOES = ["select", "insert", "update", "delete"]

# RPCs da aplicação (SECURITY INVOKER, hoje com EXECUTE para PUBLIC).
RPCS = {
    "buscar_chunks_textual": {"consulta": "ensaio", "qtd": 1},
    "buscar_chunks_vetorial": {"query_embedding": [0.0] * 768, "qtd": 1},
}

# ---------------------------------------------------------------------------
# Objetos DESCARTÁVEIS do ensaio — criados pelo operador, só no ensaio
#
# A versão anterior semeava um "canário" em cada tabela de DOMÍNIO. Era
# melhor que o `delete().neq("id","")` que substituiu, mas ainda errado:
# escrever em `usuarios`, `processos` e `governanca_eventos` insere
# linha de mentira em tabela de verdade. Um insert em `usuarios`
# significa criar CONTA — e se o ensaio morrer no meio, a conta fica.
# Em tabela com FK, a linha nasce órfã ou quebra a inserção.
#
# A divisão agora é outra, e é a que faz sentido:
#
#   * CONFIGURAÇÃO (as 28 tabelas, policies, grants, sequences, funções,
#     default privileges) é provada por CATÁLOGO — leitura pura, sem
#     escrever nada em lugar nenhum;
#
#   * COMPORTAMENTO ponta a ponta (select/insert/update/delete de fato
#     barrados) é provado nos objetos abaixo, que existem só para isso
#     e podem ser destruídos sem consequência.
# ---------------------------------------------------------------------------
TABELA_OBJETO_NOVO = "ensaio_objeto_novo"
RPC_OBJETO_NOVO = "ensaio_rpc_nova"
SEQUENCE_OBJETO_NOVO = "ensaio_seq_nova"
RPC_AUDITORIA = "ensaio_auditoria_catalogo"

PREFIXO_CANARIO = "ensaio-canario"


def marcador_de_canario() -> str:
    """Marcador único desta execução — jamais reaproveitado."""
    return f"{PREFIXO_CANARIO}-{uuid.uuid4().hex}"

_RE_CREATE_TABLE = re.compile(
    r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?"
    r"([a-z_][a-z_0-9]*)",
    re.IGNORECASE)


def tabelas_do_inventario() -> list[str]:
    """
    Inventário lido das MIGRAÇÕES, não escrito à mão.

    Lista fixa envelhece: a versão anterior deste script sondava 6
    tabelas de 28, e o "CONTIDO" que ela imprimia não significava nada
    sobre as outras 22. Derivar do repositório faz a cobertura
    acompanhar cada migração nova automaticamente.
    """
    nomes: set[str] = set()
    for arquivo in sorted(MIGRACOES.glob("*.sql")):
        nomes.update(m.group(1).lower()
                     for m in _RE_CREATE_TABLE.finditer(arquivo.read_text()))
    nomes.discard("as")          # artefato de `create table … as select`
    return sorted(nomes)


def cliente(chave_env: str):
    """
    Cliente do ENSAIO. Passa obrigatoriamente por `exigir_ensaio()`:
    não existe caminho neste módulo que construa um cliente sem a
    guarda.
    """
    from supabase import create_client

    url = exigir_ensaio()
    chave = os.getenv(chave_env, "")
    if not chave:
        raise ProducaoRecusada(f"defina {chave_env}")
    return create_client(url, chave)


_cliente = cliente          # nome anterior, mantido para compatibilidade


def cliente_autenticado() -> tuple[object | None, str]:
    """
    Sessão de usuário COMUM do Supabase Auth (papel `authenticated`),
    e o MOTIVO quando não foi possível obtê-la.

    Sem esta sondagem o ensaio não distingue "fechado" de "fechado só
    para quem não se cadastrou": qualquer visitante pode criar conta e
    virar `authenticated`.

    Antes, a ausência da conta virava um aviso impresso e o ensaio
    seguia até o CONTIDO. Agora o motivo sobe para o veredito e o
    impede — não medir o papel `authenticated` é justamente não saber
    se a contenção fecha o caminho mais provável de ataque.
    """
    email = os.getenv("GOVDOCS_ENSAIO_EMAIL", "")
    senha = os.getenv("GOVDOCS_ENSAIO_SENHA", "")
    if not (email and senha):
        return None, ("conta de ensaio não configurada "
                      "(GOVDOCS_ENSAIO_EMAIL / GOVDOCS_ENSAIO_SENHA)")
    sessao = cliente("GOVDOCS_ENSAIO_ANON_KEY")
    try:
        sessao.auth.sign_in_with_password({"email": email, "password": senha})
    except Exception as erro:  # noqa: BLE001
        return None, f"falha ao autenticar no ensaio ({type(erro).__name__})"
    return sessao, ""


_cliente_autenticado = cliente_autenticado


# ---------------------------------------------------------------------------
# Veredito de TRÊS estados
#
# A versão anterior tinha duas saídas e um padrão perigoso: qualquer
# exceção não reconhecida virava NEGADO. Um DNS que não resolve, um
# projeto pausado, uma chave errada, um timeout — tudo isso era lido
# como "a contenção funcionou", e o script imprimia CONTIDO sem ter
# medido nada.
#
# Agora só um erro EXPLÍCITO de autorização vira NEGADO. Todo o resto é
# INCONCLUSIVO, e INCONCLUSIVO impede o veredito CONTIDO.
# ---------------------------------------------------------------------------
PERMITIDO = "PERMITIDO"
NEGADO = "NEGADO"
INCONCLUSIVO = "INCONCLUSIVO"

# Quarto estado: a prova não se aplica porque o alvo não existe.
#
# Zero buckets de Storage não é "não sei se está fechado" — é "não há o
# que fechar". Contar isso como INCONCLUSIVO bloqueava o CONTIDO por
# uma ausência que não é falha, e treinava quem lê o relatório a
# ignorar inconclusivos.
NAO_APLICAVEL = "NAO_APLICAVEL"

# Códigos de AUTORIZAÇÃO — os únicos que provam negação.
#
#   42501   — insufficient_privilege do PostgreSQL: o papel não tem o
#             privilégio. É a negação por GRANT, e é inequívoca.
#
# `PGRST301` NÃO está aqui, e essa foi a correção central de um achado
# anterior. Ele significa "JWT ausente, expirado ou inválido" —
# AUTENTICAÇÃO, não autorização. Tratá-lo como negação fazia uma chave
# vencida provar "contenção funcionando": o servidor recusou antes
# mesmo de olhar quem era, e o ensaio anotava isso como se o RLS
# tivesse barrado. `PGRST303` (JWT sem claim de papel) tem o mesmo
# defeito.
#
# `42P17` também NÃO está aqui, e essa é a correção deste achado.
# `42P17` é `invalid_object_definition` — em RLS aparece como
# "infinite recursion detected in policy for relation X". A política
# não decidiu nada: ela é INVÁLIDA e a avaliação abortou. Ler isso como
# negação é a inversão mais perigosa do ensaio, porque a política
# quebrada é justamente a que ninguém sabe o que faria se funcionasse —
# e uma migração que introduzisse recursão em TODAS as políticas
# produziria um relatório inteiramente "NEGADO" com o banco sem
# contenção nenhuma. Recursão de política é ERRO ESTRUTURAL: vira
# INCONCLUSIVO, e INCONCLUSIVO impede o CONTIDO.
CODIGOS_DE_AUTORIZACAO = frozenset({"42501"})

# Códigos de AUTENTICAÇÃO — nunca provam nada sobre autorização.
CODIGOS_DE_AUTENTICACAO = frozenset({"pgrst301", "pgrst302", "pgrst303"})

# Códigos estruturais: objeto ausente, schema desatualizado, sintaxe,
# definição inválida. Nenhum deles mediu autorização.
CODIGOS_ESTRUTURAIS = frozenset({
    "pgrst202", "pgrst204", "pgrst205", "42p01", "42703", "42883", "42p17",
})

# Frases de autorização, para erros SEM código estruturado.
_FRASES_DE_AUTORIZACAO = (
    "permission denied",
    "insufficient privilege",
    "insufficient_privilege",
    "violates row-level security policy",
    "row-level security policy",
)

# Frases de autenticação. Precedem as de autorização em caso de
# conflito: um "permission denied" que venha junto de "invalid api key"
# é consequência da chave inválida, não prova de política.
_FRASES_DE_AUTENTICACAO = (
    "invalid api key", "invalid authentication", "jwt expired",
    "invalid jwt", "jwsError", "jwt is missing", "no api key",
    "unauthorized", "401",
)

# Frases ESTRUTURAIS. São conferidas ANTES das de autorização, e a
# ordem não é detalhe: "infinite recursion detected in policy for
# relation X" fala de política e passaria por negação numa leitura
# apressada. A política não decidiu — ela abortou.
_FRASES_ESTRUTURAIS = (
    "infinite recursion detected",
    "invalid_object_definition",
    "42p17",
)

_FRASES_INCONCLUSIVAS = (
    "timeout", "timed out", "connection", "getaddrinfo", "name or service",
    "temporary failure", "ssl", "certificate", "network", "unreachable",
    "502", "503", "504", "project is paused", "does not exist", "column",
    "schema cache", "could not find",
)


def _codigo_estruturado(erro: Exception) -> str:
    """
    Código do erro, quando o cliente o entrega estruturado.

    Preferir o campo `code` a procurar substring é o que separa
    "PGRST301 aconteceu" de "a palavra PGRST301 apareceu em algum
    lugar da mensagem" — inclusive dentro de um dado devolvido pela
    própria consulta.
    """
    for atributo in ("code", "codigo"):
        valor = getattr(erro, atributo, None)
        if isinstance(valor, str) and valor.strip():
            return valor.strip().casefold()
    for atributo in ("args", "json", "details"):
        valor = getattr(erro, atributo, None)
        if isinstance(valor, dict) and isinstance(valor.get("code"), str):
            return valor["code"].strip().casefold()
    # supabase-py costuma trazer um dict no primeiro argumento
    argumentos = getattr(erro, "args", ())
    if argumentos and isinstance(argumentos[0], dict):
        codigo = argumentos[0].get("code")
        if isinstance(codigo, str):
            return codigo.strip().casefold()
    return ""


def classificar(erro: Exception) -> str:
    """
    Classifica a exceção. Só erro explícito de AUTORIZAÇÃO é NEGADO.

    Ordem deliberada:
      1. código estruturado, quando existe — é a evidência mais forte;
      2. autenticação, que PREVALECE sobre autorização em caso de
         sinais conflitantes;
      3. defeito estrutural, que também PREVALECE: política inválida
         não decidiu nada;
      4. autorização por frase;
      5. tudo o mais, INCONCLUSIVO.

    Na dúvida, INCONCLUSIVO: um ensaio que não sabe o que aconteceu tem
    de dizer isso, não chutar a favor da própria tese.
    """
    codigo = _codigo_estruturado(erro)
    if codigo:
        if codigo in CODIGOS_DE_AUTENTICACAO:
            return INCONCLUSIVO
        if codigo in CODIGOS_ESTRUTURAIS:
            return INCONCLUSIVO
        if codigo in CODIGOS_DE_AUTORIZACAO:
            return NEGADO

    texto = f"{type(erro).__name__}: {erro}".casefold()

    # Autenticação primeiro: chave inválida produz mensagens que também
    # contêm "permission denied", e nesse caso a negação não prova
    # política nenhuma — prova que ninguém foi identificado.
    if any(f.casefold() in texto for f in _FRASES_DE_AUTENTICACAO):
        return INCONCLUSIVO
    if any(c in texto for c in CODIGOS_DE_AUTENTICACAO):
        return INCONCLUSIVO

    # Defeito estrutural antes de autorização, pelo mesmo motivo:
    # recursão de política menciona política e não é decisão de política.
    if any(f in texto for f in _FRASES_ESTRUTURAIS):
        return INCONCLUSIVO
    if any(c in texto for c in CODIGOS_ESTRUTURAIS):
        return INCONCLUSIVO

    if any(f in texto for f in _FRASES_DE_AUTORIZACAO):
        return NEGADO
    if any(c in texto for c in CODIGOS_DE_AUTORIZACAO):
        return NEGADO

    if any(f in texto for f in _FRASES_INCONCLUSIVAS):
        return INCONCLUSIVO
    return INCONCLUSIVO


class PreparacaoFalhou(RuntimeError):
    """
    O ensaio não pôde ser PREPARADO.

    É erro, não motivo para pular. Preparação que falha em silêncio
    produz um relatório que parece bom porque nada foi medido.
    """


def semear_canario_descartavel(servidor) -> str:
    """
    Cria UM canário, e só na tabela descartável do ensaio.

    Devolve o id. Falha em levantar `PreparacaoFalhou` — sem canário
    não há prova de leitura conclusiva, e seguir sem ele seria medir
    nada e chamar de contido.
    """
    ident = str(uuid.uuid4())
    try:
        servidor.table(TABELA_OBJETO_NOVO).insert(
            {"id": ident, "observacao": marcador_de_canario()}).execute()
    except Exception as erro:  # noqa: BLE001
        raise PreparacaoFalhou(
            f"não foi possível semear o canário em {TABELA_OBJETO_NOVO} "
            f"({type(erro).__name__}). Crie os objetos do ensaio: "
            "`--instrucoes`.") from erro
    return ident


def remover_canario(servidor, ident: str) -> None:
    """Remove pelo id exato. Nunca por filtro amplo."""
    try:
        servidor.table(TABELA_OBJETO_NOVO).delete().eq("id", ident).execute()
    except Exception:  # noqa: BLE001
        print(f"  (aviso) canário remanescente em {TABELA_OBJETO_NOVO}: "
              f"remova à mão")


FASE_CONTENCAO = "A"       # pós-0019
FASE_DEFINITIVA = "B"      # pós-0020


def auditar_catalogo(servidor, fase: str = FASE_CONTENCAO) -> list[dict]:
    """
    Auditoria de CONFIGURAÇÃO, pelo catálogo do PostgreSQL.

    É aqui que as 28 tabelas, as policies, os grants, as sequences, as
    funções e os default privileges são conferidos — sem escrever uma
    linha em lugar nenhum, e sem depender de tentar a operação para
    descobrir se ela seria barrada.

    Roda como RPC porque o PostgREST não expõe `pg_catalog`. A função é
    SECURITY DEFINER, criada pelo operador no ensaio e concedida
    exclusivamente ao papel de servidor — ver `--instrucoes`.
    """
    try:
        resposta = servidor.rpc(RPC_AUDITORIA, {"p_fase": fase}).execute()
    except Exception as erro:  # noqa: BLE001
        raise PreparacaoFalhou(
            f"a auditoria de catálogo ({RPC_AUDITORIA}) não respondeu "
            f"({type(erro).__name__}). Crie a função do ensaio: "
            "`--instrucoes`.") from erro
    dados = getattr(resposta, "data", None)
    if dados is None:
        raise PreparacaoFalhou(
            f"{RPC_AUDITORIA} não devolveu resultado algum.")
    return dados if isinstance(dados, list) else [dados]


def _tentar(cliente_sondagem, tabela: str, operacao: str,
            canario: str | None = None) -> str:
    """
    PERMITIDO | NEGADO | INCONCLUSIVO — sem DELETE amplo em lugar algum.

    Toda escrita mira o CANÁRIO por id. Sem canário, a escrita não é
    tentada: devolve INCONCLUSIVO, porque medir escrita sem alvo seguro
    exigiria apagar dado de verdade.
    """
    # A checagem vem ANTES de tocar no cliente: sem alvo seguro, a
    # operação não chega nem a ser montada.
    if operacao != "select" and canario is None:
        return INCONCLUSIVO

    alvo = cliente_sondagem.table(tabela)
    try:
        if operacao == "select":
            resposta = alvo.select("*").limit(1).execute()
            if getattr(resposta, "data", None):
                return PERMITIDO
            # Vazio só é NEGAÇÃO se sabemos que havia o que ler.
            return NEGADO if canario else INCONCLUSIVO

        if operacao == "insert":
            alvo.insert({"id": str(uuid.uuid4()),
                         "observacao": marcador_de_canario()}).execute()
            return PERMITIDO
        if operacao == "update":
            alvo.update({"observacao": "alterado-pelo-ensaio"}) \
                .eq("id", canario).execute()
            return PERMITIDO
        alvo.delete().eq("id", canario).execute()
        return PERMITIDO
    except Exception as erro:  # noqa: BLE001
        return classificar(erro)


def sondar_leitura_de_dominio(cliente_sondagem, tabela: str,
                              fechada_no_catalogo: bool) -> str:
    """
    Leitura de tabela de DOMÍNIO — sem escrever nada.

    Devolver linha é PERMITIDO, sem ambiguidade. Erro de autorização é
    NEGADO. E o caso incômodo — resposta vazia — deixa de ser
    inconclusivo quando o CATÁLOGO já provou que a tabela não tem grant
    nem policy para o papel: aí "não veio nada" é a única coisa que
    poderia ter vindo.

    É assim que a cobertura das 28 tabelas se completa sem inserir uma
    linha de mentira em `usuarios` ou em `processos`.
    """
    try:
        resposta = (cliente_sondagem.table(tabela)
                    .select("*").limit(1).execute())
    except Exception as erro:  # noqa: BLE001
        return classificar(erro)
    if getattr(resposta, "data", None):
        return PERMITIDO
    return NEGADO if fechada_no_catalogo else INCONCLUSIVO


def _tentar_rpc(cliente_sondagem, funcao: str, params: dict) -> str:
    try:
        cliente_sondagem.rpc(funcao, params).execute()
        return PERMITIDO
    except Exception as erro:  # noqa: BLE001
        return classificar(erro)


def _tentar_storage(cliente_sondagem) -> str:
    try:
        baldes = cliente_sondagem.storage.list_buckets()
    except Exception as erro:  # noqa: BLE001
        return classificar(erro)
    # Zero bucket não é "não sei se está fechado": é "não há o que
    # fechar". Marcar isso como INCONCLUSIVO bloqueava o CONTIDO por
    # uma ausência que não é falha.
    return PERMITIDO if baldes else NAO_APLICAVEL


def _confirmar_estado(servidor, ident: str, esperado: str | None) -> bool:
    """
    O canário está como deveria?

    O status HTTP não basta. O PostgREST responde 204 a um DELETE que
    não casou nenhuma linha, e responde 200 a um UPDATE filtrado por
    RLS que não alterou nada — os dois indistinguíveis de sucesso pelo
    código de resposta. Quem sabe o que aconteceu é o SERVIDOR, olhando
    a linha depois.

    `esperado=None` significa "a linha deve ter sumido".
    """
    try:
        resposta = (servidor.table(TABELA_OBJETO_NOVO)
                    .select("observacao").eq("id", ident).execute())
    except Exception:  # noqa: BLE001
        return False
    linhas = getattr(resposta, "data", None) or []
    if esperado is None:
        return not linhas
    return bool(linhas) and linhas[0].get("observacao") == esperado


def sondar_escrita_ponta_a_ponta(anon, servidor, ident: str,
                                 marcador: str) -> list[tuple[str, str]]:
    """
    Prova de COMPORTAMENTO, só no objeto descartável: `anon` tenta
    escrever e o SERVIDOR confere o estado depois.

    Devolve [(operação, veredito)].
    """
    resultados: list[tuple[str, str]] = []

    # INSERT — o veredito é a linha nova não existir
    novo = str(uuid.uuid4())
    try:
        anon.table(TABELA_OBJETO_NOVO).insert(
            {"id": novo, "observacao": "inserido-pelo-anon"}).execute()
        veredito = PERMITIDO
    except Exception as erro:  # noqa: BLE001
        veredito = classificar(erro)
    if veredito == NEGADO and _confirmar_estado(servidor, novo, "x") is False:
        # confirma que nada foi criado: a leitura pelo servidor não acha
        try:
            achou = (servidor.table(TABELA_OBJETO_NOVO)
                     .select("id").eq("id", novo).execute()).data
        except Exception:  # noqa: BLE001
            achou = None
        if achou:
            veredito = PERMITIDO      # o erro mentiu: a linha entrou
    resultados.append(("insert", veredito))

    # UPDATE — o veredito é o marcador continuar o mesmo
    try:
        anon.table(TABELA_OBJETO_NOVO).update(
            {"observacao": "alterado-pelo-anon"}).eq("id", ident).execute()
        veredito = PERMITIDO
    except Exception as erro:  # noqa: BLE001
        veredito = classificar(erro)
    if not _confirmar_estado(servidor, ident, marcador):
        veredito = PERMITIDO          # alterou de fato, dissesse o que dissesse
    resultados.append(("update", veredito))

    # DELETE — o veredito é o canário continuar lá
    try:
        anon.table(TABELA_OBJETO_NOVO).delete().eq("id", ident).execute()
        veredito = PERMITIDO
    except Exception as erro:  # noqa: BLE001
        veredito = classificar(erro)
    if not _confirmar_estado(servidor, ident, marcador):
        veredito = PERMITIDO          # apagou de fato
    resultados.append(("delete", veredito))

    return resultados


# ---------------------------------------------------------------------------
# Sondagens
# ---------------------------------------------------------------------------
def sondar_papel(cliente_sondagem, papel: str, tabelas: list[str],
                 fechadas: set[str]) -> dict:
    """
    Leitura de todas as tabelas + RPCs + Storage, para um papel.

    Nenhuma escrita: a prova de escrita acontece só no objeto
    descartável (`sondar_escrita_ponta_a_ponta`).
    """
    print(f"\n=== papel: {papel} ===")
    resultado = {}
    for tabela in tabelas:
        veredito = sondar_leitura_de_dominio(
            cliente_sondagem, tabela, tabela in fechadas)
        resultado[f"{tabela}.select"] = veredito
        print(f"  {veredito:14} {tabela}")

    for funcao, params in {**RPCS, RPC_OBJETO_NOVO: {}}.items():
        veredito = _tentar_rpc(cliente_sondagem, funcao, params)
        resultado[f"rpc:{funcao}"] = veredito
        print(f"  {veredito:14} rpc {funcao}")

    veredito = _tentar_storage(cliente_sondagem)
    resultado["storage:buckets"] = veredito
    print(f"  {veredito:14} storage (buckets)")
    return resultado


def sondar_servidor(servidor, tabelas: list[str]) -> list[str]:
    """
    Item 3: o servidor continua operando. Um "CONTIDO" que também
    fecha o servidor é um app quebrado, não um app contido.
    """
    print("\n=== papel: servidor (credencial sb_secret_) ===")
    bloqueadas = []
    for tabela in tabelas:
        try:
            servidor.table(tabela).select("*").limit(1).execute()
            print(f"  ok      {tabela}: leitura legítima funciona")
        except Exception as erro:  # noqa: BLE001
            bloqueadas.append(tabela)
            print(f"  FALHA   {tabela}: servidor bloqueado "
                  f"({type(erro).__name__})")
    return bloqueadas


def relatar_catalogo(achados: list[dict]) -> tuple[set[str], list[str]]:
    """
    Imprime a auditoria de catálogo e devolve
    (tabelas comprovadamente fechadas, problemas).

    Cada achado tem: tipo, objeto, detalhe. A ausência de achados é a
    prova positiva — o catálogo não tem nada aberto a `anon`.
    """
    print("\n=== auditoria de catálogo ===")
    fechadas: set[str] = set()
    problemas: list[str] = []
    for achado in achados:
        tipo = str(achado.get("tipo", ""))
        objeto = str(achado.get("objeto", ""))
        detalhe = str(achado.get("detalhe", ""))
        if tipo == "tabela_fechada":
            fechadas.add(objeto)
            continue
        problemas.append(f"{tipo}: {objeto} — {detalhe}")
        print(f"  ABERTO   {tipo:22} {objeto} {detalhe}")
    print(f"  {len(fechadas)} tabela(s) comprovadamente fechada(s) a anon; "
          f"{len(problemas)} problema(s) de configuração")
    return fechadas, problemas


def executar_provas_de_isolamento() -> list[str]:
    """
    EXECUTA as provas de isolamento da fase B e devolve os
    impedimentos.

    A versão anterior imprimia o comando `pytest -k isolamento` e
    seguia para o veredito. Comando impresso não é prova: o script
    podia dizer CONTIDO sem que uma única fronteira de `authenticated`
    tivesse sido medida — e é justamente na fase B que `authenticated`
    passa a ter acesso, ou seja, exatamente quando medir importa mais.

    Qualquer coisa que impeça a execução — pytest ausente, credencial
    faltando, cenário que não montou, teste pulado — vira impedimento,
    e impedimento bloqueia o CONTIDO.
    """
    import subprocess

    print("\n=== provas de isolamento (fase B) ===")
    arquivo = RAIZ / "tests" / "test_seguranca_contencao.py"
    if not arquivo.exists():
        return [f"arquivo de provas ausente: {arquivo}"]

    try:
        processo = subprocess.run(
            [sys.executable, "-m", "pytest", str(arquivo),
             "-k", "isolamento or trilha or governanca or filha or cenario",
             "-q", "--no-header", "-p", "no:cacheprovider"],
            capture_output=True, text=True, timeout=900,
            cwd=str(RAIZ))
    except FileNotFoundError:
        return ["pytest não encontrado: as provas de isolamento não "
                "puderam ser executadas"]
    except subprocess.TimeoutExpired:
        return ["as provas de isolamento excederam o tempo limite"]

    saida = (processo.stdout or "") + (processo.stderr or "")
    print(saida.strip()[-2000:] or "(sem saída)")

    impedimentos: list[str] = []
    if processo.returncode != 0:
        impedimentos.append(
            f"provas de isolamento FALHARAM (exit {processo.returncode})")

    # Skip aqui é lacuna, não neutralidade: significa que a fronteira
    # não foi medida.
    import re as _re

    pulados = _re.search(r"(\d+) skipped", saida)
    if pulados and int(pulados.group(1)):
        impedimentos.append(
            f"{pulados.group(1)} prova(s) de isolamento PULADA(S) — "
            "na fase B o conjunto mínimo não admite skip")

    passaram = _re.search(r"(\d+) passed", saida)
    if not passaram or not int(passaram.group(1)):
        impedimentos.append(
            "nenhuma prova de isolamento chegou a passar — sem elas o "
            "veredito da fase B não significa nada")
    else:
        print(f"  {passaram.group(1)} prova(s) de isolamento executada(s) "
              "e aprovada(s)")
    return impedimentos


def veredito_final(por_papel: dict[str, dict], bloqueadas: list[str],
                   problemas_catalogo: list[str], escrita: list[tuple],
                   impedimentos: list[str]) -> int:
    """
    CONTIDO exige TUDO ao mesmo tempo:

      * nenhum PERMITIDO indevido, em leitura, escrita, RPC ou Storage;
      * nenhum INCONCLUSIVO — o que não foi medido não conta a favor;
      * nenhum problema na auditoria de catálogo;
      * o servidor continuando a operar;
      * nenhum impedimento estrutural.

    NAO_APLICAVEL não conta contra: é ausência de alvo, não de prova.
    """
    print("\n=== VEREDITO ===")
    abertos = inconclusivos = nao_aplicaveis = 0

    for papel, resultado in por_papel.items():
        for objeto, veredito in resultado.items():
            if veredito == NEGADO:
                continue
            if veredito == NAO_APLICAVEL:
                nao_aplicaveis += 1
                print(f"  n/a           [{papel}] {objeto}")
            elif veredito == PERMITIDO:
                abertos += 1
                print(f"  ABERTO        [{papel}] {objeto}")
            else:
                inconclusivos += 1
                print(f"  INCONCLUSIVO  [{papel}] {objeto}")

    for operacao, veredito in escrita:
        if veredito == NEGADO:
            continue
        if veredito == PERMITIDO:
            abertos += 1
            print(f"  ABERTO        [anon] {TABELA_OBJETO_NOVO}.{operacao}")
        else:
            inconclusivos += 1
            print(f"  INCONCLUSIVO  [anon] {TABELA_OBJETO_NOVO}.{operacao}")

    for tabela in bloqueadas:
        print(f"  QUEBRADO      servidor sem acesso a {tabela}")
    for problema in problemas_catalogo:
        print(f"  ABERTO        catálogo — {problema}")
    for impedimento in impedimentos:
        print(f"  IMPEDIMENTO   {impedimento}")

    total = (abertos + inconclusivos + len(bloqueadas)
             + len(problemas_catalogo) + len(impedimentos))
    print(f"\nresumo: {abertos} aberto(s), {inconclusivos} inconclusivo(s), "
          f"{nao_aplicaveis} não aplicável(is), {len(bloqueadas)} quebra(s) "
          f"de servidor, {len(problemas_catalogo)} problema(s) de catálogo, "
          f"{len(impedimentos)} impedimento(s)")
    if not total:
        print("\nCONTIDO")
        return 0
    print("\nNÃO CONTIDO")
    if inconclusivos or impedimentos:
        print("INCONCLUSIVO não é aprovação: o que não foi medido não pode "
              "ser declarado fechado.")
    return total


INSTRUCOES = """\
Rodar no SQL Editor do projeto de ENSAIO (nunca produção).

Nada aqui toca em tabela de domínio: o ensaio prova CONFIGURAÇÃO pelo
catálogo e COMPORTAMENTO em objetos descartáveis criados só para isso.

-- 1) contas comuns, para sondar o papel `authenticated` e o
--    isolamento entre usuário, secretaria e tenant. Criar pelo painel
--    Auth → Users e gravar papel/tenant/secretaria em app_metadata
--    (NUNCA user_metadata) pela Admin API:
--
--      A       GOVDOCS_ENSAIO_EMAIL / _SENHA
--              {papel:"usuario", tenant_id:"T1", secretaria_id:"S1"}
--      COLEGA  GOVDOCS_ENSAIO_EMAIL_COLEGA / _SENHA_COLEGA
--              {papel:"usuario", tenant_id:"T1", secretaria_id:"S1"}
--              <- MESMO tenant, MESMA secretaria de A
--      B       GOVDOCS_ENSAIO_EMAIL_B / _SENHA_B
--              {papel:"usuario", tenant_id:"T1", secretaria_id:"S2"}
--              <- mesmo tenant, OUTRA secretaria
--      OUTRO   GOVDOCS_ENSAIO_EMAIL_OUTRO / _SENHA_OUTRO
--              {papel:"usuario", tenant_id:"T2", secretaria_id:"S3"}
--              <- OUTRO tenant
--      ADMIN   GOVDOCS_ENSAIO_EMAIL_ADMIN / _SENHA_ADMIN
--              {papel:"admin", tenant_id:"T1", secretaria_id:"S1"}
--
--    A conta COLEGA é a que separa leitura de escrita: ela LÊ o
--    processo de A, porque a decisão é leitura por secretaria, e NÃO
--    escreve nas filhas dele. Sem essa conta, provar que B é negado
--    não diz nada sobre quem divide a pasta.
--
--    Sem as cinco, os testes de isolamento não rodam — e provar que a
--    política FECHA é diferente de provar que ela ABRE para quem deve.
--
--    Defina também GOVDOCS_ENSAIO_TENANT com o uuid de T1.

-- 2) objetos DESCARTÁVEIS, criados DEPOIS de aplicar a 0019 — a ordem
--    é o teste: eles nascem sob os default privileges já revogados.
create table if not exists public.ensaio_objeto_novo (
  id uuid primary key default gen_random_uuid(),
  criado_em timestamptz not null default now(),
  observacao text
);
-- nenhum grant, nenhuma policy: se `anon` conseguir ler ou escrever,
-- o problema está nos default privileges, não nesta tabela.

create or replace function public.ensaio_rpc_nova()
returns text language sql stable as $$ select 'ensaio'::text $$;
-- nenhum grant: se `anon` conseguir EXECUTAR, o default
-- EXECUTE ON FUNCTIONS ainda está concedido a PUBLIC. `revoke ... from
-- public` nas funções EXISTENTES não impede isso — default privilege
-- vale para as FUTURAS, e é por isso que a 0019 precisa das duas
-- revogações.

create sequence if not exists public.ensaio_seq_nova;
-- mesma lógica para sequence: `USAGE`/`UPDATE` permitem nextval/setval.

-- 3) auditoria de catálogo. É ela que cobre as 28 tabelas, as
--    policies, os grants, as sequences, as funções e os default
--    privileges — SEM escrever nada. SECURITY DEFINER porque o
--    PostgREST não expõe pg_catalog; concedida SÓ ao service_role.
-- A auditoria recebe a FASE, porque o que é vulnerabilidade muda
-- entre elas:
--
--   'A' (pós-0019, contenção): anon, PUBLIC E authenticated têm de
--       estar TOTALMENTE fechados. Nesta fase o app opera só com
--       credencial de servidor, e qualquer policy para authenticated
--       é sobra a remover.
--
--   'B' (pós-0020, definitiva): anon e PUBLIC continuam fechados, mas
--       authenticated PRECISA de policy e grant — é o modelo. Marcar
--       essas policies como vulnerabilidade nesta fase produziria 60
--       achados falsos e ensinaria a ignorar o relatório.
create or replace function public.ensaio_auditoria_catalogo(
  p_fase text default 'A')
returns table (tipo text, objeto text, detalhe text)
language sql security definer set search_path = pg_catalog, public as $$
  with papeis as (
    select case when p_fase = 'B'
                then array['anon','public']::name[]
                else array['anon','authenticated','public']::name[]
           end as proibidos,
           case when p_fase = 'B'
                then array['anon','PUBLIC']::text[]
                else array['anon','authenticated','PUBLIC']::text[]
           end as proibidos_grant
  )
  -- tabelas comprovadamente fechadas para os papéis proibidos da fase
  select 'tabela_fechada', t.tablename::text, ''
  from pg_tables t, papeis
  where t.schemaname = 'public' and t.rowsecurity
    and not exists (select 1 from pg_policies p
                    where p.schemaname='public' and p.tablename=t.tablename
                      and p.roles && papeis.proibidos)
    and not exists (select 1 from information_schema.role_table_grants g
                    where g.table_schema='public' and g.table_name=t.tablename
                      and g.grantee = any (papeis.proibidos_grant))
  union all
  -- tabela sem RLS
  select 'tabela_sem_rls', tablename::text, 'row level security desligada'
  from pg_tables where schemaname='public' and not rowsecurity
  union all
  -- policy que alcança papel proibido NESTA fase
  select 'policy_permissiva', p.tablename::text, p.policyname::text
  from pg_policies p, papeis
  where p.schemaname='public' and p.roles && papeis.proibidos
  union all
  -- grant de tabela a papel proibido NESTA fase
  select 'grant_de_tabela', g.table_name::text,
         g.grantee::text || ' ' || g.privilege_type::text
  from information_schema.role_table_grants g, papeis
  where g.table_schema='public' and g.grantee = any (papeis.proibidos_grant)
  union all
  -- na fase B, escrita sem WITH CHECK é vulnerabilidade
  select 'escrita_sem_with_check', p.tablename::text, p.policyname::text
  from pg_policies p
  where p_fase = 'B' and p.schemaname='public'
    and p.cmd in ('INSERT','UPDATE','ALL') and p.with_check is null
  union all
  -- na fase B, grant a authenticated sem policy nenhuma é buraco
  select 'grant_sem_policy', g.table_name::text, g.grantee::text
  from information_schema.role_table_grants g
  where p_fase = 'B' and g.table_schema='public'
    and g.grantee = 'authenticated'
    and not exists (select 1 from pg_policies p
                    where p.schemaname='public' and p.tablename=g.table_name)
  group by g.table_name, g.grantee
  union all
  -- sequence aberta
  select 'sequence_aberta', c.relname::text,
         array_to_string(c.relacl, '; ')
  from pg_class c join pg_namespace n on n.oid=c.relnamespace
  where n.nspname='public' and c.relkind='S'
    and array_to_string(c.relacl,';') ~ case when p_fase='B'
          then '(anon)=|(^|;)=' else '(anon|authenticated)=|(^|;)=' end
  union all
  -- função com EXECUTE para anon/authenticated/PUBLIC (exceto extensão)
  select 'funcao_executavel', p.proname::text,
         array_to_string(p.proacl, '; ')
  from pg_proc p join pg_namespace n on n.oid=p.pronamespace
  where n.nspname='public'
    and not exists (select 1 from pg_depend d
                    where d.objid=p.oid and d.deptype='e')
    and array_to_string(p.proacl,';') ~ case when p_fase='B'
          then '(anon)=X|(^|;)=X' else '(anon|authenticated)=X|(^|;)=X' end
  union all
  -- default privilege para objetos FUTUROS
  select 'default_privilege', pg_get_userbyid(d.defaclrole)::text,
         d.defaclobjtype::text || ' ' || array_to_string(d.defaclacl,'; ')
  from pg_default_acl d join pg_namespace n on n.oid=d.defaclnamespace
  where n.nspname='public'
    and array_to_string(d.defaclacl,';') ~ '(anon|authenticated)=|(^|;)=';
$$;
-- default privilege continua proibido para authenticated nas DUAS
-- fases: objeto FUTURO não pode nascer autorizado. A 0020 concede
-- tabela a tabela, deliberadamente.

revoke all on function public.ensaio_auditoria_catalogo(text) from public;
grant execute on function public.ensaio_auditoria_catalogo(text)
  to service_role;

-- 4) a própria 0019: copiar o corpo de
--    supabase/migrations/0019_emergencial_fecha_anon.sql.NAO_APLICAR
--    e executar, com revisão humana.

SEQUÊNCIA — a ordem importa, e a versão anterior estava errada.

Ela mandava sondar a linha de base ANTES de criar os objetos
descartáveis e a RPC de auditoria. Mas a sondagem DEPENDE dos dois: sem
a RPC não há auditoria de catálogo, e sem o objeto descartável não há
canário nem prova de escrita. A "linha de base" saía vazia — e uma
linha de base vazia não serve de comparação para nada.

  1. criar objetos descartáveis, RPC de auditoria e contas (itens 1-3);
  2. --sondar --fase A      → linha de base ANTES da 0019
                              (esperado: MUITO aberto)
  3. aplicar a 0019 no ensaio;
  4. --sondar --fase A      → DEPOIS da contenção
                              (esperado: CONTIDO — anon, PUBLIC e
                               authenticated todos fechados)
  5. Security Advisors do ensaio (painel → Advisors);
  6. aplicar a 0020 no ensaio;
  7. --sondar --fase B      → DEPOIS da definitiva
                              (esperado: anon e PUBLIC fechados;
                               authenticated autorizado conforme a
                               matriz, e NÃO tratado como achado)
  8. pytest -k isolamento   → prova o isolamento entre usuário,
                              secretaria e tenant (exige as contas
                              A, B e de outro tenant);
  9. Security Advisors de novo.

Medir ANTES e DEPOIS de CADA fase é o que distingue "a contenção
funcionou" de "estava fechado desde o começo e ninguém reparou".

Limpeza, ao fim:
  drop function if exists public.ensaio_auditoria_catalogo(text);
  drop function if exists public.ensaio_rpc_nova();
  drop sequence if exists public.ensaio_seq_nova;
  drop table if exists public.ensaio_objeto_novo;

INCONCLUSIVO não é aprovação: significa que a medição não aconteceu, e
o veredito CONTIDO fica bloqueado até ser resolvida. NAO_APLICAVEL é
outra coisa — não há alvo (zero bucket de Storage, por exemplo) — e não
bloqueia.
"""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--sondar", action="store_true")
    p.add_argument("--fase", choices=[FASE_CONTENCAO, FASE_DEFINITIVA],
                   default=FASE_CONTENCAO,
                   help="A = pós-0019 (tudo fechado); "
                        "B = pós-0020 (authenticated conforme a matriz)")
    p.add_argument("--instrucoes", action="store_true")
    p.add_argument("--aplicar", metavar="MIGRACAO")
    p.add_argument("--rollback", metavar="MIGRACAO")
    args = p.parse_args()

    if args.instrucoes:
        print(INSTRUCOES)
        return 0

    if args.sondar:
        try:
            exigir_ensaio()
        except ProducaoRecusada as erro:
            print(erro)
            return 2

        tabelas = tabelas_do_inventario() + [TABELA_OBJETO_NOVO]
        print(f"inventário: {len(tabelas)} tabelas lidas das migrações")
        impedimentos: list[str] = []

        try:
            servidor = cliente("GOVDOCS_ENSAIO_SECRET_KEY")
        except ProducaoRecusada as erro:
            print(f"\nSem credencial de servidor: {erro}")
            print("\nNÃO CONTIDO — o ensaio precisa do servidor para semear "
                  "canários e provar que as operações legítimas seguem.")
            return 2

        print(f"fase: {args.fase} — "
              + ("pós-0019, anon/PUBLIC/authenticated fechados"
                 if args.fase == FASE_CONTENCAO
                 else "pós-0020, authenticated conforme a matriz RLS"))
        try:
            achados = auditar_catalogo(servidor, args.fase)
            marcador = marcador_de_canario()
            ident = str(uuid.uuid4())
            servidor.table(TABELA_OBJETO_NOVO).insert(
                {"id": ident, "observacao": marcador}).execute()
        except PreparacaoFalhou as erro:
            print(f"\nPREPARAÇÃO FALHOU: {erro}")
            print("\nNÃO CONTIDO — sem preparação não há medição, e sem "
                  "medição não há veredito.")
            return 2
        except Exception as erro:  # noqa: BLE001
            print(f"\nPREPARAÇÃO FALHOU ({type(erro).__name__}). "
                  "Crie os objetos do ensaio: `--instrucoes`.")
            return 2

        fechadas, problemas_catalogo = relatar_catalogo(achados)

        try:
            anon = cliente("GOVDOCS_ENSAIO_ANON_KEY")
            por_papel = {"anon": sondar_papel(anon, "anon", tabelas, fechadas)}

            autenticado, motivo = cliente_autenticado()
            if autenticado is None:
                impedimentos.append(
                    f"papel `authenticated` não sondado: {motivo}")
            elif args.fase == FASE_CONTENCAO:
                # Fase A: `authenticated` tem de ser negado como o anon.
                por_papel["authenticated"] = sondar_papel(
                    autenticado,
                    "authenticated (fase A: nada autorizado ainda)",
                    tabelas, fechadas)
            else:
                # Fase B: leitura autorizada é o COMPORTAMENTO ESPERADO,
                # então sondar como violação inverteria o veredito. O
                # que se prova aqui é o ISOLAMENTO — e ele é EXECUTADO,
                # não sugerido.
                isolamento = executar_provas_de_isolamento()
                impedimentos.extend(isolamento)

            print(f"\n=== escrita ponta a ponta em {TABELA_OBJETO_NOVO} ===")
            escrita = sondar_escrita_ponta_a_ponta(
                anon, servidor, ident, marcador)
            for operacao, veredito in escrita:
                print(f"  {veredito:14} {operacao}")

            bloqueadas = sondar_servidor(servidor, tabelas)
        finally:
            remover_canario(servidor, ident)

        return 1 if veredito_final(
            por_papel, bloqueadas, problemas_catalogo, escrita,
            impedimentos) else 0

    if args.aplicar or args.rollback:
        print("Aplicação/rollback NÃO são automatizados por este script.\n"
              "Copie o bloco correspondente do arquivo .NAO_APLICAR e\n"
              "execute-o no SQL Editor do projeto de ENSAIO, com revisão\n"
              "humana. Depois rode --sondar novamente e compare.\n"
              "O rollback da 0019 só pode rodar com o app em MANUTENÇÃO.")
        return 2

    p.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
