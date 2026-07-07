"""
Base de Conhecimento (RAG) — aprendizado a partir de documentos de referência.

O usuário envia arquivos (PDF, DOCX, TXT/MD) de leis, acórdãos,
entendimentos dos Tribunais de Contas, processos anteriores e modelos.
Cada arquivo é dividido em trechos (chunks), que recebem embeddings do
Gemini e são armazenados no Supabase (pgvector). Na geração de cada
documento, os trechos mais relevantes são recuperados e injetados no
prompt como fundamentação.

Estratégia de busca:
  1. Vetorial (pgvector + embeddings Gemini) — quando há chave de API;
  2. Textual em português (tsvector/websearch) — fallback automático.
"""

import io
import re

import streamlit as st

from . import db
from .config import (
    EMBEDDING_DIMENSOES,
    EMBEDDING_MODEL,
    RAG_CHUNK_SOBREPOSICAO,
    RAG_CHUNK_TAMANHO,
    RAG_TOP_K,
)

CATEGORIAS = {
    "lei": "⚖️ Lei / Norma",
    "acordao": "🏛️ Acórdão (TCU/TCE)",
    "entendimento": "📜 Entendimento / Orientação de TC",
    "processo_anterior": "🗂️ Processo anterior realizado",
    "modelo": "📐 Modelo / Minuta padrão (AGU etc.)",
    "outro": "📄 Outro",
}


class ErroRAG(Exception):
    """Erro da base de conhecimento com mensagem amigável."""


# ---------------------------------------------------------------------------
# Extração de texto dos arquivos enviados
# ---------------------------------------------------------------------------
def extrair_texto(nome_arquivo: str, dados: bytes) -> str:
    """Extrai texto de PDF, DOCX, TXT ou MD. Levanta ErroRAG se não suportado."""
    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    try:
        if extensao == "pdf":
            from pypdf import PdfReader

            leitor = PdfReader(io.BytesIO(dados))
            paginas = [pagina.extract_text() or "" for pagina in leitor.pages]
            texto = "\n".join(paginas)
        elif extensao == "docx":
            from docx import Document

            documento = Document(io.BytesIO(dados))
            partes = [p.text for p in documento.paragraphs]
            for tabela in documento.tables:
                for linha in tabela.rows:
                    partes.append(" | ".join(c.text for c in linha.cells))
            texto = "\n".join(partes)
        elif extensao in ("txt", "md"):
            texto = dados.decode("utf-8", errors="replace")
        else:
            raise ErroRAG(
                f"Formato .{extensao or '?'} não suportado — envie PDF, DOCX, TXT ou MD."
            )
    except ErroRAG:
        raise
    except Exception as exc:  # noqa: BLE001 — arquivo corrompido/ilegível
        raise ErroRAG(f"Não foi possível ler '{nome_arquivo}': {exc}") from exc

    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"\n{3,}", "\n\n", texto).strip()
    if len(texto) < 50:
        raise ErroRAG(
            f"'{nome_arquivo}' não contém texto extraível (PDF digitalizado sem OCR?)."
        )
    return texto


def dividir_em_chunks(
    texto: str,
    tamanho: int = RAG_CHUNK_TAMANHO,
    sobreposicao: int = RAG_CHUNK_SOBREPOSICAO,
) -> list[str]:
    """
    Divide o texto em trechos de ~`tamanho` caracteres com sobreposição,
    preferindo quebrar em fim de parágrafo ou sentença para não cortar
    dispositivos legais no meio.
    """
    chunks: list[str] = []
    inicio = 0
    while inicio < len(texto):
        fim = min(inicio + tamanho, len(texto))
        if fim < len(texto):
            janela = texto[inicio:fim]
            # tenta quebrar no último parágrafo; senão na última sentença
            corte = max(janela.rfind("\n\n"), janela.rfind(". "))
            if corte > tamanho // 2:
                fim = inicio + corte + 1
        trecho = texto[inicio:fim].strip()
        if trecho:
            chunks.append(trecho)
        if fim >= len(texto):
            break
        inicio = max(fim - sobreposicao, inicio + 1)
    return chunks


# ---------------------------------------------------------------------------
# Embeddings (Gemini) — opcionais; sem eles a busca textual assume
# ---------------------------------------------------------------------------
def _gerar_embeddings(textos: list[str], para_consulta: bool) -> list[list[float]] | None:
    """
    Retorna embeddings (768 dims) ou None se não houver chave de API.

    Provedor segue o motor principal: OpenAI (text-embedding-3-small com
    dimensions=768) quando há chave; senão Gemini. IMPORTANTE: indexação e
    consulta precisam do MESMO provedor — se você trocar de provedor com a
    base já populada, reindexe os arquivos (os espaços vetoriais são
    incompatíveis entre si).
    """
    from .config import OPENAI_EMBEDDING_MODEL
    from .llm import obter_api_key, obter_openai_key

    chave_openai = obter_openai_key()
    chave_gemini = obter_api_key()
    try:
        if chave_openai:
            from openai import OpenAI

            cliente = OpenAI(api_key=chave_openai, timeout=60, max_retries=1)
            resposta = cliente.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=textos,
                dimensions=EMBEDDING_DIMENSOES,
            )
            return [item.embedding for item in resposta.data]
        if chave_gemini:
            from google import genai
            from google.genai import types

            cliente = genai.Client(api_key=chave_gemini)
            resposta = cliente.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=textos,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY" if para_consulta else "RETRIEVAL_DOCUMENT",
                    output_dimensionality=EMBEDDING_DIMENSOES,
                ),
            )
            return [list(e.values) for e in resposta.embeddings]
        return None
    except Exception as exc:  # noqa: BLE001
        # Falha de embedding não deve impedir a indexação: busca textual assume
        st.warning(f"Embeddings indisponíveis ({exc}); usando busca textual.", icon="🧭")
        return None


# ---------------------------------------------------------------------------
# Indexação e gestão da biblioteca
# ---------------------------------------------------------------------------
def indexar_arquivo(nome_arquivo: str, titulo: str, categoria: str, dados: bytes) -> int:
    """Extrai, divide, gera embeddings e grava o documento. Retorna nº de chunks."""
    if not db.disponivel():
        raise ErroRAG(
            "A Base de Conhecimento exige o Supabase configurado "
            "(SUPABASE_URL e SUPABASE_KEY em .streamlit/secrets.toml)."
        )
    texto = extrair_texto(nome_arquivo, dados)
    chunks = dividir_em_chunks(texto)
    if not chunks:
        raise ErroRAG(f"'{nome_arquivo}' não gerou trechos indexáveis.")

    embeddings = _gerar_embeddings(chunks, para_consulta=False)

    try:
        cliente = db._cliente()  # noqa: SLF001 — reuso interno do cliente único
        doc = (
            cliente.table("documentos_referencia")
            .insert(
                {
                    "titulo": titulo or nome_arquivo,
                    "categoria": categoria,
                    "nome_arquivo": nome_arquivo,
                    "total_chunks": len(chunks),
                }
            )
            .execute()
        ).data[0]

        registros = [
            {
                "documento_id": doc["id"],
                "ordem": i,
                "conteudo": trecho,
                "embedding": embeddings[i] if embeddings else None,
            }
            for i, trecho in enumerate(chunks)
        ]
        # insere em lotes para não estourar o payload
        for i in range(0, len(registros), 50):
            cliente.table("chunks_referencia").insert(registros[i : i + 50]).execute()
        return len(chunks)
    except Exception as exc:  # noqa: BLE001
        raise ErroRAG(f"Falha ao gravar na base de conhecimento: {exc}") from exc


def listar_referencias() -> list[dict]:
    try:
        return (
            db._cliente()  # noqa: SLF001
            .table("documentos_referencia")
            .select("id, titulo, categoria, nome_arquivo, total_chunks, criado_em")
            .order("criado_em", desc=True)
            .execute()
        ).data or []
    except Exception as exc:  # noqa: BLE001
        raise ErroRAG(f"Falha ao listar a base de conhecimento: {exc}") from exc


def excluir_referencia(documento_id: str) -> None:
    try:
        # chunks caem em cascata (on delete cascade)
        db._cliente().table("documentos_referencia").delete().eq(  # noqa: SLF001
            "id", documento_id
        ).execute()
    except Exception as exc:  # noqa: BLE001
        raise ErroRAG(f"Falha ao excluir referência: {exc}") from exc


# ---------------------------------------------------------------------------
# Recuperação (busca) e montagem do bloco de contexto para o prompt
# ---------------------------------------------------------------------------
def buscar_referencias(consulta: str, qtd: int = RAG_TOP_K) -> list[dict]:
    """Top-k trechos relevantes: vetorial se possível, senão textual."""
    if not db.disponivel():
        return []
    cliente = db._cliente()  # noqa: SLF001

    embedding = _gerar_embeddings([consulta], para_consulta=True)
    try:
        if embedding:
            resposta = cliente.rpc(
                "buscar_chunks_vetorial",
                {"query_embedding": embedding[0], "qtd": qtd},
            ).execute()
        else:
            resposta = cliente.rpc(
                "buscar_chunks_textual",
                {"consulta": consulta, "qtd": qtd},
            ).execute()
        return resposta.data or []
    except Exception as exc:  # noqa: BLE001
        raise ErroRAG(f"Falha na busca da base de conhecimento: {exc}") from exc


def montar_consulta(dados: dict, doc_key: str) -> str:
    """Texto de busca combinando objeto, justificativa e o tipo de documento."""
    nomes = {
        "dfd": "documento de formalização da demanda",
        "etp": "estudo técnico preliminar",
        "tr": "termo de referência",
        "edital": "edital de licitação registro de preços",
    }
    partes = [
        nomes[doc_key],
        dados.get("objeto") or "",
        dados.get("justificativa") or "",
        dados.get("modelo_execucao") or "",
    ]
    return " ".join(p for p in partes if p)[:1500]


def montar_bloco_referencias(dados: dict, doc_key: str) -> str:
    """
    Bloco de texto com as referências recuperadas, pronto para anexar ao
    prompt. Retorna string vazia se não houver base configurada/conteúdo.
    Nunca levanta exceção — RAG é enriquecimento, não pré-requisito.
    """
    try:
        trechos = buscar_referencias(montar_consulta(dados, doc_key))
    except ErroRAG as erro:
        st.warning(str(erro), icon="📚")
        return ""
    if not trechos:
        return ""

    linhas = [
        "\n=== REFERÊNCIAS DA BASE DE CONHECIMENTO (trechos recuperados) ===",
        "Utilize as referências abaixo para fundamentar o documento: normas e "
        "acórdãos podem ser citados expressamente (com número/órgão quando "
        "constar do trecho); processos anteriores e modelos servem de padrão "
        "de redação e estrutura. NÃO copie dados específicos de outros "
        "processos (valores, órgãos, datas, quantidades) para o documento "
        "atual; em caso de conflito, os dados do formulário prevalecem.",
    ]
    for i, t in enumerate(trechos, start=1):
        rotulo = CATEGORIAS.get(t.get("categoria", ""), t.get("categoria", ""))
        rotulo = re.sub(r"^\W+\s*", "", rotulo)  # remove o emoji do rótulo
        linhas.append(f"\n--- Referência {i} [{rotulo}] {t.get('titulo', '')} ---")
        linhas.append((t.get("conteudo") or "").strip())
    return "\n".join(linhas)
