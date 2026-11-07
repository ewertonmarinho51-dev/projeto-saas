"""
Antes de aprovar: o que falta decidir e o que ainda recusaria a aprovação.

`DocumentoService.aprovar` recusa com uma frase só ("a análise nativa e os gates
de qualidade não autorizaram a aprovação") e não diz qual regra falhou. No
primeiro teste real, o DFD sem nenhum [PREENCHER] continuou recusado: o motor
de conhecimento tinha cinco dados ausentes que o Formulário Matriz nunca
pergunta (natureza, categoria, amostra, garantia, dedicação de mão de obra), e
`pendencias` não vazias recusam a aprovação.

Aqui ficam três leituras e uma escrita, todas com o JWT do usuário:

* `GET …/analise` roda, sobre a revisão SALVA, as mesmas verificações que a
  aprovação roda, com as mesmas funções (`conhecimento.resolver`,
  `validacao.validar_todos`, `achados`, `consistencia`, `qualidade`), e devolve
  os motivos um a um. É prévia: quem decide continua sendo `aprovar`, que
  relê tudo pelas fontes do servidor. O gate não é afrouxado em nada;
* a mesma leitura devolve a estrutura (títulos) da projeção nativa;
* `GET …/evidencias` lista os fatos do processo e as fontes que a geração usou;
* `POST /processos/{id}/decisoes` registra a resposta humana como fato
  confirmado, com fonte `decisao:revisao`. Nada aqui é inferido: o que a
  pessoa não respondeu continua ausente, e a aprovação continua recusada.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from src import db, fatos, governanca

from .documentos_nativos import (SEM_CACHE, exigir_workspace, motor_da_api, sessao_do_dominio,
                                 tipo_do_documento, transicionar_fatos)
from .erros import ErroApi
from .seguranca import Identidade, exigir_identidade

FONTE_DA_DECISAO = "decisao:revisao"
LIMITE_MOTIVOS = 30
_SIM_NAO = [{"valor": True, "rotulo": "Sim"}, {"valor": False, "rotulo": "Não"}]

# Só os dados que as regras-base do motor (`conhecimento.REGRAS_BASE`) leem e
# que o formulário não pergunta. Valores fora das opções são recusados.
DECISOES: dict[str, dict[str, Any]] = {
    "objeto.natureza": {
        "rotulo": "Natureza do objeto", "tipo": "texto",
        "ajuda": "Define, por exemplo, reajuste em vez de repactuação e o tratamento a ME/EPP.",
        "opcoes": [{"valor": "BENS", "rotulo": "Bens"},
                   {"valor": "SERVICOS", "rotulo": "Serviços"},
                   {"valor": "OBRAS_ENGENHARIA", "rotulo": "Obras e serviços de engenharia"}]},
    "objeto.categoria": {
        "rotulo": "Categoria do objeto", "tipo": "texto",
        "ajuda": "Algumas categorias trazem exigências próprias (TI, EPI, veículos).",
        "opcoes": [{"valor": "ALIMENTOS", "rotulo": "Gêneros alimentícios"},
                   {"valor": "MATERIAL_CONSUMO", "rotulo": "Material de consumo"},
                   {"valor": "TI_EQUIPAMENTO", "rotulo": "Equipamentos de informática"},
                   {"valor": "TI_SOFTWARE", "rotulo": "Software, SaaS ou hospedagem"},
                   {"valor": "EPI", "rotulo": "Equipamento de proteção individual"},
                   {"valor": "VEICULOS", "rotulo": "Veículos"},
                   {"valor": "MEDICAMENTOS", "rotulo": "Medicamentos e material hospitalar"},
                   {"valor": "OBRAS_ENGENHARIA", "rotulo": "Obras e engenharia"},
                   {"valor": "OUTRA", "rotulo": "Outra categoria"}]},
    "contratacao.amostra_exigida": {
        "rotulo": "A contratação exige amostra ou prova de conceito?", "tipo": "booleano",
        "ajuda": "Só cabe quando prevista no edital e justificada tecnicamente.",
        "opcoes": _SIM_NAO},
    "contratacao.garantia_exigida": {
        "rotulo": "A contratação exige garantia contratual?", "tipo": "booleano",
        "ajuda": "É faculdade motivada da Administração (arts. 96 a 98).",
        "opcoes": _SIM_NAO},
    "procedimento.dedicacao_mao_de_obra": {
        "rotulo": "Há dedicação exclusiva de mão de obra?", "tipo": "booleano",
        "ajuda": "Decide entre reajuste e repactuação (art. 135).",
        "opcoes": _SIM_NAO},
}


class OpcaoDeDecisao(BaseModel):
    valor: bool | str
    rotulo: str


class DecisaoPendente(BaseModel):
    path: str
    rotulo: str
    ajuda: str
    opcoes: list[OpcaoDeDecisao]


class AnaliseDaRevisao(BaseModel):
    revisao: int
    content_hash: str
    pode_aprovar: bool
    motivos: list[str]
    decisoes: list[DecisaoPendente]
    estrutura: list[str]
    score: float | None = None


class FatoDaEvidencia(BaseModel):
    path: str
    valor: Any = None
    origem: str
    confirmado: bool


class FonteDaGeracao(BaseModel):
    titulo: str
    categoria: str
    trecho: str


class Evidencias(BaseModel):
    fatos: list[FatoDaEvidencia]
    itens: int
    fontes: list[FonteDaGeracao]


class RegistroDeDecisoes(BaseModel):
    model_config = ConfigDict(extra="forbid")
    respostas: dict[str, bool | str] = Field(min_length=1, max_length=len(DECISOES))


# ---------------------------------------------------------------------------
# Análise
# ---------------------------------------------------------------------------
def _regras() -> list[dict]:
    """A base da plataforma e as regras do banco, como a aprovação as reúne."""
    from src import conhecimento, politicas

    regras = conhecimento.regras_base()
    try:
        regras += db.listar_regras()
        if db.flag_ativa(governanca.FLAG_POLITICAS_VISUAL):
            regras += politicas.regras_publicadas()
    except db.ErroBanco:
        pass
    return regras


def _unicos(motivos: list[str]) -> list[str]:
    vistos, saida = set(), []
    for motivo in motivos:
        texto = " ".join(str(motivo or "").split())[:300]
        if texto and texto not in vistos:
            vistos.add(texto)
            saida.append(texto)
    return saida[:LIMITE_MOTIVOS]


def analisar(servico, document_id: str, processo_id: str, tipo: str, dados: dict) -> AnaliseDaRevisao:
    """As verificações de `DocumentoService.aprovar`, em leitura e com o motivo de cada recusa."""
    from src import achados, conhecimento, consistencia, qualidade, validacao
    from src import wordcraft_blocos as blocos

    documento = servico.abrir(document_id)
    vigentes = [f for f in db.listar_fatos(processo_id) if f.get("status") != "substituido"]
    motivos: list[str] = []
    if not vigentes:
        motivos.append("O processo não tem fatos registrados: confira os fatos na revisão.")
    elif pendentes := [f for f in vigentes if f.get("status") != "confirmado"]:
        motivos.append(f"{len(pendentes)} fato(s) do processo ainda sem confirmação.")

    decisao = conhecimento.resolver(vigentes, _regras(), conhecimento.fontes_revogadas_do_banco(),
                                    processo_id=processo_id, documento=tipo)
    resultado = decisao["resultado"]
    ausentes = list(resultado.get("pendencias") or [])
    decisoes = [DecisaoPendente(path=p, **{k: DECISOES[p][k] for k in ("rotulo", "ajuda", "opcoes")})
                for p in ausentes if p in DECISOES]
    if decisoes:
        motivos.append(f"{len(decisoes)} decisão(ões) da contratação ainda não registrada(s).")
    motivos += [f"Dado ausente para as regras do órgão: {p}." for p in ausentes if p not in DECISOES]
    motivos += [f"Regra do órgão bloqueia: {b.get('motivo') or b.get('regra')}" for b in resultado.get("bloqueios", [])]
    motivos += [f"Regras em conflito sobre: {c.get('clausula')}" for c in resultado.get("conflitos", [])]

    estrutura: list[str] = []
    score = None
    if documento.index is None:
        motivos.append("A revisão salva não tem índice do motor: salve uma alteração para gerá-lo.")
    else:
        projecao = blocos.projetar_documento(documento.tipo, documento.payload, indice=documento.index,
                                             **servico._native)  # noqa: SLF001 — mesma projeção da aprovação
        estrutura = [b.conteudo for b in projecao.blocos if b.tipo == "titulo"][:200]
        if not projecao.apto_analise:
            motivos.append("Parte do documento não tem texto legível pela análise (objeto ou imagem sem texto).")
        textos = {documento.tipo: projecao.texto_analise}
        brutos = validacao.validar_todos(textos, {}, dados)
        motivos += [b.get("mensagem") for b in validacao.bloqueios(brutos)]
        achados_da_revisao = achados.estruturar(brutos, textos) + consistencia.verificar(vigentes, textos)
        motivos += [a.get("descricao") or a.get("blockingReason") for a in achados_da_revisao if a.get("blockingReason")]
        nota = qualidade.calcular({"findings": achados_da_revisao}, vigentes, decisao, textos)
        gate = qualidade.avaliar_gate(nota)
        score = nota.get("score")
        if gate["bloqueia"]:
            motivos.append(f"Qualidade: {gate['motivo']}.")

    motivos = _unicos(motivos)
    return AnaliseDaRevisao(revisao=documento.revision, content_hash=documento.content_hash,
                            pode_aprovar=not motivos, motivos=motivos, decisoes=decisoes,
                            estrutura=estrutura, score=score)


def _origem(fonte: str) -> str:
    fonte = str(fonte or "")
    if fonte.startswith(FONTE_DA_DECISAO):
        return "Decisão registrada na revisão"
    if fonte.startswith(fatos.PREFIXO_INFERENCIA):
        return "Inferido do formulário"
    if fonte.startswith("formulario"):
        return "Formulário Matriz"
    return "Pesquisa de preços" if "pesquisa" in fonte else "Processo"


# ---------------------------------------------------------------------------
# Rotas
# ---------------------------------------------------------------------------
def rotas() -> APIRouter:
    r = APIRouter(prefix="/processos", tags=["documentos"])

    def _processo(request: Request, eu: Identidade, processo_id: str, colunas: str) -> dict:
        rest = getattr(request.app.state, "rest", None)
        if rest is None:
            raise ErroApi(503, "AUTH_UNAVAILABLE", "Autenticação indisponível neste ambiente")
        resposta = rest.requisitar(eu.token, "GET", "processos", params={
            "select": colunas, "id": f"eq.{processo_id}", "tenant_id": f"eq.{eu.tenant_id}"})
        if resposta.status != 200:
            raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível")
        if not resposta.dados:
            raise ErroApi(404, "NOT_FOUND", "Recurso não encontrado")
        return resposta.dados[0]

    def _tipo(processo_id: str, document_id: str) -> str:
        tipo = tipo_do_documento(processo_id, document_id)
        if tipo is None:
            raise ErroApi(404, "NOT_FOUND", "Documento não encontrado")
        return tipo

    @r.get("/{processo_id}/documentos/{document_id}/analise", response_model=AnaliseDaRevisao,
           responses={404: {"description": "Documento fora do seu acesso ou editor desligado"},
                      503: {"description": "Motor indisponível"}})
    def analise(processo_id: uuid.UUID, document_id: uuid.UUID, request: Request, response: Response,
                eu: Identidade = Depends(exigir_identidade)) -> AnaliseDaRevisao:
        """O que a aprovação desta revisão salva recusaria hoje, motivo a motivo."""
        exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        pid, did = str(processo_id), str(document_id)
        tipo = _tipo(pid, did)
        dados = _processo(request, eu, pid, "id,dados").get("dados") or {}
        motor = motor_da_api(request)
        from src.documentos_editor import AcessoNegado, ErroDocumento

        with sessao_do_dominio(eu):
            try:
                return analisar(motor.servico, did, pid, tipo, dados)
            except AcessoNegado:
                raise ErroApi(404, "NOT_FOUND", "Documento ainda não aberto no editor") from None
            except (ErroDocumento, db.ErroBanco):
                raise ErroApi(503, "ANALYSIS_UNAVAILABLE", "Não foi possível analisar a revisão agora.") from None

    @r.get("/{processo_id}/documentos/{document_id}/evidencias", response_model=Evidencias,
           responses={404: {"description": "Documento fora do seu acesso ou editor desligado"}})
    def evidencias(processo_id: uuid.UUID, document_id: uuid.UUID, request: Request, response: Response,
                   eu: Identidade = Depends(exigir_identidade)) -> Evidencias:
        """Os fatos do processo e as fontes que a geração deste documento consultou."""
        exigir_workspace(request, eu)
        response.headers.update(SEM_CACHE)
        pid, did = str(processo_id), str(document_id)
        tipo = _tipo(pid, did)
        _processo(request, eu, pid, "id")
        with sessao_do_dominio(eu):
            try:
                vigentes = [f for f in db.listar_fatos(pid) if f.get("status") != "substituido"]
            except db.ErroBanco:
                raise ErroApi(503, "DATABASE_UNAVAILABLE", "Banco indisponível") from None
        itens = sum(1 for f in vigentes if str(f.get("path", "")).startswith("itens[")
                    and str(f.get("path", "")).endswith(".descricao"))
        lista = [FatoDaEvidencia(path=str(f.get("path")), valor=f.get("valor"), origem=_origem(f.get("fonte")),
                                 confirmado=f.get("status") == "confirmado")
                 for f in vigentes if not str(f.get("path", "")).startswith("itens[")][:200]
        geracao = request.app.state.rest.requisitar(eu.token, "GET", "geracoes", params={
            "select": "rag_trace", "processo_id": f"eq.{pid}", "documento": f"eq.{tipo}",
            "status": "eq.ok", "order": "criado_em.desc", "limit": "1"})
        trace = ((geracao.dados or [{}])[0].get("rag_trace") or {}) if geracao.status == 200 else {}
        fontes = [FonteDaGeracao(titulo=str(ref.get("titulo") or "Base de Conhecimento")[:200],
                                 categoria=str(ref.get("categoria") or "")[:80],
                                 trecho=str(ref.get("trecho") or "")[:300])
                  for ref in (trace.get("referencias") or []) if isinstance(ref, dict)][:20]
        return Evidencias(fatos=lista, itens=itens, fontes=fontes)

    @r.post("/{processo_id}/decisoes", status_code=204, response_class=Response,
            responses={403: {"description": "Só o titular do processo ou um administrador"},
                       422: {"description": "Decisão desconhecida ou valor fora das opções"}})
    def registrar(processo_id: uuid.UUID, pedido: RegistroDeDecisoes, request: Request,
                  eu: Identidade = Depends(exigir_identidade)) -> Response:
        """Registra a resposta humana como fato confirmado. Substitui a anterior, nunca a apaga."""
        exigir_workspace(request, eu)
        pid = str(processo_id)
        _processo(request, eu, pid, "id")
        novos = []
        for path, valor in pedido.respostas.items():
            regra = DECISOES.get(path)
            if regra is None or valor not in [o["valor"] for o in regra["opcoes"]] \
                    or (regra["tipo"] == "booleano") != isinstance(valor, bool):
                raise ErroApi(422, "VALIDATION_ERROR", "Decisão desconhecida ou valor fora das opções.")
            novos.append(governanca.novo_fato(pid, path, valor, regra["tipo"], FONTE_DA_DECISAO, confianca=1.0))
        with sessao_do_dominio(eu):
            try:
                inserir, substituir = fatos.planejar_versionamento(novos, db.listar_fatos(pid, apenas_vigentes=False))
                if inserir:
                    db.salvar_fatos(inserir)
                confirmar = [str(f["id"]) for f in db.listar_fatos(pid)
                             if f.get("path") in pedido.respostas and f.get("status") == "extraido"]
            except db.ErroBanco:
                # Sem política de INSERT é quem não é titular nem admin; quem decide é o RLS.
                raise ErroApi(403, "FORBIDDEN", "Só o titular do processo ou um administrador registra decisões.") from None
        if substituir or confirmar:
            transicionar_fatos(request, eu, pid, substituir, confirmar)
        return Response(status_code=204, headers=SEM_CACHE)

    return r
