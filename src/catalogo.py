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

from . import auth, db, governanca, perfis, trilha

_COMPORTAMENTO_POR_FIXA = {"LOCKED": "FIXED_LOCKED",
                           "PARAMETERIZED": "FIXED_PARAMETERIZED"}


class ErroCatalogo(Exception):
    """Operação de catálogo recusada (papel, estado ou contrato)."""


def _exigir(condicao: bool, mensagem: str) -> None:
    if not condicao:
        raise ErroCatalogo(mensagem)


def _evento(tipo: str, entidade_id: str | None, payload: dict) -> None:
    """
    Registra um ato na trilha.

    Duas coisas deixaram de ser feitas aqui, e as duas eram defeito.

    O `ator` NÃO é mais passado. Era `usuarios.id` — a chave da tabela
    de usuários do app, que não é `auth.uid()` e que o chamador
    escolhia. Agora sai de `auth.uid()` dentro da RPC, onde ninguém
    daqui alcança.

    A entidade declarada é `versao`, o TIPO LÓGICO, e não
    `governanca_versoes`, o nome da tabela. A matriz da 0020 fala em
    tipos lógicos; declarar o nome da tabela fazia toda chamada ser
    recusada por vocabulário mesmo com o papel correto.
    """
    db.registrar_evento_governanca(tipo, "versao", entidade_id, payload)


# ---------------------------------------------------------------------------
# Criação, edição de rascunho e derivação
# ---------------------------------------------------------------------------
def criar_artefato(tipo_artefato: str, chave_estavel: str, payload: dict,
                   plataforma: bool = False) -> tuple[dict, dict]:
    """Cria artefato + versão 1 DRAFT (genérico: cláusula/política/…)."""
    _exigir(auth.pode_criar_governanca(),
            f"Seu papel não permite criar {tipo_artefato}s.")
    if plataforma:
        _exigir(auth.governa_plataforma(),
                "Escopo da plataforma exige papel global.")
    artefato = db.obter_ou_criar_artefato(
        tipo_artefato, chave_estavel, plataforma=plataforma)
    versoes = db.listar_versoes_governanca(artefato["id"])
    proxima = max((v["versao"] for v in versoes), default=0) + 1
    contrato = governanca.nova_versao_artefato(
        tipo_artefato, chave_estavel, payload, versao=proxima)
    contrato["autor"] = (auth.usuario_logado() or {}).get("id")
    gravada = db.criar_versao_governanca(artefato["id"], contrato)
    # O ATO é "versão criada". O tipo de artefato é atributo do ato e
    # vai no payload — vocabulário que depende do dado não fecha nunca.
    _evento("versao_criada", gravada.get("id"),
            {"tipo_artefato": tipo_artefato, "chave": chave_estavel,
             "versao": proxima, "origem": "rascunho_criado"})
    return artefato, gravada


def criar_clausula(chave_estavel: str, payload: dict,
                   plataforma: bool = False) -> tuple[dict, dict]:
    return criar_artefato("clausula", chave_estavel, payload, plataforma)


def editar_rascunho(versao: dict, chave_estavel: str, payload: dict,
                    tipo_artefato: str = "clausula") -> dict:
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite editar este artefato.")
    _exigir(governanca.versao_artefato_editavel(versao),
            "Versão publicada é imutável — derive uma nova versão.")
    contrato = governanca.nova_versao_artefato(
        tipo_artefato, chave_estavel, payload,
        versao=versao["versao"], status=versao["status"])
    atualizada = db.atualizar_versao_governanca(
        versao["id"], payload=contrato["payload"],
        hash=contrato["hash"])
    _evento("versao_alterada", versao["id"],
            {"tipo_artefato": tipo_artefato, "chave": chave_estavel,
             "versao": versao["versao"], "origem": "rascunho_editado"})
    return atualizada


def derivar_nova_versao(artefato: dict, versao: dict) -> dict:
    """'Editar' uma publicada: cria a versão seguinte em rascunho."""
    _exigir(auth.pode_criar_governanca(),
            "Seu papel não permite derivar versões.")
    tipo = artefato.get("tipo_artefato", "clausula")
    versoes = db.listar_versoes_governanca(artefato["id"])
    proxima = max((v["versao"] for v in versoes), default=0) + 1
    contrato = governanca.nova_versao_artefato(
        tipo, artefato["chave_estavel"], versao["payload"],
        versao=proxima)
    contrato["autor"] = (auth.usuario_logado() or {}).get("id")
    gravada = db.criar_versao_governanca(artefato["id"], contrato)
    # derivar É criar uma versão; o que a distingue vai no payload
    _evento("versao_criada", gravada.get("id"),
            {"tipo_artefato": tipo, "chave": artefato["chave_estavel"],
             "de": versao["versao"], "para": proxima,
             "origem": "versao_derivada"})
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

    tipo = artefato.get("tipo_artefato", "clausula")
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
                _evento("versao_superada", anterior["id"],
                        {"tipo_artefato": tipo,
                         "chave": artefato["chave_estavel"],
                         "versao": anterior["versao"]})
    atualizada = db.atualizar_versao_governanca(versao["id"], **campos)
    # `f"{tipo}_{novo_status.lower()}"` produzia `clausula_published`,
    # `politica_revoked` — nomes em duas línguas, dependentes do dado e
    # ausentes de qualquer matriz. A transição tem um ato nomeado.
    _evento(trilha.evento_da_transicao(novo_status), versao["id"],
            {"tipo_artefato": tipo, "chave": artefato["chave_estavel"],
             "versao": versao["versao"], "status": novo_status})
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
def listar_com_situacao(tipo_artefato: str = "clausula") -> list[dict]:
    """Artefatos visíveis + última versão + publicada vigente."""
    resultado = []
    for artefato in db.listar_artefatos(tipo_artefato):
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
