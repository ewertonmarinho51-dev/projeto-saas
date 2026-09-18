"""
Assinaturas institucionais: quem pode assinar, e o que fica congelado.

DUAS REGRAS, E AS DUAS SÃO SOBRE NÃO INVENTAR

**Elegibilidade.** A lista de signatários de um documento não é "todos os
servidores do município". É quem tem AQUELA função, NAQUELA secretaria,
VIGENTE naquela data. Mostrar cinquenta nomes para escolher o signatário
de um edital é convidar o erro — e um edital assinado por quem não tinha
a designação é vício de forma.

**Snapshot.** Quando o documento é aprovado, o que sai dele para de
depender do cadastro. Nome, matrícula, cargo, função, secretaria e
portaria são COPIADOS. Se o servidor for exonerado amanhã, o documento
de ontem continua correto — porque ele registra o que era verdade no dia
em que foi assinado, não o que é verdade agora.

Módulo PURO: recebe as listas já lidas do banco e decide. Quem lê é
`db.py`; quem escreve o snapshot é o fluxo de aprovação.
"""

from __future__ import annotations

import datetime as _dt

from . import portarias as _portarias

# As funções que a tela oferece como "tipo de signatário". A ordem é a
# de uso, não alfabética.
TIPOS_DE_SIGNATARIO = (
    "RESPONSAVEL_DEMANDA",
    "EQUIPE_PLANEJAMENTO",
    "COORDENADOR_EQUIPE_PLANEJAMENTO",
    "SECRETARIO",
    "AUTORIDADE_COMPETENTE",
    "ORDENADOR_DESPESAS",
    "PREGOEIRO",
    "AGENTE_CONTRATACAO",
    "FISCAL_CONTRATO",
    "GESTOR_CONTRATO",
)

# As funções cuja fonte de verdade é a PORTARIA, não o cadastro avulso.
# Para elas, estar designado em portaria vigente é condição necessária —
# marcar a função na ficha do servidor não basta, porque a designação de
# equipe de planejamento é ato formal publicado.
FUNCOES_DE_PORTARIA = (
    "EQUIPE_PLANEJAMENTO",
    "COORDENADOR_EQUIPE_PLANEJAMENTO",
)

# O rótulo que o documento imprime sob o nome. Espelha o seed de
# `funcoes_administrativas` na 0025, e mora aqui — não em `db.py` —
# porque é vocabulário DO PRODUTO: a exportação de um documento
# histórico não pode depender de o banco estar de pé, nem de uma
# prefeitura ter renomeado a função na tabela dela.
# `test_multi_prefeituras.py` prova que as duas listas não divergem.
ROTULOS = {
    "RESPONSAVEL_DEMANDA": "Responsável pela Demanda",
    "EQUIPE_PLANEJAMENTO": "Integrante da Equipe de Planejamento",
    "COORDENADOR_EQUIPE_PLANEJAMENTO": "Coordenador da Equipe de Planejamento",
    "SECRETARIO": "Secretário Municipal",
    "AUTORIDADE_COMPETENTE": "Autoridade Competente",
    "ORDENADOR_DESPESAS": "Ordenador de Despesas",
    "PREGOEIRO": "Pregoeiro",
    "AGENTE_CONTRATACAO": "Agente de Contratação",
    "FISCAL_CONTRATO": "Fiscal do Contrato",
    "GESTOR_CONTRATO": "Gestor do Contrato",
}


class ErroAssinatura(Exception):
    """Signatário inelegível, ou snapshot impossível de montar."""


def _vigente(registro: dict, data_referencia: _dt.date) -> bool:
    if not registro.get("ativo", True):
        return False
    inicio = registro.get("data_inicio")
    fim = registro.get("data_fim")
    try:
        inicio = _portarias._data(inicio) if inicio else None  # noqa: SLF001
        fim = _portarias._data(fim) if fim else None  # noqa: SLF001
    except _portarias.ErroPortaria:
        return False
    if inicio and inicio > data_referencia:
        return False
    return not (fim and fim < data_referencia)


def elegiveis(*, funcao: str, servidores: list[dict],
              funcoes_do_servidor: list[dict],
              portaria: dict | None,
              membros_da_portaria: list[dict],
              secretaria_id: str | None,
              data_referencia: _dt.date) -> list[dict]:
    """
    Os servidores que podem assinar como `funcao`, e só eles.

    Para função de portaria, a fonte é a PORTARIA VIGENTE: sem portaria,
    a lista é vazia — e vazia é a resposta certa, porque nomear alguém
    "integrante da equipe de planejamento" sem ato que o designe é o erro
    que o documento carrega para o processo.

    Para as demais, a fonte é `servidor_funcoes` com vigência na data e
    secretaria compatível. `secretaria_id` nulo em `servidor_funcoes`
    significa função municipal (ex.: autoridade competente do prefeito),
    e essa alcança qualquer secretaria do tenant.
    """
    por_id = {s["id"]: s for s in servidores if s.get("ativo", True)}

    if funcao in FUNCOES_DE_PORTARIA:
        if not portaria:
            return []
        elegiveis_ids = [
            m["servidor_id"]
            for m in _portarias.membros_vigentes(membros_da_portaria)
            if m.get("portaria_id") == portaria.get("id")
            and (m.get("funcao") == funcao
                 # O coordenador também é integrante: pedir integrantes
                 # e esconder quem coordena produziria uma lista que não
                 # bate com a portaria publicada.
                 or (funcao == "EQUIPE_PLANEJAMENTO"
                     and m.get("funcao") == "COORDENADOR_EQUIPE_PLANEJAMENTO"))
        ]
        return [por_id[i] for i in elegiveis_ids if i in por_id]

    return [
        por_id[f["servidor_id"]]
        for f in funcoes_do_servidor
        if f.get("funcao") == funcao
        and f["servidor_id"] in por_id
        and f.get("secretaria_id") in (None, secretaria_id)
        and _vigente(f, data_referencia)
    ]


def montar_snapshot(*, servidor: dict, funcao: str,
                    secretaria_nome: str | None,
                    portaria: dict | None,
                    ordem: int) -> dict:
    """
    O que fica GRAVADO no documento, e nunca mais muda.

    Cada campo é uma cópia deliberada. `servidor_id` viaja junto para
    auditoria — saber quem era essa pessoa no cadastro —, mas a
    exportação lê só o snapshot: consultar o cadastro vivo para
    regenerar um documento histórico é o defeito que este módulo existe
    para impedir.
    """
    nome = (servidor.get("nome") or "").strip()
    if not nome:
        raise ErroAssinatura(
            "servidor sem nome não pode assinar: o snapshot ficaria com o "
            "campo que o documento imprime em branco")
    if funcao not in TIPOS_DE_SIGNATARIO:
        raise ErroAssinatura(f"função desconhecida para assinatura: {funcao!r}")

    return {
        "servidor_id": servidor.get("id"),
        "nome_snapshot": nome,
        "matricula_snapshot": servidor.get("matricula") or None,
        "cargo_snapshot": servidor.get("cargo") or None,
        "funcao_snapshot": funcao,
        "secretaria_snapshot": secretaria_nome or None,
        "portaria_numero_snapshot": (
            f"{portaria['numero']}/{portaria['ano']}" if portaria else None),
        "portaria_data_snapshot": (
            portaria.get("data_publicacao") if portaria else None),
        "ordem": ordem,
    }


def conferir_elegibilidade(*, servidor_id: str, funcao: str,
                           elegiveis_agora: list[dict]) -> None:
    """
    A checagem no momento de gravar, e não só ao montar a lista.

    A tela mostrou os elegíveis há cinco minutos; nesse intervalo a
    portaria pode ter sido revogada, ou o servidor inativado. Conferir de
    novo aqui é o que impede que a escolha antiga seja gravada contra o
    cadastro novo.
    """
    if any(s.get("id") == servidor_id for s in elegiveis_agora):
        return
    raise ErroAssinatura(
        f"este servidor não está elegível para assinar como {funcao} "
        "nesta secretaria e nesta data. A designação pode ter sido "
        "revogada ou expirada — confira a portaria no painel "
        "administrativo.")


def linhas_de_exportacao(signatarios: list[dict]) -> list[list[str]]:
    """
    O bloco de assinatura do DOCX/PDF, lido SÓ do snapshot.

    Formato de cada signatário:

        ANTONIO EWERTON MARINHO LEITE
        Integrante da Equipe de Planejamento
        Portaria nº 003/2026
    """
    saida: list[list[str]] = []
    for s in sorted(signatarios, key=lambda x: x.get("ordem", 1)):
        linhas = [(s.get("nome_snapshot") or "").upper()]
        rotulo = ROTULOS.get(s.get("funcao_snapshot"),
                             s.get("funcao_snapshot") or "")
        if rotulo:
            linhas.append(rotulo)
        if s.get("portaria_numero_snapshot"):
            linhas.append(f"Portaria nº {s['portaria_numero_snapshot']}")
        saida.append(linhas)
    return saida
