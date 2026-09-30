#!/usr/bin/env python3
"""
Medição do custo de geração — a MESMA régua antes e depois.

    GOVDOCS_IA_SIMULADA=coerente .venv/bin/python scripts/medir_custo.py \
        --rotulo antes --saida docs/custo/antes.json

O QUE ESTE ROTEIRO MEDE, E POR QUE ASSIM

A pergunta "quanto custa gerar um DFD" tem uma metade que se mede sem
gastar um centavo e uma metade que não. Este roteiro é explícito sobre
qual é qual, porque misturar as duas é como se produz relatório de
economia que não se sustenta.

MEDIDO AQUI, EXATO (nada estimado):

  * tokens de ENTRADA, pelo tokenizador de verdade do provedor
    (`o200k_base`, a codificação da família gpt-4o/gpt-5 — a mesma que
    a OpenAI usa para cobrar). Não é contagem de caracteres dividida
    por quatro;
  * a COMPOSIÇÃO desses tokens: quanto vem do system prompt, quanto do
    formulário, quanto da cadeia de documentos anteriores, quanto do
    RAG. É o que diz onde cortar;
  * o número de REQUISIÇÕES por documento, contando retentativa por
    modelo e queda entre motores;
  * o teto de saída pedido ao provedor (`max_completion_tokens`), que é
    o que o provedor reserva e o que limita o documento.

NÃO MEDIDO AQUI (e o relatório diz isso na cara):

  * tokens de SAÍDA reais. Saída só existe com modelo de verdade
    respondendo, e esta bateria não chama modelo nenhum. A linha de
    base de saída vem da TELEMETRIA DE PRODUÇÃO (tabela `geracoes`),
    que é medida real de gerações reais — está em
    `docs/custo/producao.json`, colhida por consulta agregada.

O RAG É SIMULADO COM TAMANHO REAL

Não há base de conhecimento neste ambiente, e medir o RAG como zero
faria o antes/depois esconder justamente a parte que mais cresce. Os
trechos são sintéticos, mas o TAMANHO deles vem da medição da base de
produção (5.595 chunks, média de 1.328 caracteres, teto de 1.500). O
que se compara entre antes e depois é o que o CÓDIGO faz com trechos
desse tamanho — que é o objeto da mudança.

NENHUM CONTEÚDO DE PROMPT É GRAVADO. Só contagens.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import pathlib
import sys
import time

RAIZ = pathlib.Path(__file__).resolve().parent.parent
for _caminho in (str(RAIZ), str(RAIZ / "tests"), str(RAIZ / "scripts"),
                 str(RAIZ / "scripts" / "bloqueio_de_custo")):
    if _caminho not in sys.path:
        sys.path.insert(0, _caminho)

import ia_simulada  # noqa: E402
import sem_llm  # noqa: E402

import massas_auditoria as massas  # noqa: E402

CHAVE_DE_ENSAIO = "ensaio-sem-custo-isto-nao-e-credencial"

# Fluxo com `flag_mapa_riscos` ligada — o de produção. `edital` e `arp`
# ficam fora porque não passam por modelo nenhum: são montados do
# catálogo de cláusulas. Contá-los inflaria a conta com chamadas que
# não existem.
COM_IA = ("dfd", "etp", "mapa_riscos", "tr")

# ---------------------------------------------------------------------------
# Medição da base de produção (consulta agregada em 30/09/2026):
#   select count(*), avg(length(conteudo)), max(length(conteudo))
#     from public.chunks_referencia;   →  5595 | 1328 | 1500
# ---------------------------------------------------------------------------
CARACTERES_POR_CHUNK = 1328
CHUNKS_DEVOLVIDOS_PELA_BUSCA = 10   # MAX_CHUNKS_PROMPT do rag.py

# ---------------------------------------------------------------------------
# Tamanho REAL da prosa de cada documento em produção (30/09/2026).
#
# Medido sobre os documentos guardados em `public.processos`, contando só
# as linhas que NÃO são de tabela — a tabela é injetada por código e
# varia com a planilha, então incluí-la misturaria duas coisas.
#
#   dfd 10.862 · etp 25.096 · tr 34.677 · edital 20.133 caracteres (média)
#
# POR QUE ISTO IMPORTA PARA A MEDIÇÃO
#
# A fixture devolve um documento curto. Se o roteiro medisse só isso, a
# CADEIA ANTERIOR — que é o maior item da conta — apareceria dez vezes
# menor do que é, e a economia medida depois seria fantasia. O texto
# continua sendo enchimento; o TAMANHO é o de produção.
#
# `mapa_riscos` não tem medida: ele nunca chegou a gerar em produção
# (era o P0 corrigido na auditoria anterior). Fica no tamanho do DFD, e
# o relatório diz que este é o único número arbitrado.
# ---------------------------------------------------------------------------
PROSA_DE_PRODUCAO = {
    "dfd": 10862,
    "etp": 25096,
    "mapa_riscos": 10862,   # arbitrado: sem geração em produção
    "tr": 34677,
    "edital": 20133,
}

# Marcadores que o montador de prompt emite. A decomposição lê o prompt
# REAL pelas fronteiras que o próprio código escreve — não por
# heurística de conteúdo.
SECOES = (
    ("memorando", "=== DOCUMENTO INICIAL DA DEMANDA"),
    ("formulario", "=== DADOS DO FORMULÁRIO MATRIZ"),
    ("cadeia_anterior", "APROVADO PELO USUÁRIO (contexto obrigatório) ==="),
    ("rag", "=== REFERÊNCIAS DA BASE DE CONHECIMENTO"),
    ("contexto_canonico", "=== CONTEXTO DO PROCESSO"),
)


# ---------------------------------------------------------------------------
# Tokenizador de verdade
# ---------------------------------------------------------------------------
def _codificacao():
    import tiktoken

    return tiktoken.get_encoding("o200k_base")


_ENC = None


def tokens(texto: str) -> int:
    global _ENC
    if _ENC is None:
        _ENC = _codificacao()
    return len(_ENC.encode(texto or "", disallowed_special=()))


def decompor(prompt_usuario: str) -> dict:
    """
    Tokens por seção do prompt do usuário.

    Corta pelas marcas que `prompts.montar_prompt` escreve. O que sobra
    antes da primeira marca é a INSTRUÇÃO do documento (abertura legal +
    esqueleto de cláusulas); o que sobra depois da última é o que os
    módulos de enriquecimento anexaram.
    """
    posicoes = []
    for nome, marca in SECOES:
        i = prompt_usuario.find(marca)
        if i >= 0:
            posicoes.append((i, nome))
    posicoes.sort()

    partes: dict[str, int] = {}
    if not posicoes:
        return {"instrucoes": tokens(prompt_usuario)}
    partes["instrucoes"] = tokens(prompt_usuario[:posicoes[0][0]])
    for ordem, (inicio, nome) in enumerate(posicoes):
        fim = (posicoes[ordem + 1][0] if ordem + 1 < len(posicoes)
               else len(prompt_usuario))
        partes[nome] = partes.get(nome, 0) + tokens(prompt_usuario[inicio:fim])
    return partes


# ---------------------------------------------------------------------------
# Observador no transporte: tokeniza o que SAIRIA para o provedor
# ---------------------------------------------------------------------------
_medidas: list[dict] = []


_ENCHIMENTO = (
    "A presente cláusula detalha o encadeamento entre a necessidade "
    "administrativa identificada, os requisitos técnicos dela decorrentes "
    "e o modelo de execução adotado, de modo que o que se exige seja "
    "exatamente o que se fiscaliza, o que se recebe e o que se paga. ")


_RE_TITULO_DE_CLAUSULA = __import__("re").compile(r"(?m)^#{1,3}\s*\d{1,2}[\.\-–]?\s")


def _ate_o_tamanho_de_producao(texto: str, doc_key: str) -> str:
    """
    Completa a resposta da fixture até a PROSA ter o tamanho medido em
    produção, DISTRIBUÍDO entre as cláusulas.

    A distribuição não é detalhe. A primeira versão desta função
    despejava o enchimento todo no fim do documento — e o fim do
    documento é uma cláusula só. Como o contexto canônico seleciona
    cláusulas, o peso inteiro caía fora da seleção e a economia medida
    saía inflada: o recorte parecia jogar fora 90% do documento quando
    jogava fora uma cláusula de enchimento.

    Espalhando proporcionalmente, cada cláusula carrega sua parte, e o
    que o recorte descarta é a fração real das cláusulas descartadas.
    """
    alvo = PROSA_DE_PRODUCAO.get(doc_key)
    if not alvo:
        return texto
    prosa = sum(len(l) + 1 for l in texto.splitlines()
                if not l.lstrip().startswith("|"))
    faltam = alvo - prosa
    if faltam <= 0:
        return texto

    cortes = [m.start() for m in _RE_TITULO_DE_CLAUSULA.finditer(texto)]
    if not cortes:
        corpo = _ENCHIMENTO * (faltam // len(_ENCHIMENTO) + 1)
        return texto + "\n\n" + corpo[:faltam]

    pedacos = [texto[:cortes[0]]] if cortes[0] else []
    for i, inicio in enumerate(cortes):
        fim = cortes[i + 1] if i + 1 < len(cortes) else len(texto)
        pedacos.append(texto[inicio:fim])

    por_clausula = faltam // len(cortes)
    corpo = _ENCHIMENTO * (por_clausula // len(_ENCHIMENTO) + 1)
    saida = []
    for pedaco in pedacos:
        if _RE_TITULO_DE_CLAUSULA.match(pedaco):
            pedaco = pedaco.rstrip() + "\n\n" + corpo[:por_clausula] + "\n\n"
        saida.append(pedaco)
    return "".join(saida)


def _instalar_observador() -> None:
    original = ia_simulada._atender  # noqa: SLF001

    def medido(corpo_bruto: bytes):
        try:
            pedido = json.loads(corpo_bruto or b"{}")
        except ValueError:
            pedido = {}
        mensagens = pedido.get("messages") or []
        sistema = "\n".join(str(m.get("content") or "") for m in mensagens
                            if m.get("role") == "system")
        usuario = "\n".join(str(m.get("content") or "") for m in mensagens
                            if m.get("role") != "system")
        _medidas.append({
            "modelo_pedido": pedido.get("model", ""),
            "teto_de_saida": (pedido.get("max_completion_tokens")
                              or pedido.get("max_tokens")),
            "tokens_sistema": tokens(sistema),
            "tokens_usuario": tokens(usuario),
            "secoes": decompor(usuario),
        })
        codigo, corpo = original(corpo_bruto)
        registrado = ia_simulada.respostas()
        doc_key = registrado[-1]["documento"] if registrado else ""
        try:
            mensagem = corpo["choices"][0]["message"]
            if mensagem.get("content"):
                mensagem["content"] = _ate_o_tamanho_de_producao(
                    mensagem["content"], doc_key)
        except (KeyError, IndexError, TypeError):
            pass
        return codigo, corpo

    ia_simulada._atender = medido  # noqa: SLF001


# ---------------------------------------------------------------------------
# RAG com tamanho de produção
# ---------------------------------------------------------------------------
# Assuntos distintos, para que os trechos sintéticos sejam DIFERENTES
# uns dos outros.
#
# Não é adorno: a primeira versão gerava todos os trechos do mesmo
# molde, mudando só o número. O deduplicador — que existe para tirar o
# mesmo dispositivo recuperado por três fontes — enxergava dez cópias e
# descartava nove. A "economia de RAG" medida era 79%, e quase toda ela
# era a fixture se auto-deduplicando. Com assuntos distintos, o corte
# passa a vir de onde ele realmente vem: do orçamento de tamanho.
_ASSUNTOS = (
    "a fase preparatória e o plano de contratações anual",
    "o critério de julgamento e o modo de disputa",
    "as condições de habilitação jurídica e fiscal",
    "o recebimento provisório e definitivo do objeto",
    "a ordem cronológica de pagamento e a liquidação",
    "as infrações administrativas e as sanções aplicáveis",
    "a garantia contratual e os seus limites",
    "o reajuste por índice em contratos de fornecimento",
    "a gestão e a fiscalização do contrato administrativo",
    "o sistema de registro de preços e a adesão à ata",
    "os impugnações e os recursos administrativos",
    "o tratamento favorecido às microempresas",
)


def _chunk_sintetico(i: int) -> str:
    """Trecho do tamanho medido na base real, com assunto próprio."""
    assunto = _ASSUNTOS[i % len(_ASSUNTOS)]
    semente = (
        f"Fonte {i}. Dispositivo que trata de {assunto}, com a redação do "
        f"caput e dos parágrafos, a orientação de controle correspondente "
        f"e o exemplo de aplicação ao caso concreto número {i}. ")
    repetido = semente * (CARACTERES_POR_CHUNK // len(semente) + 1)
    return repetido[:CARACTERES_POR_CHUNK]


def _instalar_rag_de_tamanho_real() -> None:
    """
    Substitui a BUSCA, não a recuperação.

    A diferença decide se a medição serve: trocar `rag.recuperar`
    inteiro pularia o piso de relevância, a reserva por tema, a
    deduplicação e o orçamento — que são justamente o código que muda
    entre o antes e o depois. Trocando só o que a rede traria
    (embeddings e RPC de busca), todo o resto roda de verdade.
    """
    from src import db, rag

    db.disponivel = lambda: True

    # A busca precisa ser DETERMINÍSTICA: a mesma consulta devolve os
    # mesmos trechos. Um contador global parecia inofensivo e não era —
    # o segundo pedido idêntico recebia outros trechos, o prompt saía
    # diferente, a chave do cache mudava e a medição concluía que o
    # cache não funciona. O que não funcionava era o dublê.
    #
    # O vetor carrega o hash da consulta, e o RPC deriva dele quais
    # trechos devolver. É o que uma busca vetorial de verdade faz:
    # mesma pergunta, mesma resposta.
    def _embeddings(textos, para_consulta=False):
        return [[float(int(hashlib.sha256(t.encode()).hexdigest()[:8], 16))]
                for t in textos]

    rag._gerar_embeddings = _embeddings  # noqa: SLF001

    def _rpc(nome, argumentos):
        qtd = int(argumentos.get("qtd") or 3)
        vetor = argumentos.get("query_embedding") or [0.0]
        semente = int(vetor[0]) if vetor else 0
        brutos = []
        for passo in range(qtd):
            i = (semente + passo) % 9973      # primo: espalha sem colidir
            brutos.append({
                "conteudo": _chunk_sintetico(i),
                "titulo": f"Fonte simulada {i + 1}",
                "categoria": "lei",
                "similaridade": 0.90 - (i % 10) * 0.01,
                "documento_id": f"sim-{i + 1}",
                "ordem": i,
            })
        return brutos

    rag._executar_rpc = _rpc  # noqa: SLF001


# ---------------------------------------------------------------------------
# Percurso de um processo
# ---------------------------------------------------------------------------
def _preparar_motores(llm) -> None:
    llm.obter_openai_key = lambda: CHAVE_DE_ENSAIO
    llm.obter_api_key = lambda: ""
    llm.obter_openrouter_key = lambda: ""


class _SessaoDeMedicao:
    """
    `st` com um `session_state` que FUNCIONA fora do Streamlit.

    Sem isto a medição do cache seria falsa em silêncio: fora de um
    `streamlit run`, `st.session_state` não guarda nada, o cache de
    sessão nunca acerta, e o roteiro concluiria que o cache não
    funciona quando o que não funciona é o ambiente da medição.

    O resto do módulo continua sendo o Streamlit de verdade — só o
    dicionário de sessão é substituído.
    """

    def __init__(self, real):
        self._real = real
        self.session_state: dict = {}

    def __getattr__(self, nome):
        return getattr(self._real, nome)


def _instalar_sessao() -> None:
    import streamlit as st

    from src import cache_geracao, llm

    sessao = _SessaoDeMedicao(st)
    llm.st = sessao
    cache_geracao.st = sessao


def medir_processo(cenario: dict) -> dict:
    from src import llm

    _preparar_motores(llm)
    documentos: dict[str, str] = {}
    aprovados: set[str] = set()
    por_documento = []

    for doc_key in COM_IA:
        sem_llm.zerar()
        ia_simulada.zerar()
        _medidas.clear()
        inicio = time.time()
        contexto = _contexto_da_cadeia(documentos, aprovados, doc_key)
        try:
            texto = llm.gerar_documento(doc_key, dict(cenario["dados"]),
                                        contexto)
            falha = ""
        except Exception as erro:  # noqa: BLE001
            texto, falha = "", type(erro).__name__
        documentos[doc_key] = texto
        aprovados.add(doc_key)       # o fluxo real só encadeia o aprovado

        secoes: collections.Counter = collections.Counter()
        for m in _medidas:
            secoes.update(m["secoes"])
        bloqueadas = collections.Counter(
            e["caminho"] for e in sem_llm.relatorio())

        por_documento.append({
            "documento": doc_key,
            "requisicoes_de_conversa": len(_medidas),
            "requisicoes_bloqueadas": dict(bloqueadas),
            "tokens_entrada": sum(m["tokens_sistema"] + m["tokens_usuario"]
                                  for m in _medidas),
            "tokens_sistema": sum(m["tokens_sistema"] for m in _medidas),
            "tokens_usuario": sum(m["tokens_usuario"] for m in _medidas),
            "secoes_do_prompt": dict(secoes),
            "teto_de_saida_pedido": sorted(
                {m["teto_de_saida"] for m in _medidas}),
            "modelos_pedidos": sorted({m["modelo_pedido"] for m in _medidas}),
            "caracteres_de_saida": len(texto),
            "segundos": round(time.time() - inicio, 2),
            "falha": falha,
        })

    return {"cenario": cenario["id"], "titulo": cenario["titulo"],
            "documentos": por_documento,
            "total": _somar(por_documento)}


def _contexto_da_cadeia(documentos: dict, aprovados: set, doc_key: str):
    """
    O MESMO contexto que a tela monta — `state.contexto_para_documento`
    sem o `st.session_state`, para o roteiro rodar fora do Streamlit.

    Quando o contexto canônico existir, esta função passa por ele: é o
    ponto único em que a cadeia vira prompt, aqui e no app.
    """
    from src.config import DOCUMENTOS, SEQUENCIA_COM_MAPA

    try:
        from src import resumo_processo
    except ImportError:
        resumo_processo = None

    ordem = list(SEQUENCIA_COM_MAPA)
    anteriores = [d for d in ordem[:ordem.index(doc_key)]
                  if d in documentos and d in aprovados and documentos[d]]
    if not anteriores:
        return None
    if resumo_processo is not None and resumo_processo.ativo():
        return resumo_processo.contexto_canonico(
            {d: documentos[d] for d in anteriores}, doc_key)
    return "\n\n".join(
        f"=== {DOCUMENTOS[d]['titulo']} aprovado ===\n{documentos[d]}"
        for d in anteriores)


def _somar(por_documento: list[dict]) -> dict:
    return {
        "requisicoes_de_conversa": sum(d["requisicoes_de_conversa"]
                                       for d in por_documento),
        "tokens_entrada": sum(d["tokens_entrada"] for d in por_documento),
        "segundos": round(sum(d["segundos"] for d in por_documento), 2),
        "secoes_do_prompt": dict(sum(
            (collections.Counter(d["secoes_do_prompt"])
             for d in por_documento), collections.Counter())),
    }


# ---------------------------------------------------------------------------
# Pior caso: uma ação do servidor quando o provedor recusa
# ---------------------------------------------------------------------------
def medir_tempestade_de_retentativa() -> dict:
    """
    UM clique do servidor quando o provedor recusa: quantas requisições
    saem, e por quanto tempo a tela fica presa.

    Com os três motores configurados, que é o pior caso possível e não
    um cenário inventado: é o estado de uma instalação com chave da
    OpenAI, do Gemini e do OpenRouter no painel.
    """
    from src import llm

    llm.obter_openai_key = lambda: CHAVE_DE_ENSAIO
    llm.obter_api_key = lambda: CHAVE_DE_ENSAIO
    llm.obter_openrouter_key = lambda: CHAVE_DE_ENSAIO
    ia_simulada.remover()        # ninguém atende: força o caminho de falha
    sem_llm.zerar()
    inicio = time.time()
    try:
        llm.chamar_ia_texto("sistema", "usuário")
    except Exception:  # noqa: BLE001 — a falha É o objeto da medição
        pass
    por_host = collections.Counter(e["host"] for e in sem_llm.relatorio())
    total = sem_llm.tentativas()
    segundos = round(time.time() - inicio, 1)
    ia_simulada.instalar()
    _preparar_motores(llm)
    return {
        "requisicoes_em_uma_acao_que_falha": total,
        "por_host": dict(por_host),
        "segundos_ate_desistir": segundos,
        "tentativas_por_modelo": getattr(llm, "API_TENTATIVAS", "?"),
    }


def medir_repeticao(cenario: dict) -> dict:
    """
    O MESMO documento pedido duas vezes: quantas chamadas saem?

    É a medida mais direta de "eliminar chamadas duplicadas", que é a
    prioridade 1 do pedido. Clique duplo, rerun e reload produzem
    exatamente esta situação — pedido idêntico, processo inalterado.
    """
    from src import cache_geracao, llm

    _preparar_motores(llm)
    # Sessão limpa: os processos medidos antes desta função já passaram
    # pelo mesmo DFD, e sem a limpeza a medição começaria com o cache
    # quente — o primeiro pedido apareceria como zero chamada e o
    # número não diria nada sobre repetição.
    cache_geracao.st.session_state.pop(cache_geracao.CHAVE_NA_SESSAO, None)
    sem_llm.zerar()
    _medidas.clear()
    for _ in range(2):
        llm.gerar_documento("dfd", dict(cenario["dados"]), None)
    return {
        "cenario": cenario["id"],
        "pedidos_do_servidor": 2,
        "requisicoes_ao_provedor": len(_medidas),
        "tokens_entrada": sum(m["tokens_sistema"] + m["tokens_usuario"]
                              for m in _medidas),
    }


def medir_alteracao_de_um_campo(cenario: dict) -> dict:
    """
    Um campo do formulário muda: quanto do processo precisa ser refeito?

    Mede as duas grandezas que decidem a conta:
      * quantos DOCUMENTOS são descartados (antes: todos);
      * que fração das CLÁUSULAS de cada documento preservado precisa
        ser reescrita — que é a fração da SAÍDA que se paga.

    A saída em tokens não é medida aqui (não há modelo respondendo);
    o que se mede é a fração de cláusulas, e o relatório aplica essa
    fração à saída real de produção dizendo que é o que está fazendo.
    """
    from src import perfis, regeneracao

    campo = "prazo"
    antes = dict(cenario["dados"])
    depois = {**antes, campo: "Contratação pretendida para o segundo "
                              "semestre de 2026."}
    alterados = regeneracao.campos_alterados(antes, depois)
    ligada = regeneracao.ativo()

    por_documento = []
    for doc_key in COM_IA:
        # Com a flag desligada não existe plano nenhum: o formulário
        # alterado descarta os documentos seguintes, que é o
        # comportamento de hoje e o que a medição do "antes" tem de
        # refletir.
        pedidas = (regeneracao.clausulas_afetadas(doc_key, alterados)
                   if ligada else None)
        total = len(perfis.PERFIS.get(doc_key, {}).get("clausulas", []))
        por_documento.append({
            "documento": doc_key,
            "descartado": pedidas is None,
            "clausulas_reescritas": len(pedidas) if pedidas else total,
            "clausulas_no_documento": total,
        })
    preservados = [d for d in por_documento if not d["descartado"]]
    return {
        "cenario": cenario["id"],
        "campo_alterado": campo,
        "documentos_descartados_antes": len(COM_IA),
        "documentos_descartados_depois": len(por_documento) - len(preservados),
        "por_documento": por_documento,
        "fracao_de_clausulas_reescritas": round(
            sum(d["clausulas_reescritas"] for d in preservados)
            / max(sum(d["clausulas_no_documento"] for d in preservados), 1), 3)
        if preservados else 1.0,
    }


def medir_auditoria_semantica(cenario: dict) -> dict:
    """
    O que a auditoria semântica manda por chamada.

    Ela entra aqui porque em produção é o MAIOR consumidor que existe —
    47 chamadas de corretor e 18 de auditor contra 25 de geração de
    documento, cada uma com ~23 mil tokens de entrada. Um relatório de
    economia que olhasse só a geração mediria a metade menor.
    """
    from src import ciclo, llm

    _preparar_motores(llm)
    documentos: dict[str, str] = {}
    aprovados: set[str] = set()
    for doc_key in COM_IA:
        contexto = _contexto_da_cadeia(documentos, aprovados, doc_key)
        try:
            documentos[doc_key] = llm.gerar_documento(
                doc_key, dict(cenario["dados"]), contexto)
            aprovados.add(doc_key)
        except Exception:  # noqa: BLE001
            documentos[doc_key] = ""

    _medidas.clear()
    try:
        ciclo.auditoria_semantica(documentos)
    except Exception:  # noqa: BLE001 — a fixture não devolve JSON de finding
        pass
    return {
        "cenario": cenario["id"],
        "requisicoes": len(_medidas),
        "tokens_entrada": sum(m["tokens_sistema"] + m["tokens_usuario"]
                              for m in _medidas),
        "teto_de_saida_pedido": sorted({m["teto_de_saida"] for m in _medidas}),
        "modelos_pedidos": sorted({m["modelo_pedido"] for m in _medidas}),
        "caracteres_dos_documentos": sum(len(v) for v in documentos.values()),
    }


def _ligar_flags(nomes: list[str]) -> None:
    """
    Liga as flags de custo para ESTA medição.

    A medição declara a configuração que mede: sem isto, o roteiro
    leria as flags do banco — que não existe aqui — e mediria sempre o
    estado desligado, de modo que "antes" e "depois" dariam o mesmo
    número e o relatório não provaria nada.

    Só o que está em `nomes` é ligado. Toda flag fora da lista continua
    respondendo o que responderia, que é `False`.
    """
    from src import db

    ligadas = set(nomes)
    original = db.flag_ativa
    db.flag_ativa = lambda nome: nome in ligadas or (
        False if nome in TODAS_AS_FLAGS else original(nome))


TODAS_AS_FLAGS = ("cache_geracao", "contexto_canonico", "rag_enxuto",
                  "regeneracao_parcial", "politica_de_modelo")


def principal() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", default="antes")
    ap.add_argument("--saida", default="docs/custo/antes.json")
    ap.add_argument(
        "--flags", default="",
        help="flags de custo a ligar nesta medição, separadas por vírgula; "
             f"'todas' liga {', '.join(TODAS_AS_FLAGS)}")
    argumentos = ap.parse_args()

    flags = ([] if not argumentos.flags else
             list(TODAS_AS_FLAGS) if argumentos.flags == "todas" else
             [f.strip() for f in argumentos.flags.split(",") if f.strip()])
    if flags:
        _ligar_flags(flags)

    sem_llm.instalar()
    ia_simulada.instalar()
    ia_simulada.autoteste()
    _instalar_observador()
    _instalar_rag_de_tamanho_real()
    _instalar_sessao()

    relatorio = {
        "rotulo": argumentos.rotulo,
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tokenizador": "o200k_base (tiktoken)",
        "rag_simulado": {
            "chunks": CHUNKS_DEVOLVIDOS_PELA_BUSCA,
            "caracteres_por_chunk": CARACTERES_POR_CHUNK,
            "origem_do_tamanho": "medição de public.chunks_referencia "
                                 "(5.595 chunks, média 1.328 caracteres)",
        },
        "processos": [medir_processo(c) for c in (
            massas.CENARIO_F, massas.CENARIO_A, massas.cenario_g())],
        "repeticao_do_mesmo_pedido": medir_repeticao(massas.CENARIO_A),
        "alteracao_de_um_campo": medir_alteracao_de_um_campo(massas.CENARIO_A),
        "auditoria_semantica": [medir_auditoria_semantica(c) for c in (
            massas.CENARIO_A, massas.cenario_g())],
        "tempestade_de_retentativa": medir_tempestade_de_retentativa(),
    }

    caminho = RAIZ / argumentos.saida
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(relatorio, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
