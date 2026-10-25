"""
`/api/v1/admin/base-conhecimento` — Base de Conhecimento (M6).

O domínio é o de `src/rag.py`, o mesmo da tela do Streamlit
(`ui/biblioteca`): extrair o texto, dividir em trechos, vetorizar com o
modelo PINADO do índice (`text-embedding-3-small`) e gravar. Só o
administrador, como no menu do Streamlit; o RLS (0020 + 0034) é quem
decide de verdade.

Diferenças deliberadas:

* um arquivo por requisição. A tela envia o lote em sequência e mostra o
  resultado de cada um — o que o Streamlit faz no laço dele;
* sem a chave de embeddings no ambiente da API, o material entra para a
  busca TEXTUAL e a resposta diz `pendente_de_vetor`. Nunca se vetoriza
  com outro provedor: corromperia o índice em silêncio.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from src import rag
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .processos import _falha
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

LIMITE_POR_ARQUIVO = 10 * 1024 * 1024
EXTENSOES = ("pdf", "docx", "txt", "md")
Categoria = Literal[tuple(rag.CATEGORIAS)]  # type: ignore[valid-type]


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Opcao(BaseModel):
    codigo: str
    rotulo: str


class Referencia(BaseModel):
    id: str
    titulo: str
    categoria: str
    categoria_rotulo: str
    nome_arquivo: str
    total_chunks: int
    criado_em: str


class BaseDeConhecimento(BaseModel):
    categorias: list[Opcao]
    extensoes: list[str]
    referencias: list[Referencia]


class NovaReferencia(_Entrada):
    nome_arquivo: str = Field(min_length=1, max_length=200)
    titulo: str = Field(default="", max_length=300)
    categoria: Categoria
    # O arquivo em base64; o teto vale para o texto codificado (~4/3).
    conteudo: str = Field(min_length=1, max_length=LIMITE_POR_ARQUIVO * 4 // 3 + 8)


class ReferenciaIndexada(BaseModel):
    id: str
    nome_arquivo: str
    trechos: int
    pendente_de_vetor: bool


class ReferenciaExcluida(BaseModel):
    id: str


class Consulta(_Entrada):
    consulta: str = Field(min_length=3, max_length=500)


class Trecho(BaseModel):
    titulo: str
    categoria_rotulo: str
    similaridade: float
    conteudo: str


def rotas() -> APIRouter:
    r = APIRouter(prefix="/admin/base-conhecimento", tags=["administracao"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _admin(eu: Identidade) -> None:
        # O RLS recusaria a escrita de qualquer forma; isto devolve o
        # código certo e fecha também a leitura administrativa.
        if eu.papel != "admin":
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, {
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id, "nome": ""})

    def _referencia(linha: dict) -> Referencia:
        categoria = str(linha.get("categoria") or "")
        return Referencia(
            id=str(linha["id"]), titulo=str(linha.get("titulo") or ""), categoria=categoria,
            categoria_rotulo=rag.CATEGORIAS.get(categoria, categoria),
            nome_arquivo=str(linha.get("nome_arquivo") or ""),
            total_chunks=int(linha.get("total_chunks") or 0),
            criado_em=str(linha.get("criado_em") or ""))

    @r.get("", response_model=BaseDeConhecimento)
    def listar(request: Request, eu: Identidade = Depends(exigir_identidade)) -> BaseDeConhecimento:
        _admin(eu)
        resposta = _rest(request).requisitar(eu.token, "GET", "documentos_referencia", params={
            "select": "id,titulo,categoria,nome_arquivo,total_chunks,criado_em",
            "tenant_id": f"eq.{eu.tenant_id}", "order": "criado_em.desc"})
        if resposta.status != 200:
            raise _falha(resposta)
        return BaseDeConhecimento(
            categorias=[Opcao(codigo=c, rotulo=r) for c, r in rag.CATEGORIAS.items()],
            extensoes=list(EXTENSOES),
            referencias=[_referencia(l) for l in resposta.dados or []])

    @r.post("", status_code=201, response_model=ReferenciaIndexada,
            responses={413: {"description": "Arquivo acima de 10 MB"},
                       422: {"description": "Formato não aceito ou sem texto indexável"}})
    def indexar(corpo: NovaReferencia, eu: Identidade = Depends(exigir_identidade)) -> ReferenciaIndexada:
        _admin(eu)
        extensao = corpo.nome_arquivo.rsplit(".", 1)[-1].lower() if "." in corpo.nome_arquivo else ""
        if extensao not in EXTENSOES:
            raise ErroApi(422, "VALIDATION_ERROR", "Formato não aceito: envie PDF, DOCX, TXT ou MD")
        try:
            dados = base64.b64decode(corpo.conteudo, validate=True)
        except (binascii.Error, ValueError):
            raise ErroApi(422, "VALIDATION_ERROR", "Arquivo corrompido no envio") from None
        if len(dados) > LIMITE_POR_ARQUIVO:
            raise ErroApi(413, "PAYLOAD_TOO_LARGE", "O arquivo passa do limite de 10 MB")
        try:
            with _sessao(eu):
                feito = rag.indexar(corpo.nome_arquivo, corpo.titulo.strip(), corpo.categoria, dados)
        except rag.ErroRAG as erro:
            # A mensagem do domínio já é escrita para quem indexa, e a do
            # provedor nunca chega aqui (`_gerar_embeddings` a registra).
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None
        _log.info("referencia_indexada trechos=%s pendente=%s", feito.trechos, feito.pendente_de_vetor)
        return ReferenciaIndexada(id=feito.documento_id, nome_arquivo=corpo.nome_arquivo,
                                  trechos=feito.trechos, pendente_de_vetor=feito.pendente_de_vetor)

    @r.delete("/{referencia_id}", response_model=ReferenciaExcluida,
              responses={404: {"description": "Referência fora do seu acesso"}})
    def excluir(referencia_id: uuid.UUID, request: Request,
                eu: Identidade = Depends(exigir_identidade)) -> ReferenciaExcluida:
        _admin(eu)
        # `return=representation`: o RLS que recusa um DELETE não dá erro,
        # devolve zero linhas — e zero linhas aqui é 404, não sucesso.
        resposta = _rest(request).requisitar(eu.token, "DELETE", "documentos_referencia", params={
            "select": "id", "id": f"eq.{referencia_id}", "tenant_id": f"eq.{eu.tenant_id}"},
            prefer="return=representation")
        if resposta.status != 200:
            raise _falha(resposta)
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        _log.info("referencia_excluida id=%s", referencia_id)
        # Os trechos caem pelo `on delete cascade` da 0003.
        return ReferenciaExcluida(id=str(referencia_id))

    @r.post("/busca", response_model=list[Trecho])
    def buscar(corpo: Consulta, eu: Identidade = Depends(exigir_identidade)) -> list[Trecho]:
        """O que a IA veria: os trechos que a recuperação devolve para a consulta."""
        _admin(eu)
        try:
            with _sessao(eu):
                trechos = rag.buscar_referencias(corpo.consulta.strip())
        except rag.ErroRAG as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None
        return [Trecho(titulo=str(t.get("titulo") or ""),
                       categoria_rotulo=rag.CATEGORIAS.get(str(t.get("categoria") or ""), ""),
                       similaridade=float(t.get("similaridade") or 0),
                       conteudo=str(t.get("conteudo") or "")[:400])
                for t in trechos]

    return r
