"""
Atualização por cláusula: barata, mas nunca ao preço da coerência.

O QUE ESTAS PROVAS GUARDAM

Mudar um campo do formulário descartava os cinco documentos do
processo. Passar a reescrever só as cláusulas alcançadas economiza a
maior parte da SAÍDA — e cria um modo de falha novo, silencioso e pior
que o desperdício: um documento em que a cláusula nova diz 30 dias e a
cláusula vizinha, que ninguém regenerou, continua dizendo 15.

Por isso metade das provas aqui não mede economia nenhuma. Elas medem
a RECUSA: o que acontece quando o modelo devolve cláusula a mais, a
menos, ou mexe no que não devia.
"""

from __future__ import annotations

import pytest

from src import perfis, regeneracao


def _documento(doc_key: str, marca: str = "v1") -> str:
    partes = []
    for c in perfis.PERFIS[doc_key]["clausulas"]:
        partes.append(f"## {c['n']}. {c['titulo']}")
        partes.append(f"{c['n']}.1. texto {marca} da cláusula {c['n']}.")
    return "\n\n".join(partes)


TR = _documento("tr")


# ---------------------------------------------------------------------------
# O plano: o que a mudança alcança
# ---------------------------------------------------------------------------
def test_campos_alterados_ignora_chave_interna():
    """
    `_fluxo_mapa_riscos` não é dado do processo. Se ela contasse como
    alteração, ligar o fluxo do Mapa marcaria todos os documentos para
    atualização sem que um único campo tivesse mudado.
    """
    antes = {"prazo": "30 dias", "_fluxo_mapa_riscos": False}
    depois = {"prazo": "30 dias", "_fluxo_mapa_riscos": True}
    assert regeneracao.campos_alterados(antes, depois) == []


def test_prazo_no_tr_alcanca_tudo_que_pode_cita_lo():
    """
    O mapa é conservador de propósito. Prazo aparece em execução,
    formalização, recebimento, pagamento, liquidação e sanção — e uma
    cláusula esquecida contradiz a nova sem levantar erro nenhum.
    """
    afetadas = regeneracao.clausulas_afetadas("tr", ["prazo"])
    assert afetadas and len(afetadas) >= 5
    assert {5, 7, 10, 12} <= afetadas


def test_objeto_e_itens_exigem_o_documento_inteiro():
    """
    Objeto e planilha atravessam o documento todo. Um mapa com quinze
    cláusulas daria no mesmo e ainda fingiria que houve recorte.
    """
    for campo in ("objeto", "itens"):
        assert regeneracao.clausulas_afetadas("tr", [campo]) is None


def test_campo_sem_regra_declarada_nunca_vira_permissao():
    """
    A ausência de regra não pode significar "não afeta nada" — seria o
    caminho pelo qual um campo novo entraria no formulário e deixaria de
    atualizar documento nenhum, em silêncio.
    """
    assert regeneracao.clausulas_afetadas("tr", ["campo_que_nao_existe"]) is None


def test_mapa_de_riscos_nao_tem_recorte_possivel():
    """Ele é uma matriz, não uma sequência de cláusulas endereçáveis."""
    assert regeneracao.clausulas_afetadas("mapa_riscos", ["riscos"]) is None


def test_alteracao_ampla_demais_volta_ao_documento_inteiro():
    """
    Recortar metade do documento não economiza: o prompt fica do tamanho
    do documento e a conferência fica mais frágil sem contrapartida.
    """
    todos = [c for c in regeneracao.MAPA_DE_IMPACTO["tr"]]
    assert regeneracao.clausulas_afetadas("tr", todos) is None


def test_todo_campo_do_formulario_tem_decisao_declarada():
    """
    Campo novo no formulário sem decisão aqui é campo que passa
    despercebido. Esta prova obriga quem acrescentar um a dizer o que
    ele alcança — ou a declará-lo como exigente de documento inteiro.
    """
    from src.config import CAMPOS_FORMULARIO

    for doc_key, mapa in regeneracao.MAPA_DE_IMPACTO.items():
        if not mapa:          # documento sem cláusula endereçável
            continue
        faltando = [c for c in CAMPOS_FORMULARIO
                    if c not in mapa
                    and c not in regeneracao.CAMPOS_QUE_EXIGEM_DOCUMENTO_INTEIRO]
        assert not faltando, (
            f"{doc_key}: os campos {faltando} não têm regra declarada. "
            "Sem regra, a atualização parcial os ignora — e o documento "
            "fica afirmando um dado que mudou.")


def test_toda_clausula_do_mapa_existe_no_perfil():
    """
    Um número de cláusula errado no mapa pede ao modelo uma cláusula que
    não existe, e a conferência rejeita tudo — a funcionalidade ficaria
    ligada e sem efeito nenhum.
    """
    for doc_key, mapa in regeneracao.MAPA_DE_IMPACTO.items():
        if not mapa:
            continue
        validas = {c["n"] for c in perfis.PERFIS[doc_key]["clausulas"]}
        for campo, numeros in mapa.items():
            invalidas = set(numeros) - validas
            assert not invalidas, f"{doc_key}/{campo}: {sorted(invalidas)}"


# ---------------------------------------------------------------------------
# A aplicação: o que entra e o que é recusado
# ---------------------------------------------------------------------------
def test_substitui_apenas_as_clausulas_pedidas():
    resposta = ("## 5. EXECUÇÃO DO OBJETO\n\n5.1. texto v2 da cláusula 5.\n\n"
                "## 7. DO CRITÉRIO DE ACEITAÇÃO DO OBJETO\n\n"
                "7.1. texto v2 da cláusula 7.")
    novo = regeneracao.aplicar(TR, resposta, {5, 7})

    assert "texto v2 da cláusula 5" in novo
    assert "texto v2 da cláusula 7" in novo
    # todas as outras intactas
    for n in (1, 2, 3, 4, 6, 8, 9, 10):
        assert f"texto v1 da cláusula {n}." in novo
    assert len(regeneracao.dividir_por_clausula(novo)) == \
        len(regeneracao.dividir_por_clausula(TR))


def test_clausula_fora_do_escopo_rejeita_tudo():
    """
    O modelo aproveitou a viagem e reescreveu a cláusula 9. Aceitar isso
    aplicaria uma alteração que ninguém pediu nem revisou.
    """
    resposta = ("## 5. EXECUÇÃO DO OBJETO\n\n5.1. novo.\n\n"
                "## 9. DAS OBRIGAÇÕES DA CONTRATADA\n\n9.1. novo também.")
    with pytest.raises(regeneracao.RecorteRejeitado, match="fora do escopo"):
        regeneracao.aplicar(TR, resposta, {5})


def test_clausula_pedida_e_nao_entregue_rejeita_tudo():
    """
    A mutação que importa: aceitar o parcial deixaria a cláusula 7
    afirmando o prazo antigo ao lado da 5 com o novo — a contradição
    que esta funcionalidade existe para não criar.
    """
    resposta = "## 5. EXECUÇÃO DO OBJETO\n\n5.1. novo."
    with pytest.raises(regeneracao.RecorteRejeitado, match="não trouxe"):
        regeneracao.aplicar(TR, resposta, {5, 7})


def test_resposta_sem_clausula_numerada_rejeita_tudo():
    with pytest.raises(regeneracao.RecorteRejeitado):
        regeneracao.aplicar(TR, "Claro! Aqui está o texto atualizado.", {5})


def test_clausula_ausente_do_documento_vigente_rejeita_tudo():
    """Documento editado à mão pode não ter a cláusula que o mapa pede."""
    sem_cinco = "\n\n".join(
        p for p in TR.split("\n\n") if not p.startswith(("## 5.", "5.1.")))
    resposta = "## 5. EXECUÇÃO DO OBJETO\n\n5.1. novo."
    with pytest.raises(regeneracao.RecorteRejeitado, match="vigente"):
        regeneracao.aplicar(sem_cinco, resposta, {5})


def test_a_substituicao_nao_se_confunde_entre_clausulas_parecidas():
    """
    Cláusulas com texto quase igual (11, 12 e 13 do TR são as três de
    pagamento). Substituir por texto, e não por posição, poderia trocar
    a errada — e o documento sairia coerente na aparência.
    """
    resposta = "## 12. PRAZO DE PAGAMENTO\n\n12.1. texto v2 da cláusula 12."
    novo = regeneracao.aplicar(TR, resposta, {12})
    fatias = regeneracao.dividir_por_clausula(novo)
    assert "v2" in fatias[12]
    assert "v1" in fatias[11] and "v1" in fatias[13]


def test_o_marcador_da_tabela_sobrevive_ao_recorte():
    """
    A tabela é injetada por código depois. Se o recorte comesse o
    marcador, o documento sairia sem a planilha.
    """
    com_marcador = TR.replace("1.1. texto v1 da cláusula 1.",
                              "1.1. texto v1.\n\n[[TABELA_ITENS]]")
    resposta = "## 5. EXECUÇÃO DO OBJETO\n\n5.1. novo."
    novo = regeneracao.aplicar(com_marcador, resposta, {5})
    assert "[[TABELA_ITENS]]" in novo


def test_instrucoes_de_recorte_nao_levam_a_tabela_de_volta():
    """
    O documento vigente viaja como referência de coerência — mas sem as
    linhas de tabela, que são o maior item da conta e que o modelo não
    pode alterar de qualquer forma.
    """
    com_tabela = TR + "\n\n" + "\n".join(
        f"| {i} | 0000{i} | Material | R$ 1,00 |" for i in range(50))
    bloco = regeneracao.instrucoes_de_recorte(
        "tr", {5}, ["prazo"], com_tabela)
    assert "| 00001 |" not in bloco
    assert "EXECUÇÃO DO OBJETO" in bloco
