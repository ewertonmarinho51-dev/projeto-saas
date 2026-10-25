"""
`/api/v1/admin/instituicao` — cadastro institucional (M7a).

A aba "Instituição" da Administração do Streamlit (`ui/instituicional`):
servidores, portarias e seus membros, módulos por prefeitura e por
secretaria, e a prévia do timbrado que a exportação vai usar. O domínio é
o mesmo (`db.*`, `portarias`, `modulos`, `contexto.resolver_identidade`),
dentro da sessão do usuário: toda leitura e escrita vai ao PostgREST com o
JWT do ADMIN, e quem garante é o RLS da 0025 (`e_admin()` e
`tenant_do_jwt()` nas políticas de escrita).

Fora daqui, de propósito, até a migração que dá ao admin a escrita em
`tenants` e `secretarias` (M7b): dados da Prefeitura, cadastro de
secretarias e identidade visual. O Streamlit grava essas duas tabelas com
a credencial de servidor; a API não tem — e não deve ter — essa saída.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import assinaturas, branding, contexto, db, modulos, portarias
from src.instituicional_catalogo import (FLAG_MULTI_PREFEITURAS, FLAG_PORTARIAS,
                                         FLAG_SERVIDORES, MODULOS_OFERECIDOS,
                                         SITUACOES_DECLARADAS, TIPOS_DE_PORTARIA,
                                         secao_liberada)
from src.streamlit_opcional import sessao_da_requisicao

from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade

_log = logging.getLogger("govconect_api")

TIPOS = {codigo for codigo, _ in TIPOS_DE_PORTARIA}
ESTADOS_DE_MODULO = (modulos.HERDAR, modulos.HABILITADO, modulos.DESABILITADO)


# ---------------------------------------------------------------------------
# Contratos
# ---------------------------------------------------------------------------
class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Opcao(BaseModel):
    codigo: str
    rotulo: str


class Secretaria(BaseModel):
    id: str
    nome: str


class Instituicao(BaseModel):
    secoes: list[str]
    secretarias: list[Secretaria]
    tipos_de_portaria: list[Opcao]
    funcoes_de_membro: list[Opcao]
    situacoes_declaradas: list[str]


class Servidor(BaseModel):
    id: str
    nome: str
    cargo: str | None
    matricula: str | None
    email: str | None
    ativo: bool


class NovoServidor(_Entrada):
    nome: str = Field(min_length=1, max_length=200)
    cargo: str | None = Field(default=None, max_length=200)
    matricula: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=200)


class EdicaoDeServidor(_Entrada):
    nome: str | None = Field(default=None, min_length=1, max_length=200)
    cargo: str | None = Field(default=None, max_length=200)
    matricula: str | None = Field(default=None, max_length=60)
    email: str | None = Field(default=None, max_length=200)
    ativo: bool | None = None


class Membro(BaseModel):
    nome: str
    funcao: str
    funcao_rotulo: str
    servidor_ativo: bool


class Portaria(BaseModel):
    id: str
    tipo: str
    tipo_rotulo: str
    numero: str
    ano: int
    situacao: str
    situacao_declarada: str
    citacao: str
    data_publicacao: str | None
    data_inicio_vigencia: str | None
    data_fim_vigencia: str | None
    membros: list[Membro]


class Portarias(BaseModel):
    portarias: list[Portaria]
    # Defeitos de cadastro que a tela precisa mostrar (duas vigentes do
    # mesmo tipo, data ilegível) — onde eles se consertam.
    avisos: list[str]


class NovaPortaria(_Entrada):
    secretaria_id: uuid.UUID
    tipo: str
    numero: str = Field(min_length=1, max_length=20)
    ano: int = Field(ge=2000, le=2100)
    data_publicacao: dt.date | None = None
    data_inicio_vigencia: dt.date
    data_fim_vigencia: dt.date | None = None

    @field_validator("tipo")
    @classmethod
    def _tipo(cls, valor: str) -> str:
        if valor not in TIPOS:
            raise ValueError("tipo de portaria inexistente")
        return valor


class SituacaoDaPortaria(_Entrada):
    status: Literal["RASCUNHO", "ATIVA", "REVOGADA"]


class NovoMembro(_Entrada):
    servidor_id: uuid.UUID
    funcao: str

    @field_validator("funcao")
    @classmethod
    def _funcao(cls, valor: str) -> str:
        if valor not in assinaturas.FUNCOES_DE_PORTARIA:
            raise ValueError("função inexistente para membro de portaria")
        return valor


class Modulo(BaseModel):
    modulo: str
    rotulo: str
    # A flag global é a palavra final: desligada, o módulo não existe.
    disponivel_no_sistema: bool
    na_prefeitura: bool
    na_secretaria: str | None
    explicacao: str


class Modulos(BaseModel):
    modulos: list[Modulo]


class ModuloNaPrefeitura(_Entrada):
    habilitado: bool


class ModuloNaSecretaria(_Entrada):
    estado: Literal["HERDAR", "HABILITADO", "DESABILITADO"]


class Timbrado(BaseModel):
    # secretaria | municipio | nenhuma
    origem: str
    cabecalho_img: str | None
    rodape_img: str | None
    marca_img: str | None
    cabecalho_texto: str
    rodape_texto: str
    marca_texto: str


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def _como_data_url(bruto: str | None) -> str | None:
    """Imagem do timbrado (base64 no banco) como data URL de PNG/JPEG."""
    dados = branding.de_base64(bruto)
    if not dados:
        return None
    tipo = "image/png" if dados.startswith(b"\x89PNG") else "image/jpeg"
    import base64

    return f"data:{tipo};base64,{base64.b64encode(dados).decode()}"


def rotas() -> APIRouter:
    r = APIRouter(prefix="/admin/instituicao", tags=["administracao"])

    def _sessao(eu: Identidade):
        return sessao_da_requisicao(eu.token, eu.tenant_id, {
            "id": eu.usuario_id, "auth_user_id": eu.auth_user_id,
            "secretaria_id": eu.secretaria_id, "nome": ""})

    def _admin(eu: Identidade) -> None:
        # O RLS recusaria a escrita de qualquer forma; isto devolve o
        # código certo e fecha também a LEITURA administrativa.
        if eu.papel != "admin":
            raise ErroApi(403, "FORBIDDEN", "Acesso negado")

    def _executar(eu: Identidade, funcao, *, exige_secao: str | None = None):
        _admin(eu)
        try:
            with _sessao(eu):
                if not db.flag_ativa(FLAG_MULTI_PREFEITURAS):
                    raise ErroApi(404, "MODULE_UNAVAILABLE", "Cadastro institucional desligado")
                if exige_secao and not secao_liberada(db.obter_config(f"flag_{exige_secao}")):
                    raise ErroApi(404, "MODULE_UNAVAILABLE", "Seção desligada")
                return funcao()
        except db.ErroBanco as erro:
            # A mensagem do domínio já é escrita para o administrador
            # (recusa de habilitar o que a prefeitura proíbe, por exemplo).
            raise ErroApi(422, "VALIDATION_ERROR", str(erro)[:300]) from None

    @r.get("", response_model=Instituicao)
    def visao(eu: Identidade = Depends(exigir_identidade)) -> Instituicao:
        def ler():
            secoes = ["Timbrado", "Módulos"]
            if secao_liberada(db.obter_config(f"flag_{FLAG_SERVIDORES}")):
                secoes.append("Servidores")
            if secao_liberada(db.obter_config(f"flag_{FLAG_PORTARIAS}")):
                secoes.append("Portarias")
            return Instituicao(
                secoes=secoes,
                secretarias=[Secretaria(id=str(s["id"]), nome=str(s.get("nome") or s.get("sigla") or "—"))
                             for s in db.listar_secretarias()],
                tipos_de_portaria=[Opcao(codigo=c, rotulo=r) for c, r in TIPOS_DE_PORTARIA],
                funcoes_de_membro=[Opcao(codigo=f, rotulo=assinaturas.ROTULOS.get(f, f))
                                   for f in assinaturas.FUNCOES_DE_PORTARIA],
                situacoes_declaradas=list(SITUACOES_DECLARADAS))
        return _executar(eu, ler)

    # -- servidores --------------------------------------------------------
    def _servidor(s: dict) -> Servidor:
        return Servidor(id=str(s["id"]), nome=str(s.get("nome") or ""), cargo=s.get("cargo"),
                        matricula=s.get("matricula"), email=s.get("email"), ativo=bool(s.get("ativo", True)))

    @r.get("/servidores", response_model=list[Servidor])
    def servidores(eu: Identidade = Depends(exigir_identidade)) -> list[Servidor]:
        return _executar(eu, lambda: [_servidor(s) for s in db.listar_servidores(incluir_inativos=True)],
                         exige_secao=FLAG_SERVIDORES)

    @r.post("/servidores", status_code=201, response_model=Servidor)
    def criar_servidor(corpo: NovoServidor, eu: Identidade = Depends(exigir_identidade)) -> Servidor:
        def criar():
            registro = {k: (v or None) for k, v in corpo.model_dump().items()}
            sid = db.salvar_servidor(registro)
            _log.info("servidor_cadastrado tenant=%s", eu.tenant_id)
            return Servidor(id=str(sid), ativo=True, **registro)
        return _executar(eu, criar, exige_secao=FLAG_SERVIDORES)

    @r.patch("/servidores/{servidor_id}", response_model=Servidor,
             responses={404: {"description": "Inexistente ou de outro município"}})
    def editar_servidor(servidor_id: uuid.UUID, corpo: EdicaoDeServidor,
                        eu: Identidade = Depends(exigir_identidade)) -> Servidor:
        mudancas = corpo.model_dump(exclude_unset=True)
        if not mudancas:
            raise ErroApi(400, "BAD_REQUEST", "Nada para alterar")

        def editar():
            atual = next((s for s in db.listar_servidores(incluir_inativos=True)
                          if str(s["id"]) == str(servidor_id)), None)
            if atual is None:
                raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
            registro = {k: (v if not isinstance(v, str) else (v or None)) for k, v in mudancas.items()}
            db.salvar_servidor(registro, str(servidor_id))
            return _servidor({**atual, **registro})
        return _executar(eu, editar, exige_secao=FLAG_SERVIDORES)

    # -- portarias ---------------------------------------------------------
    def _portaria(p: dict, hoje: dt.date) -> Portaria:
        try:
            situacao = portarias.situacao(p, hoje)
        except portarias.ErroPortaria:
            situacao = "RASCUNHO"
        membros = [Membro(nome=str(m.get("nome") or "—"), funcao=str(m.get("funcao") or ""),
                          funcao_rotulo=assinaturas.ROTULOS.get(m.get("funcao"), m.get("funcao") or ""),
                          servidor_ativo=bool(m.get("servidor_ativo", True)))
                   for m in db.listar_membros_de_portaria(str(p["id"]))]
        declarada = str(p.get("status") or "RASCUNHO").upper()
        return Portaria(
            id=str(p["id"]), tipo=str(p.get("tipo") or ""),
            tipo_rotulo=dict(TIPOS_DE_PORTARIA).get(p.get("tipo"), str(p.get("tipo") or "")),
            numero=str(p.get("numero") or ""), ano=int(p.get("ano") or 0), situacao=situacao,
            situacao_declarada=declarada if declarada in SITUACOES_DECLARADAS else "RASCUNHO",
            citacao=portarias.citacao(p), data_publicacao=p.get("data_publicacao"),
            data_inicio_vigencia=p.get("data_inicio_vigencia"), data_fim_vigencia=p.get("data_fim_vigencia"),
            membros=membros)

    @r.get("/portarias", response_model=Portarias)
    def listar_portarias(secretaria_id: uuid.UUID = Query(...),
                         eu: Identidade = Depends(exigir_identidade)) -> Portarias:
        def ler():
            hoje = dt.date.today()
            acervo = db.listar_portarias(secretaria_id=str(secretaria_id))
            avisos = []
            for codigo, rotulo in TIPOS_DE_PORTARIA:
                try:
                    portarias.resolver(acervo, secretaria_id=str(secretaria_id), tipo=codigo,
                                       data_referencia=hoje)
                except portarias.PortariaAmbigua as erro:
                    avisos.append(f"{rotulo} — {erro}")
                except portarias.ErroPortaria as erro:
                    avisos.append(str(erro))
            return Portarias(portarias=[_portaria(p, hoje) for p in acervo], avisos=avisos)
        return _executar(eu, ler, exige_secao=FLAG_PORTARIAS)

    @r.post("/portarias", status_code=201, response_model=Portaria)
    def criar_portaria(corpo: NovaPortaria, eu: Identidade = Depends(exigir_identidade)) -> Portaria:
        if corpo.data_fim_vigencia and corpo.data_fim_vigencia < corpo.data_inicio_vigencia:
            raise ErroApi(422, "VALIDATION_ERROR", "O fim da vigência é anterior ao início.")

        def criar():
            if str(corpo.secretaria_id) not in {str(s["id"]) for s in db.listar_secretarias()}:
                raise ErroApi(404, "NOT_FOUND", "Secretaria não encontrada")
            registro = {
                "secretaria_id": str(corpo.secretaria_id), "tipo": corpo.tipo,
                "numero": corpo.numero, "ano": corpo.ano,
                "data_publicacao": corpo.data_publicacao.isoformat() if corpo.data_publicacao else None,
                "data_inicio_vigencia": corpo.data_inicio_vigencia.isoformat(),
                "data_fim_vigencia": corpo.data_fim_vigencia.isoformat() if corpo.data_fim_vigencia else None,
                # Nasce RASCUNHO, como no Streamlit: ativar é ato separado.
                "status": "RASCUNHO"}
            pid = db.salvar_portaria(registro)
            return _portaria({**registro, "id": pid}, dt.date.today())
        return _executar(eu, criar, exige_secao=FLAG_PORTARIAS)

    def _portaria_do_tenant(portaria_id: uuid.UUID) -> dict:
        p = next((p for p in db.listar_portarias() if str(p["id"]) == str(portaria_id)), None)
        if p is None:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return p

    @r.patch("/portarias/{portaria_id}", response_model=Portaria)
    def mudar_situacao(portaria_id: uuid.UUID, corpo: SituacaoDaPortaria,
                       eu: Identidade = Depends(exigir_identidade)) -> Portaria:
        def mudar():
            atual = _portaria_do_tenant(portaria_id)
            db.salvar_portaria({"status": corpo.status}, str(portaria_id))
            return _portaria({**atual, "status": corpo.status}, dt.date.today())
        return _executar(eu, mudar, exige_secao=FLAG_PORTARIAS)

    @r.post("/portarias/{portaria_id}/membros", status_code=201, response_model=Portaria)
    def adicionar_membro(portaria_id: uuid.UUID, corpo: NovoMembro,
                         eu: Identidade = Depends(exigir_identidade)) -> Portaria:
        def adicionar():
            atual = _portaria_do_tenant(portaria_id)
            # Membro referencia cadastro EXISTENTE (§53): nada de nome livre.
            if str(corpo.servidor_id) not in {str(s["id"]) for s in db.listar_servidores()}:
                raise ErroApi(422, "VALIDATION_ERROR", "Servidor inexistente ou inativo no cadastro.")
            ordem = len(db.listar_membros_de_portaria(str(portaria_id))) + 1
            db.salvar_membro_de_portaria(str(portaria_id), str(corpo.servidor_id), corpo.funcao, ordem=ordem)
            return _portaria(atual, dt.date.today())
        return _executar(eu, adicionar, exige_secao=FLAG_PORTARIAS)

    # -- módulos -----------------------------------------------------------
    @r.get("/modulos", response_model=Modulos)
    def listar_modulos(secretaria_id: uuid.UUID | None = Query(None),
                       eu: Identidade = Depends(exigir_identidade)) -> Modulos:
        def ler():
            no_tenant = db.modulos_do_tenant()
            na_secretaria = db.modulos_da_secretaria(str(secretaria_id)) if secretaria_id else {}
            saida = []
            for modulo, rotulo in MODULOS_OFERECIDOS:
                global_ = db.flag_ativa(modulo)
                estado = modulos.estado_valido(na_secretaria.get(modulo)) if secretaria_id else None
                saida.append(Modulo(
                    modulo=modulo, rotulo=rotulo, disponivel_no_sistema=global_,
                    na_prefeitura=bool(no_tenant.get(modulo, False)), na_secretaria=estado,
                    explicacao=modulos.explicar(flag_global=global_, no_tenant=bool(no_tenant.get(modulo, False)),
                                                na_secretaria=estado or modulos.HERDAR)))
            return Modulos(modulos=saida)
        return _executar(eu, ler)

    def _modulo_oferecido(modulo: str) -> None:
        if modulo not in {m for m, _ in MODULOS_OFERECIDOS}:
            raise ErroApi(404, "NOT_FOUND", "Módulo inexistente")

    @r.put("/modulos/prefeitura/{modulo}", response_model=Modulos)
    def modulo_na_prefeitura(modulo: str, corpo: ModuloNaPrefeitura,
                             eu: Identidade = Depends(exigir_identidade)) -> Modulos:
        _modulo_oferecido(modulo)

        def gravar():
            if not db.flag_ativa(modulo):
                raise ErroApi(409, "MODULE_UNAVAILABLE", "Módulo indisponível nesta versão do sistema")
            db.salvar_modulo_do_tenant(modulo, corpo.habilitado)
        _executar(eu, gravar)
        return listar_modulos(None, eu)

    @r.put("/modulos/secretarias/{secretaria_id}/{modulo}", response_model=Modulos)
    def modulo_na_secretaria(secretaria_id: uuid.UUID, modulo: str, corpo: ModuloNaSecretaria,
                             eu: Identidade = Depends(exigir_identidade)) -> Modulos:
        _modulo_oferecido(modulo)

        def gravar():
            if str(secretaria_id) not in {str(s["id"]) for s in db.listar_secretarias()}:
                raise ErroApi(404, "NOT_FOUND", "Secretaria não encontrada")
            if not db.flag_ativa(modulo):
                raise ErroApi(409, "MODULE_UNAVAILABLE", "Módulo indisponível nesta versão do sistema")
            # A recusa de habilitar o que a prefeitura proíbe vem do domínio.
            db.salvar_modulo_da_secretaria(str(secretaria_id), modulo, corpo.estado)
        _executar(eu, gravar)
        return listar_modulos(secretaria_id, eu)

    # -- timbrado (só leitura) ---------------------------------------------
    @r.get("/timbrado", response_model=Timbrado)
    def timbrado(secretaria_id: uuid.UUID = Query(...),
                 eu: Identidade = Depends(exigir_identidade)) -> Timbrado:
        def ler():
            secretarias = db.listar_secretarias()
            if str(secretaria_id) not in {str(s["id"]) for s in secretarias}:
                raise ErroApi(404, "NOT_FOUND", "Secretaria não encontrada")
            # O MESMO resolvedor da exportação: a tela mostra a decisão que
            # o documento vai tomar, não uma segunda cópia da regra.
            identidade, origem = contexto.resolver_identidade(secretarias, str(secretaria_id))
            identidade = identidade or {}
            return Timbrado(
                origem=origem or "nenhuma",
                cabecalho_img=_como_data_url(identidade.get("cabecalho_img")),
                rodape_img=_como_data_url(identidade.get("rodape_img")),
                marca_img=_como_data_url(identidade.get("marca_img")),
                cabecalho_texto=str(identidade.get("cabecalho") or ""),
                rodape_texto=str(identidade.get("rodape") or ""),
                marca_texto=str(identidade.get("marca_dagua") or ""))
        return _executar(eu, ler)

    return r
