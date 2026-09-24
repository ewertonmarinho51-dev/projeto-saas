"""
Varredura: toda consulta a tabela com `tenant_id` carrega o filtro?

POR QUE ESTA PROVA EXISTE

A auditoria de 24/09/2026 achou o mesmo defeito em duas tabelas — a
identidade visual e os PROCESSOS. Nos dois casos a coluna `tenant_id`
existia desde a migração 0006 e os acessos em `db.py` nunca passaram a
usá-la: a listagem devolvia o de todas as prefeituras, e o id que ela
entregava abria, renomeava, sobrescrevia e apagava o alheio.

Achar dois casos à mão não diz quantos existem. Esta varredura responde
isso, e é o que impede o terceiro: quem acrescentar um acesso a tabela
com `tenant_id` sem o filtro falha aqui.

POR QUE O RLS NÃO SUBSTITUI ISTO

O app opera com a credencial de SERVIDOR, e `service_role` tem
BYPASSRLS. As 82 políticas do banco protegem contra uma chave publicável
vazada; contra a consulta do próprio app que esqueceu o `where`, não há
política que valha. Neste caminho, o `.eq("tenant_id", …)` É a
contenção.

A LISTA DE EXCEÇÕES É O PONTO

Ela não existe para silenciar a varredura: existe para que cada ausência
seja uma DECISÃO ESCRITA, com o motivo ao lado, em vez de um esquecimento
que ninguém revisou. Acrescentar nome aqui é ato deliberado — e a prova
seguinte cobra que a justificativa exista.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
FONTE_DB = RAIZ / "src" / "db.py"
MIGRACOES = RAIZ / "supabase" / "migrations"


# Por que cada função pode consultar uma tabela com `tenant_id` sem
# filtrar por ele. Sem motivo escrito, não entra.
SEM_FILTRO_COM_MOTIVO = {
    "obter_config": "config_app é GLOBAL por desenho — a chave primária "
                    "é só `chave`, e uma flag vale para a instalação "
                    "inteira. Ver src/ambiente.py.",
    "salvar_config": "mesma tabela global de `obter_config`.",
    "obter_revisao": "escopo pelo id da revisão, que só chega por "
                     "caminho já filtrado por processo.",
    "obter_revisao_por_chave": "escopo pelo processo + chave do "
                               "documento; o processo já vem filtrado.",
    "atualizar_revisao": "escopo pelo id da revisão obtida acima.",
    "listar_fatos": "escopo pelo processo, cuja leitura já filtra tenant.",
    "atualizar_fato": "escopo pelo id do fato listado acima.",
    "listar_decisoes": "escopo pelo processo, já filtrado na origem.",
    "atualizar_feedback": "escopo pelo id do registro de aprendizado "
                          "vinculado ao processo.",
    "modulos_da_secretaria": "escopo pela secretaria, e "
                             "`listar_secretarias` já filtra tenant.",
    "listar_membros_de_portaria": "escopo pela portaria, e "
                                  "`listar_portarias` já filtra tenant.",
    "signatarios_do_documento": "escopo pelo documento do processo "
                                "aberto, já filtrado na origem.",
    "identidade_do_documento": "escopo pelo documento do processo "
                               "aberto, já filtrado na origem.",
}

# FRONTEIRA, dita para não virar promessa: as justificativas acima são
# de escopo INDIRETO — a função é segura enquanto o id do pai vier de
# uma consulta já filtrada. É defesa em profundidade que falta, e está
# registrada no laudo como "parcialmente confirmado": a ausência do
# filtro foi medida; a exposição não foi reproduzida.


def _tabelas_com_tenant() -> set[str]:
    """
    Lido das MIGRAÇÕES, e não de um banco de pé.

    Ligado a um banco, a prova só rodaria onde houvesse banco — e a
    varredura que existe para não deixar passar acesso novo passaria a
    pular justamente na CI.
    """
    tabelas: set[str] = set()
    for arquivo in sorted(MIGRACOES.glob("*.sql")):
        texto = arquivo.read_text(encoding="utf-8")
        for bloco in re.finditer(
                r"create table (?:if not exists )?public\.(\w+)\s*\((.*?)\n\);",
                texto, re.S | re.I):
            if re.search(r"\btenant_id\b", bloco.group(2)):
                tabelas.add(bloco.group(1))
        for bloco in re.finditer(
                r"alter table\s+public\.(\w+)([^;]*);", texto, re.S | re.I):
            corpo = bloco.group(2)
            if re.search(r"add column\s+(if not exists\s+)?tenant_id",
                         corpo, re.I):
                tabelas.add(bloco.group(1))
    return tabelas


def _acessos_sem_filtro() -> dict[str, set[str]]:
    """{função: {tabelas com tenant_id consultadas sem `tenant_id`}}."""
    com_tenant = _tabelas_com_tenant()
    achados: dict[str, set[str]] = {}
    for bloco in re.split(r"\ndef ", FONTE_DB.read_text(encoding="utf-8")):
        nome = bloco.split("(")[0].strip()
        if not nome or "tenant_id" in bloco:
            continue
        alvo = {t for t in re.findall(r'\.table\("(\w+)"\)', bloco)
                if t in com_tenant}
        if alvo:
            achados[nome] = alvo
    return achados


def test_as_migracoes_declaram_as_tabelas_com_tenant():
    """
    Régua antes da medição: se a leitura das migrações devolvesse pouca
    coisa, a varredura passaria por não ter o que varrer.
    """
    tabelas = _tabelas_com_tenant()
    assert len(tabelas) >= 30, (
        f"só {len(tabelas)} tabelas com `tenant_id` — a leitura das "
        "migrações quebrou, e a varredura abaixo perdeu o sentido")
    for esperada in ("processos", "config_orgaos", "secretarias",
                     "servidores", "portarias"):
        assert esperada in tabelas, f"{esperada} não foi reconhecida"


def test_nenhum_acesso_novo_a_tabela_de_tenant_sem_filtro():
    novos = {f: t for f, t in _acessos_sem_filtro().items()
             if f not in SEM_FILTRO_COM_MOTIVO}
    assert not novos, (
        "consulta a tabela com `tenant_id` sem filtrar por ele: "
        f"{ {f: sorted(t) for f, t in novos.items()} }. "
        "O app opera com `service_role`, que atravessa o RLS — aqui o "
        "filtro É a contenção. Se a ausência for deliberada, escreva o "
        "motivo em SEM_FILTRO_COM_MOTIVO.")


@pytest.mark.parametrize("funcao", sorted(SEM_FILTRO_COM_MOTIVO))
def test_toda_excecao_tem_motivo_escrito_e_ainda_existe(funcao):
    """
    Exceção sem motivo é esquecimento com aparência de decisão. E
    exceção para função que não existe mais é lixo que esconde a
    próxima — a lista precisa envelhecer junto com o código.
    """
    motivo = SEM_FILTRO_COM_MOTIVO[funcao]
    assert len(motivo) > 30, f"{funcao}: motivo curto demais para valer"
    assert f"\ndef {funcao}(" in FONTE_DB.read_text(encoding="utf-8"), (
        f"{funcao} está na lista de exceções e não existe mais em db.py")


@pytest.mark.parametrize("funcao", sorted(SEM_FILTRO_COM_MOTIVO))
def test_excecao_que_ganhou_filtro_sai_da_lista(funcao):
    """
    O inverso do teste acima: quem passou a filtrar não pode continuar
    listado como exceção, senão a lista vira um lugar onde nomes entram
    e nunca saem — e deixa de descrever o código.
    """
    assert funcao in _acessos_sem_filtro(), (
        f"{funcao} passou a filtrar por tenant: tire-a de "
        "SEM_FILTRO_COM_MOTIVO")
