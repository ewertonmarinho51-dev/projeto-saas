"""
Fase 3 da pesquisa de preços — máquina de estados e repositório.

O que este arquivo prova e o que NÃO prova, dito de saída para que
ninguém leia verde demais:

* **prova** a lógica que roda em Python — ordem dos estados, tradução
  de domínio para linha, recusa de campo que exige revisão, conversão
  de dinheiro sem `float`, e o tratamento da corrida perdida;
* **não prova** isolamento, RLS nem unicidade. Isso é do banco e está
  em `tests/test_precos_fase3_rls.py`, que roda contra um PostgreSQL de
  verdade. O cliente falso daqui EMULA os índices únicos apenas para
  exercitar o caminho de erro do Python — um fake que se apresentasse
  como prova de segurança seria pior que nenhum teste.
"""

from __future__ import annotations

import types

from datetime import date
from decimal import Decimal

import pytest

from src import db
from src.precos import estados, matching
from src.precos import repositorio as repo
from src.precos.estados import (EstadoItem, EstadoPesquisa, TransicaoInvalida,
                                estado_derivado)
from src.precos.estatistica import Estimativa
from src.precos.modelo import Fonte, Referencia, StatusReferencia
from tests.conftest import ClientePrecosFalso

# ===========================================================================
# Máquina de estados (§42) — sem banco
# ===========================================================================
def test_transicao_declarada_vale():
    assert estados.transitar_pesquisa(
        EstadoPesquisa.RASCUNHO, EstadoPesquisa.NA_FILA) is EstadoPesquisa.NA_FILA


def test_transicao_nao_declarada_e_recusada():
    with pytest.raises(TransicaoInvalida) as erro:
        estados.transitar_pesquisa(EstadoPesquisa.RASCUNHO,
                                   EstadoPesquisa.CONCLUIDA)
    # A mensagem diz o que foi tentado E o que era possível — senão o
    # servidor lê "transição inválida" e não sabe o que fazer.
    assert "draft" in str(erro.value) and "completed" in str(erro.value)
    assert "queued" in str(erro.value)


def test_reaplicar_o_mesmo_estado_e_no_op():
    """
    O repositório é idempotente. Se repetir o estado explodisse, uma
    reexecução legítima viraria erro na cara do usuário.
    """
    assert estados.transitar_pesquisa(
        EstadoPesquisa.EM_REVISAO,
        EstadoPesquisa.EM_REVISAO) is EstadoPesquisa.EM_REVISAO
    assert estados.transitar_item(
        EstadoItem.COMPLETO, EstadoItem.COMPLETO) is EstadoItem.COMPLETO


def test_pesquisa_aplicada_nao_volta_para_revisao():
    """
    O preço já entrou no processo. Editar em cima da linha que sustentou
    o ato administrativo apagaria a memória dele — mexer cria revisão
    nova (§44).
    """
    with pytest.raises(TransicaoInvalida):
        estados.transitar_pesquisa(EstadoPesquisa.APLICADA,
                                   EstadoPesquisa.EM_REVISAO)
    # Arquivar, sim.
    assert estados.pode_transitar_pesquisa(EstadoPesquisa.APLICADA,
                                           EstadoPesquisa.ARQUIVADA)


def test_arquivada_e_terminal():
    for destino in EstadoPesquisa:
        if destino is EstadoPesquisa.ARQUIVADA:
            continue
        assert not estados.pode_transitar_pesquisa(
            EstadoPesquisa.ARQUIVADA, destino), destino


def test_item_nao_pula_da_fila_para_concluido():
    """
    O defeito que a máquina existe para impedir: um item marcado
    `complete` sem que ninguém tenha pesquisado nada. O relatório diria
    "concluído", e só a auditoria descobriria.
    """
    with pytest.raises(TransicaoInvalida):
        estados.transitar_item(EstadoItem.PENDENTE, EstadoItem.COMPLETO)


def test_incompleto_nao_e_erro():
    """
    Dois desfechos diferentes com tratamento diferente: `INCOMPLETO` é
    "o mercado não tinha referência bastante" e admite revisão humana;
    `ERRO` é falha técnica e só admite nova tentativa.
    """
    assert estados.pode_transitar_item(EstadoItem.INCOMPLETO,
                                       EstadoItem.EM_REVISAO)
    assert not estados.pode_transitar_item(EstadoItem.ERRO,
                                           EstadoItem.EM_REVISAO)
    assert estados.pode_transitar_item(EstadoItem.ERRO, EstadoItem.BUSCANDO)


@pytest.mark.parametrize("itens,esperado", [
    ([], EstadoPesquisa.RASCUNHO),
    ([EstadoItem.COMPLETO, EstadoItem.PENDENTE], EstadoPesquisa.EXECUTANDO),
    ([EstadoItem.COMPLETO, EstadoItem.EM_REVISAO], EstadoPesquisa.EM_REVISAO),
    ([EstadoItem.COMPLETO, EstadoItem.ERRO], EstadoPesquisa.EM_REVISAO),
    ([EstadoItem.COMPLETO, EstadoItem.INCOMPLETO], EstadoPesquisa.PARCIAL),
    ([EstadoItem.COMPLETO, EstadoItem.COMPLETO], EstadoPesquisa.CONCLUIDA),
])
def test_o_estado_da_pesquisa_e_derivado_dos_itens(itens, esperado):
    """
    Derivado, nunca digitado. É isto que impede marcar como concluída
    uma pesquisa com dois itens em erro.
    """
    assert estado_derivado(itens) is esperado


def test_revisao_pendente_vence_parcial():
    """
    Com item aguardando decisão humana E item incompleto, o que a
    pesquisa precisa é de revisor — não de mais uma rodada de busca.
    """
    assert estado_derivado([EstadoItem.EM_REVISAO, EstadoItem.INCOMPLETO]) \
        is EstadoPesquisa.EM_REVISAO


def test_so_versiona_o_que_muda_o_resultado():
    assert estados.exige_nova_revisao({"metodologia"})
    assert estados.exige_nova_revisao({"nome", "preco_estimado"})
    # Corrigir a grafia do nome não é revisão da pesquisa.
    assert not estados.exige_nova_revisao({"nome", "objeto", "responsavel"})


# ===========================================================================
# Cliente falso — definido em `tests/conftest.py`, porque a Fase 4 usa
# o mesmo dublê. Ver lá a fronteira do que ele prova e do que não.
# ===========================================================================
@pytest.fixture
def banco(monkeypatch):
    cliente = ClientePrecosFalso()
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    # Se o repositório cair para a credencial de servidor, o teste
    # explode aqui em vez de passar em silêncio.
    monkeypatch.setattr(db, "_cliente", _proibido)
    return cliente


def _proibido(*_a, **_k):
    raise AssertionError(
        "a pesquisa de preços não pode usar a credencial de servidor")


DONO = "00000000-0000-0000-0000-00000000d0n0"


def _pesquisa(banco_falso, **extras) -> dict:
    return repo.criar_pesquisa("Material de expediente",
                               auth_user_id=DONO, **extras)


# ===========================================================================
# Repositório — identidade
# ===========================================================================
def test_sem_sessao_o_modulo_recusa_em_vez_de_usar_o_servidor(monkeypatch):
    """
    A regra da Etapa E aplicada ao módulo novo.

    Cair para `db._cliente()` transformaria a matriz de políticas
    provada no ensaio em decoração: a credencial de servidor atravessa
    o RLS por definição, e política que nunca é avaliada não protege —
    só parece proteger.
    """
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    monkeypatch.setattr(db, "_cliente", _proibido)
    with pytest.raises(repo.SemSessao):
        repo.listar_pesquisas()


def test_sem_sessao_e_um_erro_de_banco():
    """
    Herda de `ErroBanco` para que quem já trata erro de persistência não
    precise de um `except` novo — mas é uma classe própria, porque a
    interface responde com tela de login, não com incidente.
    """
    assert issubclass(repo.SemSessao, db.ErroBanco)


def test_o_modulo_nasce_desligado(monkeypatch):
    monkeypatch.setattr(db, "obter_config", lambda chave: "")
    assert repo.modulo_ativo() is False


# ===========================================================================
# Repositório — idempotência (§43)
# ===========================================================================
def test_a_pesquisa_nasce_em_rascunho(banco):
    linha = _pesquisa(banco)
    assert linha["estado"] == EstadoPesquisa.RASCUNHO.value
    assert linha["tenant_id"] == db.TENANT_PADRAO


def test_mesma_chave_de_idempotencia_devolve_a_mesma_pesquisa(banco):
    primeira = _pesquisa(banco, idempotency_key="import-2026-01")
    segunda = _pesquisa(banco, idempotency_key="import-2026-01")
    assert primeira["id"] == segunda["id"]
    assert len(banco.tabelas["pesquisas_preco"]) == 1


def test_corrida_perdida_devolve_a_linha_da_outra_aba(banco, monkeypatch):
    """
    Duas abas criando ao mesmo tempo: a checagem prévia não vê nada nas
    duas, e quem chega depois leva a violação do índice único. O
    comportamento idempotente é devolver a linha que venceu — não
    propagar o erro.
    """
    _pesquisa(banco, idempotency_key="corrida")
    # Simula a janela: a consulta prévia não encontra, o insert colide.
    chamadas = {"n": 0}
    original = repo.obter_por_chave

    def primeira_vez_cega(chave):
        chamadas["n"] += 1
        return None if chamadas["n"] == 1 else original(chave)

    monkeypatch.setattr(repo, "obter_por_chave", primeira_vez_cega)
    linha = _pesquisa(banco, idempotency_key="corrida")
    assert linha["idempotency_key"] == "corrida"
    assert len(banco.tabelas["pesquisas_preco"]) == 1


def test_sem_chave_duas_pesquisas_sao_duas_pesquisas(banco):
    """
    O índice é parcial. A criação interativa não tem chave, e duas
    pesquisas criadas na mão não podem colidir uma com a outra.
    """
    _pesquisa(banco)
    _pesquisa(banco)
    assert len(banco.tabelas["pesquisas_preco"]) == 2


def test_importar_a_mesma_planilha_duas_vezes_nao_dobra_os_itens(banco):
    """
    O caso real do projeto: 210 itens. Importar de novo deixa 210, não
    420 — a chave é (pesquisa, número).
    """
    pesquisa = _pesquisa(banco)
    itens = [{"numero": n, "descricao": f"ITEM {n}", "unidade": "UNIDADE",
              "quantidade": n} for n in range(1, 211)]
    repo.salvar_itens(pesquisa["id"], itens)
    repo.salvar_itens(pesquisa["id"], itens)
    assert len(banco.tabelas["pesquisa_preco_itens"]) == 210


def test_pesquisar_de_novo_nao_duplica_referencia(banco):
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(pesquisa["id"], [{"descricao": "CANETA"}])[0]
    referencias = [_referencia("ref-1"), _referencia("ref-2")]
    repo.registrar_referencias(item["id"], referencias)
    repo.registrar_referencias(item["id"], referencias)
    assert len(banco.tabelas["pesquisa_preco_referencias"]) == 2


def test_evento_repetido_com_a_mesma_chave_nao_derruba_a_operacao(banco):
    """
    Trilha é registro, não regra de negócio. A segunda gravação devolve
    `None` — o evento já está lá — e quem chamou segue seu caminho.
    """
    pesquisa = _pesquisa(banco)
    primeiro = repo.registrar_evento(pesquisa["id"], "busca_concluida",
                                     idempotency_key="rodada-7",
                                     automatico=True)
    segundo = repo.registrar_evento(pesquisa["id"], "busca_concluida",
                                    idempotency_key="rodada-7",
                                    automatico=True)
    assert primeiro is not None and segundo is None
    assert len(banco.tabelas["pesquisa_preco_eventos"]) == 1


# ===========================================================================
# Repositório — dinheiro e evidência
# ===========================================================================
FONTE = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
              "sistema_oficial")


def _referencia(id_externo: str, valor="12.3456") -> Referencia:
    return Referencia(
        fonte=FONTE, id_externo=id_externo,
        bruto={"id": id_externo, "preco": valor},
        descricao_original="CANETA ESFEROGRAFICA AZUL",
        unidade_original="UNIDADE",
        quantidade_original=Decimal("100"),
        valor_unitario_original=Decimal(valor),
        codigo_catalogo="236168", tipo_catalogo="CATMAT",
        uf="PA", data_compra=date(2026, 3, 14),
        unidade_normalizada="UNIDADE",
        valor_unitario_normalizado=Decimal(valor))


def _sem_float(valor, caminho="raiz"):
    """Nenhum `float` em lugar nenhum da linha — nem aninhado."""
    if isinstance(valor, float):
        raise AssertionError(f"float encontrado em {caminho}: {valor!r}")
    if isinstance(valor, dict):
        for chave, item in valor.items():
            _sem_float(item, f"{caminho}.{chave}")
    elif isinstance(valor, (list, tuple)):
        for indice, item in enumerate(valor):
            _sem_float(item, f"{caminho}[{indice}]")


def test_dinheiro_vai_para_o_banco_como_texto(banco):
    """
    `float` reintroduz o erro binário que o módulo inteiro existe para
    evitar. O Postgres converte texto para `numeric` sem perda.
    """
    linha = repo.linha_de_referencia(
        _referencia("ref-1"), tenant_id=db.TENANT_PADRAO, item_id="item-1")
    assert linha["valor_unitario_original"] == "12.3456"
    assert isinstance(linha["valor_unitario_original"], str)
    _sem_float(linha)


def test_a_evidencia_vai_junto_com_o_normalizado(banco):
    """
    §34 e §35: o bruto, o hash e o identificador oficial na mesma linha
    do valor normalizado. Sem os três, a pesquisa não se refaz depois
    que a API mudar.
    """
    referencia = _referencia("ref-1")
    linha = repo.linha_de_referencia(
        referencia, tenant_id=db.TENANT_PADRAO, item_id="item-1")
    assert linha["bruto"] == referencia.bruto
    assert linha["raw_hash"] == referencia.raw_hash
    assert linha["id_externo"] == "ref-1"
    assert linha["fonte_tipo"] == "sistema_oficial"


def test_o_score_explicado_entra_na_mesma_escrita(banco):
    """
    Score e fatores gravados junto com a referência, não numa segunda
    passada — que poderia falhar e deixar referência sem explicação.
    """
    referencia = _referencia("ref-1")
    comparabilidade = matching.comparar(
        referencia, descricao="CANETA ESFEROGRAFICA AZUL",
        codigo_catalogo="236168", uf="PA", data_base=date(2026, 4, 1))
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(pesquisa["id"], [{"descricao": "CANETA"}])[0]
    gravadas = repo.registrar_referencias(
        item["id"], [(referencia, comparabilidade)])
    linha = gravadas[0]
    assert linha["score"] == format(comparabilidade.score, "f")
    assert linha["identidade"] == format(comparabilidade.identidade, "f")
    assert [f["nome"] for f in linha["fatores"]] == [
        f.nome for f in comparabilidade.fatores]
    _sem_float(linha)


def test_a_segunda_coleta_reclassifica_mas_nao_reescreve_a_evidencia(banco):
    """
    Reexecutar pode mudar o que o motor DERIVOU (status, score). Não pode
    mudar o que a fonte DEVOLVEU na primeira coleta — é a prova.
    """
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(pesquisa["id"], [{"descricao": "CANETA"}])[0]
    original = _referencia("ref-1")
    repo.registrar_referencias(item["id"], [original])

    de_novo = _referencia("ref-1")
    de_novo.status = StatusReferencia.SELECIONADA
    repo.registrar_referencias(item["id"], [de_novo])

    linhas = banco.tabelas["pesquisa_preco_referencias"]
    assert len(linhas) == 1
    assert linhas[0]["status"] == StatusReferencia.SELECIONADA.value
    assert linhas[0]["raw_hash"] == original.raw_hash


# ===========================================================================
# Repositório — estado e versionamento
# ===========================================================================
def test_transicao_invalida_nao_chega_ao_banco(banco):
    """
    A validação vem ANTES da escrita. Se fosse depois, o banco gravaria
    e o erro apareceria com a linha já suja.
    """
    pesquisa = _pesquisa(banco)
    with pytest.raises(TransicaoInvalida):
        repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.CONCLUIDA)
    assert banco.tabelas["pesquisas_preco"][0]["estado"] == "draft"


def test_transicao_valida_grava(banco):
    pesquisa = _pesquisa(banco)
    atualizada = repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.NA_FILA)
    assert atualizada["estado"] == "queued"


def test_aplicar_carimba_a_data(banco):
    pesquisa = _pesquisa(banco)
    repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.NA_FILA)
    repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.EXECUTANDO)
    repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.EM_REVISAO)
    repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.CONCLUIDA)
    aplicada = repo.mover_pesquisa(pesquisa["id"], EstadoPesquisa.APLICADA)
    # ISO, e não a string 'now()': o corpo vai como JSON, e o Postgres
    # não converte o literal 'now()' para timestamptz.
    assert aplicada["aplicada_em"].startswith("20")
    assert "now()" not in aplicada["aplicada_em"]


def test_alterar_metodologia_por_update_e_recusado(banco):
    """
    §44: o que muda o resultado cria revisão. A recusa aponta o caminho
    certo em vez de apenas negar.
    """
    pesquisa = _pesquisa(banco)
    with pytest.raises(ValueError) as erro:
        repo.atualizar_pesquisa(pesquisa["id"], metodologia="mediana")
    assert "revisar" in str(erro.value)


def test_corrigir_o_nome_nao_exige_revisao(banco):
    pesquisa = _pesquisa(banco)
    linha = repo.atualizar_pesquisa(pesquisa["id"],
                                    nome="Material de expediente 2026")
    assert linha["nome"] == "Material de expediente 2026"


def test_escrever_o_estado_direto_e_recusado(banco):
    """
    O buraco que a lista de PERMITIDOS fecha.

    `estado` não está entre os campos que versionam, então uma lista de
    proibidos o deixaria passar — e escrevê-lo por aqui pularia a
    máquina de estados inteira. A recusa aponta `mover_pesquisa`.
    """
    pesquisa = _pesquisa(banco)
    with pytest.raises(ValueError) as erro:
        repo.atualizar_pesquisa(pesquisa["id"], estado="completed")
    assert "mover_pesquisa" in str(erro.value)
    assert banco.tabelas["pesquisas_preco"][0]["estado"] == "draft"


def test_campo_derivado_nao_se_digita(banco):
    """
    `valor_global` é a soma dos itens. Digitá-lo faria o total divergir
    do que o sustenta — e o relatório mostraria os dois.
    """
    pesquisa = _pesquisa(banco)
    with pytest.raises(ValueError) as erro:
        repo.atualizar_pesquisa(pesquisa["id"], valor_global="999999.00")
    assert "não é campo editável" in str(erro.value)


def test_vincular_a_um_processo_depois_e_permitido(banco):
    """§17-B: a pesquisa autônoma pode ganhar processo mais tarde."""
    pesquisa = _pesquisa(banco)
    linha = repo.atualizar_pesquisa(pesquisa["id"], processo_id="proc-1")
    assert linha["processo_id"] == "proc-1"


def test_revisar_delega_a_copia_ao_banco(banco):
    """
    ~6.300 referências não atravessam a rede para serem reescritas: a
    cópia é uma transação só, dentro do Postgres.
    """
    pesquisa = _pesquisa(banco)
    novo_id = repo.revisar(pesquisa["id"], "troca de metodologia")
    assert banco.rpcs == [("revisar_pesquisa_preco",
                           {"p_pesquisa": pesquisa["id"],
                            "p_motivo": "troca de metodologia"})]
    assert novo_id


# ===========================================================================
# Repositório — item e referência
# ===========================================================================
def _estimativa(valor, status, memoria) -> Estimativa:
    return Estimativa(
        valor_unitario=valor, metodo="mediana", status=status,
        estatisticas=None,
        cesta=types.SimpleNamespace(selecionadas=[], descartadas=[],
                                    motivos=[]),
        memoria=memoria)


def test_a_cesta_que_nao_fecha_vira_incompleta_e_nao_revisao(banco):
    """
    Quem decide o estado é a `Estimativa`, não quem chama. Mandar para
    revisão um item sem cesta defensável apresentaria ao servidor algo
    para aprovar onde não há preço nenhum.
    """
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(pesquisa["id"], [{"descricao": "CANETA"}])[0]
    repo.mover_item(item["id"], EstadoItem.BUSCANDO, EstadoItem.PENDENTE)

    linha = repo.registrar_estimativa(
        item["id"], _estimativa(None, "INCOMPLETO",
                                ["apenas 1 referência defensável"]),
        atual=EstadoItem.BUSCANDO)
    assert linha["estado"] == EstadoItem.INCOMPLETO.value
    assert linha["preco_estimado"] is None
    assert "apenas 1 referência" in linha["justificativa"]


def test_o_motor_calcula_e_para_na_revisao(banco):
    """
    O ponto que a máquina de estados fez aparecer: o cálculo terminado
    NÃO conclui o item.

    `matching → complete` não existe. Quem conclui é a pessoa que olhou
    a cesta, os discrepantes e a memória (§20) — senão a pesquisa sai
    "concluída" sem que ninguém a tenha lido.
    """
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(
        pesquisa["id"], [{"descricao": "CANETA", "quantidade": 100}])[0]
    repo.mover_item(item["id"], EstadoItem.BUSCANDO, EstadoItem.PENDENTE)
    repo.mover_item(item["id"], EstadoItem.CLASSIFICANDO, EstadoItem.BUSCANDO)

    linha = repo.registrar_estimativa(
        item["id"], _estimativa(Decimal("2.35"), "CONCLUIDO",
                                ["mediana de 30 referências"]),
        atual=EstadoItem.CLASSIFICANDO, quantidade=Decimal("100"))
    assert linha["estado"] == EstadoItem.EM_REVISAO.value

    # O preço e o estado foram na MESMA escrita: dois writes deixariam
    # uma janela em que o item está em revisão sem preço para revisar.
    assert linha["preco_estimado"] == "2.35"
    assert linha["preco_total"] == "235.00"
    assert linha["metodo"] in ("media", "mediana", "menor", "manual")

    confirmado = repo.confirmar_item(
        item["id"], atual=EstadoItem.EM_REVISAO,
        justificativa="cesta conferida; discrepantes mantidos com motivo")
    assert confirmado["estado"] == EstadoItem.COMPLETO.value
    assert "discrepantes mantidos" in confirmado["justificativa"]


def test_excluir_referencia_exige_motivo(banco):
    """
    A 0021 não concede DELETE a ninguém: excluir é mudar status. E
    mudar status sem dizer por quê seria exclusão silenciosa com outro
    nome.
    """
    with pytest.raises(ValueError):
        repo.reclassificar_referencia("qualquer", "rejected", "   ")


def test_excluir_referencia_acumula_o_motivo(banco):
    pesquisa = _pesquisa(banco)
    item = repo.salvar_itens(pesquisa["id"], [{"descricao": "CANETA"}])[0]
    referencia = repo.registrar_referencias(
        item["id"], [_referencia("ref-1")])[0]
    linha = repo.reclassificar_referencia(
        referencia["id"], "rejected", "preço fora da curva")
    assert linha["status"] == "rejected"
    assert "preço fora da curva" in linha["motivos"]
