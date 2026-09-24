"""
Homologação e produção: o que as separa, e o que NÃO as separa.

O QUE O OPERADOR DECIDIU, EM 19/09/2026

1. o Streamlit Cloud fica no ar depois da migração para o VPS, para
   conferir alterações antes de promovê-las;
2. ele continua apontando para o **banco de produção**;
3. a homologação acompanha `main`; a produção só se move por TAG.

A decisão (2) é a que estas provas precisam tornar impossível de
esquecer. Com ela, o Streamlit **não é** um ambiente de teste: é um
segundo acesso a produção com outra URL. Processo criado ali é real,
documento aprovado congela assinatura real, evento entra na trilha —
que a 0027 tornou não-apagável pela credencial do app —, e flag ligada
ali vale para todo mundo, porque `config_app` não tem escopo por
instalação.

Nada disso é impedido por código, e não deveria ser: um "modo seguro"
que desligasse escrita seria uma segunda verdade sobre o que o sistema
faz, e divergiria da primeira no primeiro caminho esquecido. O que dá
para fazer é NÃO DEIXAR NINGUÉM SE ENGANAR, e é isso que se mede aqui.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src import ambiente

RAIZ = Path(__file__).resolve().parent.parent
PROMOVER = RAIZ / "implantacao" / "promover.sh"


# ---------------------------------------------------------------------------
# 1) O DEFAULT É PRODUÇÃO — e a direção do default é a decisão
# ---------------------------------------------------------------------------
def test_instalacao_que_nao_se_declara_e_tratada_como_producao(monkeypatch):
    """
    Ausente → produção, nunca o contrário.

    Uma instalação que esqueceu de se declarar deve ser tratada como a
    mais séria, não como a menos. O default invertido faria uma
    produção recém-subida, antes de alguém preencher a variável, se
    apresentar como homologação — e aí o aviso que protege passa a
    mentir na direção perigosa.
    """
    monkeypatch.delenv(ambiente.VARIAVEL, raising=False)
    assert ambiente.atual() == ambiente.PRODUCAO


@pytest.mark.parametrize("lixo", ["", "   ", "teste", "staging", "PROD", "1"])
def test_valor_desconhecido_tambem_cai_em_producao(monkeypatch, lixo):
    """Erro de digitação não pode rebaixar a instalação."""
    monkeypatch.setenv(ambiente.VARIAVEL, lixo)
    assert ambiente.atual() == ambiente.PRODUCAO


def test_homologacao_precisa_ser_declarada_explicitamente(monkeypatch):
    monkeypatch.setenv(ambiente.VARIAVEL, "homologacao")
    assert ambiente.atual() == ambiente.HOMOLOGACAO
    monkeypatch.setenv(ambiente.VARIAVEL, "  HOMOLOGACAO  ")
    assert ambiente.atual() == ambiente.HOMOLOGACAO


# ---------------------------------------------------------------------------
# 2) O AVISO DIZ A VERDADE INCÔMODA
# ---------------------------------------------------------------------------
def test_producao_nao_desenha_tarja(monkeypatch):
    """Tarja em toda tela vira moldura, e moldura ninguém lê."""
    chamadas = []
    monkeypatch.setenv(ambiente.VARIAVEL, "producao")
    monkeypatch.setattr(ambiente.st, "error",
                        lambda *a, **k: chamadas.append(a))
    monkeypatch.setattr(ambiente.st, "info",
                        lambda *a, **k: chamadas.append(a))
    ambiente.render_aviso()
    assert chamadas == []


def test_a_tarja_da_homologacao_avisa_que_o_banco_e_o_de_producao(monkeypatch):
    """
    ESTA É A PROVA QUE JUSTIFICA O MÓDULO.

    Enquanto a homologação compartilhar o banco, a tarja precisa dizer
    isso com todas as letras — e precisa ser `error`, não `info`. O
    risco aqui não é alguém achar que está em produção quando não está;
    é o contrário, e é por isso que o tom importa.
    """
    monkeypatch.setenv(ambiente.VARIAVEL, "homologacao")
    erros, infos = [], []
    monkeypatch.setattr(ambiente.st, "error", lambda t, **k: erros.append(t))
    monkeypatch.setattr(ambiente.st, "info", lambda t, **k: infos.append(t))

    ambiente.render_aviso()

    assert len(erros) == 1 and not infos, (
        "a tarja saiu como aviso brando — o risco é o operador achar "
        "que está num ambiente isolado quando não está")
    texto = erros[0].lower()
    assert "produção" in texto or "producao" in texto
    assert "flag" in texto, (
        "a tarja não avisa que flag ligada aqui muda produção, que é a "
        "armadilha mais fácil de cair")


def test_a_tarja_muda_quando_o_banco_deixar_de_ser_compartilhado(monkeypatch):
    """
    O dia em que a homologação ganhar banco próprio, a tarja precisa
    parar de assustar — senão vira ruído e ensina a ignorar.

    A prova existe para que essa transição seja UMA linha em
    `grava_em_producao()` com um teste que já a descreve, e não uma
    caçada por todo lugar que assumiu a coincidência.
    """
    monkeypatch.setenv(ambiente.VARIAVEL, "homologacao")
    monkeypatch.setattr(ambiente, "grava_em_producao", lambda: False)
    erros, infos = [], []
    monkeypatch.setattr(ambiente.st, "error", lambda t, **k: erros.append(t))
    monkeypatch.setattr(ambiente.st, "info", lambda t, **k: infos.append(t))

    ambiente.render_aviso()
    assert not erros and len(infos) == 1


def _com_url(monkeypatch, url: str):
    from src import db

    monkeypatch.setattr(
        db, "_segredo",
        lambda nome, _u=url: _u if nome == "SUPABASE_URL" else "")


@pytest.mark.parametrize("url", [
    "https://umprojeto.supabase.co",
    "https://banco.prefeitura.gov.br",
    "",                                   # sem configuração declarada
    "://url torta",                       # nem dá para ler o host
])
def test_o_que_nao_se_prova_separado_conta_como_producao(monkeypatch, url):
    """
    Guarda contra otimismo, e é a metade que importa da decisão.

    "Não é o projeto de produção" NÃO é a mesma coisa que "é um banco
    separado": o Streamlit Cloud aponta para produção e tem URL de
    `supabase.co` como qualquer outro projeto. Enquanto a separação não
    estiver PROVADA, a tarja precisa dizer a verdade mais séria — senão
    ela passa a anunciar "não alcança produção" e convida ao erro exato
    que existe para evitar.
    """
    _com_url(monkeypatch, url)
    assert ambiente.grava_em_producao() is True


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:3001",
    "http://localhost:3001",
    "http://[::1]:3001",
    "HTTP://LocalHost:3001/",
])
def test_loopback_prova_que_o_banco_nao_e_o_de_producao(monkeypatch, url):
    """
    Nada que responda em loopback é o banco da Prefeitura. É a única
    separação que a aplicação consegue provar sozinha, e é a que a pilha
    de homologação local usa.

    Até a auditoria pré-operacional de 24/09/2026 isto devolvia True sem
    condição, e a tarja MENTIA numa instalação isolada: anunciava "o
    banco é o de PRODUÇÃO" para quem estava num Postgres descartável.
    Aviso que erra desse lado ensina a ignorá-lo — e é o mesmo aviso que
    precisa ser levado a sério quando a instalação de fato escreve em
    produção.
    """
    _com_url(monkeypatch, url)
    assert ambiente.grava_em_producao() is False


# ---------------------------------------------------------------------------
# 3) O APP DESENHA A TARJA ANTES DA TELA DE TRABALHO
# ---------------------------------------------------------------------------
def test_o_app_chama_o_aviso_depois_do_cabecalho_e_antes_do_wizard():
    """
    Ordem é o conteúdo: depois do cabeçalho para não competir com ele,
    e antes de qualquer página para que ninguém clique sem saber onde
    está.
    """
    app = (RAIZ / "app.py").read_text(encoding="utf-8")
    assert "ambiente.render_aviso()" in app, "o app não desenha a tarja"

    pos_aviso = app.index("ambiente.render_aviso()")
    pos_cabecalho = app.index("components.render_cabecalho()")
    pos_pagina = app.index('pagina = st.session_state.get("pagina"')
    assert pos_cabecalho < pos_aviso < pos_pagina, (
        "a tarja saiu de posição: precisa vir depois do cabeçalho e "
        "antes da navegação por página")


# ---------------------------------------------------------------------------
# 4) A PROMOÇÃO É POR TAG, E CONFERE ANTES DE MEXER
# ---------------------------------------------------------------------------
def _promover() -> str:
    assert PROMOVER.exists(), "o script de promoção sumiu"
    return PROMOVER.read_text(encoding="utf-8")


def test_o_script_de_promocao_e_executavel():
    import os
    assert os.access(PROMOVER, os.X_OK), (
        "promover.sh não tem bit de execução — quem seguir o runbook "
        "esbarra num 'permission denied'")


def test_a_promocao_recusa_tag_inexistente_antes_de_tocar_no_servico():
    """
    Sem esta checagem, um erro de digitação derruba o serviço e só se
    descobre no `docker compose up` seguinte, com o app fora do ar.

    A ordem no arquivo é o que importa: a verificação vem ANTES do
    `git checkout`.
    """
    texto = _promover()
    assert "rev-parse -q --verify" in texto, (
        "a promoção não confere se a tag existe")
    assert texto.index("rev-parse -q --verify") < texto.index("git checkout"), (
        "a conferência da tag vem DEPOIS do checkout — tarde demais")


def test_a_promocao_guarda_a_versao_anterior_antes_de_trocar():
    """
    "Qual era mesmo a versão de ontem?" não é pergunta para se
    responder de memória no meio de um incidente.
    """
    texto = _promover()
    assert "ANTERIOR=" in texto
    assert texto.index("ANTERIOR=") < texto.index("git checkout"), (
        "a versão anterior é capturada depois do checkout, quando já "
        "não dá para saber qual era")


def test_a_promocao_so_declara_sucesso_quando_o_app_responde():
    """
    `docker compose up` devolve o controle quando os contentores foram
    criados, não quando o aplicativo está servindo. Declarar sucesso
    ali é declarar cedo demais — e a diferença aparece justamente no
    dia em que a versão nova não sobe.
    """
    texto = _promover()
    assert "_stcore/health" in texto, (
        "a promoção não confere se o app respondeu depois de subir")
    assert texto.index("docker compose up") < texto.index("_stcore/health")


def test_a_promocao_ensina_o_caminho_de_volta():
    texto = _promover()
    assert re.search(r"para voltar.*\$ANTERIOR", texto), (
        "a mensagem de falha não diz como voltar para a versão anterior")


def test_a_promocao_nao_segue_main():
    """
    Produção seguir `main` anularia a decisão inteira: a homologação
    acompanha `main`, e não haveria intervalo nenhum entre uma e outra.
    """
    texto = _promover()
    assert "git pull" not in texto, (
        "o script faz `git pull` — produção voltaria a seguir o branch, "
        "e a janela de conferência deixaria de existir")
    assert "checkout --detach" in texto
