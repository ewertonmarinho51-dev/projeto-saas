"""
Assistente de implantação (Fase 7 do Centro de Governança V6).

Fluxo guiado para colocar um município novo (ou reorganizar um tenant)
no ar a partir dos DOCUMENTOS APROVADOS dele:

  1. município e secretarias já têm cadastro próprio (Fase 2 multi-
     tenant / aba Secretarias);
  2. o administrador importa documentos aprovados (DOCX/PDF/TXT/MD);
  3. o sistema extrai DETERMINISTICAMENTE as cláusulas candidatas
     (títulos numerados + corpo, via o mesmo parser de blocos do v4);
  4. duplicidades e variações são detectadas por hash e por título;
  5. o administrador revisa item a item e cria RASCUNHOS no catálogo —
     a importação NUNCA publica nada (T14): o caminho é sempre
     rascunho → revisão → simulação → shadow → publicação gradual.

A IA pode sugerir/agrupar em fases futuras; a extração aqui é código
puro — ninguém decide que um texto é cláusula oficial além do humano.

Flag `flag_onboarding_assistant`: liga o módulo na página Governança.
"""

from . import blocos, catalogo, db, governanca, rag


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_IMPLANTACAO)


# ---------------------------------------------------------------------------
# Extração determinística de cláusulas candidatas
# ---------------------------------------------------------------------------
def extrair_candidatas(nome_arquivo: str, conteudo: bytes,
                       tipo_documental: str = "tr") -> list[dict]:
    """Cláusulas candidatas: título numerado + corpo, com hash próprio."""
    texto = rag.extrair_texto(nome_arquivo, conteudo)
    blocos_doc = blocos.dividir_em_blocos(tipo_documental, texto)
    candidatas = []
    for bloco in blocos_doc:
        if bloco["tipo"] != "titulo":
            continue
        corpo = [b["conteudo"] for b in blocos_doc
                 if b.get("clausula") == bloco["clausula"]
                 and b["tipo"] != "titulo"]
        titulo = bloco["conteudo"].lstrip("#").strip()
        titulo = titulo.split(".", 1)[-1].strip() if "." in titulo[:4] \
            else titulo
        if not corpo:
            continue
        candidatas.append({
            "titulo": titulo,
            "tipo_documental": tipo_documental,
            "blocos": corpo,
            "origem": nome_arquivo,
            "hash": governanca.hash_canonico(
                {"titulo": titulo, "blocos": corpo}),
        })
    return candidatas


def detectar_duplicatas(candidatas: list[dict],
                        existentes: list[dict] | None = None
                        ) -> list[dict]:
    """
    Marca cada candidata: 'nova', 'duplicata' (hash idêntico a outra
    candidata/cláusula do catálogo) ou 'variacao' (mesmo título, texto
    diferente — o administrador decide qual versão vale).
    """
    if existentes is None:
        existentes = catalogo.listar_com_situacao("clausula") \
            if db.disponivel() else []
    hashes_catalogo = {}
    titulos_catalogo = {}
    for item in existentes:
        ultima = item.get("ultima")
        if not ultima:
            continue
        payload = ultima.get("payload") or {}
        hash_conteudo = governanca.hash_canonico(
            {"titulo": payload.get("titulo"),
             "blocos": payload.get("blocos")})
        hashes_catalogo[hash_conteudo] = item["artefato"]["chave_estavel"]
        titulos_catalogo[str(payload.get("titulo", "")).upper()] = \
            item["artefato"]["chave_estavel"]

    vistos: dict[str, str] = {}
    resultado = []
    for candidata in candidatas:
        situacao, referencia = "nova", None
        if candidata["hash"] in hashes_catalogo:
            situacao = "duplicata"
            referencia = hashes_catalogo[candidata["hash"]]
        elif candidata["hash"] in vistos:
            situacao = "duplicata"
            referencia = vistos[candidata["hash"]]
        elif candidata["titulo"].upper() in titulos_catalogo:
            situacao = "variacao"
            referencia = titulos_catalogo[candidata["titulo"].upper()]
        vistos[candidata["hash"]] = candidata["origem"]
        resultado.append({**candidata, "situacao": situacao,
                          "referencia": referencia})
    return resultado


def criar_rascunhos(candidatas: list[dict]) -> list[str]:
    """Candidatas selecionadas viram RASCUNHOS do catálogo — nunca
    publicadas (T14)."""
    criadas = []
    for candidata in candidatas:
        chave = (f"clausula.{candidata['tipo_documental']}."
                 f"{catalogo._slug(candidata['titulo'])}")  # noqa: SLF001
        catalogo.criar_clausula(chave, {
            "titulo": candidata["titulo"],
            "tipo_documental": candidata["tipo_documental"],
            "comportamento": "AI_GENERATED",
            "blocos": candidata["blocos"],
            "base_legal": [],
            "importado_de": candidata["origem"],
        })
        criadas.append(chave)
    return criadas
