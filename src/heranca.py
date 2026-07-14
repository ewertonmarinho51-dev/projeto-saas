"""
Herança e precedência de artefatos (Fase 6 do Centro de Governança V6).

Resolução: processo → secretaria → município → plataforma — o nível
mais ESPECÍFICO com versão publicada prevalece; sem override, vale a
herança. O catálogo NUNCA é duplicado por tenant: um override cria
apenas o artefato sobrescrito no escopo local (rascunho derivado da
versão herdada), e restaurar a herança REVOGA o override local — o
histórico permanece (nada é apagado).

O administrador vê a ORIGEM de cada item (plataforma/município/
secretaria), pode sobrescrever, comparar (hash e payload) e restaurar.

Flag `flag_tenant_inheritance_admin`: liga o módulo na página
Governança. A precedência de POLÍTICAS já é aplicada pelo motor V5
(camadas); aqui se resolve a versão efetiva de cláusulas/templates.
"""

from . import catalogo, db, governanca


class ErroHeranca(Exception):
    """Operação de herança recusada."""


def ativa() -> bool:
    return db.flag_ativa(governanca.FLAG_HERANCA)


def _escopo(artefato: dict) -> str:
    if artefato.get("secretaria_id"):
        return "secretaria"
    if artefato.get("tenant_id"):
        return "municipio"
    return "plataforma"


_PRECEDENCIA = {"plataforma": 0, "municipio": 1, "secretaria": 2}


def visao_heranca(tipo_artefato: str = "clausula") -> list[dict]:
    """
    Uma linha por CHAVE visível: versão efetiva (escopo mais específico
    com publicada), origem e overrides existentes — a matriz que o
    administrador vê antes de decidir sobrescrever ou restaurar.
    """
    por_chave: dict[str, list[dict]] = {}
    for item in catalogo.listar_com_situacao(tipo_artefato):
        chave = item["artefato"]["chave_estavel"]
        por_chave.setdefault(chave, []).append(item)

    visao = []
    for chave, itens in sorted(por_chave.items()):
        publicados = [i for i in itens if i["publicada"]]
        efetivo = max(
            publicados,
            key=lambda i: _PRECEDENCIA[_escopo(i["artefato"])],
            default=None)
        visao.append({
            "chave": chave,
            "efetivo": efetivo,
            "origem": _escopo(efetivo["artefato"]) if efetivo else None,
            "escopos": {_escopo(i["artefato"]): i for i in itens},
            "tem_override": len(itens) > 1,
        })
    return visao


def versao_efetiva(tipo_artefato: str, chave: str) -> dict | None:
    """Versão publicada vigente da chave, respeitando a precedência."""
    linha = next((l for l in visao_heranca(tipo_artefato)
                  if l["chave"] == chave), None)
    return linha["efetivo"]["publicada"] if linha and linha["efetivo"] \
        else None


def sobrescrever(linha: dict) -> dict:
    """
    Cria o override LOCAL (município) da chave herdada da plataforma:
    um rascunho derivado da versão efetiva — nada é duplicado além do
    item sobrescrito, e a plataforma permanece intacta.
    """
    if "municipio" in linha["escopos"]:
        raise ErroHeranca(
            f"'{linha['chave']}' já possui override neste município.")
    efetivo = linha["efetivo"]
    if not efetivo:
        raise ErroHeranca(
            f"'{linha['chave']}' não tem versão publicada para herdar.")
    tipo = efetivo["artefato"]["tipo_artefato"]
    _, rascunho = catalogo.criar_artefato(
        tipo, linha["chave"], efetivo["publicada"]["payload"])
    return rascunho


def restaurar_heranca(linha: dict) -> None:
    """
    Volta a herdar: REVOGA a versão publicada do override local (e o
    histórico fica preservado). Sem override local, não há o que fazer.
    """
    local = linha["escopos"].get("municipio") \
        or linha["escopos"].get("secretaria")
    if not local:
        raise ErroHeranca(
            f"'{linha['chave']}' não tem override local para restaurar.")
    if not local["publicada"]:
        raise ErroHeranca(
            f"O override de '{linha['chave']}' não está publicado — "
            "descarte o rascunho no catálogo.")
    catalogo.transicionar(local["artefato"], local["publicada"], "REVOKED")


def comparar(linha: dict) -> dict | None:
    """Diferenças override × plataforma (hash e campos do payload)."""
    plataforma = linha["escopos"].get("plataforma")
    local = linha["escopos"].get("municipio") \
        or linha["escopos"].get("secretaria")
    if not (plataforma and local and plataforma["publicada"]
            and local["publicada"]):
        return None
    payload_plataforma = plataforma["publicada"]["payload"]
    payload_local = local["publicada"]["payload"]
    campos = sorted(set(payload_plataforma) | set(payload_local))
    return {
        "iguais": plataforma["publicada"]["hash"]
        == local["publicada"]["hash"],
        "campos_diferentes": [
            c for c in campos
            if payload_plataforma.get(c) != payload_local.get(c)],
        "hash_plataforma": plataforma["publicada"]["hash"],
        "hash_local": local["publicada"]["hash"],
    }
