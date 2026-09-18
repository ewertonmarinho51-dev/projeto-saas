"""
Emissão: o instante em que o cadastro vivo vira documento congelado.

O QUE ACONTECE AQUI, E POR QUE SÓ AQUI

Enquanto o documento está em rascunho ele pode usar os dados atuais — se
o cargo do servidor mudar hoje, o rascunho de hoje mostra o cargo de hoje
(§35). No momento da APROVAÇÃO isso para: o timbrado e os signatários são
COPIADOS para `documento_identidades` e `documento_signatarios`, e a
exportação passa a ler de lá.

A diferença não é técnica, é jurídica. Um edital aprovado é ato
administrativo publicado. Se o servidor for exonerado em março, o edital
de janeiro continua tendo sido assinado por quem o assinou, com o cargo
que ele tinha — e um sistema que regenerasse o PDF consultando o cadastro
de março produziria um documento que nunca existiu.

BEST-EFFORT, E A ESCOLHA É DELIBERADA

Falha ao congelar NÃO impede a aprovação. É a mesma decisão que
`aprendizado.capturar_edicao` já tomou no mesmo ponto do fluxo: travar o
avanço do processo porque uma tabela auxiliar não respondeu seria trocar
um registro incompleto por um servidor público parado.

O que a falha produz é um documento sem bloco de assinatura — visível,
não silencioso —, e uma linha de log. O que ela NUNCA produz é assinatura
lida do cadastro vivo na hora de exportar: sem snapshot, sem bloco.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging

from . import assinaturas as _assinaturas

_log = logging.getLogger("govdocs.emissao")

# A chave onde a escolha de signatários do usuário fica ENQUANTO o
# documento é rascunho. Mora em `processos.dados`, junto do resto do
# processo, pelo mesmo motivo que a consolidação de demanda mora lá: é
# dado DO processo, e uma tabela separada criaria um segundo lugar onde a
# mesma coisa vive.
CHAVE_ESCOLHA = "signatarios_escolhidos"


def data_de_referencia(processo: dict) -> _dt.date:
    """
    A data que resolve portaria e vigência de função.

    É a CRIAÇÃO DO PROCESSO, não `hoje`. Um DFD de janeiro cita a equipe
    designada pela portaria de janeiro; reaberto em dezembro, ele não
    pode passar a citar outra — o documento histórico mentiria sobre o
    ato que o fundamentou.

    Sem data legível, cai para hoje: é a única escolha que não trava o
    processo, e o caso só acontece em registro corrompido.
    """
    bruto = processo.get("criado_em")
    if not bruto:
        return _dt.date.today()
    try:
        return _dt.date.fromisoformat(str(bruto)[:10])
    except ValueError:
        _log.warning("criado_em ilegível (%r): usando hoje como referência",
                     bruto)
        return _dt.date.today()


def impressao_da_identidade(identidade: dict | None) -> str:
    """
    Hash do timbrado efetivamente aplicado.

    Permite responder "este PDF saiu com a identidade que o snapshot
    registra?" sem guardar a imagem duas vezes. Ordenado por chave para
    que o mesmo timbrado dê sempre o mesmo hash.
    """
    corpo = json.dumps(identidade or {}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(corpo.encode("utf-8")).hexdigest()[:32]


def montar_identidade(identidade: dict | None, origem: str,
                      *, secretaria_id: str | None) -> dict:
    """A linha de `documento_identidades` — sem o processo, que o db põe."""
    return {
        "secretaria_id": secretaria_id,
        "origem": origem if origem in ("secretaria", "municipio", "nenhuma")
                  else "nenhuma",
        "identidade": identidade or {},
        "hash_identidade": impressao_da_identidade(identidade),
        "versao": 1,
    }


def montar_signatarios(escolhas: list[dict], *, servidores: list[dict],
                       secretaria_nome: str | None,
                       portaria: dict | None) -> list[dict]:
    """
    Os snapshots, na ordem escolhida.

    `escolhas` é o que o usuário marcou na tela: `[{servidor_id, funcao}]`.
    Uma escolha cujo servidor sumiu do cadastro é DESCARTADA com log, e
    não vira snapshot com nome vazio: bloco de assinatura sem nome é pior
    que bloco ausente, porque parece assinado.
    """
    por_id = {s["id"]: s for s in servidores}
    saida: list[dict] = []
    for ordem, escolha in enumerate(escolhas, start=1):
        servidor = por_id.get(escolha.get("servidor_id"))
        if not servidor:
            _log.warning("signatário escolhido não está mais no cadastro: %r",
                         escolha.get("servidor_id"))
            continue
        try:
            saida.append(_assinaturas.montar_snapshot(
                servidor=servidor, funcao=escolha.get("funcao") or "",
                secretaria_nome=secretaria_nome,
                portaria=portaria if _precisa_de_portaria(escolha) else None,
                ordem=ordem))
        except _assinaturas.ErroAssinatura as erro:
            _log.warning("signatário descartado no congelamento: %s", erro)
    return saida


def _precisa_de_portaria(escolha: dict) -> bool:
    """
    Só as funções designadas por portaria carregam o número dela.

    Carimbar "Portaria nº 003/2026" sob o nome do Secretário Municipal
    seria atribuir a ele uma designação que a portaria não fez.
    """
    return (escolha.get("funcao") or "") in _assinaturas.FUNCOES_DE_PORTARIA


def congelar(processo_id: str, doc_key: str, *, escolhas: list[dict],
             servidores: list[dict], secretaria_id: str | None,
             secretaria_nome: str | None, portaria: dict | None,
             identidade: dict | None, origem: str, gravar) -> bool:
    """
    Congela identidade e signatários. Devolve se gravou.

    `gravar(identidade_linha, signatarios_linhas)` é injetado para que
    esta função seja testável sem banco — e para que o módulo não precise
    conhecer `db`.

    Qualquer exceção vira `False` e log. Ver o cabeçalho: aprovação não
    para por causa de tabela auxiliar.
    """
    try:
        linha_identidade = montar_identidade(
            identidade, origem, secretaria_id=secretaria_id)
        linhas_signatarios = montar_signatarios(
            escolhas, servidores=servidores,
            secretaria_nome=secretaria_nome, portaria=portaria)
        gravar(linha_identidade, linhas_signatarios)
        return True
    except Exception as erro:  # noqa: BLE001 — ver o cabeçalho
        _log.warning("não foi possível congelar %s/%s: %s",
                     processo_id, doc_key, erro)
        return False


def bloco_de_assinaturas(signatarios: list[dict]) -> str:
    """
    O bloco em markdown que a exportação insere no fim do documento.

    Lê SÓ o snapshot — nunca o cadastro. Lista vazia devolve string
    vazia, e o documento sai sem bloco: é o comportamento legado dos
    processos antigos (§58), e é melhor que um bloco em branco, que
    pareceria assinatura pendente.
    """
    linhas = _assinaturas.linhas_de_exportacao(signatarios)
    if not linhas:
        return ""
    partes = [""]
    for bloco in linhas:
        partes.append("")
        partes.append("\\_" * 30)
        partes += bloco
    return "\n\n".join(partes)
