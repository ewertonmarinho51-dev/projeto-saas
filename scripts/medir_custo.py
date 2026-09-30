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


def _ate_o_tamanho_de_producao(texto: str, doc_key: str) -> str:
    """
    Completa a resposta da fixture até a PROSA ter o tamanho medido em
    produção. Não toca no que a fixture escreveu — o acréscimo vai ao
    final, depois do documento, e existe só para a cadeia pesar o que
    pesa de verdade na etapa seguinte.
    """
    alvo = PROSA_DE_PRODUCAO.get(doc_key)
    if not alvo:
        return texto
    prosa = sum(len(l) + 1 for l in texto.splitlines()
                if not l.lstrip().startswith("|"))
    faltam = alvo - prosa
    if faltam <= 0:
        return texto
    corpo = _ENCHIMENTO * (faltam // len(_ENCHIMENTO) + 1)
    return texto + "\n\n" + corpo[:faltam]


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
def _chunk_sintetico(i: int) -> str:
    """Trecho do tamanho medido na base real. Conteúdo é preenchimento."""
    semente = (f"Trecho de referência {i} da base de conhecimento. "
               "Dispositivo da Lei nº 14.133/2021 aplicável ao caso, com "
               "a redação integral do artigo e seus parágrafos. ")
    repetido = semente * (CARACTERES_POR_CHUNK // len(semente) + 1)
    return repetido[:CARACTERES_POR_CHUNK]


def _instalar_rag_de_tamanho_real() -> None:
    from src import rag

    def recuperar(dados, doc_key):
        temas = rag.temas_para(dados, doc_key) or ["geral"]
        referencias = []
        for i in range(CHUNKS_DEVOLVIDOS_PELA_BUSCA):
            tema = temas[i % len(temas)]
            rotulo = rag.TEMAS_JURIDICOS.get(tema, (tema,))[0]
            referencias.append({
                "conteudo": _chunk_sintetico(i),
                "titulo": f"Fonte simulada {i + 1}",
                "categoria": "lei",
                "score": 0.9 - i * 0.01,
                "tema": tema,
                "tema_rotulo": rotulo,
                "documento_id": f"sim-{i + 1}",
                "ordem": i,
            })
        return {
            "referencias": referencias,
            "consultas": [{"tema": t, "texto": f"consulta {t}",
                           "recuperados": rag.TOP_K_TEMA} for t in temas],
            "modo": "vetorial", "piso": rag.PISO_VETORIAL_PADRAO,
            "descartados": 0,
        }

    rag.recuperar = recuperar


# ---------------------------------------------------------------------------
# Percurso de um processo
# ---------------------------------------------------------------------------
def _preparar_motores(llm) -> None:
    llm.obter_openai_key = lambda: CHAVE_DE_ENSAIO
    llm.obter_api_key = lambda: ""
    llm.obter_openrouter_key = lambda: ""


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


def principal() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rotulo", default="antes")
    ap.add_argument("--saida", default="docs/custo/antes.json")
    argumentos = ap.parse_args()

    sem_llm.instalar()
    ia_simulada.instalar()
    ia_simulada.autoteste()
    _instalar_observador()
    _instalar_rag_de_tamanho_real()

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
