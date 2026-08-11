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
# Credenciais — resolvidas, NUNCA exibidas
#
# Ordem: variável de ambiente → .streamlit/secrets.toml → configuração
# administrativa no banco (`config_app`, o mesmo contrato que a aplicação
# usa em llm._ler_chave). O valor não é impresso, logado, mascarado nem
# medido: o script só informa se a credencial existe.
# ---------------------------------------------------------------------------
def _do_ambiente(nome: str) -> str:
    return os.environ.get(nome, "").strip()


def _dos_secrets(nome: str) -> str:
    caminho = RAIZ / ".streamlit" / "secrets.toml"
    if not caminho.exists():
        return ""
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
        return ""
    with open(caminho, "rb") as fh:
        return str(tomllib.load(fh).get(nome, "")).strip()


def _do_banco(nome: str) -> str:
    """Configuração administrativa (config_app) — contrato da aplicação."""
    try:
        from src import db

        return db.obter_config(nome).strip()
    except Exception:  # noqa: BLE001 — sem banco disponível, segue vazio
        return ""


def resolver_credencial(nome: str, com_banco: bool = True) -> str:
    """Valor da credencial (jamais impresso) ou string vazia."""
    for origem in (_do_ambiente, _dos_secrets):
        valor = origem(nome)
        if valor:
            return valor
    return _do_banco(nome) if com_banco else ""


def credencial_disponivel(nome: str, com_banco: bool = True) -> bool:
    """Presença da credencial — é isto que o script pode reportar."""
    return bool(resolver_credencial(nome, com_banco))


def _exigir(nome: str, com_banco: bool = True) -> str:
    valor = resolver_credencial(nome, com_banco)
    if not valor:
        raise SystemExit(
            f"[ABORTADO] credencial {nome} indisponível (ambiente, secrets "
            "e configuração administrativa). Nada foi alterado.")
    return valor


def cliente_supabase():
    from supabase import create_client

    # o acesso ao banco não pode depender do próprio banco
    return create_client(_exigir("SUPABASE_URL", com_banco=False),
                         _exigir("SUPABASE_KEY", com_banco=False))


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


# Tentativas por LOTE antes de desistir da execução. Esgotadas, o script
# encerra com erro em vez de martelar a API: os chunks continuam com
# `embedding_v2 is null` e a próxima execução os reprocessa.
MAX_TENTATIVAS_LOTE = 3
BACKOFF_BASE_SEGUNDOS = 2


class BackfillInterrompido(RuntimeError):
    """Provedor persistentemente indisponível — execução encerrada."""


def _vetorizar_com_backoff(openai_, textos: list[str], dormir) -> list[list[float]]:
    ultimo = None
    for tentativa in range(1, MAX_TENTATIVAS_LOTE + 1):
        try:
            return vetorizar(openai_, textos)
        except Exception as erro:  # noqa: BLE001
            ultimo = erro
            print(f"  [tentativa {tentativa}/{MAX_TENTATIVAS_LOTE}] "
                  f"{type(erro).__name__}")
            if tentativa < MAX_TENTATIVAS_LOTE:
                dormir(BACKOFF_BASE_SEGUNDOS ** tentativa)
    raise BackfillInterrompido(
        f"provedor indisponível após {MAX_TENTATIVAS_LOTE} tentativas "
        f"({type(ultimo).__name__})")


def executar(lote: int, maximo: int | None, simular: bool,
             sb=None, openai_=None, dormir=time.sleep) -> int:
    """
    Vetoriza os pendentes. `maximo` limita o total desta execução — e
    nunca é ultrapassado, mesmo com lote maior que ele.

    Levanta BackfillInterrompido se o provedor não responder após as
    tentativas previstas: sem laço infinito e sem trocar de provedor.
    """
    sb = sb or cliente_supabase()
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

    openai_ = openai_ or cliente_openai()
    processados = 0
    while maximo is None or processados < maximo:
        # o lote nunca pode ultrapassar o que ainda cabe no limite
        tamanho = lote if maximo is None else min(lote, maximo - processados)
        atual = pendentes(sb, tamanho)
        if not atual:
            break
        try:
            vetores = _vetorizar_com_backoff(
                openai_, [c["conteudo"] for c in atual], dormir)
        except BackfillInterrompido:
            for c in atual:
                marcar_falha(sb, c)   # visível no banco; segue retomável
            print(f"  [interrompido] lote de {len(atual)} marcado como "
                  "'falha'; reexecute quando o provedor voltar")
            raise
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
    parser.add_argument("--credenciais", action="store_true",
                        help="informa apenas se as credenciais existem")
    args = parser.parse_args()
    if args.credenciais:
        for nome, com_banco in (("SUPABASE_URL", False),
                                ("SUPABASE_KEY", False),
                                ("OPENAI_API_KEY", True)):
            rotulo = ("credencial do provedor V2" if nome == "OPENAI_API_KEY"
                      else nome)
            disponivel = "sim" if credencial_disponivel(nome, com_banco) else "não"
            print(f"{rotulo} disponível: {disponivel}")
        return
    if args.validar:
        validar()
        return
    try:
        executar(args.lote, args.limite, args.simular)
    except BackfillInterrompido as erro:
        raise SystemExit(f"[ERRO] {erro}") from erro


if __name__ == "__main__":
    main()
