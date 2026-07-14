"""
Catálogo de cláusulas oficiais (Fase 2 do Centro de Governança V6).

Serviço administrativo sobre `governanca_artefatos`/`governanca_versoes`
(migração 0010): criar cláusula, editar RASCUNHO, derivar nova versão de
uma publicada, transicionar no fluxo oficial e publicar com supersede.

Regras aplicadas AQUI (a UI só chama):
  - papel: criar exige pode_criar; aprovar revisão exige pode_revisar;
    publicar/revogar exige pode_publicar; escopo plataforma exige
    governa_plataforma (T09 — servidor comum nem chega à página);
  - versão publicada é IMUTÁVEL (guarda também no db.py); editar uma
    publicada = derivar nova versão DRAFT;
  - publicar SUPERSEDE automaticamente a versão publicada anterior do
    mesmo artefato (uma vigente por vez);
  - toda operação grava evento na trilha append-only
    `governanca_eventos`;
  - o seed a partir de perfis.py cria APENAS RASCUNHOS — importação
    jamais publica sozinha (T14).
"""

from . import auth, db, governanca, perfis

_COMPORTAMENTO_POR_FIXA = {"LOCKED": "FIXED_LOCKED",
                           "PARAMETERIZED": "FIXED_PARAMETERIZED"}


class ErroCatalogo(Exception):
    """Operação de catálogo recusada (papel, estado ou contrato)."""


def _exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise ErroCatalogo(mensagem)


def _evento(tipo: str, entidade_id: str | None, payload: dict) -> None:
    usuario = (auth.usuario_logado() or {})
    db.registrar_evento_governanca(
        tipo, "governanca_versoes", entidade_id, payload,
        ator=usuario.get("id"))


# ---------------------------------------------------------------------------
# Criação, edição de rascunho e derivação
# ---------------------------------------------------------------------------
def criar_clausula(chave_estavel: str, payload: dict,
                   plataforma: bool = False) -> tuple[dict, dict]:
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite criar cláusulas.")
    if plataforma:
        _exigir(auth.governa_plataforma(),
                "Escopo da plataforma exige papel global.")
    artefato = db.obter_ou_criar_artefato(
        "clausula", chave_estavel, plataforma=plataforma)
    versoes = db.listar_versoes_governanca(artefato["id"])
    proxima = max((v["versao"] for v in versoes), default=0) + 1
    contrato = governanca.nova_versao_artefato(
        "clausula", chave_estavel, payload, versao=proxima)
    contrato["autor"] = (auth.usuario_logado() or {}).get("id")
    gravada = db.criar_versao_governanca(artefato["id"], contrato)
    _evento("clausula_rascunho_criado", gravada.get("id"),
            {"chave": chave_estavel, "versao": proxima})
    return artefato, gravada


def editar_rascunho(versao: dict, chave_estavel: str,
                    payload: dict) -> dict:
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite editar cláusulas.")
    _exigir(governanca.versao_artefato_editavel(versao),
            "Versão publicada é imutável — derive uma nova versão.")
    contrato = governanca.nova_versao_artefato(
        "clausula", chave_estavel, payload,
        versao=versao["versao"], status=versao["status"])
    atualizada = db.atualizar_versao_governanca(
        versao["id"], payload=contrato["payload"],
        hash=contrato["hash"])
    _evento("clausula_rascunho_editado", versao["id"],
            {"chave": chave_estavel, "versao": versao["versao"]})
    return atualizada


def derivar_nova_versao(artefato: dict, versao: dict) -> dict:
    """'Editar' uma publicada: cria a versão seguinte em rascunho."""
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite derivar versões.")
    versoes = db.listar_versoes_governanca(artefato["id"])
    proxima = max((v["versao"] for v in versoes), default=0) + 1
    contrato = governanca.nova_versao_artefato(
        "clausula", artefato["chave_estavel"], versao["payload"],
        versao=proxima)
    contrato["autor"] = (auth.usuario_logado() or {}).get("id")
    gravada = db.criar_versao_governanca(artefato["id"], contrato)
    _evento("clausula_versao_derivada", gravada.get("id"),
            {"chave": artefato["chave_estavel"], "de": versao["versao"],
             "para": proxima})
    return gravada


# ---------------------------------------------------------------------------
# Workflow de estados (com papéis e supersede na publicação)
# ---------------------------------------------------------------------------
_PAPEL_POR_TRANSICAO = {
    "APPROVED_FOR_SIMULATION": auth.pode_revisar_governanca,
    "PUBLISHED": auth.pode_publicar_governanca,
    "REVOKED": auth.pode_publicar_governanca,
}


def transicionar(artefato: dict, versao: dict, novo_status: str,
                 vigencia_inicio: str | None = None) -> dict:
    _exigir(governanca.transicao_artefato_valida(
        versao.get("status", ""), novo_status),
        f"transição inválida: {versao.get('status')} → {novo_status}")
    checagem = _PAPEL_POR_TRANSICAO.get(novo_status)
    if checagem:
        _exigir(checagem(), f"Seu papel não permite {novo_status}.")

    campos: dict = {"status": novo_status}
    usuario_id = (auth.usuario_logado() or {}).get("id")
    if novo_status == "APPROVED_FOR_SIMULATION" and usuario_id:
        campos["revisor"] = usuario_id
    if novo_status == "PUBLISHED":
        if usuario_id:
            campos["aprovador"] = usuario_id
        if vigencia_inicio:
            campos["vigencia_inicio"] = vigencia_inicio
        # uma vigente por vez: a publicada anterior é SUPERSEDED
        for anterior in db.listar_versoes_governanca(artefato["id"]):
            if anterior.get("status") == "PUBLISHED" and \
                    anterior["id"] != versao["id"]:
                db.atualizar_versao_governanca(anterior["id"],
                                               status="SUPERSEDED")
                _evento("clausula_versao_superada", anterior["id"],
                        {"chave": artefato["chave_estavel"],
                         "versao": anterior["versao"]})
    atualizada = db.atualizar_versao_governanca(versao["id"], **campos)
    _evento(f"clausula_{novo_status.lower()}", versao["id"],
            {"chave": artefato["chave_estavel"],
             "versao": versao["versao"]})
    return atualizada


def proximas_transicoes(versao: dict) -> list[str]:
    """Transições possíveis para o papel do usuário atual (UI)."""
    destinos = [d for d in governanca.ESTADOS_ARTEFATO
                if governanca.transicao_artefato_valida(
                    versao.get("status", ""), d)]
    return [d for d in destinos
            if _PAPEL_POR_TRANSICAO.get(d, lambda: True)()]


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
def listar_com_situacao() -> list[dict]:
    """Cláusulas visíveis + última versão + publicada vigente."""
    resultado = []
    for artefato in db.listar_artefatos("clausula"):
        versoes = db.listar_versoes_governanca(artefato["id"])
        publicada = next((v for v in versoes
                          if v.get("status") == "PUBLISHED"), None)
        resultado.append({
            "artefato": artefato,
            "versoes": versoes,
            "ultima": versoes[0] if versoes else None,
            "publicada": publicada,
        })
    return resultado


# ---------------------------------------------------------------------------
# Seed: perfis.py → rascunhos do catálogo (nunca publica — T14)
# ---------------------------------------------------------------------------
def _slug(texto: str) -> str:
    import re
    import unicodedata

    sem_acentos = "".join(
        c for c in unicodedata.normalize("NFKD", texto)
        if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", sem_acentos.lower()).strip("-")


def semear_dos_perfis() -> list[str]:
    """Cada cláusula dos perfis aprovados vira um RASCUNHO do catálogo."""
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite importar os perfis.")
    existentes = {item["artefato"]["chave_estavel"]
                  for item in listar_com_situacao()}
    criadas = []
    for doc_key in ("dfd", "etp", "tr"):
        fixas = perfis.clausulas_fixas(doc_key)
        for clausula in perfis.clausulas_obrigatorias(doc_key):
            chave = f"clausula.{doc_key}.{_slug(clausula['titulo'])}"
            if chave in existentes:
                continue
            comportamento = _COMPORTAMENTO_POR_FIXA.get(
                fixas.get(clausula["n"]), "AI_GENERATED")
            payload = {
                "titulo": clausula["titulo"],
                "tipo_documental": doc_key,
                "comportamento": comportamento,
                "blocos": [clausula["finalidade"]],
                "posicao_preferencial": clausula["n"],
                "base_legal": [],
            }
            if comportamento == "FIXED_PARAMETERIZED":
                payload["parametros_permitidos"] = [
                    "prazo", "valor", "data", "percentual"]
            criar_clausula(chave, payload)
            criadas.append(chave)
    return criadas
