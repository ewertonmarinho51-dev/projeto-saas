"""
Laboratório de melhorias e publicações (Fases 9–10 do V6).

Do achado de parecer à melhoria PUBLICADA, sempre com humano no
comando:

  clusters (pareceres.clusterizar) → PROPOSTA de melhoria → regressão
  histórica → shadow → aprovação → publicação → rollback restaurador

Regras de publicação (09_LABORATORIO do pacote):
  - proposta SEMPRE nasce de evidência real (achados de parecer) — uma
    sugestão de IA sozinha nunca é evidência suficiente;
  - um único parecer PODE originar proposta (recorrência aumenta
    prioridade, não é requisito — T20);
  - a proposta é ANONIMIZADA e não carrega dados específicos do
    processo (nem processo_id);
  - mudança jurídica (cláusula/política/modelo) exige papel publicador+
    para aceitar;
  - REGRESSÃO histórica: a política candidata roda contra contextos de
    processos anteriores e as DIFERENÇAS de decisão são expostas (T22);
  - rollback = NOVA PUBLICAÇÃO RESTAURADORA (deriva a versão antiga e
    publica por cima; nada é editado nem apagado — T23);
  - gate de publicação (`flag_governance_publication_gate`): publicar
    exige APROVAÇÃO registrada por usuário DIFERENTE do autor.
"""

from . import auth, catalogo, conhecimento, db, governanca, politicas

TIPOS_ALVO = (
    "formulario", "fato_obrigatorio", "validacao", "politica",
    "clausula", "modelo", "prompt", "auditor", "operacional",
)
_TIPOS_JURIDICOS = ("politica", "clausula", "modelo")

ESTADOS_PROPOSTA = ("DRAFT", "UNDER_REVIEW", "ACCEPTED", "REJECTED")


class ErroLaboratorio(Exception):
    """Proposta/publicação recusada."""


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_LABORATORIO)


def gate_publicacao_ativo() -> bool:
    return db.flag_ativa(governanca.FLAG_PUBLICACAO_GATE)


# ---------------------------------------------------------------------------
# Propostas de melhoria (sem dados específicos — T20)
# ---------------------------------------------------------------------------
def criar_proposta(cluster: dict, tipo_alvo: str,
                   descricao: str, mudanca: dict | None = None) -> dict:
    if tipo_alvo not in TIPOS_ALVO:
        raise ErroLaboratorio(f"tipo de alvo inválido: {tipo_alvo!r}")
    if not cluster.get("achado_ids"):
        raise ErroLaboratorio(
            "proposta sem evidência: é preciso ao menos um achado de "
            "parecer — sugestão de IA sozinha não basta.")
    proposta = {
        "tipo_alvo": tipo_alvo,
        "descricao": governanca.anonimizar_texto(descricao)[:1000],
        "mudanca": {
            chave: (governanca.anonimizar_texto(valor)
                    if isinstance(valor, str) else valor)
            for chave, valor in (mudanca or {}).items()
            if chave not in ("processo_id", "processo", "interessado")
        },
        "evidencias": {
            "achado_ids": list(cluster["achado_ids"]),
            "pareceres": list(cluster.get("pareceres", [])),
            "ocorrencias": cluster.get("ocorrencias", 1),
        },
    }
    registro = {
        "tenant_id": db.tenant_atual(),
        "cluster_id": cluster.get("id"),
        "tipo_alvo": tipo_alvo,
        "status": "DRAFT",
        "proposta": proposta,
        "criado_por": (auth.usuario_logado() or {}).get("id"),
    }
    if not db.disponivel():
        return registro
    try:
        return db._cliente().table("melhoria_propostas").insert(  # noqa: SLF001
            registro).execute().data[0]
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def decidir_proposta(proposta: dict, decisao: str,
                     motivo: str = "") -> dict:
    """ACCEPTED/REJECTED — mudança jurídica exige papel publicador+."""
    if decisao not in ("ACCEPTED", "REJECTED"):
        raise ErroLaboratorio(f"decisão inválida: {decisao!r}")
    if decisao == "ACCEPTED" and \
            proposta.get("tipo_alvo") in _TIPOS_JURIDICOS and \
            not auth.pode_publicar_governanca():
        raise ErroLaboratorio(
            "mudança jurídica exige aprovador autorizado (publicador+).")
    campos = {"status": decisao}
    if db.disponivel() and proposta.get("id"):
        try:
            db._cliente().table("melhoria_propostas").update(  # noqa: SLF001
                campos).eq("id", proposta["id"]).execute()
            db.registrar_evento_governanca(
                f"proposta_{decisao.lower()}", "melhoria_propostas",
                proposta["id"], {"motivo": motivo})
        except Exception as exc:  # noqa: BLE001
            raise db._traduzir_erro(exc) from exc  # noqa: SLF001
    return {**proposta, **campos}


# ---------------------------------------------------------------------------
# Regressão histórica (T22): decisão ANTES × DEPOIS da candidata
# ---------------------------------------------------------------------------
def regressao_historica(artefato: dict, versao: dict,
                        contextos: list[dict]) -> list[dict]:
    """
    Roda o motor com e sem a política candidata sobre contextos de
    processos históricos (anonimizados) e devolve SÓ as diferenças —
    o administrador vê exatamente o que mudaria.
    """
    candidata = politicas.como_regra(artefato, versao)
    candidata["status"] = "PUBLISHED"  # apenas em memória
    publicadas = politicas.regras_publicadas()
    diferencas = []
    for i, contexto in enumerate(contextos):
        fatos = politicas._fatos_de_contexto(contexto)  # noqa: SLF001
        antes = conhecimento.resolver(fatos, publicadas, set(), None)
        depois = conhecimento.resolver(fatos, publicadas + [candidata],
                                       set(), None)
        if antes["output_hash"] != depois["output_hash"]:
            diferencas.append({
                "contexto": i,
                "antes": antes["resultado"],
                "depois": depois["resultado"],
            })
    return diferencas


# ---------------------------------------------------------------------------
# Publicações (releases) e rollback restaurador (T23)
# ---------------------------------------------------------------------------
def registrar_aprovacao(versao: dict, decisao: str,
                        motivo: str = "") -> dict:
    """Aprovação segregada: o AUTOR da versão não pode se aprovar."""
    aprovador = (auth.usuario_logado() or {}).get("id")
    if aprovador and versao.get("autor") and \
            aprovador == versao.get("autor"):
        raise ErroLaboratorio(
            "segregação de funções: o autor não pode aprovar a própria "
            "versão.")
    registro = {
        "tenant_id": db.tenant_atual(),
        "entidade_tipo": "governanca_versoes",
        "entidade_id": versao["id"],
        "papel_exigido": "publicador",
        "aprovador": aprovador,
        "decisao": decisao,
        "motivo": motivo,
    }
    if not db.disponivel():
        return registro
    try:
        return db._cliente().table("governanca_aprovacoes").insert(  # noqa: SLF001
            registro).execute().data[0]
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def aprovacao_existente(versao_id: str) -> bool:
    if not db.disponivel():
        return False
    try:
        registros = (db._cliente().table("governanca_aprovacoes")  # noqa: SLF001
                     .select("*").eq("entidade_id", versao_id)
                     .eq("decisao", "APROVADO").limit(1).execute()).data
        return bool(registros)
    except Exception:  # noqa: BLE001
        return False


def publicar_com_gate(artefato: dict, versao: dict,
                      vigencia_inicio: str | None = None) -> dict:
    """
    Publicação sob o gate (flag_governance_publication_gate): exige
    aprovação registrada por usuário diferente do autor. Sem a flag,
    delega ao fluxo normal (que já exige o caminho por SHADOW).
    """
    if gate_publicacao_ativo() and not aprovacao_existente(versao["id"]):
        raise ErroLaboratorio(
            "gate de publicação: registre a aprovação (por usuário "
            "diferente do autor) antes de publicar.")
    if artefato.get("tipo_artefato") == "politica":
        return politicas.publicar(artefato, versao, vigencia_inicio)
    return catalogo.transicionar(artefato, versao, "PUBLISHED",
                                 vigencia_inicio)


def registrar_release(itens: list[dict], motivo: str,
                      reverte: str | None = None) -> dict:
    registro = {
        "tenant_id": db.tenant_atual(),
        "status": "ATIVA",
        "itens": itens,
        "motivo": motivo,
        "publicado_por": (auth.usuario_logado() or {}).get("id"),
        "reverte": reverte,
    }
    if not db.disponivel():
        return registro
    try:
        return db._cliente().table("governanca_publicacoes").insert(  # noqa: SLF001
            registro).execute().data[0]
    except Exception as exc:  # noqa: BLE001
        raise db._traduzir_erro(exc) from exc  # noqa: SLF001


def rollback_restaurador(artefato: dict, versao_antiga: dict,
                         motivo: str = "") -> dict:
    """
    Rollback SEM apagar nada (T23): deriva uma NOVA versão com o payload
    da versão antiga e a publica (a atual fica SUPERSEDED). Documentos
    históricos e snapshots permanecem intocados.
    """
    rascunho = catalogo.derivar_nova_versao(artefato, versao_antiga)
    versao = rascunho
    for destino in ("UNDER_REVIEW", "APPROVED_FOR_SIMULATION", "SHADOW"):
        versao = catalogo.transicionar(artefato, versao, destino)
    publicada = catalogo.transicionar(artefato, versao, "PUBLISHED")
    registrar_release(
        [{"artefato": artefato["chave_estavel"],
          "versao": publicada["versao"], "hash": publicada["hash"]}],
        motivo or f"rollback restaurador para o conteúdo da "
                  f"v{versao_antiga['versao']}",
        reverte=str(versao_antiga.get("id")))
    return publicada
