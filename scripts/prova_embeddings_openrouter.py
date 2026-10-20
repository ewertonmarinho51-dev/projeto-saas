#!/usr/bin/env python
"""
Prova de equivalência: os vetores servidos pelo OpenRouter caem no MESMO
espaço do índice v2 gravado? (C09)

O índice v2 foi gerado com `text-embedding-3-small` (768 dimensões) pela
API da OpenAI. O OpenRouter serve `openai/text-embedding-3-small`. Mesmo
nome não é prova: este script pega uma amostra de chunks JÁ indexados,
pede o vetor do MESMO texto ao OpenRouter e mede o cosseno contra o vetor
gravado. Mesmo modelo, mesma dimensão e mesma normalização dão cosseno
~1,0; qualquer outra coisa reprova.

SOMENTE LEITURA: não grava vetor, status nem proveniência. Não imprime
conteúdo de chunk, chave, token nem URL do projeto — só estatística.

Uso, dentro do contentor do app no VPS (que já tem as credenciais no
ambiente):

    docker compose exec -T app python - < scripts/prova_embeddings_openrouter.py

Saída 0 = equivalente (pode ligar GOVDOCS_EMBEDDINGS_OPENROUTER=1);
1 = reprovado (NÃO ligar: reindexar em índice novo versionado);
2 = não foi possível medir (credencial, rede, amostra vazia).
"""

from __future__ import annotations

import math
import os
import sys

AMOSTRA = int(os.environ.get("PROVA_AMOSTRA", "40"))
LIMIAR = float(os.environ.get("PROVA_LIMIAR", "0.999"))
MODELO = "openai/text-embedding-3-small"
DIMENSOES = 768
BASE_URL = "https://openrouter.ai/api/v1"


def _cosseno(a: list[float], b: list[float]) -> float:
    pa = math.sqrt(sum(x * x for x in a))
    pb = math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (pa * pb) if pa and pb else 0.0


def _vetor(valor) -> list[float]:
    # o PostgREST devolve `vector` como texto "[0.1,0.2,...]"
    if isinstance(valor, str):
        return [float(x) for x in valor.strip("[]").split(",") if x]
    return [float(x) for x in valor]


def _chave_openrouter(cliente) -> str:
    chave = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if chave:
        return chave
    # mesmo contrato do app: o painel do administrador grava em config_app
    linhas = (cliente.table("config_app").select("valor")
              .eq("chave", "OPENROUTER_API_KEY").limit(1).execute()).data
    return ((linhas or [{}])[0].get("valor") or "").strip()


def main() -> int:
    from openai import OpenAI
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL", "").strip()
    servidor = (os.environ.get("SUPABASE_SECRET_KEY", "")
                or os.environ.get("SUPABASE_SERVICE_KEY", "")).strip()
    if not (url and servidor):
        print("SEM_CREDENCIAL: SUPABASE_URL/credencial de servidor ausentes")
        return 2
    banco = create_client(url, servidor)
    chave = _chave_openrouter(banco)
    if not chave:
        print("SEM_CREDENCIAL: chave do OpenRouter ausente")
        return 2

    linhas = (banco.table("chunks_referencia")
              .select("id,conteudo,embedding_v2,embedding_model,"
                      "embedding_dimensions,embedding_version")
              .eq("embedding_status", "ok").order("id")
              .limit(AMOSTRA).execute()).data or []
    linhas = [l for l in linhas if l.get("embedding_v2")]
    if not linhas:
        print("AMOSTRA_VAZIA: nenhum chunk com embedding_v2 'ok'")
        return 2

    cliente = OpenAI(api_key=chave, base_url=BASE_URL, timeout=60,
                     max_retries=1)
    resposta = cliente.embeddings.create(
        model=MODELO, input=[l["conteudo"] for l in linhas],
        dimensions=DIMENSOES)
    novos = [item.embedding for item in resposta.data]
    if len(novos) != len(linhas) or any(len(v) != DIMENSOES for v in novos):
        print(f"REPROVADO: dimensão/quantidade divergente "
              f"({len(novos)} vetores para {len(linhas)} chunks)")
        return 1

    cossenos = sorted(_cosseno(_vetor(l["embedding_v2"]), v)
                      for l, v in zip(linhas, novos))
    modelos = sorted({str(l.get("embedding_model")) for l in linhas})
    print(f"amostra={len(cossenos)} modelos_gravados={modelos}")
    print(f"cosseno min={cossenos[0]:.6f} "
          f"mediana={cossenos[len(cossenos) // 2]:.6f} "
          f"max={cossenos[-1]:.6f} limiar={LIMIAR}")
    if cossenos[0] >= LIMIAR:
        print("EQUIVALENTE: pode ligar GOVDOCS_EMBEDDINGS_OPENROUTER=1")
        return 0
    print("REPROVADO: não ligar a rota; preparar índice novo versionado")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 — sem corpo de erro na saída
        print(f"ERRO_DE_MEDICAO: {type(exc).__name__}")
        sys.exit(2)
