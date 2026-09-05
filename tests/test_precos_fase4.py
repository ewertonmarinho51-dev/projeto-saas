"""
Fase 4 da pesquisa de preços — execução em lotes, filtros e interface.

A divisão é deliberada: o motor de execução e os filtros são **lógica
pura**, testados sem Streamlit e sem rede; a interface é testada por
AppTest, e só naquilo que é contrato (a porta de entrada, o que a tela
diz quando falta sessão, e o fato de o módulo nascer invisível).

O que este arquivo NÃO tenta provar: o desenho da tela. Asserção sobre
DOM do Streamlit quebra a cada versão e não protege nada que importe.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from src import db
from src.precos import execucao, filtros as filtros_mod
from src.precos.estados import EstadoItem, EstadoPesquisa
from src.precos.fontes import Consulta, ResultadoBusca
from src.precos.modelo import Fonte, Referencia
from src.precos import repositorio as repo
from tests.conftest import ClientePrecosFalso

APP = str(Path(__file__).resolve().parents[1] / "app.py")

FONTE_OFICIAL = Fonte("compras_gov_precos", "Compras.gov — preços praticados",
                      "sistema_oficial")
FONTE_SIMILAR = Fonte("pncp", "PNCP", "contratacao_similar")


# ===========================================================================
# Progresso e fila
# ===========================================================================
def _item(numero: int, estado: str = EstadoItem.PENDENTE.value,
          **extras) -> dict:
    return {"id": f"item-{numero}", "numero": numero, "estado": estado,
            "descricao": f"ITEM {numero}", "unidade": "UNIDADE",
            "quantidade": "100", **extras}


def test_progresso_conta_cada_estado():
    itens = [
        _item(1, EstadoItem.COMPLETO.value),
        _item(2, EstadoItem.INCOMPLETO.value),
        _item(3, EstadoItem.EM_REVISAO.value),
        _item(4, EstadoItem.ERRO.value),
        _item(5),
    ]
    p = execucao.progresso_de(itens)
    assert (p.total, p.concluidos, p.incompletos, p.em_revisao,
            p.com_erro, p.pendentes) == (5, 1, 1, 1, 1, 1)
    assert not p.terminou
    assert p.processados == 4


def test_pesquisa_sem_item_esta_completa_e_nao_zerada():
    """
    `0/0` é 100%, não 0%. Uma barra parada em zero para uma pesquisa sem
    item faria parecer que algo travou.
    """
    p = execucao.progresso_de([])
    assert p.fracao == 1.0 and p.terminou


def test_a_fila_respeita_a_ordem_da_planilha():
    itens = [_item(3), _item(1), _item(2)]
    assert [i["numero"] for i in execucao.proximo_lote(itens, 3)] == [1, 2, 3]


def test_a_fila_pega_erro_e_deixa_incompleto_de_fora():
    """
    A distinção que o §19 exige: `error` é falha técnica e volta para a
    fila (retry); `incomplete` já rodou e o mercado não tinha referência
    bastante — refazer sozinho gastaria a API para chegar ao mesmo
    lugar. Repetir um incompleto é decisão do revisor.
    """
    itens = [_item(1, EstadoItem.ERRO.value),
             _item(2, EstadoItem.INCOMPLETO.value),
             _item(3, EstadoItem.COMPLETO.value),
             _item(4, EstadoItem.PENDENTE.value)]
    assert [i["numero"] for i in execucao.proximo_lote(itens, 10)] == [1, 4]


def test_o_lote_e_pequeno_de_proposito():
    itens = [_item(n) for n in range(1, 51)]
    assert len(execucao.proximo_lote(itens)) == execucao.LOTE_PADRAO
    # Nunca zero: um tamanho inválido travaria a execução para sempre.
    assert len(execucao.proximo_lote(itens, 0)) == 1


# ===========================================================================
# Consulta derivada do item
# ===========================================================================
def test_a_janela_temporal_e_da_pesquisa_e_nao_da_fonte():
    hoje = date(2026, 9, 1)
    consulta = execucao.consulta_do_item(
        _item(1), {"data_base": hoje, "janela_dias": 180})
    assert consulta.data_final == hoje
    assert consulta.data_inicial == hoje - timedelta(days=180)


def test_catser_vira_consulta_de_servico():
    consulta = execucao.consulta_do_item(
        _item(1, codigo="123", tipo_catalogo="CATSER"))
    assert consulta.material_ou_servico == "S"
    assert consulta.codigo_catalogo == "123"


def test_item_sem_codigo_ainda_consulta():
    """A decisão de produto: CATMAT é aceito, nunca exigido."""
    consulta = execucao.consulta_do_item(_item(1))
    assert consulta.codigo_catalogo is None
    assert consulta.descricao == "ITEM 1"
    assert consulta.material_ou_servico == "M"


# ===========================================================================
# Pipeline de um item
# ===========================================================================
class _FonteFalsa:
    def __init__(self, fonte: Fonte, referencias=None, explode=False):
        self.fonte = fonte
        self._referencias = referencias or []
        self._explode = explode
        self.chamadas = 0

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        self.chamadas += 1
        if self._explode:
            raise RuntimeError("timeout")
        return ResultadoBusca(fonte=self.fonte,
                              referencias=list(self._referencias))


def _referencia(fonte: Fonte, id_externo: str, valor: str,
                descricao="CANETA ESFEROGRAFICA AZUL") -> Referencia:
    return Referencia(
        fonte=fonte, id_externo=id_externo,
        bruto={"id": id_externo, "valor": valor},
        descricao_original=descricao, unidade_original="UNIDADE",
        quantidade_original=Decimal("100"),
        valor_unitario_original=Decimal(valor),
        uf="PA", data_compra=date(2026, 6, 1))


def test_uma_fonte_fora_do_ar_nao_derruba_o_item():
    """
    §37: falha de uma fonte não derruba a pesquisa. A ocorrência é
    registrada e o item segue com as demais.
    """
    viva = _FonteFalsa(FONTE_OFICIAL, [
        _referencia(FONTE_OFICIAL, f"r{n}", str(10 + n)) for n in range(5)])
    morta = _FonteFalsa(FONTE_SIMILAR, explode=True)

    resultado = execucao.pesquisar_item(
        _item(1, descricao="CANETA ESFEROGRAFICA AZUL"), [viva, morta])

    assert not resultado.falhou
    assert resultado.encontradas == 5
    assert any("PNCP" in o for o in resultado.ocorrencias)
    assert resultado.estimativa is not None


def test_todas_as_fontes_fora_do_ar_e_erro_tecnico_e_nao_incompleto():
    """
    A distinção que decide se o item volta para a fila. "Nenhuma fonte
    respondeu" é problema nosso e se repete; "o mercado não tinha o
    item" é resposta e não se repete sozinha.
    """
    resultado = execucao.pesquisar_item(
        _item(1), [_FonteFalsa(FONTE_OFICIAL, explode=True),
                   _FonteFalsa(FONTE_SIMILAR, explode=True)])
    assert resultado.falhou
    assert resultado.estimativa is None


def test_referencia_repetida_entre_fontes_conta_uma_vez():
    repetida = _referencia(FONTE_OFICIAL, "mesmo-id", "12.00")
    outra = _referencia(FONTE_OFICIAL, "mesmo-id", "12.00")
    resultado = execucao.pesquisar_item(
        _item(1), [_FonteFalsa(FONTE_OFICIAL, [repetida]),
                   _FonteFalsa(FONTE_OFICIAL, [outra])])
    assert resultado.encontradas == 1


def test_a_estimativa_sai_incompleta_em_vez_de_inventar_preco():
    """A regra dos três: nunca se fabrica a referência que falta."""
    resultado = execucao.pesquisar_item(
        _item(1, descricao="CANETA ESFEROGRAFICA AZUL"),
        [_FonteFalsa(FONTE_OFICIAL,
                     [_referencia(FONTE_OFICIAL, "r1", "12.00")])])
    assert resultado.estimativa is not None
    assert not resultado.estimativa.concluida
    assert any("defensável" in m or "referência" in m
               for m in resultado.estimativa.memoria)


# ===========================================================================
# Rodada com persistência
# ===========================================================================
class _RepositorioFalso:
    """
    Dublê do repositório com a ORDEM das escritas registrada.

    A ordem é o que este teste mede: se a estimativa fosse gravada antes
    das referências, uma queda no meio deixaria um item com preço e sem
    a amostra que o sustenta.
    """

    def __init__(self, itens: list[dict]):
        self.itens = {str(i["id"]): dict(i) for i in itens}
        self.chamadas: list[tuple] = []
        self.referencias: dict[str, list] = {}

    def mover_item(self, item_id, destino, atual, **campos):
        self.chamadas.append(("mover", item_id, destino.value))
        linha = self.itens[str(item_id)]
        linha.update(campos)
        linha["estado"] = destino.value
        return linha

    def registrar_referencias(self, item_id, coletadas):
        self.chamadas.append(("referencias", item_id, len(coletadas)))
        self.referencias.setdefault(str(item_id), [])
        # Emula a chave única (item, fonte, id externo): reexecutar não
        # duplica.
        vistas = {(r.fonte.id, r.id_externo)
                  for r in self.referencias[str(item_id)]}
        for entrada in coletadas:
            ref = entrada[0] if isinstance(entrada, tuple) else entrada
            if (ref.fonte.id, ref.id_externo) not in vistas:
                self.referencias[str(item_id)].append(ref)
                vistas.add((ref.fonte.id, ref.id_externo))
        return self.referencias[str(item_id)]

    def registrar_estimativa(self, item_id, estimativa, *, atual,
                             quantidade=None):
        self.chamadas.append(("estimativa", item_id,
                              estimativa.status if estimativa else None))
        destino = (EstadoItem.EM_REVISAO if estimativa.concluida
                   else EstadoItem.INCOMPLETO)
        linha = self.itens[str(item_id)]
        linha["estado"] = destino.value
        linha["preco_estimado"] = estimativa.valor_unitario
        return linha


def _com_amostra(n: int) -> _FonteFalsa:
    return _FonteFalsa(FONTE_OFICIAL, [
        _referencia(FONTE_OFICIAL, f"r{i}", str(10 + i)) for i in range(n)])


def test_a_ordem_das_escritas_protege_o_checkpoint():
    itens = [_item(1, descricao="CANETA ESFEROGRAFICA AZUL")]
    repositorio = _RepositorioFalso(itens)
    execucao.executar_lote({"filtros": {}}, itens, [_com_amostra(5)],
                           repositorio)

    tipos = [c[0] for c in repositorio.chamadas]
    # buscando → referências → classificando → estimativa
    assert tipos == ["mover", "referencias", "mover", "estimativa"]
    assert repositorio.chamadas[0][2] == EstadoItem.BUSCANDO.value
    assert repositorio.chamadas[2][2] == EstadoItem.CLASSIFICANDO.value


def test_reexecutar_o_lote_nao_dobra_a_amostra():
    """
    §43 na prática: a segunda rodada faz `upsert` e a amostra continua
    do mesmo tamanho. Se dobrasse, a estatística dobraria com ela.
    """
    itens = [_item(1, descricao="CANETA ESFEROGRAFICA AZUL")]
    repositorio = _RepositorioFalso(itens)
    fonte = _com_amostra(5)

    execucao.executar_lote({"filtros": {}}, itens, [fonte], repositorio)
    # devolve o item para a fila e roda de novo
    itens[0]["estado"] = EstadoItem.PENDENTE.value
    repositorio.itens["item-1"]["estado"] = EstadoItem.PENDENTE.value
    execucao.executar_lote({"filtros": {}}, itens, [fonte], repositorio)

    assert len(repositorio.referencias["item-1"]) == 5


def test_um_item_ruim_nao_para_o_lote():
    """
    Numa pesquisa de 210 itens, um item que explode não pode levar os
    outros 209 junto.
    """
    itens = [_item(1), _item(2), _item(3)]
    repositorio = _RepositorioFalso(itens)

    original = repositorio.registrar_estimativa

    def quebra_no_dois(item_id, estimativa, **kwargs):
        if str(item_id) == "item-2":
            raise RuntimeError("falha de gravação")
        return original(item_id, estimativa, **kwargs)

    repositorio.registrar_estimativa = quebra_no_dois

    progresso, relato = execucao.executar_lote(
        {"filtros": {}}, itens, [_com_amostra(5)], repositorio)

    assert repositorio.itens["item-2"]["estado"] == EstadoItem.ERRO.value
    assert repositorio.itens["item-1"]["estado"] != EstadoItem.ERRO.value
    assert repositorio.itens["item-3"]["estado"] != EstadoItem.ERRO.value
    assert len(relato) == 3
    assert progresso.com_erro == 1


def test_o_relato_tem_a_forma_pedida_no_prompt():
    """`Item 01  ✓  8 preços encontrados` — item, marca, contagem."""
    itens = [_item(1, descricao="CANETA ESFEROGRAFICA AZUL")]
    _, relato = execucao.executar_lote(
        {"filtros": {}}, itens, [_com_amostra(8)], _RepositorioFalso(itens))
    assert relato[0].startswith("Item 01")
    assert "✓" in relato[0] or "!" in relato[0]
    assert "8 referência(s)" in relato[0]


def test_o_estado_da_pesquisa_sai_dos_itens():
    assert execucao.estado_apos_lote(
        [_item(1, EstadoItem.COMPLETO.value)]) is EstadoPesquisa.CONCLUIDA
    assert execucao.estado_apos_lote(
        [_item(1, EstadoItem.PENDENTE.value)]) is EstadoPesquisa.EXECUTANDO
    assert execucao.estado_apos_lote(
        [_item(1, EstadoItem.INCOMPLETO.value)]) is EstadoPesquisa.PARCIAL


# ===========================================================================
# Filtros (§20)
# ===========================================================================
def _linha(**extras) -> dict:
    base = {
        "id": "ref-1", "fonte_id": "compras_gov_precos",
        "fonte_nome": "Compras.gov", "status": "selected",
        "descricao_original": "CANETA ESFEROGRAFICA AZUL",
        "unidade_original": "UNIDADE", "unidade_normalizada": "UNIDADE",
        "quantidade_original": "100", "uf": "PA",
        "data_resultado": "2026-06-01", "score": "0.82",
        "orgao": "PREFEITURA", "fornecedor": "PAPELARIA LTDA",
        "tipo_catalogo": "CATMAT", "codigo_catalogo": "236168",
    }
    base.update(extras)
    return base


def test_filtro_vazio_devolve_tudo_numa_lista_nova():
    linhas = [_linha(), _linha(id="ref-2")]
    resultado = filtros_mod.aplicar(linhas, filtros_mod.Filtros())
    assert resultado == linhas
    assert resultado is not linhas   # esconde, nunca apaga


def test_campo_em_branco_nao_zera_a_lista():
    """
    Uma tela que some com tudo porque o servidor não escolheu UF parece
    quebrada. Branco significa "não me importo".
    """
    linhas = [_linha()]
    assert filtros_mod.aplicar(linhas, filtros_mod.Filtros(uf="")) == linhas


@pytest.mark.parametrize("filtro,passa", [
    (filtros_mod.Filtros(uf="PA"), True),
    (filtros_mod.Filtros(uf="sp"), False),
    (filtros_mod.Filtros(status={"selected"}), True),
    (filtros_mod.Filtros(status={"rejected"}), False),
    (filtros_mod.Filtros(fontes={"compras_gov_precos"}), True),
    (filtros_mod.Filtros(fontes={"pncp"}), False),
    (filtros_mod.Filtros(tipo_catalogo="CATMAT"), True),
    (filtros_mod.Filtros(tipo_catalogo="CATSER"), False),
    (filtros_mod.Filtros(texto="papelaria"), True),
    (filtros_mod.Filtros(texto="grampeador"), False),
    (filtros_mod.Filtros(quantidade_minima=Decimal("50")), True),
    (filtros_mod.Filtros(quantidade_minima=Decimal("500")), False),
    (filtros_mod.Filtros(somente_alta_compatibilidade=True), True),
])
def test_cada_criterio_isola_o_que_promete(filtro, passa):
    assert bool(filtros_mod.aplicar([_linha()], filtro)) is passa


def test_alta_compatibilidade_corta_acima_do_piso_da_cesta():
    """
    O corte do filtro é mais exigente que o da cesta automática (0,5):
    aqui é quem quer olhar só o que é claramente comparável.
    """
    quase = _linha(score="0.60")
    filtro = filtros_mod.Filtros(somente_alta_compatibilidade=True)
    assert filtros_mod.aplicar([quase], filtro) == []


def test_a_unidade_encontra_tambem_a_referencia_nao_convertida():
    """
    Referência cuja unidade não pôde ser convertida fica com a original.
    Se o filtro olhasse só a normalizada, ela sumiria justamente do
    filtro em que o revisor a procura.
    """
    nao_convertida = _linha(unidade_normalizada=None, unidade_original="CAIXA")
    filtro = filtros_mod.Filtros(unidade="caixa")
    assert filtros_mod.aplicar([nao_convertida], filtro) == [nao_convertida]


def test_referencia_sem_data_so_cai_no_filtro_de_periodo():
    sem_data = _linha(data_resultado=None, data_compra=None)
    periodo = filtros_mod.Filtros(desde=date(2026, 1, 1))
    assert filtros_mod.aplicar([sem_data], periodo) == []
    # …e continua visível em qualquer outro recorte
    assert filtros_mod.aplicar([sem_data],
                               filtros_mod.Filtros(uf="PA")) == [sem_data]


def test_a_contagem_e_da_lista_inteira_e_nao_da_filtrada():
    """
    §21: nunca esconder os descartados. O contador precisa dizer que há
    9 excluídas mesmo quando a tela mostra só as da cesta.
    """
    linhas = [_linha(), *[_linha(id=f"r{n}", status="rejected")
                          for n in range(9)]]
    contagem = filtros_mod.contar_por_status(linhas)
    assert contagem["selected"] == 1 and contagem["rejected"] == 9


def test_os_seletores_saem_do_que_existe():
    linhas = [_linha(), _linha(id="r2", uf="SP", fonte_id="pncp",
                               fonte_nome="PNCP", unidade_normalizada="CAIXA")]
    assert filtros_mod.ufs_presentes(linhas) == ["PA", "SP"]
    assert dict(filtros_mod.fontes_presentes(linhas))["pncp"] == "PNCP"
    assert "CAIXA" in filtros_mod.unidades_presentes(linhas)


# ===========================================================================
# Interface
# ===========================================================================
def test_o_modulo_nasce_invisivel(monkeypatch):
    """
    §40: implementar não é ativar. Com a flag desligada, a navegação do
    app continua exatamente como antes.
    """
    from src.ui import precos_ui

    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)
    assert precos_ui.disponivel() is False


def test_a_flag_usa_a_convencao_do_projeto():
    """
    A auditoria da Fase 0 registrou a convenção: constante em
    `governanca.py`, valor inglês em snake_case. A Fase 3 nasceu fora
    dela e foi corrigida antes de a interface existir.
    """
    from src import governanca

    assert repo.FLAG == governanca.FLAG_PESQUISA_PRECOS == "price_research"


def _como_servidor_comum(monkeypatch, flag_ligada: bool) -> AppTest:
    """
    Cenário de SERVIDOR COMUM de verdade.

    Nada de `GOVDOCS_MODO_ABERTO` aqui: em modo aberto `eh_admin()`
    devolve True para todo mundo, e o teste acabaria medindo o ramo do
    administrador achando que media o do servidor. A primeira versão
    desta prova caía nisso — passava mesmo com o ramo do servidor
    comum desligado.
    """
    from src import auth

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(auth, "tem_admin", lambda: True)
    monkeypatch.setattr(
        db, "flag_ativa", lambda nome: flag_ligada and nome == repo.FLAG)
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["usuario"] = {
        "id": "u1", "nome": "Servidor Comum", "login": "servidor",
        "papel": "usuario",
    }
    return at


def test_com_a_flag_ligada_o_servidor_comum_alcanca_o_modulo(monkeypatch):
    """
    A pesquisa é de quem elabora o processo, não do administrador. Se o
    módulo só aparecesse para admin, quem precisa dele não chegaria lá.
    """
    at = _como_servidor_comum(monkeypatch, flag_ligada=True)
    at.run()

    assert not at.exception
    navegacao = [r for r in at.radio if r.key == "pagina"]
    assert navegacao, "servidor comum deveria ter navegação com o módulo"
    assert "Pesquisa de Preços" in navegacao[0].options
    # E continua sem as páginas de administração.
    assert "Administração" not in navegacao[0].options
    assert "Base de Conhecimento" not in navegacao[0].options


def test_com_a_flag_desligada_o_servidor_comum_nao_ganha_navegacao(monkeypatch):
    """
    A regressão que o `test_auth` já protege, medida também aqui: sem a
    flag, a sidebar do servidor comum é exatamente a de antes.
    """
    at = _como_servidor_comum(monkeypatch, flag_ligada=False)
    at.run()

    assert not at.exception
    assert not [r for r in at.radio if r.key == "pagina"]


def test_sem_sessao_a_tela_explica_em_vez_de_mostrar_lista_vazia(monkeypatch):
    """
    O repositório recusa a credencial de servidor. A interface não pode
    disfarçar essa recusa com uma lista vazia — lista vazia por falta de
    permissão é a pior tela possível: parece que não há nada, quando na
    verdade não se pode ver.
    """
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.run()

    assert not at.exception
    textos = " ".join(i.value for i in at.info)
    assert "identidade" in textos.lower() or "entre no sistema" in textos.lower()


def test_com_sessao_a_lista_abre(monkeypatch):
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.run()

    assert not at.exception
    titulos = " ".join(s.value for s in at.subheader)
    assert "Pesquisa de Preços" in titulos
    # sem pesquisa nenhuma, o recado é "nenhuma pesquisa", não erro
    legendas = " ".join(c.value for c in at.caption)
    assert "Nenhuma pesquisa" in legendas


def test_a_flag_desligada_devolve_o_wizard(monkeypatch):
    """
    Alguém desliga a flag com a página apontada para o módulo: o app
    volta ao wizard em vez de mostrar tela em branco.
    """
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda _nome: False)

    at = AppTest.from_file(APP, default_timeout=60)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.run()

    assert not at.exception
    assert at.session_state["pagina"] == "Novo processo"
    titulos = " ".join(s.value for s in at.subheader)
    assert "Formulário Matriz" in titulos


# ===========================================================================
# Fumaça das telas internas
#
# As quatro telas de dentro do módulo — itens, execução, revisão e
# resumo — são a maior parte do código da Fase 4, e nenhuma das provas
# acima chega a elas. Um render com dados semeados não valida desenho,
# mas pega o que mais dói: atributo inexistente, chave errada, `None`
# onde o código esperava número.
# ===========================================================================
def _semear(cliente: ClientePrecosFalso) -> dict:
    """Uma pesquisa com um item pesquisado e duas referências."""
    pesquisa = {
        "id": "pesq-1", "tenant_id": db.TENANT_PADRAO,
        "auth_user_id": "u-1", "nome": "Material de expediente",
        "objeto": "Aquisição de material", "estado": EstadoPesquisa.EM_REVISAO.value,
        "versao": 1, "perfil_normativo": "lei_14133",
        "filtros": {}, "valor_global": "1235.00", "processo_id": None,
    }
    item = {
        "id": "item-1", "pesquisa_id": "pesq-1", "tenant_id": db.TENANT_PADRAO,
        "numero": 1, "descricao": "CANETA ESFEROGRAFICA AZUL",
        "unidade": "UNIDADE", "quantidade": "100",
        "estado": EstadoItem.EM_REVISAO.value, "metodo": "mediana",
        "preco_estimado": "12.35", "preco_total": "1235.00",
        "justificativa": "mediana de 2 referências",
        "estatisticas": {
            "estatisticas": {"quantidade": 2, "menor": "12.00",
                             "maior": "12.70", "media": "12.35",
                             "mediana": "12.35",
                             "coeficiente_variacao": "0.03"},
            "anomalias": [{"valor": "83.90", "criterio": "IQR",
                           "motivo": "321% acima da mediana"}],
        },
    }
    referencias = [{
        "id": f"ref-{n}", "item_id": "item-1", "tenant_id": db.TENANT_PADRAO,
        "fonte_id": "compras_gov_precos", "fonte_nome": "Compras.gov",
        "fonte_tipo": "sistema_oficial", "id_externo": f"e{n}",
        "raw_hash": "abc123", "status": "selected" if n == 0 else "rejected",
        "descricao_original": "CANETA ESFEROGRAFICA AZUL",
        "unidade_original": "UNIDADE", "unidade_normalizada": "UNIDADE",
        "quantidade_original": "100", "valor_unitario_original": "12.00",
        "valor_unitario_normalizado": "12.00", "uf": "PA",
        "orgao": "PREFEITURA", "fornecedor": "PAPELARIA LTDA",
        "data_resultado": "2026-06-01", "score": "0.82",
        "identidade": "0.90", "circunstancias": "0.91",
        "fatores": [{"nome": "unidade", "peso": "0.45", "score": "1",
                     "explicacao": "mesma unidade", "conforme": True}],
        "motivos": [], "bruto": {}, "coletado_em": "2026-09-01T10:00:00",
        "codigo_catalogo": "236168", "tipo_catalogo": "CATMAT",
    } for n in range(2)]

    cliente.tabelas["pesquisas_preco"] = [pesquisa]
    cliente.tabelas["pesquisa_preco_itens"] = [item]
    cliente.tabelas["pesquisa_preco_referencias"] = referencias
    cliente.tabelas["pesquisa_preco_eventos"] = []
    return pesquisa


def _app_com_dados(monkeypatch, tela: str, **sessao) -> AppTest:
    from src.ui import precos_ui

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    _semear(cliente)
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    # Nenhuma chamada de rede nos testes: as fontes são dublês.
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_com_amostra(4)])

    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.session_state[precos_ui.TELA] = tela
    at.session_state[precos_ui.PESQUISA] = "pesq-1"
    for chave, valor in sessao.items():
        at.session_state[chave] = valor
    return at


def test_a_tela_de_itens_renderiza(monkeypatch):
    at = _app_com_dados(monkeypatch, "itens")
    at.run()
    assert not at.exception
    corpo = " ".join(str(m.value) for m in at.markdown)
    assert "CANETA ESFEROGRAFICA AZUL" in corpo


def test_a_tela_de_revisao_mostra_cesta_descartados_e_anomalia(monkeypatch):
    """
    §21 e §23 na mesma tela: as descartadas continuam listadas, e o
    discrepante é sinalizado sem virar acusação.
    """
    from src.ui import precos_ui

    at = _app_com_dados(monkeypatch, "revisao", **{precos_ui.ITEM: "item-1"})
    at.run()
    assert not at.exception

    corpo = " ".join(str(m.value) for m in at.markdown)
    assert "1" in corpo and "cesta" in corpo.lower()

    avisos = " ".join(w.value for w in at.warning)
    assert "discrepante" in avisos
    # O texto sinaliza; NÃO conclui juridicamente. A checagem procura a
    # forma AFIRMATIVA, não a palavra solta: desde a Fase 7 o GovBot usa
    # "inexequível" justamente para negá-la ("não afirma que o preço seja
    # inexequível nem irregular"), e um `not in` cru reprovaria o texto
    # correto — que é o oposto do que este teste defende.
    tudo = (corpo + avisos + " ".join(str(c.value) for c in at.caption)
            + " ".join(str(e.value) for e in at.error)
            + " ".join(str(i.value) for i in at.info)).lower()
    for afirmacao in (r"\bé inexequível", r"\bé ilegal", r"\bé irregular",
                      r"\bpreço irregular", r"\bsuperfaturad"):
        assert not re.search(afirmacao, tudo), (
            f"a tela conclui juridicamente: {afirmacao}")


def test_o_resumo_nao_soma_item_sem_preco(monkeypatch):
    """
    §25: o valor global é dos concluídos. Somar o pendente produziria um
    total que parece completo e não é.
    """
    at = _app_com_dados(monkeypatch, "resumo")
    at.run()
    assert not at.exception
    # o item semeado está em REVISÃO, não concluído: não entra na soma
    metricas = {m.label: m.value for m in at.metric}
    assert metricas.get("Valor global estimado") in ("R$ 0,00", "—")
    avisos = " ".join(w.value for w in at.warning)
    assert "sem preço formado" in avisos


def test_valor_global_soma_so_o_concluido():
    """A regra do resumo, isolada do Streamlit."""
    itens = [
        {"numero": 1, "estado": EstadoItem.COMPLETO.value,
         "preco_total": "100.00"},
        {"numero": 2, "estado": EstadoItem.EM_REVISAO.value,
         "preco_total": "999.00"},
        {"numero": 3, "estado": EstadoItem.INCOMPLETO.value,
         "preco_total": None},
    ]
    from src.ui import precos_ui

    total, sem_preco = precos_ui._valor_global(itens)
    assert total == Decimal("100.00")
    assert sem_preco == [2, 3]


def test_a_execucao_roda_um_lote_e_devolve_o_controle(monkeypatch):
    """
    O coração do §46: a tela não congela. Cada script run processa um
    lote, grava e chama `st.rerun()` — e a rodada TERMINA sozinha
    quando a fila esvazia, em vez de girar para sempre.

    Se este teste estourar o tempo, é porque o laço deixou de convergir
    — que é exatamente o defeito que ele existe para pegar.
    """
    from src.ui import precos_ui

    # O item semeado já está em revisão: a fila nasce vazia, e o que se
    # mede aqui é o ENCERRAMENTO — a tela reconhecer que não há mais
    # trabalho e sair, em vez de reenfileirar para sempre.
    at = _app_com_dados(monkeypatch, "execucao")
    at.run()
    assert not at.exception

    # A fila esvaziou e a tela devolveu o usuário aos itens.
    assert at.session_state[precos_ui.TELA] == precos_ui.ITENS


def test_a_execucao_processa_o_item_pendente(monkeypatch):
    """
    Mesma tela, com item PENDENTE de verdade: ao fim da rodada ele saiu
    da fila e ganhou preço — sem nenhuma chamada de rede.
    """
    from src.ui import precos_ui

    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    monkeypatch.setattr(db, "flag_ativa", lambda nome: nome == repo.FLAG)
    cliente = ClientePrecosFalso()
    _semear(cliente)
    cliente.tabelas["pesquisa_preco_itens"][0]["estado"] = \
        EstadoItem.PENDENTE.value
    cliente.tabelas["pesquisa_preco_referencias"] = []
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    monkeypatch.setattr(precos_ui, "_fontes", lambda: [_com_amostra(6)])

    at = AppTest.from_file(APP, default_timeout=90)
    at.secrets["SUPABASE_URL"] = ""
    at.secrets["SUPABASE_KEY"] = ""
    at.session_state["pagina"] = "Pesquisa de Preços"
    at.session_state[precos_ui.TELA] = precos_ui.EXECUCAO
    at.session_state[precos_ui.PESQUISA] = "pesq-1"
    at.run()

    assert not at.exception
    item = cliente.tabelas["pesquisa_preco_itens"][0]
    assert item["estado"] not in (EstadoItem.PENDENTE.value,
                                  EstadoItem.BUSCANDO.value)
    # as referências coletadas foram persistidas
    assert len(cliente.tabelas["pesquisa_preco_referencias"]) == 6


def test_duplicar_cria_pesquisa_nova_sem_herdar_preco(monkeypatch):
    """
    Duplicar ≠ revisar, e a diferença não é cosmética.

    `revisar()` cria outra versão da MESMA pesquisa lógica (mesma raiz),
    para quando o resultado muda. Duplicar cria outra pesquisa, com
    linhagem própria, para repetir a coleta no ano seguinte. Se
    duplicar herdasse a raiz, o histórico de 2027 apareceria pendurado
    na pesquisa de 2026.

    E os preços NÃO vêm junto: eles são o que a nova coleta vai formar.
    """
    import streamlit as st

    from src.ui import precos_ui

    cliente = ClientePrecosFalso()
    origem = _semear(cliente)
    cliente.tabelas["pesquisa_preco_itens"][0]["preco_estimado"] = "12.35"
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    st.session_state["usuario"] = {"auth_user_id": "u-1", "papel": "usuario"}

    novo_id = precos_ui._duplicar(origem)

    assert novo_id and novo_id != origem["id"]
    copia = next(p for p in cliente.tabelas["pesquisas_preco"]
                 if p["id"] == novo_id)
    assert copia["nome"].endswith("(cópia)")
    assert copia["estado"] == EstadoPesquisa.RASCUNHO.value
    # linhagem PRÓPRIA: não é revisão da origem
    assert copia.get("raiz_id") is None
    assert copia.get("revisao_de") is None

    itens_copiados = [i for i in cliente.tabelas["pesquisa_preco_itens"]
                      if i["pesquisa_id"] == novo_id]
    assert len(itens_copiados) == 1
    assert itens_copiados[0]["descricao"] == "CANETA ESFEROGRAFICA AZUL"
    assert itens_copiados[0]["estado"] == EstadoItem.PENDENTE.value
    assert itens_copiados[0].get("preco_estimado") is None

    st.session_state.pop("usuario", None)


def test_o_modulo_nunca_emite_delete():
    """
    A 0021 não concede DELETE a ninguém, e o §29 manda analisar a
    política antes de apagar pesquisa auditável.

    A prova é ESTRUTURAL, não textual: nem o repositório nem a interface
    chamam `.delete(` do PostgREST, e o repositório não expõe função de
    exclusão. Uma asserção sobre o texto-fonte brigaria com os próprios
    comentários que explicam por que a exclusão não existe.
    """
    import inspect

    from src.ui import precos_ui

    for modulo in (repo, precos_ui):
        fonte = inspect.getsource(modulo)
        assert ".delete(" not in fonte, modulo.__name__

    exclusoes = [nome for nome in dir(repo)
                 if any(p in nome.lower()
                        for p in ("excluir", "apagar", "remover", "delete"))]
    assert exclusoes == [], exclusoes
