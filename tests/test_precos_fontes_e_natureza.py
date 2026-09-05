"""
Rodada corretiva — capacidade da fonte e natureza do valor.

Duas confusões que a auditoria expôs, e que não são detalhe de
implementação: as duas faziam o sistema afirmar coisa falsa sobre a
pesquisa que acabou de rodar.

**1. "A fonte respondeu" não é "a fonte forneceu preço".**
O motor contava adapters. Com o PNCP de pé (que só enriquece) e o
Compras.gov fora (que é quem tem preço), a pesquisa se declarava
tecnicamente bem-sucedida e o item saía `incomplete` — que o relatório
traduz como "o mercado não tinha este item". O mercado não tinha nada a
ver com isso: a fonte de preço caiu.

Pior: `falhas` só contava EXCEÇÃO, e nenhum dos dois adapters levanta
exceção — os dois tratam o erro por dentro e devolvem resultado vazio.
Então nem um HTTP 503 total contava como falha.

**2. "Tem um número" não é "é um preço".**
`valorUnitarioEstimado` — a expectativa do órgão de origem — entrava na
cesta como preço praticado quando a contratação ainda não tinha
resultado. Fundamentar a estimativa da Administração na estimativa de
outra Administração é ciranda: ninguém nunca olhou preço real.

Os cenários A–D vêm do enunciado da auditoria e estão nomeados como tal.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.precos import estatistica, execucao, matching
from src.precos.fontes import (Capacidade, Consulta, Desfecho,
                               FontePesquisaPreco, ResultadoBusca,
                               fornece_preco)
from src.precos.modelo import (NATUREZAS_COMPARAVEIS, Fonte, NaturezaValor,
                               Referencia, StatusReferencia)
from src.precos.perfil import PADRAO

# ---------------------------------------------------------------------------
# Dublês
# ---------------------------------------------------------------------------
F_PRECO = Fonte(id="compras_gov_precos", nome="Compras.gov — Preços",
                tipo="sistema_oficial")
F_PRECO_2 = Fonte(id="compras_gov_itens", nome="Compras.gov — Itens",
                  tipo="contratacao_similar")
F_EVIDENCIA = Fonte(id="pncp", nome="PNCP", tipo="sistema_oficial")

ITEM = {"id": "i1", "numero": 1, "descricao": "CANETA ESFEROGRAFICA AZUL",
        "unidade": "UN", "quantidade": "100"}


def _ref(fonte: Fonte, ident: str, valor: str,
         natureza: NaturezaValor = NaturezaValor.PRATICADO) -> Referencia:
    return Referencia(
        fonte=fonte, id_externo=ident, bruto={"id": ident},
        descricao_original="CANETA ESFEROGRAFICA AZUL",
        unidade_original="UN", valor_unitario_original=Decimal(valor),
        natureza_valor=natureza)


class FonteDeDuble(FontePesquisaPreco):
    """Adapter controlado: decide o que devolve e se falha."""

    def __init__(self, fonte, capacidades, *, referencias=None, falha=None,
                 recado=None, explode=False):
        self.fonte = fonte
        self.capacidades = frozenset(capacidades)
        self._referencias = referencias or []
        self._falha = falha
        self._recado = recado
        self._explode = explode

    def pesquisar(self, consulta: Consulta) -> ResultadoBusca:
        if self._explode:
            raise TimeoutError("dublê estourou de propósito")
        resultado = ResultadoBusca(fonte=self.fonte)
        if self._falha:
            resultado.falhar(self._falha)
        if self._recado:
            resultado.registrar(self._recado)
        resultado.referencias.extend(self._referencias)
        return resultado

    def healthcheck(self) -> bool:
        return self._falha is None


def _rodar(fontes):
    return execucao.pesquisar_item(ITEM, fontes, perfil=PADRAO)


def _comparabilidade_maxima() -> matching.Comparabilidade:
    """
    Nota cheia: mesmo produto, circunstância impecável.

    É de propósito que ela seja MÁXIMA nos testes de natureza — o ponto
    é que nem a comparabilidade perfeita salva um valor que não é preço.
    """
    return matching.Comparabilidade(
        score=Decimal("1"), identidade=Decimal("1"),
        circunstancias=Decimal("1"), fatores=[])


# ---------------------------------------------------------------------------
# Desfecho por fonte
# ---------------------------------------------------------------------------
def test_recado_nao_e_falha():
    """
    A raiz da confusão: `houve_falha` era `bool(ocorrencias)`. O PNCP
    registrava "sou fonte de enriquecimento" a cada item e aparecia
    permanentemente quebrado.
    """
    resultado = ResultadoBusca(fonte=F_EVIDENCIA)
    resultado.registrar("não sou porta de entrada")

    assert resultado.houve_falha is False
    assert resultado.desfecho is Desfecho.SEM_RESULTADO


def test_falha_tecnica_e_falha_mesmo_sem_excecao():
    """
    O outro buraco: os adapters tratam o erro por dentro. Um 503 vinha
    como resultado vazio, e nada no modelo dizia que fora falha.
    """
    resultado = ResultadoBusca(fonte=F_PRECO)
    resultado.falhar("respondeu HTTP 503")

    assert resultado.houve_falha is True
    assert resultado.desfecho is Desfecho.FALHA


def test_a_primeira_falha_e_a_que_fica():
    resultado = ResultadoBusca(fonte=F_PRECO)
    resultado.falhar("HTTP 503 em /precos")
    resultado.falhar("HTTP 503 em /itens")

    assert resultado.falha == "HTTP 503 em /precos"
    assert len(resultado.ocorrencias) == 2, "as duas continuam visíveis"


def test_os_quatro_desfechos_sao_distinguiveis():
    vazio = ResultadoBusca(fonte=F_PRECO)
    assert vazio.desfecho is Desfecho.SEM_RESULTADO

    com_preco = ResultadoBusca(fonte=F_PRECO,
                               referencias=[_ref(F_PRECO, "a", "1.50")])
    assert com_preco.desfecho is Desfecho.COM_PRECOS

    so_evidencia = ResultadoBusca(fonte=F_PRECO, referencias=[
        _ref(F_PRECO, "b", "1.50", NaturezaValor.ESTIMADO_ORIGEM)])
    assert so_evidencia.desfecho is Desfecho.SO_EVIDENCIA

    falhou = ResultadoBusca(fonte=F_PRECO)
    falhou.falhar("caiu")
    assert falhou.desfecho is Desfecho.FALHA


def test_capacidade_e_declarada_pela_classe_nao_deduzida():
    """
    Se a capacidade fosse deduzida do resultado, uma fonte de preço que
    voltasse vazia POR FALHA seria reclassificada como fonte de
    evidência — e a falha sumiria. É o apagamento que o modelo impede.
    """
    caiu = FonteDeDuble(F_PRECO, {Capacidade.PRECO}, falha="caiu")

    assert fornece_preco(caiu) is True
    assert caiu.pesquisar(Consulta(descricao="x")).desfecho is Desfecho.FALHA


def test_adapter_sem_declaracao_conta_como_fonte_de_preco():
    """
    Omissão não pode fazer uma fonte de preço sumir da conta de falhas —
    o padrão seguro é PREÇO.
    """
    class Antigo:
        fonte = F_PRECO

    assert fornece_preco(Antigo()) is True


# ---------------------------------------------------------------------------
# Cenários A–D do enunciado
# ---------------------------------------------------------------------------
def test_cenario_A_fonte_de_preco_cai_e_evidencia_responde():
    """
    A) Compras.gov falha; PNCP evidence-only responde.
       → falha TÉCNICA da fonte de preço, não amostra insuficiente.

    Este é o caso que motivou a rodada inteira. Antes, `falhas (0) !=
    len(fontes) (2)` e o item saía `incomplete`, dizendo que o mercado
    não tinha o produto.
    """
    resultado = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, falha="HTTP 503"),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA},
                     recado="uso apenas para comprovação"),
    ])

    assert resultado.falhou, "falha da fonte de preço tem de ser falha"
    assert "falha técnica" in resultado.erro
    assert "não ausência de preço no mercado" in resultado.erro
    assert resultado.desfechos["compras_gov_precos"] == Desfecho.FALHA.value
    assert resultado.desfechos["pncp"] == Desfecho.SEM_RESULTADO.value


def test_cenario_B_fonte_de_preco_responde_vazia():
    """
    B) Compras.gov responde sem preços; PNCP evidence-only responde.
       → ausência REAL de preço, distinta de indisponibilidade técnica.

    Aqui repetir a busca amanhã dá o mesmo, e o item deve seguir para o
    caminho normal de amostra insuficiente — não para a fila de retry.
    """
    resultado = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}),
    ])

    assert not resultado.falhou, "sem preço no mercado não é falha técnica"
    assert resultado.desfechos["compras_gov_precos"] == \
        Desfecho.SEM_RESULTADO.value
    assert resultado.estimativa is not None
    assert resultado.encontradas == 0


def test_cenario_C_fonte_de_preco_entrega_e_evidencia_acompanha():
    """C) Compras.gov fornece preços; PNCP fornece evidência → válida."""
    resultado = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, referencias=[
            _ref(F_PRECO, "a", "1.50"), _ref(F_PRECO, "b", "1.80"),
            _ref(F_PRECO, "c", "1.60")]),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}),
    ])

    assert not resultado.falhou
    assert resultado.desfechos["compras_gov_precos"] == \
        Desfecho.COM_PRECOS.value
    assert resultado.encontradas == 3


def test_cenario_D_a_regra_nao_conhece_fonte_nenhuma_pelo_nome():
    """
    D) Com várias fontes de preço, a regra continua valendo — e ela não
       cita `compras_gov` nem `pncp` em lugar nenhum.

    Uma de duas fontes de preço de pé basta para não ser falha técnica;
    as duas fora é falha, ainda que a evidência responda.
    """
    uma_de_pe = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, falha="caiu"),
        FonteDeDuble(F_PRECO_2, {Capacidade.PRECO},
                     referencias=[_ref(F_PRECO_2, "z", "2.00",
                                       NaturezaValor.HOMOLOGADO)]),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}),
    ])
    assert not uma_de_pe.falhou

    todas_fora = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, falha="caiu"),
        FonteDeDuble(F_PRECO_2, {Capacidade.PRECO}, falha="caiu também"),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}),
    ])
    assert todas_fora.falhou


def test_falha_da_fonte_de_evidencia_nao_derruba_o_item():
    """
    O caso discriminante — e ele veio de uma mutação que passou.

    Quebrei a conta de propósito para somar TODAS as fontes caídas em vez
    das de preço, e a suíte ficou verde: nenhum dos cenários A–D separava
    as duas contas, porque em todos eles quem caía era fonte de preço.

    Aqui o PNCP cai e o Compras.gov entrega. A pesquisa é válida: perder
    o enriquecimento custa o link oficial no relatório, não o preço. Com
    a conta errada, `len(falharam)==1 == len(de_preco)==1` e o item
    inteiro seria marcado como falha técnica por causa de uma fonte que
    nunca teve preço nenhum.
    """
    resultado = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, referencias=[
            _ref(F_PRECO, "a", "1.50")]),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}, falha="PNCP caiu"),
    ])

    assert not resultado.falhou, (
        "falha de fonte de evidência não é falha da pesquisa")
    assert resultado.desfechos["pncp"] == Desfecho.FALHA.value, (
        "mas a falha continua VISÍVEL — some do veredito, não do relato")
    assert resultado.encontradas == 1


def test_excecao_do_adapter_continua_sendo_falha():
    """O caminho antigo não regrediu: exceção também é falha técnica."""
    resultado = _rodar([
        FonteDeDuble(F_PRECO, {Capacidade.PRECO}, explode=True),
        FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA}),
    ])

    assert resultado.falhou
    assert resultado.desfechos["compras_gov_precos"] == Desfecho.FALHA.value


def test_pesquisa_sem_fonte_de_preco_e_erro_de_configuracao():
    """
    Só evidência configurada: a pesquisa não pode dar certo nunca. Sair
    `incomplete` culparia o mercado por um erro nosso.
    """
    resultado = _rodar([FonteDeDuble(F_EVIDENCIA, {Capacidade.EVIDENCIA})])

    assert resultado.falhou
    assert "nenhuma fonte capaz de fornecer preço" in resultado.erro


# ---------------------------------------------------------------------------
# Natureza do valor
# ---------------------------------------------------------------------------
def test_valor_estimado_de_terceiro_nao_e_preco_praticado():
    """
    A regressão explícita que o enunciado pede. `valorEstimado` tem
    número e não é preço: `tem_preco` é verdadeiro, `serve_de_preco` não.
    """
    estimado = _ref(F_PRECO_2, "x", "99.00", NaturezaValor.ESTIMADO_ORIGEM)
    praticado = _ref(F_PRECO, "y", "1.50", NaturezaValor.PRATICADO)

    assert estimado.tem_preco is True
    assert estimado.serve_de_preco is False
    assert praticado.serve_de_preco is True
    assert NaturezaValor.ESTIMADO_ORIGEM not in NATUREZAS_COMPARAVEIS


def test_estimado_nao_entra_na_cesta_mesmo_sendo_perfeitamente_comparavel():
    """
    O ponto exato da correção, e por que a ordem das checagens importa.

    Um valor estimado pode descrever o MESMO produto, na mesma unidade,
    na mesma região — comparabilidade máxima. É justamente por isso que
    ele passaria no piso e entraria. Comparabilidade responde "é o mesmo
    produto?"; natureza responde "este número é um preço?".
    """
    estimado = _ref(F_PRECO_2, "x", "99.00", NaturezaValor.ESTIMADO_ORIGEM)
    estimado.unidade_normalizada = "UN"
    estimado.valor_unitario_normalizado = Decimal("99.00")

    cesta = estatistica.selecionar_cesta(
        [(estimado, _comparabilidade_maxima())], PADRAO)

    assert estimado not in cesta.selecionadas
    assert estimado in cesta.descartadas
    assert estimado.status is StatusReferencia.REVISAO_MANUAL
    # Descartada da cesta, NUNCA apagada: continua listada com o motivo.
    assert any("não é preço efetivamente praticado" in m
               for m in estimado.motivos)


def test_a_estimativa_ignora_o_estimado_e_usa_so_o_praticado():
    """
    A consequência que importa: o número final não é contaminado.

    Três praticados a R$ 1,50 / 1,60 / 1,80 e um estimado a R$ 99,00. A
    série dos praticados é homogênea (CV 0,09), então o método
    automático escolhe a MÉDIA: R$ 1,63. Se o estimado tivesse entrado,
    a mesma média daria R$ 25,97 — e é essa a diferença entre uma
    estimativa defensável e uma contratação superavaliada em 16 vezes.
    """
    refs = []
    for ident, valor, natureza in [
            ("a", "1.50", NaturezaValor.PRATICADO),
            ("b", "1.60", NaturezaValor.PRATICADO),
            ("c", "1.80", NaturezaValor.PRATICADO),
            ("d", "99.00", NaturezaValor.ESTIMADO_ORIGEM)]:
        r = _ref(F_PRECO, ident, valor, natureza)
        r.unidade_normalizada = "UN"
        r.valor_unitario_normalizado = Decimal(valor)
        refs.append(r)

    cesta = estatistica.selecionar_cesta(
        [(r, _comparabilidade_maxima()) for r in refs], PADRAO)
    estimativa = estatistica.estimar(cesta, perfil=PADRAO)

    assert len(cesta.selecionadas) == 3
    assert estimativa.valor_unitario == Decimal("1.63"), \
        "a média dos três preços praticados"
    assert estimativa.valor_unitario < Decimal("2.00"), \
        "o valor estimado de terceiro contaminou a cesta"


def test_natureza_desconhecida_tambem_fica_de_fora():
    """
    A lista de naturezas aceitas é POSITIVA. Uma natureza nova — de uma
    fonte futura — não nasce aceita só porque ninguém a proibiu.
    """
    desconhecida = _ref(F_PRECO, "n", "5.00", NaturezaValor.OUTRO)
    desconhecida.unidade_normalizada = "UN"
    desconhecida.valor_unitario_normalizado = Decimal("5.00")

    cesta = estatistica.selecionar_cesta(
        [(desconhecida, _comparabilidade_maxima())], PADRAO)

    assert not cesta.selecionadas


def test_proposta_de_fornecedor_nao_e_preco_praticado():
    """Oferta não é contrato: ninguém disputou, ninguém pagou."""
    proposta = _ref(F_PRECO, "p", "3.00", NaturezaValor.PROPOSTA)
    assert proposta.serve_de_preco is False


@pytest.mark.parametrize("natureza", sorted(NATUREZAS_COMPARAVEIS,
                                            key=lambda n: n.value))
def test_as_naturezas_comparaveis_servem_de_preco(natureza):
    assert _ref(F_PRECO, "k", "1.00", natureza).serve_de_preco is True


def test_a_provenance_sobrevive_ao_relatorio():
    """
    §4 do enunciado: provenance completa preservada. A natureza vai
    junto — sem ela, quem audita meses depois não sabe se o número foi
    pago ou só esperado por alguém.
    """
    referencia = _ref(F_PRECO_2, "x", "99.00", NaturezaValor.ESTIMADO_ORIGEM)
    referencia.orgao = "PREFEITURA DE EXEMPLO"
    referencia.uf = "PA"
    referencia.referencia_externa = "00038166000105-1-000273/2025"
    projecao = referencia.para_relatorio()

    for campo in ("fonte_id", "id_externo", "raw_hash", "orgao", "uf",
                  "unidade_original", "valor_unitario_original",
                  "referencia_externa", "natureza_valor", "serve_de_preco"):
        assert campo in projecao, f"provenance perdeu {campo}"
    assert projecao["natureza_valor"] == "estimado_origem"
    assert projecao["serve_de_preco"] is False
    assert projecao["rotulo_natureza"] == "valor ESTIMADO pelo órgão de origem"


# ---------------------------------------------------------------------------
# Os adapters reais classificam pelo campo que veio
# ---------------------------------------------------------------------------
def test_compras_gov_marca_homologado_e_estimado_pelo_campo_de_origem():
    """
    A correção no adapter: era `homologado or estimado` e seguia adiante.
    Agora o campo que preencheu o valor carimba a natureza.
    """
    from src.precos.compras_gov import _referencia_de_item_contratado

    com_resultado = _referencia_de_item_contratado({
        "idCompraItem": "1", "descricaodetalhada": "CANETA",
        "unidadeMedida": "UN", "valorUnitarioResultado": "1.50",
        "valorUnitarioEstimado": "9.00"})
    assert com_resultado.natureza_valor is NaturezaValor.HOMOLOGADO
    assert com_resultado.valor_unitario_original == Decimal("1.50")
    assert com_resultado.serve_de_preco is True

    sem_resultado = _referencia_de_item_contratado({
        "idCompraItem": "2", "descricaodetalhada": "CANETA",
        "unidadeMedida": "UN", "valorUnitarioEstimado": "9.00"})
    assert sem_resultado.natureza_valor is NaturezaValor.ESTIMADO_ORIGEM
    assert sem_resultado.serve_de_preco is False
    assert any("ESTIMADO" in m for m in sem_resultado.motivos)


def test_precos_praticados_e_praticado():
    from src.precos.compras_gov import _referencia_de_preco_praticado

    referencia = _referencia_de_preco_praticado({
        "idCompraItem": "9", "descricaoItem": "CANETA",
        "siglaUnidadeFornecimento": "UN", "precoUnitario": "1.50"})

    assert referencia.natureza_valor is NaturezaValor.PRATICADO
    assert referencia.serve_de_preco is True


def test_o_pncp_declara_que_hoje_so_traz_evidencia():
    """
    Verdade sobre o que o adapter faz, não sobre o que se gostaria que
    fizesse. A investigação de 05/09/2026 está no docstring do módulo:
    os endpoints de item/resultado do PNCP responderam 502/503, então
    não há como confirmar os campos de preço unitário — e inventá-los
    seria adivinhar o contrato de uma API.
    """
    from src.precos.pncp import PNCPAdapter

    adapter = PNCPAdapter()
    assert Capacidade.PRECO not in adapter.capacidades
    assert Capacidade.EVIDENCIA in adapter.capacidades
    assert fornece_preco(adapter) is False

    # E o recado de projeto não é falha.
    resultado = adapter.pesquisar(Consulta(descricao="caneta"))
    assert resultado.houve_falha is False
    assert resultado.desfecho is Desfecho.SEM_RESULTADO


# ---------------------------------------------------------------------------
# O que o servidor LÊ na tela e no relatório
# ---------------------------------------------------------------------------
def test_o_govbot_manda_repetir_na_falha_e_mudar_criterios_no_vazio():
    """
    §8 do enunciado: a diferença tem de aparecer na UI.

    As duas situações pedem ações OPOSTAS. Falha técnica pede repetir;
    amostra insuficiente pede mudar critérios ou justificar. Antes, as
    duas produziam "encontrei apenas 0 referências" — e o servidor
    ampliava a janela e caçava CATMAT inutilmente, porque não havia nada
    de errado com a busca.
    """
    from src.precos import orientacao

    com_erro = orientacao.do_item(
        {"numero": 1, "estado": "error", "unidade": "UN",
         "desfechos": {"compras_gov_precos": "failure", "pncp": "success_empty"}},
        [])
    texto_erro = " ".join(o.texto for o in com_erro)

    assert com_erro[0].severidade == orientacao.IMPEDE
    assert "indisponibilidade técnica" in texto_erro
    assert "NÃO ausência de preço no mercado" in texto_erro
    assert "rode a pesquisa outra vez" in texto_erro.lower()
    assert "compras_gov_precos" in texto_erro, "diz QUAL fonte caiu"
    assert "amplie a janela" not in texto_erro.lower(), (
        "mandar mexer nos critérios por causa de falha técnica é o "
        "conselho errado — foi o defeito")

    incompleto = orientacao.do_item(
        {"numero": 1, "estado": "incomplete", "unidade": "UN"}, [])
    texto_vazio = " ".join(o.texto for o in incompleto)

    assert "As fontes responderam" in texto_vazio
    assert "o mercado é que não tinha" in texto_vazio
    assert "janela" in texto_vazio


def test_o_panorama_contrasta_as_duas_causas():
    from src.precos import orientacao

    saida = orientacao.da_pesquisa({}, [
        {"numero": 1, "estado": "incomplete"},
        {"numero": 2, "estado": "error"},
    ])
    texto = " ".join(o.texto for o in saida)

    assert "Repetir a busca tende a dar o mesmo" in texto
    assert "as fontes de preço não responderam" in texto
    assert "nada indica que falte preço no mercado" in texto


def test_a_natureza_e_coluna_do_relatorio():
    """
    §4: provenance visível. A diferença entre um preço pago e um valor
    apenas esperado por outro órgão é a primeira pergunta de um auditor —
    não pode ficar escondida no campo de motivos.
    """
    from src.precos import relatorio

    tabela = relatorio._tabela_de_referencias([
        {"fonte_nome": "Compras.gov", "orgao": "PREF", "uf": "PA",
         "valor_unitario_original": "1.50", "unidade_original": "UN",
         "natureza_valor": "praticado"},
        {"fonte_nome": "Compras.gov", "orgao": "PREF", "uf": "PA",
         "valor_unitario_original": "99.00", "unidade_original": "UN",
         "natureza_valor": "estimado_origem"},
    ])

    assert "| Natureza |" in tabela
    assert "preço praticado" in tabela
    assert "valor ESTIMADO pelo órgão de origem" in tabela
    # A tabela continua bem formada: cabeçalho, separador e duas linhas
    # com o mesmo número de colunas.
    linhas = tabela.splitlines()
    colunas = {ln.count("|") for ln in linhas}
    assert len(colunas) == 1, f"colunas desalinhadas: {colunas}"


# ---------------------------------------------------------------------------
# §6 — a IA no pipeline, com motor mockado
# ---------------------------------------------------------------------------
def _motor_que_responde(texto: str):
    """Dublê do modelo: devolve sempre a mesma resposta."""
    return lambda sistema, usuario: texto


TERMOS_OK = ('{"acao":"sugerir_termos",'
             '"termos":["esferografica","caneta azul","tinta azul"]}')


def test_sem_motor_o_pipeline_roda_deterministico():
    """
    A camada é opcional de verdade. Sem credencial, a busca acontece
    igual — o que se perde é sinônimo, não a pesquisa.
    """
    from src.precos import semantica

    assert semantica.sugerir_termos(None, ITEM) == []

    resultado = _rodar([FonteDeDuble(F_PRECO, {Capacidade.PRECO},
                                     referencias=[_ref(F_PRECO, "a", "1.50")])])
    assert not resultado.falhou
    assert resultado.termos_semanticos == []
    assert resultado.encontradas == 1


def test_com_motor_os_termos_chegam_a_consulta():
    """
    A integração de verdade: o que o modelo sugere vira `Consulta`, e a
    `Consulta` é o que os adapters recebem. Se parasse antes disso, a
    camada estaria "implementada" sem participar de nada.
    """
    from src.precos import execucao, semantica

    vistas = []

    class Espia(FonteDeDuble):
        def pesquisar(self, consulta):
            vistas.append(consulta)
            return super().pesquisar(consulta)

    execucao.pesquisar_item(
        ITEM, [Espia(F_PRECO, {Capacidade.PRECO})], perfil=PADRAO,
        motor_semantico=_motor_que_responde(TERMOS_OK))

    assert vistas, "a fonte não foi consultada"
    assert "esferografica" in vistas[0].termos_alternativos
    assert len(vistas[0].termos_alternativos) == 3


def test_os_termos_ampliam_a_busca_sem_mudar_o_preco():
    """
    O limite exato da IA no fluxo (§6): ela mexe em QUEM entra na lista
    de candidatos, nunca no valor de ninguém.

    Aqui o registro não casa com a descrição do item ("caneta
    esferográfica azul" contra "ESFEROGRAFICA AZUL PONTA MEDIA"), mas
    casa com um termo sugerido. Ele entra — e entra com o preço que a
    fonte informou, não um que o modelo tenha dito.
    """
    from src.precos.compras_gov import ComprasGovAdapter
    from src.precos.fontes import Consulta
    import json

    registro = {"idCompraItem": "9",
                "descricaodetalhada": "TINTA AZUL PONTA MEDIA",
                "unidadeMedida": "UN", "valorUnitarioResultado": "1.77"}
    payload = json.dumps({"resultado": [registro], "totalRegistros": 1})
    adapter = ComprasGovAdapter(abrir_url=lambda url: payload)

    sem_termos = adapter.pesquisar(Consulta(descricao="CANETA ESFEROGRAFICA"))
    assert not sem_termos.referencias, "não casaria sem sinônimo"

    com_termos = adapter.pesquisar(Consulta(
        descricao="CANETA ESFEROGRAFICA",
        termos_alternativos=("TINTA AZUL",)))
    assert len(com_termos.referencias) == 1
    # O preço é o da FONTE. A IA não tocou nele.
    assert com_termos.referencias[0].valor_unitario_original == Decimal("1.77")
    assert com_termos.referencias[0].natureza_valor is NaturezaValor.HOMOLOGADO


def test_modelo_que_inventa_preco_nao_contamina_a_busca():
    """
    §6: a IA não pode inventar valor. Se a resposta traz um número, a
    proposta inteira cai — e a pesquisa segue sem sinônimo, não com um
    preço fabricado.
    """
    from src.precos import execucao, semantica

    hostil = ('{"acao":"sugerir_termos","termos":["caneta"],'
              '"valor":"999.00","preco_sugerido":"999.00"}')
    assert semantica.sugerir_termos(_motor_que_responde(hostil), ITEM) == []

    resultado = execucao.pesquisar_item(
        ITEM, [FonteDeDuble(F_PRECO, {Capacidade.PRECO},
                            referencias=[_ref(F_PRECO, "a", "1.50")])],
        perfil=PADRAO, motor_semantico=_motor_que_responde(hostil))

    assert resultado.termos_semanticos == []
    assert resultado.estimativa.valor_unitario == Decimal("1.50")


def test_modelo_fora_do_ar_nao_derruba_a_pesquisa():
    """
    A camada é opcional, então falha dela é degradação, não erro. Uma
    pesquisa que para porque o serviço de sinônimo caiu seria pior do que
    não ter sinônimo nenhum.
    """
    from src.precos import execucao, semantica

    def motor_quebrado(sistema, usuario):
        raise TimeoutError("o modelo não respondeu")

    assert semantica.sugerir_termos(motor_quebrado, ITEM) == []

    resultado = execucao.pesquisar_item(
        ITEM, [FonteDeDuble(F_PRECO, {Capacidade.PRECO},
                            referencias=[_ref(F_PRECO, "a", "1.50")])],
        perfil=PADRAO, motor_semantico=motor_quebrado)
    assert not resultado.falhou


def test_resposta_nao_json_tambem_degrada_em_silencio_util():
    from src.precos import semantica

    assert semantica.sugerir_termos(
        _motor_que_responde("desculpe, não posso ajudar"), ITEM) == []


def test_a_participacao_da_ia_fica_registrada():
    """
    §58: precisa dar para responder depois "o que a IA fez nesta
    pesquisa". A resposta honesta é a lista de palavras que ela sugeriu.
    """
    from src.precos import execucao

    resultado = execucao.pesquisar_item(
        ITEM, [FonteDeDuble(F_PRECO, {Capacidade.PRECO})], perfil=PADRAO,
        motor_semantico=_motor_que_responde(TERMOS_OK))

    assert resultado.termos_semanticos == [
        "esferografica", "caneta azul", "tinta azul"]
    assert any("camada semântica" in o for o in resultado.ocorrencias)


def test_o_motor_do_projeto_reusa_o_llm_existente():
    """
    §17: nada de um segundo sistema de IA. Sem credencial devolve `None`;
    com credencial, o que sai é uma função com a assinatura do `Motor`.
    """
    from src.precos import semantica

    assert semantica.motor_disponivel() is False, (
        "este ambiente não tem motor; com credencial, revise o registro "
        "de bloqueio da Fase 7")
    assert semantica.motor_do_projeto() is None
