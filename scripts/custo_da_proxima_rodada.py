#!/usr/bin/env python3
"""
§15 e §20-E: quanto a rodada OPERACIONAL vai chamar, medido com zero custo.

    GOVDOCS_IA_SIMULADA=coerente python scripts/custo_da_proxima_rodada.py

O §20-E pede orçamento e limites para a bateria com APIs reais. Orçamento
sem medida é chute, e chute em cima de LLM erra por ordem de grandeza.
Este roteiro percorre um processo inteiro com a IA simulada e CONTA:

  * quantas requisições de conversa saem por documento;
  * quantas requisições de EMBEDDING saem por documento — que é o
    achado: elas existem e ninguém as conta ao pensar no custo;
  * quantos caracteres viajam em cada prompt, por documento;
  * quantas requisições uma ÚNICA ação do servidor pode disparar quando
    o provedor falha, contando a retentativa por modelo e a queda entre
    motores.

Nada aqui chama API paga: as conversas são atendidas por fixture e as
demais tentativas são barradas e contadas por `sem_llm`.
"""

from __future__ import annotations

import collections
import json
import pathlib
import sys

RAIZ = pathlib.Path(__file__).resolve().parent.parent
for caminho in (str(RAIZ), str(RAIZ / "tests"), str(RAIZ / "scripts"),
                str(RAIZ / "scripts" / "bloqueio_de_custo")):
    if caminho not in sys.path:
        sys.path.insert(0, caminho)

import ia_simulada  # noqa: E402
import sem_llm  # noqa: E402

import massas_auditoria as massas  # noqa: E402

SAIDA = pathlib.Path("/tmp/auditoria")
CHAVE_DE_ENSAIO = "ensaio-sem-custo-isto-nao-e-credencial"

# O fluxo com `flag_mapa_riscos` ligada, que é o de produção. `edital` e
# `arp` ficam de fora porque não passam por modelo nenhum — são montados
# do catálogo de cláusulas, e contá-los inflaria o orçamento com
# chamadas que não existem.
COM_IA = ("dfd", "etp", "mapa_riscos", "tr")


def _preparar(llm):
    llm.obter_openai_key = lambda: CHAVE_DE_ENSAIO
    llm.obter_api_key = lambda: ""
    llm.obter_openrouter_key = lambda: ""


def medir_um_processo(cenario: dict) -> dict:
    from src import llm

    _preparar(llm)
    por_documento = []
    contexto = None
    for doc_key in COM_IA:
        sem_llm.zerar()
        ia_simulada.zerar()
        try:
            texto = llm.gerar_documento(doc_key, dict(cenario["dados"]),
                                        contexto)
            contexto = texto
            falhou = ""
        except Exception as erro:  # noqa: BLE001
            texto, falhou = "", f"{type(erro).__name__}"

        caminhos = collections.Counter(
            evento["caminho"] for evento in sem_llm.relatorio())
        respostas = ia_simulada.respostas()
        por_documento.append({
            "documento": doc_key,
            "conversas": len(respostas),
            "bloqueadas": dict(caminhos),
            "caracteres_no_prompt": sum(
                r["caracteres_no_sistema"] + r["caracteres_no_usuario"]
                for r in respostas),
            "saida_caracteres": len(texto),
            "falha": falhou,
        })
    return {"cenario": cenario["id"], "documentos": por_documento}


def medir_uma_falha_de_provedor() -> dict:
    """
    Quantas requisições UMA ação do servidor dispara quando o provedor
    recusa.

    É o pior caso de custo, e o que ninguém orça: `_openai_uma_chamada`
    repete `API_TENTATIVAS` vezes com espera crescente, `_chamar_openai`
    percorre a lista de modelos alternativos, e `_percorrer_motores` cai
    para o motor seguinte. Com a fixture desligada, tudo isso esbarra no
    bloqueio e vira contagem.
    """
    from src import llm

    _preparar(llm)
    ia_simulada.remover()          # ninguém atende: força o caminho de falha
    sem_llm.zerar()
    try:
        llm.chamar_ia_texto("sistema", "usuário")
    except Exception:  # noqa: BLE001 — a falha é o objeto da medição
        pass
    caminhos = collections.Counter(
        evento["caminho"] for evento in sem_llm.relatorio())
    ia_simulada.instalar()
    return {"requisicoes_em_uma_acao_que_falha": sem_llm.tentativas(),
            "por_caminho": dict(caminhos),
            "tentativas_por_modelo": getattr(llm, "API_TENTATIVAS", "?")}


def principal() -> int:
    sem_llm.instalar()
    ia_simulada.instalar()

    relatorio = {
        "processos": [medir_um_processo(c)
                      for c in (massas.CENARIO_F, massas.CENARIO_A,
                                massas.cenario_g())],
        "falha_de_provedor": medir_uma_falha_de_provedor(),
    }

    for processo in relatorio["processos"]:
        conversas = sum(d["conversas"] for d in processo["documentos"])
        embeddings = sum(
            v for d in processo["documentos"]
            for k, v in d["bloqueadas"].items() if "embedding" in k)
        caracteres = sum(d["caracteres_no_prompt"]
                         for d in processo["documentos"])
        processo["total"] = {
            "conversas": conversas,
            "requisicoes_de_embedding": embeddings,
            "caracteres_de_prompt": caracteres,
        }

    SAIDA.mkdir(parents=True, exist_ok=True)
    (SAIDA / "custo.json").write_text(
        json.dumps(relatorio, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(relatorio, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
