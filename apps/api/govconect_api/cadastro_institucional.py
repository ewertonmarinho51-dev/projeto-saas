"""
`/api/v1/admin/instituicao` — Prefeitura, Secretarias e Identidade visual (M7b).

O resto do cadastro institucional da Administração do Streamlit: a seção
"Prefeitura" da aba Instituição (`ui/instituicional._render_prefeitura`)
e as abas "Secretarias" e "Identidade visual" (`ui/admin`). O domínio é o
mesmo (`db.salvar_dados_do_tenant`, `db.salvar_secretaria`,
`db.salvar_orgao` — que espelha a identidade em `secretarias` —, `branding`
para capturar o timbrado de um PDF-modelo), dentro da sessão do ADMIN: o
PostgREST recebe o JWT dele, e quem garante é o RLS da 0035.

Diferenças deliberadas:

* a captura por imagem aceita só PDF: DOCX precisa do LibreOffice, que só
  existe na imagem do worker. O arquivo vem a cada prévia (base64, como o
  M4) e nada fica guardado até "Salvar";
* o vínculo usuário → secretaria e a flag de resolução automática ficam no
  Streamlit (ver o "O QUE NÃO RESOLVE" da 0035).
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field

from src import branding, contexto, db
from src.instituicional_catalogo import (CAMPOS_DA_PREFEITURA, FLAG_ADMIN,
                                         FLAG_MULTI_PREFEITURAS, secao_liberada)
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .processos import _falha
from .seguranca import Identidade, exigir_identidade
from .supabase_rest import ClienteRest

_log = logging.getLogger("govconect_api")

LIMITE_DO_MODELO = 10 * 1024 * 1024
CAMPOS = tuple(chave for chave, _, _ in CAMPOS_DA_PREFEITURA)


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class CampoDaPrefeitura(BaseModel):
    chave: str
    rotulo: str
    exemplo: str
    valor: str


class Prefeitura(BaseModel):
    nome: str
    campos: list[CampoDaPrefeitura]


class DadosDaPrefeitura(_Entrada):
    nome_oficial: str | None = Field(default=None, max_length=300)
    cnpj: str | None = Field(default=None, max_length=30)
    sigla: str | None = Field(default=None, max_length=30)
    cidade: str | None = Field(default=None, max_length=120)
    endereco: str | None = Field(default=None, max_length=300)
    telefone: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=200)
    site: str | None = Field(default=None, max_length=300)


class SecretariaCadastrada(BaseModel):
    id: str
    nome: str
    sigla: str
    ativo: bool
    padrao: bool
    identidade_propria: bool


class NovaSecretaria(_Entrada):
    nome: str = Field(min_length=1, max_length=200)
    sigla: str = Field(default="", max_length=30)


class EdicaoDeSecretaria(_Entrada):
    ativo: bool | None = None
    # Só `true`: desmarcar a padrão é marcar outra.
    padrao: bool | None = None


class IdentidadeVisual(BaseModel):
    id: str
    orgao: str
    padrao: bool
    por_imagem: bool
    cabecalho: str
    rodape: str
    marca_dagua: str
    cabecalho_img: str | None


class ModeloEnviado(_Entrada):
    nome_arquivo: str = Field(min_length=1, max_length=200)
    conteudo: str = Field(min_length=1, max_length=LIMITE_DO_MODELO * 4 // 3 + 8)
    cabecalho_pct: float = Field(default=14, ge=3, le=40)
    rodape_pct: float = Field(default=10, ge=3, le=40)
    marca: bool = False


class PreviaDoModelo(BaseModel):
    pagina: str
    cabecalho: str
    rodape: str
    marca: str | None


class IdentidadePorImagem(ModeloEnviado):
    orgao: str = Field(min_length=1, max_length=200)
    padrao: bool = False


class IdentidadePorTexto(_Entrada):
    orgao: str = Field(min_length=1, max_length=200)
    cabecalho: str = Field(default="", max_length=500)
    rodape: str = Field(default="", max_length=500)
    marca_dagua: str = Field(default="", max_length=120)
    padrao: bool = False


class Excluida(BaseModel):
    id: str


def _data_url(png: bytes | None) -> str | None:
    if not png:
        return None
    return "data:image/png;base64," + base64.b64encode(png).decode()


def _imagem_guardada(bruto: str | None) -> str | None:
    dados = branding.de_base64(bruto)
    if not dados:
        return None
    tipo = "image/png" if dados.startswith(b"\x89PNG") else "image/jpeg"
    return f"data:{tipo};base64,{base64.b64encode(dados).decode()}"


def _recortes(modelo: ModeloEnviado):
    """Renderiza a 1ª página do PDF e recorta as três faixas."""
    if not modelo.nome_arquivo.lower().endswith(".pdf"):
        raise ErroApi(422, "VALIDATION_ERROR",
                      "Envie o documento-modelo em PDF (DOCX só pelo GovDocs, que tem o conversor)")
    try:
        dados = base64.b64decode(modelo.conteudo, validate=True)
    except (binascii.Error, ValueError):
        raise ErroApi(422, "VALIDATION_ERROR", "Arquivo corrompido no envio") from None
    if len(dados) > LIMITE_DO_MODELO:
        raise ErroApi(413, "PAYLOAD_TOO_LARGE", "O documento-modelo passa do limite de 10 MB")
    if not dados.startswith(b"%PDF"):
        raise ErroApi(422, "VALIDATION_ERROR", "O arquivo não é um PDF")
    try:
        img = branding.renderizar_modelo(modelo.nome_arquivo, dados)
    except branding.ErroBranding as erro:
        raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None
    cabecalho = branding.recortar_cabecalho(img, modelo.cabecalho_pct)
    rodape = branding.recortar_rodape(img, modelo.rodape_pct)
    marca = branding.recortar_marca_dagua(img) if modelo.marca else b""
    return img, cabecalho, rodape, marca


def rotas() -> APIRouter:
    r = APIRouter(prefix="/admin/instituicao", tags=["administracao"])

    def _rest(request: Request) -> ClienteRest:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        return rest

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, {
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id, "nome": ""})

    def _executar(eu: Identidade, funcao, *, exige_secao: str | None = None):
        # O RLS recusaria a escrita de qualquer forma; isto devolve o
        # código certo e fecha também a leitura administrativa.
        if eu.papel != "admin":
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")
        try:
            with _sessao(eu):
                if not db.flag_ativa(FLAG_MULTI_PREFEITURAS):
                    raise ErroApi(404, "MODULE_UNAVAILABLE", "Cadastro institucional desligado")
                if exige_secao and not secao_liberada(db.obter_config(f"flag_{exige_secao}")):
                    raise ErroApi(404, "MODULE_UNAVAILABLE", "Seção desligada")
                return funcao()
        except db.ErroBanco as erro:
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None

    # -- prefeitura --------------------------------------------------------
    def _prefeitura() -> Prefeitura:
        registro = db.tenant_atual_registro()
        return Prefeitura(
            nome=str(registro.get("nome") or "Prefeitura"),
            campos=[CampoDaPrefeitura(chave=c, rotulo=rotulo, exemplo=exemplo, valor=str(registro.get(c) or ""))
                    for c, rotulo, exemplo in CAMPOS_DA_PREFEITURA])

    @r.get("/prefeitura", response_model=Prefeitura)
    def prefeitura(eu: Identidade = Depends(exigir_identidade)) -> Prefeitura:
        return _executar(eu, _prefeitura, exige_secao=FLAG_ADMIN)

    @r.put("/prefeitura", response_model=Prefeitura)
    def salvar_prefeitura(corpo: DadosDaPrefeitura, eu: Identidade = Depends(exigir_identidade)) -> Prefeitura:
        def salvar():
            # Vazio vira NULL, como no Streamlit: o sistema não inventa dado.
            db.salvar_dados_do_tenant({c: (getattr(corpo, c) or None) for c in CAMPOS})
            return _prefeitura()
        return _executar(eu, salvar, exige_secao=FLAG_ADMIN)

    # -- secretarias -------------------------------------------------------
    def _secretaria(s: dict) -> SecretariaCadastrada:
        return SecretariaCadastrada(
            id=str(s["id"]), nome=str(s.get("nome") or ""), sigla=str(s.get("sigla") or ""),
            ativo=bool(s.get("ativo", True)), padrao=bool(s.get("padrao")),
            identidade_propria=contexto.tem_identidade_propria(s))

    def _todas() -> list[SecretariaCadastrada]:
        return [_secretaria(s) for s in db.listar_secretarias(incluir_inativas=True)]

    @r.get("/secretarias", response_model=list[SecretariaCadastrada])
    def secretarias(eu: Identidade = Depends(exigir_identidade)) -> list[SecretariaCadastrada]:
        return _executar(eu, _todas)

    @r.post("/secretarias", status_code=201, response_model=list[SecretariaCadastrada])
    def criar_secretaria(corpo: NovaSecretaria, eu: Identidade = Depends(exigir_identidade)) -> list[SecretariaCadastrada]:
        def criar():
            if any(s.nome.casefold() == corpo.nome.casefold() for s in _todas()):
                raise ErroApi(409, "CONFLICT", f"Já existe a secretaria '{corpo.nome}'")
            # O tenant vem da sessão (`salvar_secretaria` o põe), nunca do corpo.
            db.salvar_secretaria({"nome": corpo.nome, "sigla": corpo.sigla})
            _log.info("secretaria_criada")
            return _todas()
        return _executar(eu, criar)

    @r.patch("/secretarias/{secretaria_id}", response_model=list[SecretariaCadastrada],
             responses={404: {"description": "Secretaria fora do seu acesso"}})
    def editar_secretaria(secretaria_id: uuid.UUID, corpo: EdicaoDeSecretaria,
                          eu: Identidade = Depends(exigir_identidade)) -> list[SecretariaCadastrada]:
        def editar():
            atual = next((s for s in _todas() if s.id == str(secretaria_id)), None)
            if atual is None:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            registro: dict = {}
            if corpo.ativo is not None:
                registro["ativo"] = corpo.ativo
            if corpo.padrao:
                # A mesma regra da tela: só vira padrão quem tem timbrado.
                if not atual.identidade_propria:
                    raise ErroApi(422, "VALIDATION_ERROR",
                                  "Só uma secretaria com identidade visual própria pode ser a padrão")
                registro["padrao"] = True
            if not registro:
                raise ErroApi(422, "VALIDATION_ERROR", "Nada a alterar")
            db.salvar_secretaria(registro, str(secretaria_id))
            return _todas()
        return _executar(eu, editar)

    # -- identidade visual -------------------------------------------------
    def _identidades() -> list[IdentidadeVisual]:
        return [IdentidadeVisual(
            id=str(o["id"]), orgao=str(o.get("orgao") or ""), padrao=bool(o.get("padrao")),
            por_imagem=bool(o.get("cabecalho_img") or o.get("rodape_img")),
            cabecalho=str(o.get("cabecalho") or ""), rodape=str(o.get("rodape") or ""),
            marca_dagua=str(o.get("marca_dagua") or ""),
            cabecalho_img=_imagem_guardada(o.get("cabecalho_img")))
            for o in db.listar_orgaos()]

    @r.get("/identidades", response_model=list[IdentidadeVisual])
    def identidades(eu: Identidade = Depends(exigir_identidade)) -> list[IdentidadeVisual]:
        return _executar(eu, _identidades)

    @r.post("/identidades/previa", response_model=PreviaDoModelo,
            responses={413: {"description": "Modelo acima de 10 MB"}})
    def previa(corpo: ModeloEnviado, eu: Identidade = Depends(exigir_identidade)) -> PreviaDoModelo:
        def montar():
            img, cabecalho, rodape, marca = _recortes(corpo)
            pagina = branding._png_bytes(img)  # noqa: SLF001 — o mesmo PNG que o Streamlit mostra
            return PreviaDoModelo(pagina=_data_url(pagina) or "", cabecalho=_data_url(cabecalho) or "",
                                  rodape=_data_url(rodape) or "", marca=_data_url(marca))
        return _executar(eu, montar)

    @r.post("/identidades/imagem", status_code=201, response_model=list[IdentidadeVisual])
    def salvar_por_imagem(corpo: IdentidadePorImagem, eu: Identidade = Depends(exigir_identidade)) -> list[IdentidadeVisual]:
        def salvar():
            _, cabecalho, rodape, marca = _recortes(corpo)
            db.salvar_orgao({
                "orgao": corpo.orgao,
                "cabecalho_img": branding.para_base64(cabecalho),
                "rodape_img": branding.para_base64(rodape),
                "marca_img": branding.para_base64(marca) if marca else "",
                "cabecalho_pct": float(corpo.cabecalho_pct),
                "rodape_pct": float(corpo.rodape_pct),
                "padrao": corpo.padrao,
            })
            _log.info("identidade_salva por_imagem=1 padrao=%s", corpo.padrao)
            return _identidades()
        return _executar(eu, salvar)

    @r.post("/identidades/texto", status_code=201, response_model=list[IdentidadeVisual])
    def salvar_por_texto(corpo: IdentidadePorTexto, eu: Identidade = Depends(exigir_identidade)) -> list[IdentidadeVisual]:
        def salvar():
            db.salvar_orgao({"orgao": corpo.orgao, "cabecalho": corpo.cabecalho, "rodape": corpo.rodape,
                             "marca_dagua": corpo.marca_dagua, "padrao": corpo.padrao})
            _log.info("identidade_salva por_imagem=0 padrao=%s", corpo.padrao)
            return _identidades()
        return _executar(eu, salvar)

    @r.put("/identidades/{orgao_id}/padrao", response_model=list[IdentidadeVisual],
           responses={404: {"description": "Identidade fora do seu acesso"}})
    def tornar_padrao(orgao_id: uuid.UUID, eu: Identidade = Depends(exigir_identidade)) -> list[IdentidadeVisual]:
        def marcar():
            if not any(o.id == str(orgao_id) for o in _identidades()):
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            db.salvar_orgao({"padrao": True}, str(orgao_id))
            return _identidades()
        return _executar(eu, marcar)

    @r.delete("/identidades/{orgao_id}", response_model=Excluida,
              responses={404: {"description": "Identidade fora do seu acesso"}})
    def excluir(orgao_id: uuid.UUID, request: Request, eu: Identidade = Depends(exigir_identidade)) -> Excluida:
        def apagar():
            # `return=representation`: o RLS que recusa um DELETE devolve
            # zero linhas, e zero linhas aqui é 404, não sucesso.
            resposta = _rest(request).requisitar(eu.token, "DELETE", "config_orgaos", params={
                "select": "id", "id": f"eq.{orgao_id}", "tenant_id": f"eq.{eu.tenant_id}"},
                prefer="return=representation")
            if resposta.status != 200:
                raise _falha(resposta)
            if not resposta.dados:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            _log.info("identidade_excluida")
            return Excluida(id=str(orgao_id))
        return _executar(eu, apagar)

    return r
