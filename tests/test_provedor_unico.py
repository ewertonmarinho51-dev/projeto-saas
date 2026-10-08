"""
Provedor único de geração — uma conta, uma fatura, e nenhuma surpresa.

O QUE MUDOU, E POR QUE PRECISOU MUDAR

A cascata responde "quem está configurado?". Ela NÃO responde "quem eu
escolhi?", e as duas perguntas deixaram de ter a mesma resposta no
momento em que a chave da OpenAI passou a ser necessária apenas para o
ÍNDICE VETORIAL.

O índice usa `text-embedding-3-small` da OpenAI e não tem substituto: o
OpenRouter não serve embedding nenhum (dos 467 modelos do catálogo em
08/10/2026, nenhum devolve vetor; as modalidades de saída são texto,
áudio e imagem). Então a chave da OpenAI tem de continuar existindo —
e, enquanto bastava existir para entrar na cascata, ela trazia a
GERAÇÃO de volta para a OpenAI sem que ninguém tivesse pedido.

As provas abaixo guardam as duas metades disso: que a escolha é
respeitada, e que ela NÃO é o padrão — quem não escolher nada continua
com a cascata de sempre, byte a byte.
"""

from __future__ import annotations

import pytest

from src import llm, rag


def _chaves(monkeypatch, openai="", gemini="", openrouter="",
            embeddings="", provedor=""):
    monkeypatch.setattr(llm, "obter_openai_key", lambda: openai)
    monkeypatch.setattr(llm, "obter_api_key", lambda: gemini)
    monkeypatch.setattr(llm, "obter_openrouter_key", lambda: openrouter)
    monkeypatch.setattr(llm, "provedor_declarado", lambda: provedor)
    monkeypatch.setattr(llm, "obter_chave_de_embeddings",
                        lambda: embeddings or openai)


# ---------------------------------------------------------------------------
# O padrão não muda
# ---------------------------------------------------------------------------
def test_sem_escolha_a_cascata_e_a_de_sempre(monkeypatch):
    """
    Rollback desta mudança é deixar `IA_PROVEDOR` vazio. Se a cascata
    mudasse de comportamento no padrão, não haveria rollback — haveria
    um caminho novo obrigatório.
    """
    _chaves(monkeypatch, openai="sk-x", gemini="g-y", openrouter="or-z")
    assert [m for m, _ in llm.motores_disponiveis()] == [
        "openai", "gemini", "openrouter"]
    assert llm.motor_ativo() == "openai"


def test_nome_invalido_cai_na_cascata_em_vez_de_travar(monkeypatch):
    """
    Erro de digitação em `IA_PROVEDOR` não pode deixar o sistema sem
    provedor nenhum e com a tela dizendo "nenhuma chave configurada" —
    com três chaves válidas configuradas.
    """
    monkeypatch.setattr(llm, "_ler_chave",
                        lambda nome, _s: "openrouterr"
                        if nome == "IA_PROVEDOR" else "")
    assert llm.provedor_declarado() == ""


@pytest.mark.parametrize("nome", ["openai", "gemini", "openrouter"])
def test_todo_provedor_pode_ser_escolhido(monkeypatch, nome):
    monkeypatch.setattr(llm, "_ler_chave",
                        lambda chave, _s, _n=nome: _n
                        if chave == "IA_PROVEDOR" else "")
    assert llm.provedor_declarado() == nome


# ---------------------------------------------------------------------------
# A escolha é exclusiva
# ---------------------------------------------------------------------------
def test_o_provedor_escolhido_e_o_unico_mesmo_com_as_outras_chaves(monkeypatch):
    """
    O coração da mudança: a chave da OpenAI continua configurada — ela
    precisa, para o índice — e a geração NÃO volta para a OpenAI.
    """
    _chaves(monkeypatch, openai="sk-x", gemini="g-y", openrouter="or-z",
            provedor="openrouter")
    assert [m for m, _ in llm.motores_disponiveis()] == ["openrouter"]
    assert llm.motor_ativo() == "openrouter"


def test_nao_ha_queda_para_outro_provedor(monkeypatch):
    """
    A contrapartida, e ela tem de ser real: provedor único não cai para
    outro provedor. Se caísse, a fatura apareceria na conta que o
    operador acreditava ter desligado.
    """
    _chaves(monkeypatch, openai="sk-x", gemini="g-y", openrouter="or-z",
            provedor="openrouter")

    def nunca(*_a, **_k):
        pytest.fail("um provedor não escolhido foi chamado")

    monkeypatch.setattr(llm, "_chamar_openai", nunca)
    monkeypatch.setattr(llm, "_chamar_gemini", nunca)
    monkeypatch.setattr(
        llm, "_chamar_openrouter",
        lambda *_a, **_k: (_ for _ in ()).throw(
            llm.ErroGeracaoIA("limite diário do openrouter")))
    with pytest.raises(llm.ErroGeracaoIA, match="limite diário"):
        llm.chamar_ia_texto("s", "u")


def test_provedor_escolhido_sem_chave_diz_o_que_fazer(monkeypatch):
    """
    Declarar um provedor e esquecer a chave dele é um estado diferente
    de não ter configurado nada. A mensagem genérica mandaria o servidor
    procurar a chave errada.
    """
    _chaves(monkeypatch, openai="sk-x", provedor="openrouter")
    assert llm.motores_disponiveis() == []
    recado = llm._sem_motor()
    assert "OpenRouter" in recado
    assert "IA_PROVEDOR" in recado


def test_sem_escolha_e_sem_chave_a_mensagem_e_a_antiga(monkeypatch):
    _chaves(monkeypatch)
    assert "Modo" in llm._sem_motor()


# ---------------------------------------------------------------------------
# O índice vetorial não acompanha a escolha
# ---------------------------------------------------------------------------
def test_a_chave_de_embeddings_tem_nome_proprio(monkeypatch):
    """
    É o que permite desligar a OpenAI da GERAÇÃO e manter a BUSCA
    funcionando. Enquanto a chave do índice se chamava
    `OPENAI_API_KEY`, as duas coisas eram a mesma decisão.
    """
    valores = {"OPENAI_EMBEDDINGS_KEY": "sk-emb", "OPENAI_API_KEY": ""}
    monkeypatch.setattr(llm, "_ler_chave",
                        lambda nome, _s: valores.get(nome, ""))
    assert llm.obter_chave_de_embeddings() == "sk-emb"


def test_a_chave_antiga_continua_servindo_ao_indice(monkeypatch):
    """
    Nenhuma instalação pode parar de indexar por causa desta mudança:
    quem não migrou continua com a `OPENAI_API_KEY` servindo ao índice.
    """
    valores = {"OPENAI_EMBEDDINGS_KEY": "", "OPENAI_API_KEY": "sk-antiga"}
    monkeypatch.setattr(llm, "_ler_chave",
                        lambda nome, _s: valores.get(nome, ""))
    assert llm.obter_chave_de_embeddings() == "sk-antiga"


def test_a_dedicada_tem_precedencia_sobre_a_antiga(monkeypatch):
    valores = {"OPENAI_EMBEDDINGS_KEY": "sk-nova",
               "OPENAI_API_KEY": "sk-antiga"}
    monkeypatch.setattr(llm, "_ler_chave",
                        lambda nome, _s: valores.get(nome, ""))
    assert llm.obter_chave_de_embeddings() == "sk-nova"


def test_o_indice_usa_a_chave_de_embeddings_e_nao_a_de_geracao(monkeypatch):
    """
    Prova de ligação: `rag._gerar_embeddings` tem de ler a chave do
    ÍNDICE. Se lesse a de geração, migrar para o OpenRouter derrubaria a
    busca vetorial em silêncio e o lastro das citações pioraria sem
    nenhum aviso.
    """
    pedidas = []
    monkeypatch.setattr(llm, "obter_chave_de_embeddings",
                        lambda: pedidas.append("embeddings") or "")
    monkeypatch.setattr(llm, "obter_openai_key",
                        lambda: pedidas.append("geracao") or "sk-geracao")
    monkeypatch.setattr(rag.st, "warning", lambda *_a, **_k: None)

    assert rag._gerar_embeddings(["consulta"], para_consulta=True) is None
    assert pedidas == ["embeddings"], (
        f"o índice consultou a chave errada: {pedidas}")


def test_sem_chave_de_embeddings_a_busca_degrada_e_avisa(monkeypatch):
    """
    Degradar para busca textual é o comportamento correto — documento
    não pode deixar de sair porque a busca piorou. O que não pode é
    degradar CALADO: a mensagem precisa nomear a chave dedicada, senão
    o servidor reabre a `OPENAI_API_KEY` que acabou de fechar.
    """
    avisos = []
    monkeypatch.setattr(llm, "obter_chave_de_embeddings", lambda: "")
    monkeypatch.setattr(rag.st, "warning", lambda m, *_a, **_k: avisos.append(m))

    assert rag._gerar_embeddings(["x"], para_consulta=True) is None
    assert avisos and "OPENAI_EMBEDDINGS_KEY" in avisos[0]
    assert "textual" in avisos[0]


def test_o_indice_recusa_provedor_diferente_de_openai(monkeypatch):
    """
    A guarda que impede a troca silenciosa do provedor do índice.
    Trocá-lo invalida todos os vetores gravados — 5.595 chunks — e a
    busca passaria a comparar vetores incomparáveis, devolvendo
    referências erradas com aparência de certas.
    """
    from src import config

    monkeypatch.setattr(config, "EMBEDDING_V2_PROVEDOR", "openrouter")
    with pytest.raises(rag.ErroRAG, match="não suportado"):
        rag._gerar_embeddings(["x"], para_consulta=True)


# ---------------------------------------------------------------------------
# O modelo de raciocínio do OpenRouter
# ---------------------------------------------------------------------------
def test_a_nemotron_e_reconhecida_como_modelo_de_raciocinio():
    """
    Ela gasta orçamento pensando. Tratada como modelo comum, recebe o
    teto sem folga e devolve conteúdo VAZIO — e o identificador do
    OpenRouter traz o fornecedor na frente, então a detecção por
    PREFIXO (que servia a `gpt-5`) nunca casaria.
    """
    assert llm.e_modelo_de_raciocinio(
        "nvidia/nemotron-3-ultra-550b-a55b:free")
    assert llm.e_modelo_de_raciocinio(
        "nvidia/nemotron-3-super-120b-a12b:free")


@pytest.mark.parametrize("identificador", [
    "gpt-5-mini",                 # como a OpenAI o chama
    "openai/gpt-5-mini",          # como o OpenRouter o chama
    "openai/gpt-5-mini:batch",    # com sufixo de endpoint
    "openai/gpt-5",
    "openai/o3-mini",
])
def test_o_mesmo_modelo_e_reconhecido_nos_dois_provedores(identificador):
    """
    O defeito que esta prova fecha, e ele era meu.

    `openai/gpt-5-mini` é o modelo RECOMENDADO para a migração: é o que
    as 168 gerações de produção validaram, e pelo OpenRouter ele vem com
    o fornecedor na frente. A primeira versão desta detecção comparava o
    prefixo do identificador cru, de modo que reconhecia `gpt-5-mini` e
    NÃO reconhecia `openai/gpt-5-mini`.

    Consequência: o modelo que eu estava recomendando receberia o teto
    de saída SEM a folga de raciocínio e sem `reasoning_effort: low`,
    gastaria o orçamento pensando e devolveria documento VAZIO — o
    defeito exato que a lista de famílias existe para evitar, no modelo
    exato da recomendação.
    """
    assert llm.e_modelo_de_raciocinio(identificador)
    assert llm._params_modelo_openai(identificador) == {
        "reasoning_effort": "low"}


def test_modelo_comum_com_fornecedor_na_frente_continua_comum():
    """
    A mutação simétrica: normalizar demais marcaria tudo como
    raciocínio e desfaria a calibragem dos tetos.
    """
    for identificador in ("openai/gpt-4o-mini", "google/gemma-4-31b-it:free",
                          "anthropic/claude-haiku-5.5",
                          "mistralai/mistral-large-2512"):
        assert not llm.e_modelo_de_raciocinio(identificador), identificador


def test_modelo_sem_raciocinio_nao_recebe_esforco():
    """
    A mutação simétrica: marcar tudo como raciocínio infla o teto de
    saída de todo mundo e desfaz a calibragem da política de modelo.
    """
    for modelo in ("google/gemma-4-31b-it:free", "gpt-4o-mini",
                   "gemini-2.5-flash"):
        assert not llm.e_modelo_de_raciocinio(modelo)
        assert llm._params_modelo_openai(modelo) == {}


def test_o_esforco_baixo_acompanha_o_pedido_ao_openrouter():
    """
    `reasoning_effort` é documentado pelo OpenRouter com a mesma
    semântica da OpenAI, e os dois Nemotron o listam em
    `supported_parameters`. É o que permite aos dois motores reusarem
    `_openai_uma_chamada` sem um segundo conjunto de parâmetros.
    """
    assert llm._params_modelo_openai(
        "nvidia/nemotron-3-ultra-550b-a55b:free") == {
            "reasoning_effort": "low"}


def test_a_politica_de_saida_da_folga_ao_modelo_do_openrouter(monkeypatch):
    from src import politica_ia

    monkeypatch.setattr(politica_ia, "ativo", lambda: True)
    com_raciocinio = politica_ia.teto_de_saida(
        "tr", "nvidia/nemotron-3-ultra-550b-a55b:free")
    sem_raciocinio = politica_ia.teto_de_saida(
        "tr", "google/gemma-4-31b-it:free")
    assert com_raciocinio > sem_raciocinio


def test_a_deteccao_de_raciocinio_tem_uma_fonte_so():
    """
    Havia duas listas — uma em `llm`, outra em `politica_ia` — e a
    segunda já estava errada para o OpenRouter. Duas listas divergem, e
    aqui a divergência aparece como documento vazio.
    """
    from src import politica_ia

    for modelo in ("gpt-5-mini", "nvidia/nemotron-3-ultra-550b-a55b:free",
                   "gpt-4o-mini", "google/gemma-4-31b-it:free"):
        assert (politica_ia.e_de_raciocinio(modelo)
                == llm.e_modelo_de_raciocinio(modelo)), modelo


# ---------------------------------------------------------------------------
# O painel precisa poder configurar o que o sistema usa
# ---------------------------------------------------------------------------
def test_o_painel_cobre_todos_os_provedores():
    """
    O OpenRouter rodava em produção sem um único campo no painel: nem
    chave, nem modelo, nem botão de teste — e o rótulo de motor ativo
    só sabia dizer "OpenAI" ou "Gemini", de modo que o OpenRouter
    aparecia na tela como "Gemini (fallback)".
    """
    import pathlib

    fonte = (pathlib.Path(__file__).resolve().parent.parent
             / "src" / "ui" / "admin.py").read_text(encoding="utf-8")
    for nome in ("OPENROUTER_API_KEY", "OPENROUTER_MODEL",
                 "OPENAI_EMBEDDINGS_KEY", "IA_PROVEDOR"):
        assert nome in fonte, f"{nome} não tem campo no painel"


def test_todo_provedor_tem_rotulo_para_a_tela():
    from src.config import PROVEDORES_DE_IA

    for nome in PROVEDORES_DE_IA:
        assert llm.ROTULOS_MOTOR.get(nome), nome


def test_testar_conexao_aceita_os_tres_provedores(monkeypatch):
    """
    O botão de diagnóstico tem de alcançar o provedor que de fato gera.
    """
    monkeypatch.setattr(llm, "_chamar_motor", lambda *_a, **_k: "OK")
    for nome in ("openai", "gemini", "openrouter"):
        monkeypatch.setattr(llm, "obter_openai_key", lambda: "k")
        monkeypatch.setattr(llm, "obter_api_key", lambda: "k")
        monkeypatch.setattr(llm, "obter_openrouter_key", lambda: "k")
        ok, msg = llm.testar_conexao(nome)
        assert ok, msg
