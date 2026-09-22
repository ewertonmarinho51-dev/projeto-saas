"""
Os itens que faltavam do escopo: §13, §39 e §59.

§39 é o que tem risco de verdade, e o risco não é o óbvio.

`db.modulo_disponivel` existia desde a entrega da fundação, dizia de si
mesma "a resposta que a navegação consulta" — e NÃO ERA CHAMADA EM LUGAR
NENHUM. A navegação olhava só a flag global, então uma secretaria que
desabilitou um módulo no painel continuava vendo o item no menu.

Ligar a função à navegação parecia trivial. Não era: `modulos_do_tenant()`
devolve `{}` para prefeitura ainda não cadastrada, e `{}.get(modulo,
False)` significa NEGADO. Em produção, onde `tenant_modulos` está vazia,
a ligação ingênua apagaria Pesquisa de Preços, Consolidar Demandas e
Parecer Jurídico do menu de todo mundo — uma camada criada para
ORGANIZAR funcionalidade removendo funcionalidade.

Ausência de linha é "ninguém decidiu", e a decisão volta ao nível de
cima. Recusa tem que ser ATO: alguém marcando desabilitado no painel.
"""

from __future__ import annotations

import pytest

from src import contexto, db, modulos
from src.ui import instituicional


# ---------------------------------------------------------------------------
# §39 — A REGRESSÃO QUE QUASE ACONTECEU
# ---------------------------------------------------------------------------
@pytest.fixture
def _banco(monkeypatch):
    """Dublê mínimo: flags e as duas tabelas de módulo."""
    estado = {"flags": {}, "tenant": {}, "secretaria": {}}
    monkeypatch.setattr(db, "flag_ativa",
                        lambda nome: bool(estado["flags"].get(nome)))
    monkeypatch.setattr(db, "modulos_do_tenant", lambda: estado["tenant"])
    monkeypatch.setattr(db, "modulos_da_secretaria",
                        lambda sid: estado["secretaria"])
    return estado


def test_prefeitura_sem_cadastro_nao_perde_modulo(_banco):
    """
    ESTA É A PROVA QUE PROTEGE PRODUÇÃO.

    `tenant_modulos` vazia é o estado de toda prefeitura que ainda não
    foi cadastrada — inclusive a de produção hoje. Se a ausência de
    linha valesse como recusa, ligar a navegação a esta função apagaria
    três itens do menu no mesmo instante.
    """
    _banco["flags"]["price_research"] = True
    _banco["tenant"] = {}          # ninguém cadastrou nada ainda
    assert db.modulo_disponivel("price_research") is True


def test_recusa_precisa_ser_ato_explicito(_banco):
    """Uma linha com `habilitado = false`, gravada por alguém no painel."""
    _banco["flags"]["price_research"] = True
    _banco["tenant"] = {"price_research": False}
    assert db.modulo_disponivel("price_research") is False


def test_a_flag_global_continua_sendo_a_palavra_final(_banco):
    """
    Nível de baixo nunca abre o que o de cima fechou. Prefeitura marcar
    uma caixa não faz o produto entregar o que ele não tem.
    """
    _banco["flags"]["price_research"] = False
    _banco["tenant"] = {"price_research": True}
    assert db.modulo_disponivel("price_research") is False


def test_a_secretaria_pode_dispensar_o_que_a_prefeitura_habilitou(_banco):
    _banco["flags"]["price_research"] = True
    _banco["tenant"] = {"price_research": True}
    _banco["secretaria"] = {"price_research": modulos.DESABILITADO}
    assert db.modulo_disponivel("price_research", "sec-1") is False


def test_secretaria_sem_registro_herda(_banco):
    _banco["flags"]["price_research"] = True
    _banco["tenant"] = {"price_research": True}
    _banco["secretaria"] = {}
    assert db.modulo_disponivel("price_research", "sec-1") is True


def test_banco_indisponivel_devolve_a_flag_global(_banco, monkeypatch):
    """
    O módulo sumir porque o Supabase piscou seria queda de
    funcionalidade causada pela camada que organiza.
    """
    _banco["flags"]["price_research"] = True

    def cair():
        raise db.ErroBanco("sem banco")

    monkeypatch.setattr(db, "modulos_do_tenant", cair)
    assert db.modulo_disponivel("price_research") is True


# ---------------------------------------------------------------------------
# §39 — A NAVEGAÇÃO PASSOU A CONSULTAR DE FATO
# ---------------------------------------------------------------------------
def test_a_navegacao_nao_pode_voltar_a_olhar_so_a_flag():
    """
    A função existia e era código morto. Esta prova existe para que ela
    não volte a ser: se alguém trocar `modulo_disponivel_aqui` de volta
    por `flag_ativa`, a resolução de três níveis some sem aviso e o
    menu volta a ignorar o que a secretaria decidiu.
    """
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    for arquivo in ("precos_ui.py", "demanda_ui.py", "parecer_ui.py"):
        texto = (raiz / "src" / "ui" / arquivo).read_text(encoding="utf-8")
        corpo = texto.split("def disponivel()", 1)[1].split("\ndef ", 1)[0]
        assert "modulo_disponivel_aqui" in corpo, (
            f"{arquivo}: disponivel() deixou de consultar os três níveis")
        assert "flag_ativa" not in corpo, (
            f"{arquivo}: disponivel() voltou a olhar só a flag global")


def test_a_resolucao_por_sessao_nunca_derruba_a_navegacao(monkeypatch):
    """
    Navegação que quebra porque a resolução falhou é pior que navegação
    generosa demais: o servidor fica sem o menu INTEIRO em vez de sem
    um item.
    """
    def explodir(*_a, **_k):
        raise RuntimeError("banco caiu")

    monkeypatch.setattr(contexto, "contexto_institucional", explodir)
    monkeypatch.setattr(db, "modulo_disponivel", explodir)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)

    assert contexto.modulo_disponivel_aqui("price_research") is True


def test_a_secretaria_vem_da_sessao_e_nao_do_formulario(monkeypatch):
    """A regra do §4, que vale para esta camada também."""
    vistos = []
    monkeypatch.setattr(contexto, "contexto_institucional",
                        lambda: {"secretaria_id": "sec-da-sessao"})
    monkeypatch.setattr(db, "modulo_disponivel",
                        lambda m, s=None: vistos.append(s) or True)

    contexto.modulo_disponivel_aqui("price_research")
    assert vistos == ["sec-da-sessao"]


# ---------------------------------------------------------------------------
# §59 — AS TRÊS FLAGS DE SEÇÃO
# ---------------------------------------------------------------------------
@pytest.fixture
def _config(monkeypatch):
    valores: dict[str, str] = {}
    monkeypatch.setattr(db, "obter_config", lambda c: valores.get(c, ""))
    return valores


def test_secao_sem_flag_cadastrada_aparece(_config):
    """
    Ausente = liberada, ao contrário da `multi_prefeituras`.

    Quem ligou a aba decidiu usar a funcionalidade; fazer cada seção
    exigir uma segunda decisão transformaria o §59 num labirinto de
    caixas. Estas flags existem para DESLIGAR seção que ainda não está
    pronta.
    """
    assert instituicional.secoes_visiveis() == (
        "Prefeitura", "Timbrado", "Módulos", "Servidores", "Portarias")


@pytest.mark.parametrize("falso", ["0", "false", "FALSE", "off", "nao", "não"])
def test_a_secao_some_quando_alguem_desliga(_config, falso):
    _config["flag_servidores"] = falso
    assert "Servidores" not in instituicional.secoes_visiveis()
    assert "Portarias" in instituicional.secoes_visiveis()


def test_cada_flag_controla_a_sua_secao(_config):
    _config["flag_portarias"] = "0"
    secoes = instituicional.secoes_visiveis()
    assert "Portarias" not in secoes
    assert "Servidores" in secoes


def test_desligar_o_cadastro_institucional_leva_tambem_timbrado_e_modulos(
        _config):
    """
    Sem a seção Prefeitura, "Módulos" e "Timbrado" perdem o objeto: os
    dois configuram e exibem a prefeitura que aquela seção cadastra.
    """
    _config["flag_multi_tenant_admin"] = "0"
    secoes = instituicional.secoes_visiveis()
    assert "Prefeitura" not in secoes
    assert "Módulos" not in secoes
    assert "Timbrado" not in secoes


def test_tudo_desligado_devolve_vazio_e_a_tela_explica(_config):
    _config["flag_multi_tenant_admin"] = "0"
    _config["flag_servidores"] = "0"
    _config["flag_portarias"] = "0"
    assert instituicional.secoes_visiveis() == ()


# ---------------------------------------------------------------------------
# §13 — A PRÉ-VISUALIZAÇÃO DO TIMBRADO
# ---------------------------------------------------------------------------
def test_o_timbrado_tem_secao_propria():
    assert "Timbrado" in instituicional._SECOES_FIXAS


def test_a_previa_usa_o_resolvedor_existente_e_nao_uma_segunda_copia():
    """
    A herança secretaria → município → nenhuma já existia em
    `contexto.resolver_identidade`, testada e usada pela exportação.

    Se esta tela implementasse a própria versão da regra, as duas
    divergiriam — e a tela mostraria um timbrado diferente do que o PDF
    usaria, que é o oposto do que uma pré-visualização serve para fazer.
    """
    from pathlib import Path

    fonte = (Path(__file__).resolve().parent.parent / "src" / "ui" /
             "instituicional.py").read_text(encoding="utf-8")
    corpo = fonte.split("def _render_timbrado()", 1)[1].split("\ndef _previa",
                                                              1)[0]
    assert "contexto.resolver_identidade" in corpo, (
        "a prévia deixou de usar o resolvedor compartilhado")


@pytest.mark.parametrize("origem,esperado", [
    ("secretaria", "success"),
    ("municipio", "info"),
    ("nenhuma", "warning"),
])
def test_a_previa_nomeia_a_origem_da_identidade(monkeypatch, origem, esperado):
    """
    "Herdado do município" e "identidade própria" levam a ações
    diferentes do administrador. Mostrar a imagem sem dizer de ONDE ela
    veio esconderia justamente a informação que a tela existe para dar.
    """
    chamadas: list[str] = []
    for metodo in ("success", "info", "warning", "error", "caption",
                   "markdown", "text", "image", "divider"):
        monkeypatch.setattr(instituicional.st, metodo,
                            (lambda m: lambda *a, **k: chamadas.append(m))(metodo))
    monkeypatch.setattr(instituicional.st, "selectbox",
                        lambda *a, **k: "sec-1")
    monkeypatch.setattr(db, "listar_secretarias",
                        lambda *a, **k: [{"id": "sec-1", "nome": "SEMAD"}])
    monkeypatch.setattr(contexto, "resolver_identidade",
                        lambda s, i: ({"cabecalho": "X"}, origem))

    instituicional._render_timbrado()
    assert esperado in chamadas


def test_sem_identidade_nenhuma_a_previa_nao_desenha_nada(monkeypatch):
    """Avisar e parar. Desenhar caixa vazia sugeriria que há algo lá."""
    imagens: list = []
    for metodo in ("success", "info", "warning", "error", "caption",
                   "markdown", "text", "divider"):
        monkeypatch.setattr(instituicional.st, metodo, lambda *a, **k: None)
    monkeypatch.setattr(instituicional.st, "image",
                        lambda *a, **k: imagens.append(a))
    monkeypatch.setattr(instituicional.st, "selectbox",
                        lambda *a, **k: "sec-1")
    monkeypatch.setattr(db, "listar_secretarias",
                        lambda *a, **k: [{"id": "sec-1", "nome": "SEMED"}])
    monkeypatch.setattr(contexto, "resolver_identidade",
                        lambda s, i: (None, "nenhuma"))

    instituicional._render_timbrado()
    assert imagens == []
