#!/usr/bin/env python
"""
Backfill do índice vetorial V2 (openai/text-embedding-3-small/768).

Reconstrói `chunks_referencia.embedding_v2` para TODOS os chunks — não
apenas os que estão sem vetor —, porque a origem dos vetores da coluna
legada `embedding` não pôde ser comprovada (auditoria de 11/08/2026) e
misturar espaços vetoriais produz busca que responde errado em silêncio.

Garantias:
  - NÃO altera `conteudo`, `ordem`, `documento_id`, `tsv` nem a coluna
    legada `embedding` (a produção continua funcionando durante todo o
    processo);
  - idempotente e retomável: processa apenas `embedding_v2 is null`, em
    ordem estável; uma execução interrompida continua de onde parou;
  - sem fallback de provedor: se a OpenAI falhar, o lote é marcado como
    'falha' e reprocessado na execução seguinte — jamais se grava vetor
    de outro modelo;
  - proveniência gravada em cada chunk (provedor, modelo, dimensão,
    versão, data).

Uso (no ambiente que tem as credenciais — Streamlit Cloud ou local):
    python scripts/reindexar_embeddings_v2.py --lote 100
    python scripts/reindexar_embeddings_v2.py --validar
    python scripts/reindexar_embeddings_v2.py --simular   # nada grava

Credenciais: SUPABASE_URL, SUPABASE_KEY e OPENAI_API_KEY no ambiente ou
em .streamlit/secrets.toml. Nenhuma chave é impressa.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from src.config import (  # noqa: E402
    EMBEDDING_V2_DIMENSOES, EMBEDDING_V2_MODELO, EMBEDDING_V2_PROVEDOR,
    EMBEDDING_V2_VERSAO,
)

TABELA = "chunks_referencia"


# ---------------------------------------------------------------------------
# Credenciais (ambiente ou .streamlit/secrets.toml) — nunca impressas
# ---------------------------------------------------------------------------
def _segredo(nome: str) -> str:
    valor = os.environ.get(nome, "")
    if valor:
        return valor
    caminho = RAIZ / ".streamlit" / "secrets.toml"
    if not caminho.exists():
        return ""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        return ""
    with open(caminho, "rb") as fh:
        return str(tomllib.load(fh).get(nome, ""))


def _exigir(nome: str) -> str:
    valor = _segredo(nome)
    if not valor:
        raise SystemExit(
            f"[ABORTADO] {nome} não configurado. Rode este script no "
            "ambiente que possui as credenciais; nada foi alterado.")
    return valor


def cliente_supabase():
    from supabase import create_client

    return create_client(_exigir("SUPABASE_URL"), _exigir("SUPABASE_KEY"))


def cliente_openai():
    from openai import OpenAI

    return OpenAI(api_key=_exigir("OPENAI_API_KEY"), timeout=120,
                  max_retries=2)


# ---------------------------------------------------------------------------
# Backfill
# ---------------------------------------------------------------------------
def pendentes(sb, limite: int) -> list[dict]:
    """Próximo lote a vetorizar, em ordem estável (retomada natural)."""
    return (sb.table(TABELA)
            .select("id, documento_id, ordem, conteudo")
            .is_("embedding_v2", "null")
            .order("documento_id").order("ordem")
            .limit(limite).execute()).data or []


def total_pendentes(sb) -> int:
    return (sb.table(TABELA).select("id", count="exact")
            .is_("embedding_v2", "null").limit(1).execute()).count or 0


def vetorizar(openai_, textos: list[str]) -> list[list[float]]:
    """Embeddings do modelo FIXO. Erro sobe — nunca troca de provedor."""
    resposta = openai_.embeddings.create(
        model=EMBEDDING_V2_MODELO, input=textos,
        dimensions=EMBEDDING_V2_DIMENSOES)
    vetores = [item.embedding for item in resposta.data]
    if len(vetores) != len(textos):
        raise RuntimeError(
            f"a API devolveu {len(vetores)} vetores para {len(textos)} textos")
    for vetor in vetores:
        if len(vetor) != EMBEDDING_V2_DIMENSOES:
            raise RuntimeError(
                f"dimensão inesperada: {len(vetor)} ≠ {EMBEDDING_V2_DIMENSOES}")
    return vetores


def gravar(sb, chunk: dict, vetor: list[float]) -> None:
    """Grava vetor + proveniência. Só toca colunas do índice V2."""
    sb.table(TABELA).update({
        "embedding_v2": vetor,
        "embedding_provider": EMBEDDING_V2_PROVEDOR,
        "embedding_model": EMBEDDING_V2_MODELO,
        "embedding_dimensions": EMBEDDING_V2_DIMENSOES,
        "embedding_version": EMBEDDING_V2_VERSAO,
        "embedding_generated_at": datetime.now(timezone.utc).isoformat(),
        "embedding_status": "ok",
    }).eq("id", chunk["id"]).execute()


def marcar_falha(sb, chunk: dict) -> None:
    sb.table(TABELA).update({"embedding_status": "falha"}).eq(
        "id", chunk["id"]).execute()


def executar(lote: int, maximo: int | None, simular: bool) -> int:
    sb = cliente_supabase()
    restantes = total_pendentes(sb)
    print(f"[inicio] {restantes} chunk(s) pendente(s) de "
          f"{EMBEDDING_V2_PROVEDOR}/{EMBEDDING_V2_MODELO}/"
          f"{EMBEDDING_V2_DIMENSOES} ({EMBEDDING_V2_VERSAO})")
    if simular:
        amostra = pendentes(sb, min(lote, 3))
        for c in amostra:
            print(f"  [simulação] chunk {c['id']} ordem {c['ordem']} "
                  f"({len(c['conteudo'])} caracteres) — nada gravado")
        return 0

    openai_ = cliente_openai()
    processados = 0
    while True:
        if maximo is not None and processados >= maximo:
            break
        atual = pendentes(sb, lote)
        if not atual:
            break
        try:
            vetores = vetorizar(openai_, [c["conteudo"] for c in atual])
        except Exception as erro:  # noqa: BLE001
            # lote inteiro fica para a próxima execução (retomável)
            print(f"  [falha] lote de {len(atual)}: {type(erro).__name__} — "
                  "marcado para reprocessamento")
            for c in atual:
                marcar_falha(sb, c)
            time.sleep(5)
            continue
        for chunk, vetor in zip(atual, vetores):
            gravar(sb, chunk, vetor)
        processados += len(atual)
        print(f"  [ok] {processados} processado(s); "
              f"{total_pendentes(sb)} restante(s)")
    print(f"[fim] {processados} chunk(s) vetorizado(s) nesta execução")
    return processados


# ---------------------------------------------------------------------------
# Validação (item 8 do plano)
# ---------------------------------------------------------------------------
CONSULTAS_VALIDACAO = """
select
  (select count(*) from public.chunks_referencia) as chunks,
  (select count(*) from public.chunks_referencia where embedding_v2 is not null) as com_v2,
  (select count(*) from public.chunks_referencia where embedding_status <> 'ok') as fora_de_ok,
  (select count(distinct vector_dims(embedding_v2)) from public.chunks_referencia
    where embedding_v2 is not null) as dimensoes_distintas,
  (select count(*) from public.chunks_referencia where embedding is not null) as legado_intacto,
  (select md5(string_agg(id::text || '|' || documento_id::text || '|' ||
                         ordem::text || '|' || md5(conteudo), ',' order by id))
     from public.chunks_referencia) as impressao_estrutural;
"""


def validar() -> None:
    """Confere cobertura e integridade (roda as verificações via REST)."""
    sb = cliente_supabase()
    total = (sb.table(TABELA).select("id", count="exact").limit(1)
             .execute()).count or 0
    com_v2 = (sb.table(TABELA).select("id", count="exact")
              .not_.is_("embedding_v2", "null").limit(1).execute()).count or 0
    fora = (sb.table(TABELA).select("id", count="exact")
            .neq("embedding_status", "ok").limit(1).execute()).count or 0
    legado = (sb.table(TABELA).select("id", count="exact")
              .not_.is_("embedding", "null").limit(1).execute()).count or 0
    print(f"cobertura ......... {com_v2}/{total}")
    print(f"fora de 'ok' ...... {fora}")
    print(f"legado intacto .... {legado} (esperado: 2978)")
    print("\nExecute também, no SQL Editor, a conferência completa:"
          + CONSULTAS_VALIDACAO)
    if com_v2 != total or fora:
        raise SystemExit("[INCOMPLETO] backfill ainda não está pronto para o corte")
    print("[OK] cobertura integral — apto ao índice e ao corte do RPC")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lote", type=int, default=100,
                        help="chunks por chamada de embedding (padrão 100)")
    parser.add_argument("--limite", type=int, default=None,
                        help="processa no máximo N chunks e para")
    parser.add_argument("--simular", action="store_true",
                        help="mostra o que faria, sem gravar nada")
    parser.add_argument("--validar", action="store_true",
                        help="apenas confere a cobertura do índice V2")
    args = parser.parse_args()
    if args.validar:
        validar()
        return
    executar(args.lote, args.limite, args.simular)


if __name__ == "__main__":
    main()
