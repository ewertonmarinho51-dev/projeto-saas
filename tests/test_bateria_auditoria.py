"""
§8 e §14 da auditoria: a cadeia documental percorrida pelos oito cenários.

O QUE ESTA BATERIA MEDE

Que os FATOS do processo atravessam formulário → prompt → resposta →
injeção da tabela → documento, sem se perder e sem mudar de valor. É
comparação determinística, não semelhança de texto: quantidade de
linhas, valor global, presença do objeto, ausência de marcador interno.

O QUE ELA NÃO MEDE, E O §8 MANDA DIZER

Que uma LLM real redigirá documento completo, correto ou juridicamente
adequado. A resposta aqui vem de fixture; o que se prova é o transporte,
a validação, a montagem e a exportação em volta dela. A avaliação da
redação fica pendente para a rodada operacional.

POR QUE A RESPOSTA SIMULADA RESPONDE NO TRANSPORTE HTTP

Porque um dublê em `llm._chamar_openai` desviaria justamente o que
interessa: a montagem do prompt, o cliente real da OpenAI, a leitura de
`choices[0].message.content`, o `finish_reason` vazio, a troca de modelo
e a injeção da tabela. Respondendo no transporte, tudo isso roda de
verdade — ver `scripts/bloqueio_de_custo/ia_simulada.py`.

E o contador do §3 fica junto em toda prova: `sem_llm.tentativas() == 0`
é o critério obrigatório da rodada, e uma bateria que o afirmasse sem
medir não valeria nada.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "bloqueio_de_custo"))

import ia_simulada  # noqa: E402
import sem_llm  # noqa: E402

import massas_auditoria as massas  # noqa: E402

from src import llm, planilha, templates_gov  # noqa: E402

CHAVE_DE_ENSAIO = "sk-ensaio-sem-custo-nao-e-credencial"

# Documentos redigidos com apoio de IA. `edital` e `arp` NÃO entram:
# `llm.gerar_documento` os monta por código, a partir do catálogo
# versionado de cláusulas, e nunca passa por modelo nenhum.
COM_IA = ("dfd", "etp", "mapa_riscos", "tr")


@pytest.fixture
def bateria(monkeypatch):
    """
    Bloqueio do §3 por fora, IA simulada por dentro — nesta ordem.

    Invertida, toda geração apareceria como tentativa de gasto e o
    contador do §3 ficaria ilegível.
    """
    monkeypatch.setenv("GOVDOCS_IA_SIMULADA", "coerente")
    monkeypatch.setattr(llm, "obter_openai_key", lambda: CHAVE_DE_ENSAIO)
    monkeypatch.setattr(llm, "obter_api_key", lambda: "")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "")

    sem_llm.zerar()
    ia_simulada.zerar()
    sem_llm.instalar()
    ia_simulada.instalar()
    try:
        yield
    finally:
        ia_simulada.remover()
        sem_llm.remover()
        ia_simulada.zerar()
        sem_llm.zerar()


def _linhas_da_tabela(texto: str) -> list[str]:
    """As linhas de DADOS da tabela markdown — sem cabeçalho e separador."""
    linhas = [ln.strip() for ln in texto.splitlines()
              if ln.strip().startswith("|")]
    return [ln for ln in linhas[2:]
            if ln and "VALOR GLOBAL" not in ln.upper()]


def _reais(texto: str) -> set[str]:
    return set(re.findall(r"R\$\s*[\d.]+,\d{2}", texto))


def _formatar(valor: float) -> str:
    inteiro = f"{valor:,.2f}".replace(",", "§").replace(".", ",")
    return "R$ " + inteiro.replace("§", ".")


# ---------------------------------------------------------------------------
# 1) A cadeia inteira, cenário por cenário
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cenario", massas.TODOS, ids=[c["id"] for c in massas.TODOS])
def test_os_fatos_do_processo_atravessam_a_cadeia(cenario, bateria):
    dados = cenario["dados"]
    esperado = cenario["esperado"]
    contexto = None

    for doc_key in COM_IA:
        texto = llm.gerar_documento(doc_key, dict(dados), contexto)
        contexto = texto

        assert dados["objeto"][:40] in texto, (
            f"{cenario['id']}/{doc_key}: o objeto não chegou ao documento")
        assert "[[TABELA_ITENS]]" not in texto, (
            f"{cenario['id']}/{doc_key}: marcador interno vazou para o "
            "documento — o servidor veria isso na tela")

    assert sem_llm.tentativas() == 0, (
        f"{cenario['id']}: {sem_llm.tentativas()} chamadas pagas tentadas; "
        f"o critério do §3 é zero. {sem_llm.relatorio()}")
    assert ia_simulada.quantas() == len(COM_IA), (
        f"{cenario['id']}: {ia_simulada.quantas()} respostas simuladas para "
        f"{len(COM_IA)} documentos — o caminho da IA não foi exercitado "
        "como se supôs")


@pytest.mark.parametrize(
    "cenario", massas.TODOS, ids=[c["id"] for c in massas.TODOS])
def test_a_planilha_chega_completa_e_com_a_soma_certa(cenario, bateria):
    dados = cenario["dados"]
    texto = llm.gerar_documento("dfd", dict(dados), None)

    linhas = _linhas_da_tabela(texto)
    assert len(linhas) == cenario["esperado"]["itens"], (
        f"{cenario['id']}: {len(linhas)} linhas na tabela do documento, "
        f"{cenario['esperado']['itens']} na planilha do processo")

    esperado = massas.valor_global_esperado(cenario)
    assert _formatar(esperado) in texto, (
        f"{cenario['id']}: valor global {_formatar(esperado)} não aparece no "
        f"documento. Valores presentes: {sorted(_reais(texto))[:6]}")


# ---------------------------------------------------------------------------
# 2) Os instrumentos oficiais — sem IA, por construção
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "cenario", massas.TODOS, ids=[c["id"] for c in massas.TODOS])
def test_edital_e_arp_nao_passam_por_modelo_algum(cenario, bateria):
    """
    `edital` e `arp` são de conteúdo obrigatório (art. 25 e arts. 82 a
    86) e vêm do catálogo versionado de cláusulas. Se um dia passarem a
    ser redigidos por IA, esta prova cai — e essa é a intenção: a
    mudança precisa ser deliberada, não um efeito colateral.
    """
    assert set(templates_gov.TEMPLATES_OFICIAIS) >= {"edital", "arp"}

    llm.gerar_documento("edital", dict(cenario["dados"]), "TR aprovado")

    assert ia_simulada.quantas() == 0, (
        f"{cenario['id']}: o edital consultou o modelo {ia_simulada.quantas()} "
        "vez(es) — deixou de ser instrumento de catálogo")
    assert sem_llm.tentativas() == 0


def test_srp_produz_ata_e_o_resto_nao(bateria):
    """
    A Ata só existe no Sistema de Registro de Preços. Gerá-la fora dele
    seria peça inventada; não gerá-la dentro seria peça faltando.
    """
    from src import state

    for cenario in massas.TODOS:
        assert state.usa_srp(cenario["dados"]) is cenario["esperado"]["arp"], (
            f"{cenario['id']}: modelo de execução "
            f"{cenario['dados']['modelo_execucao']!r} decidiu ARP errado")


# ---------------------------------------------------------------------------
# 3) Cenário H — a informação ausente não pode virar fato
# ---------------------------------------------------------------------------
def test_processo_incompleto_nao_ganha_fato_inventado(bateria):
    """
    O §6 é a regra: "o sistema não pode transformar uma informação
    ausente em um fato inventado". O cenário H chega sem responsável,
    sem requisitos, sem prazo, sem riscos e com valor unitário zero.
    """
    cenario = massas.CENARIO_H
    itens, valor_global = planilha.calcular(cenario["dados"]["itens"])

    assert valor_global == 0.0, (
        f"valor global {valor_global} para planilha sem preço — estimativa "
        "não pode nascer de campo vazio")

    texto = llm.gerar_documento("dfd", dict(cenario["dados"]), None)
    assert "[[TABELA_ITENS]]" not in texto


# ---------------------------------------------------------------------------
# 4) ESTRUTURAS INCORRETAS — o §8 manda testá-las, não só as corretas
#
# Estas são as provas que separam "o sistema transporta texto" de "o
# sistema CONFERE o texto que recebeu". Um mock só com resposta boa
# mediria a primeira coisa e chamaria de aprovação.
# ---------------------------------------------------------------------------
@pytest.fixture
def bateria_adversa(monkeypatch):
    """Como `bateria`, mas o modo da fixture é escolhido pelo teste."""
    monkeypatch.setattr(llm, "obter_openai_key", lambda: CHAVE_DE_ENSAIO)
    monkeypatch.setattr(llm, "obter_api_key", lambda: "")
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "")

    def preparar(modo: str):
        monkeypatch.setenv("GOVDOCS_IA_SIMULADA", modo)
        sem_llm.zerar()
        ia_simulada.zerar()
        sem_llm.instalar()
        ia_simulada.instalar()

    try:
        yield preparar
    finally:
        ia_simulada.remover()
        sem_llm.remover()
        ia_simulada.zerar()
        sem_llm.zerar()


def test_documento_que_contradiz_a_planilha_e_BLOQUEADO(bateria_adversa):
    """
    A fixture `contraditoria` afirma "7 itens, valor global de R$ 1,00"
    num processo de 20 itens e milhares de reais.

    Aceitar isso seria o ato administrativo declarar número que o
    processo não tem — e o §8 é explícito: o sistema não pode aceitar
    silenciosamente um documento incompatível com os dados de entrada.
    """
    from src import validacao

    bateria_adversa("contraditoria")
    cenario = massas.CENARIO_A
    texto = llm.gerar_documento("dfd", dict(cenario["dados"]), None)

    achados = validacao.validar_documento("dfd", texto,
                                          dados=cenario["dados"])
    bloqueios = validacao.bloqueios(achados)
    assert bloqueios, (
        "documento que contradiz a planilha passou sem bloqueio; achados: "
        f"{[a['mensagem'][:80] for a in achados]}")
    assert sem_llm.tentativas() == 0


def test_a_planilha_entra_mesmo_quando_o_modelo_esquece_o_marcador(
        bateria_adversa):
    """
    A fixture `sem_tabela` escreve "conforme planilha anexa" e omite o
    `[[TABELA_ITENS]]`.

    Medido: a planilha entra assim mesmo. `planilha.injetar_tabela`
    acrescenta a tabela ao fim quando não encontra o marcador, em vez de
    devolver o texto como veio — e isso é o comportamento certo, porque
    a planilha é dado do processo e não pode depender de o modelo ter
    lembrado de uma marca.

    A prova fica registrada para que a defesa não seja removida por
    parecer supérflua: sem ela, a tabela sumiria em silêncio, que é pior
    que sair errada — ninguém procura o que não sabe que faltou.
    """
    bateria_adversa("sem_tabela")
    cenario = massas.CENARIO_A
    texto = llm.gerar_documento("dfd", dict(cenario["dados"]), None)

    linhas = _linhas_da_tabela(texto)
    assert len(linhas) == cenario["esperado"]["itens"]
    assert _formatar(massas.valor_global_esperado(cenario)) in texto


def test_pendencia_vira_PERGUNTA_e_nao_texto_publicado(bateria_adversa):
    """
    A fixture `incompleta` devolve `[PREENCHER: valor estimado …]`.

    O certo não é apagar o marcador — é transformá-lo em pergunta ao
    servidor, com o nome do campo que falta. Apagar produziria um
    documento que parece completo e não está; publicar o colchete
    produziria um ato com marcação de rascunho.
    """
    from src import validacao

    bateria_adversa("incompleta")
    texto = llm.gerar_documento("dfd", dict(massas.CENARIO_A["dados"]), None)

    pendentes = validacao.campos_pendentes(texto)
    assert pendentes, "o marcador [PREENCHER] não virou pendência nomeada"
    assert any("valor" in (p.get("campo") or "").lower()
               for p in pendentes), (
        f"a pendência não nomeia o campo que falta: "
        f"{[p.get('campo') for p in pendentes]}")
    assert all(p.get("linha") and p.get("clausula") for p in pendentes), (
        "a pendência não localiza o trecho — o §10 pede que o alerta "
        "aponte onde o problema está, e não só que ele existe")


def test_resposta_vazia_nao_vira_documento_vazio(bateria_adversa):
    """
    Modelos de raciocínio devolvem `finish_reason=length` com conteúdo
    vazio. Com só um motor configurado, o certo é FALHAR — e não
    entregar um documento em branco como se fosse a redação encomendada.
    """
    bateria_adversa("vazia")
    with pytest.raises(llm.ErroGeracaoIA):
        llm.gerar_documento("dfd", dict(massas.CENARIO_F["dados"]), None)
    assert sem_llm.tentativas() == 0, (
        "a queda entre motores tentou sair para a rede — numa rodada "
        "operacional isso seria uma fatura por documento que não saiu")


@pytest.mark.parametrize("campo", ("responsavel", "requisitos", "prazo",
                                   "riscos", "alinhamento"))
def test_campo_ausente_aparece_como_ausente_no_prompt(campo):
    """
    Antes de acusar o documento, é preciso saber o que o sistema
    CONTOU ao modelo. Campo vazio tem de viajar como "(não informado)":
    omiti-lo faria o modelo preencher a lacuna sozinho, que é
    exatamente o que o §6 proíbe.
    """
    from src.prompts import formatar_dados_formulario

    bloco = formatar_dados_formulario(massas.CENARIO_H["dados"], "dfd")
    rotulo = __import__("src.config", fromlist=["config"]) \
        .CAMPOS_FORMULARIO[campo]["rotulo"]
    assert f"- {rotulo}: (não informado)" in bloco, (
        f"{campo}: o prompt não declara o campo como ausente")
