"""
Contenção P0 — testes.

Três grupos:

  * CREDENCIAL E MANUTENÇÃO (locais): a credencial atual
    `SUPABASE_SECRET_KEY` tem prioridade, a `service_role` legada é
    aceita só com aviso de descontinuação, e a ausência da credencial
    obrigatória coloca o app em MANUTENÇÃO — sem operação degradada
    "sem persistência" e sem fallback para a chave publicável;

  * REDAÇÃO E CORRELAÇÃO (locais): a interface recebe mensagem genérica
    com identificador de correlação, e o log recebe o texto já
    sanitizado — em URL, querystring, cabeçalho, JSON, multilinha e
    valores codificados;

  * CONTRA BANCO (pulados por padrão): provam que `anon` não lê nem
    escreve nas tabelas privadas. Só rodam com um projeto de ENSAIO
    apontado por GOVDOCS_ENSAIO_URL/GOVDOCS_ENSAIO_ANON_KEY — nunca
    contra produção. Ver scripts/ensaio_seguranca.py.

Nenhum teste imprime valor de credencial, hash ou dado pessoal: os
valores usados aqui são literais falsos, criados no próprio arquivo.
"""

import ast
import base64
import json
import hashlib
import logging
import os
import re
import sys
import types
import uuid
from pathlib import Path

import pytest

from src import auth, db

# ---------------------------------------------------------------------------
# Grupo 1 — credencial de servidor e modo de manutenção (local, sem rede)
# ---------------------------------------------------------------------------
def _jwt(payload, cabecalho=None) -> str:
    """
    Monta um JWT de teste. A assinatura é decorativa — e é justamente
    esse o ponto: o que decide não é a forma, é o `role` do payload.
    """
    def _b64(dado) -> str:
        if isinstance(dado, (dict, list)):
            dado = json.dumps(dado).encode()
        elif isinstance(dado, str):
            dado = dado.encode()
        return base64.urlsafe_b64encode(dado).decode().rstrip("=")

    cabecalho = cabecalho or {"alg": "HS256", "typ": "JWT"}
    return f"{_b64(cabecalho)}.{_b64(payload)}.assinatura-de-teste"


def _montar(*pedacos: str) -> str:
    """
    Junta fragmentos que, sozinhos, não casam padrão nenhum.

    O disco não guarda o token contíguo; a memória, sim. É a mesma
    disciplina de `tests/test_varredura_segredos.py`, e ela chegou aqui
    pelo caminho mais didático: o Push Protection do GitHub RECUSOU o
    push por causa das linhas que estes `_montar` substituem.

    Ele estava certo. Bloqueia por PADRÃO, não por veracidade — não tem
    como saber que a chave é inventada, e não deve acreditar na palavra
    de quem empurra. Pedir exceção ao scanner seria repetir, na porta
    do repositório, o defeito que esta suíte inteira existe para
    apontar: o segredo de mentira ensinando todo mundo a desligar o
    alarme.
    """
    return "".join(pedacos)


CHAVE_FALSA_ATUAL = _montar("sb_", "secret_", "credencial-de-teste-jamais-real")
# A `service_role` legada é um JWT que DECLARA o papel. A falsa precisa
# declarar o mesmo, senão o teste passa por um motivo diferente do que
# afirma medir.
CHAVE_FALSA_LEGADA = _jwt({"role": "service_role", "iss": "supabase"})
CHAVE_FALSA_PUBLICA = _montar("sb_", "publishable_",
                              "credencial-de-teste-publica")


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Isola o teste de secrets/ambiente reais da máquina."""
    for nome in (db.NOME_CHAVE_SERVIDOR, db.NOME_CHAVE_SERVIDOR_LEGADA,
                 db.NOME_CHAVE_PUBLICA, db.FLAG_EXIGIR_SERVIDOR,
                 "SUPABASE_URL", "GOVDOCS_MODO_ABERTO"):
        monkeypatch.delenv(nome, raising=False)
    monkeypatch.setattr(db.st, "secrets", {}, raising=False)


def _producao(monkeypatch):
    """Produção = falha fechada ligada, com URL configurada."""
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.FLAG_EXIGIR_SERVIDOR, "1")


@pytest.fixture()
def sem_sonda(monkeypatch):
    """
    Desliga a sonda remota EXPLICITAMENTE.

    Em produção ela é obrigatória — e é isso que faz estes testes de
    FORMATO precisarem declarar que não a exercitam. Sem a declaração
    eles abririam conexão de verdade, que é justamente o que a sonda
    obrigatória garante.
    """
    monkeypatch.setenv(db.FLAG_SONDAR_CREDENCIAL, "0")


def test_credencial_atual_tem_prioridade_sobre_a_publica(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    _, chave = db._config()
    assert chave == CHAVE_FALSA_ATUAL


def test_credencial_atual_tem_prioridade_sobre_a_legada(monkeypatch):
    """A `service_role` legada é o último recurso, nunca o preferido."""
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, CHAVE_FALSA_LEGADA)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    _, chave = db._config()
    assert chave == CHAVE_FALSA_ATUAL
    assert db.avisos_de_credencial() == []


def test_service_role_legada_funciona_com_aviso_de_descontinuacao(monkeypatch):
    """Transição: aceita, mas o administrador é avisado — sem o valor."""
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, CHAVE_FALSA_LEGADA)
    _, chave = db._config()
    assert chave == CHAVE_FALSA_LEGADA
    avisos = db.avisos_de_credencial()
    assert len(avisos) == 1
    texto = " ".join(avisos)
    assert db.NOME_CHAVE_SERVIDOR in texto          # aponta o substituto
    assert CHAVE_FALSA_LEGADA not in texto          # jamais o valor
    assert db.em_manutencao() is False              # a legada não derruba o app


# ---------------------------------------------------------------------------
# Achado 5 — "presente" não é "válida"
#
# Antes, qualquer valor não vazio em SUPABASE_SECRET_KEY satisfazia a
# falha fechada. Uma chave publicável colada no campo errado subia o
# app conectado como ANÔNIMO — exatamente o que a falha fechada existe
# para impedir —, e o erro só apareceria depois, disfarçado de
# "permissão negada" no meio de uma operação de negócio.
# ---------------------------------------------------------------------------
CREDENCIAIS_INVALIDAS = {
    "chave publicável no campo errado":
        CHAVE_FALSA_PUBLICA,
    "valor aleatório": "uma-coisa-qualquer-que-alguem-digitou",
    "placeholder": "sb_secret_",
    "prefixo certo mas curta demais": "sb_secret_abc",
    "JWT no campo da secreta": ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                                "cGF5bG9hZC1kZS10ZXN0ZQ.assinatura-de-teste"),
    "espaço em branco": "   ",
}


@pytest.mark.parametrize("caso", sorted(CREDENCIAIS_INVALIDAS))
def test_credencial_mal_formada_mantem_o_app_em_manutencao(monkeypatch, caso):
    valor = CREDENCIAIS_INVALIDAS[caso]
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, valor)
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)

    assert db.em_manutencao() is True, caso
    assert db.credencial_de_servidor_valida() is False, caso
    assert db.disponivel() is False, caso
    with pytest.raises(db.ErroBanco):
        db.exigir_operacional()
    # e jamais cai para a publicável
    with pytest.raises(db.ErroBanco):
        db._config()


@pytest.mark.parametrize("caso", sorted(CREDENCIAIS_INVALIDAS))
def test_o_motivo_explica_sem_ecoar_o_valor(monkeypatch, caso):
    valor = CREDENCIAIS_INVALIDAS[caso]
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, valor)
    motivo = db.motivo_de_manutencao()
    assert motivo
    if valor.strip():           # "" está contido em tudo: não prova nada
        assert valor.strip() not in motivo, motivo


def test_credencial_publicavel_e_nomeada_no_motivo(monkeypatch):
    """O erro mais provável merece a mensagem mais direta."""
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_PUBLICA)
    motivo = db.motivo_de_manutencao()
    assert "PUBLICÁVEL" in motivo
    assert db.PREFIXO_CHAVE_PUBLICA in motivo


def test_credencial_valida_continua_operando(monkeypatch, sem_sonda):
    """A validação não pode transformar chave boa em manutenção."""
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    assert db.credencial_de_servidor_valida() is True
    assert db.em_manutencao() is False
    assert db.disponivel() is True


# ---------------------------------------------------------------------------
# Achado 2 — o papel do JWT legado, não a forma dele
# ---------------------------------------------------------------------------
JWT_SERVICE_ROLE = CHAVE_FALSA_LEGADA


def test_service_role_legada_valida_continua_aceita(monkeypatch, sem_sonda):
    """A transição não pode ser quebrada pela validação."""
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, JWT_SERVICE_ROLE)
    assert db.credencial_de_servidor_valida() is True
    assert db.em_manutencao() is False
    assert len(db.avisos_de_credencial()) == 1     # segue avisando


JWTS_SEM_PRIVILEGIO = {
    "role=anon": _jwt({"role": "anon", "iss": "supabase"}),
    "role=authenticated": _jwt({"role": "authenticated"}),
    "sem claim role": _jwt({"iss": "supabase", "exp": 9999999999}),
    "role não textual": _jwt({"role": ["service_role"]}),
    "payload não é objeto": _jwt(["service_role"]),
    "payload não é JSON": _jwt("service_role"),
    "payload não é base64": "eyJhbGciOiJIUzI1NiJ9.@@@nao-e-base64@@@.assin",
    "forma de JWT sem partes": "eyJhbGciOiJIUzI1NiJ9.soduaspartes",
}


@pytest.mark.parametrize("caso", sorted(JWTS_SEM_PRIVILEGIO))
def test_jwt_legado_sem_service_role_mantem_manutencao(monkeypatch, caso):
    """
    Regressão do achado: a forma do JWT estava certa e a forma era tudo
    que se conferia. Um `role: anon` bem formado passava como credencial
    de servidor, e o app subia com privilégio de anônimo acreditando ser
    servidor.
    """
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA,
                       JWTS_SEM_PRIVILEGIO[caso])
    assert db.credencial_de_servidor_valida() is False, caso
    assert db.em_manutencao() is True, caso
    assert db.disponivel() is False, caso
    with pytest.raises(db.ErroBanco):
        db._config()


def test_o_motivo_nomeia_o_papel_mas_nao_o_jwt(monkeypatch):
    _producao(monkeypatch)
    jwt_anon = JWTS_SEM_PRIVILEGIO["role=anon"]
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, jwt_anon)
    motivo = db.motivo_de_manutencao()
    assert "role=anon" in motivo            # o diagnóstico que se precisa
    assert jwt_anon not in motivo           # jamais a chave
    assert "eyJ" not in motivo              # nem pedaço dela


def test_o_payload_do_jwt_nunca_vai_para_o_log(monkeypatch, caplog):
    _producao(monkeypatch)
    segredo_no_payload = "tenant-secreto-que-nao-pode-vazar"
    jwt = _jwt({"role": "anon", "nota": segredo_no_payload})
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, jwt)
    with caplog.at_level(logging.DEBUG):
        db.motivo_de_manutencao()
        db.em_manutencao()
        db.credencial_de_servidor_valida()
    assert segredo_no_payload not in caplog.text
    assert jwt not in caplog.text


def test_papel_do_jwt_devolve_vazio_sem_explodir():
    for entrada in ("", "x", "a.b", "a.b.c.d", "eyJ.eyJ.x"):
        assert db._papel_do_jwt(entrada) == ""


def test_legada_mal_formada_tambem_derruba(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR_LEGADA, "nao-e-um-jwt")
    assert db.em_manutencao() is True


# ---------------------------------------------------------------------------
# Achado 2b — formato não é validade: a sonda remota
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def sonda_limpa():
    """O cache da sonda não pode atravessar testes."""
    db._sonda_bem_sucedida.clear()
    yield
    db._sonda_bem_sucedida.clear()


def _com_sonda(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.FLAG_SONDAR_CREDENCIAL, "1")
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)


@pytest.mark.parametrize("falha", [
    "permission denied for table config_app",       # sem privilégio
    "Invalid API key",                              # incorreta
    '{"code":"PGRST301","message":"JWT expired"}',  # revogada
    "401 Unauthorized",
])
def test_credencial_sem_privilegio_mantem_falha_fechada(monkeypatch, falha):
    """
    Formato não é validade. Uma `sb_secret_…` impecável pode estar
    revogada, ter sido copiada errada ou ser de outro projeto — e nada
    disso aparece olhando a string.
    """
    _com_sonda(monkeypatch)

    def explode(*_a, **_k):
        raise RuntimeError(falha)

    monkeypatch.setitem(sys.modules, "supabase", type(sys)("supabase"))
    sys.modules["supabase"].create_client = explode

    assert db.em_manutencao() is True, falha
    assert db.disponivel() is False


def test_sonda_bem_sucedida_libera_o_app(monkeypatch):
    _com_sonda(monkeypatch)
    pedidos = []

    class _Alvo:
        def select(self, *a, **k): pedidos.append(("select", a, k)); return self
        def limit(self, n): pedidos.append(("limit", n)); return self
        def execute(self): return type("R", (), {"data": []})()

    class _Cliente:
        def table(self, nome): pedidos.append(("table", nome)); return _Alvo()

    monkeypatch.setitem(sys.modules, "supabase", type(sys)("supabase"))
    sys.modules["supabase"].create_client = lambda *a, **k: _Cliente()

    assert db.em_manutencao() is False
    assert ("table", db.TABELA_DA_SONDA) in pedidos
    assert ("limit", 0) in pedidos          # ZERO linhas: nada é revelado


def test_a_sonda_desligada_nao_faz_rede(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    monkeypatch.setenv(db.FLAG_SONDAR_CREDENCIAL, "0")

    def explode(*_a, **_k):
        raise AssertionError("sonda desligada não pode abrir conexão")

    monkeypatch.setitem(sys.modules, "supabase", type(sys)("supabase"))
    sys.modules["supabase"].create_client = explode
    assert db.em_manutencao() is False


def test_a_sonda_nao_registra_a_credencial(monkeypatch, caplog):
    _com_sonda(monkeypatch)

    def explode(*_a, **_k):
        raise RuntimeError(f"401 com apikey={CHAVE_FALSA_ATUAL}")

    monkeypatch.setitem(sys.modules, "supabase", type(sys)("supabase"))
    sys.modules["supabase"].create_client = explode

    with caplog.at_level(logging.DEBUG):
        motivo = db.motivo_de_manutencao()
    assert CHAVE_FALSA_ATUAL not in caplog.text
    assert CHAVE_FALSA_ATUAL not in motivo
    assert "Referência:" in motivo


def test_formato_invalido_nao_chega_a_sondar(monkeypatch):
    """Sem formato válido não há o que sondar — e nem se abre conexão."""
    _producao(monkeypatch)
    monkeypatch.setenv(db.FLAG_SONDAR_CREDENCIAL, "1")
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_PUBLICA)

    def explode(*_a, **_k):
        raise AssertionError("sondou uma credencial de formato inválido")

    monkeypatch.setitem(sys.modules, "supabase", type(sys)("supabase"))
    sys.modules["supabase"].create_client = explode
    assert db.em_manutencao() is True


def test_fora_de_producao_a_validacao_nao_bloqueia(monkeypatch):
    """
    Sem a falha fechada ligada (desenvolvimento), o formato não derruba
    o app — só produção exige credencial de servidor.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, "qualquer-coisa-local")
    assert db.em_manutencao() is False
    assert db.disponivel() is True


def test_sem_falha_fechada_cai_para_a_chave_publica(monkeypatch):
    """Compatibilidade de desenvolvimento — nunca em produção."""
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    assert not db.exigir_credencial_servidor()
    assert db.em_manutencao() is False
    _, chave = db._config()
    assert chave == CHAVE_FALSA_PUBLICA


def test_falha_fechada_recusa_a_chave_publica(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    with pytest.raises(db.ErroBanco) as erro:
        db._config()
    mensagem = str(erro.value)
    # a mensagem orienta sem vazar valor algum
    assert db.NOME_CHAVE_SERVIDOR in mensagem
    assert CHAVE_FALSA_PUBLICA not in mensagem
    assert CHAVE_FALSA_ATUAL not in mensagem


def test_credencial_de_servidor_satisfaz_a_falha_fechada(monkeypatch, sem_sonda):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    assert db.credencial_de_servidor_presente() is True
    assert db.em_manutencao() is False
    assert db.disponivel() is True


def test_diagnostico_e_booleano_nunca_o_valor(monkeypatch):
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    resultado = db.credencial_de_servidor_presente()
    assert resultado is True
    assert not isinstance(resultado, str)


def test_a_credencial_nunca_vem_do_banco(monkeypatch):
    """A credencial do banco não pode depender do banco."""
    def explode(*_a, **_k):
        raise AssertionError("_segredo consultou o banco")

    monkeypatch.setattr(db, "obter_config", explode, raising=False)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    assert db._segredo(db.NOME_CHAVE_SERVIDOR) == CHAVE_FALSA_ATUAL


# ---------------------------------------------------------------------------
# Grupo 1b — manutenção fecha TUDO (o "sem persistência" era o furo)
# ---------------------------------------------------------------------------
def test_sem_credencial_em_producao_o_app_entra_em_manutencao(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    assert db.em_manutencao() is True
    motivo = db.motivo_de_manutencao()
    assert db.NOME_CHAVE_SERVIDOR in motivo
    assert CHAVE_FALSA_PUBLICA not in motivo


def test_manutencao_bloqueia_a_conexao(monkeypatch):
    """Nem o cliente é construído — logo não há operação com a anon."""
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    with pytest.raises(db.ErroBanco):
        db.exigir_operacional()
    assert db.disponivel() is False


def test_manutencao_bloqueia_o_login(monkeypatch):
    _producao(monkeypatch)
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    with pytest.raises(auth.ErroAuth):
        auth.autenticar("qualquer", "coisa")
    with pytest.raises(auth.ErroAuth):
        auth.criar_usuario("Fulano", "fulano", "senha-de-teste", "admin")


def test_manutencao_nao_vira_modo_aberto(monkeypatch):
    """
    O furo mais perigoso: `disponivel()` False + GOVDOCS_MODO_ABERTO=1
    liberaria o app INTEIRO sem login, justamente durante a contenção.
    """
    _producao(monkeypatch)
    monkeypatch.setenv("GOVDOCS_MODO_ABERTO", "1")
    assert auth.modo_aberto() is False
    assert auth.eh_admin() is False


def test_manutencao_bloqueia_a_emissao(monkeypatch):
    from src.ui import revisao

    _producao(monkeypatch)
    # gate desligado: sem a checagem de manutenção, isto liberaria tudo
    monkeypatch.setattr(revisao.db, "flag_ativa", lambda n: False)
    liberada, motivo = revisao.emissao_liberada({"dfd": "## 1. OBJETO\n\nx\n"})
    assert liberada is False
    assert db.NOME_CHAVE_SERVIDOR in motivo


def test_manutencao_bloqueia_a_aprovacao(monkeypatch):
    import streamlit as st

    from src import state

    _producao(monkeypatch)
    registrados: list[str] = []
    monkeypatch.setattr(st, "error", registrados.append)
    st.session_state["documentos"] = {"dfd": "texto"}
    st.session_state["aprovados"] = set()
    st.session_state["etapa"] = 1
    state.aprovar_e_avancar("dfd", "texto editado")
    assert "dfd" not in st.session_state["aprovados"]   # não aprovou
    assert st.session_state["etapa"] == 1               # não avançou
    assert registrados and db.NOME_CHAVE_SERVIDOR in registrados[0]


# ---------------------------------------------------------------------------
# Grupo 2 — redação e identificador de correlação (local, sem rede)
# ---------------------------------------------------------------------------
JWT_FALSO = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
             "cGF5bG9hZC1kZS10ZXN0ZQ.assinatura-de-teste")


def test_interface_recebe_mensagem_generica_com_referencia():
    """
    A defesa principal não é a expressão regular: é a interface nunca
    receber o texto original. Mesmo um segredo em formato desconhecido
    fica retido.
    """
    inedito = "FORMATO-DE-CREDENCIAL-QUE-AINDA-NAO-EXISTE-2099"
    traduzido = str(db._traduzir_erro(Exception(f"boom {inedito}")))
    assert inedito not in traduzido
    assert "Referência:" in traduzido


def test_referencia_e_unica_por_incidente():
    a = str(db._traduzir_erro(Exception("falha A")))
    b = str(db._traduzir_erro(Exception("falha B")))
    assert a != b   # identificadores distintos casam com linhas distintas


def test_log_recebe_o_texto_ja_sanitizado(caplog):
    with caplog.at_level(logging.ERROR):
        correlacao = db.registrar_incidente(
            Exception(f"GET /rest/v1/usuarios?apikey={JWT_FALSO} 401"))
    assert correlacao in caplog.text          # dá para casar tela e log
    assert JWT_FALSO not in caplog.text       # sem o segredo
    assert "usuarios" in caplog.text          # com a parte útil


@pytest.mark.parametrize("bruto", [
    # querystring
    f"GET /rest/v1/usuarios?apikey={JWT_FALSO}&select=* 500",
    # cabeçalho
    f"Authorization: Bearer {JWT_FALSO}",
    # cabeçalho em outra caixa, com aspas
    f'headers={{"apiKey": "{JWT_FALSO}"}}',
    # corpo JSON
    f'{{"error":"invalid","apikey":"{JWT_FALSO}","hint":null}}',
    # multilinha (traceback)
    f"Traceback:\n  File 'x.py'\n    apikey={JWT_FALSO}\n  KeyError",
    # percent-encoded (URL escapada dentro da mensagem)
    f"falha em https%3A%2F%2Fx%2Frest%2Fv1%3Fapikey%3D{JWT_FALSO}",
    # credencial embutida na URL
    "postgres://usuario:senha-super-secreta@db.exemplo.supabase.co:5432",
    # chave secreta atual
    _montar("recusada: sb_", "secret_", "ABCDEFGH12345678IJKLMNOP"),
    # chave publicável
    _montar("usando sb_", "publishable_", "ABCDEFGH12345678IJKLMNOP"),
    # chave de IA
    _montar("openai 401 sk-", "proj-", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
    _montar("google 400 AIza", "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"),
    # hash de senha
    "payload: senha_hash: pbkdf2_sha256$200000$sal$hashdasenha",
    # valor opaco longo, sem rótulo algum
    "resposta: QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5MA==",
])
def test_redacao_cobre_todas_as_formas(bruto):
    limpo = db.redigir(bruto)
    for segredo in (JWT_FALSO,
                    _montar("sb_", "secret_", "ABCDEFGH12345678IJKLMNOP"),
                    _montar("sb_", "publishable_",
                            "ABCDEFGH12345678IJKLMNOP"),
                    _montar("sk-", "proj-",
                            "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"),
                    _montar("AIza", "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456"),
                    "pbkdf2_sha256$200000$sal$hashdasenha",
                    "senha-super-secreta",
                    "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVowMTIzNDU2Nzg5MA"):
        assert segredo not in limpo, f"vazou em: {limpo}"


def test_redacao_esconde_a_referencia_do_projeto():
    """A referência identifica a instalação; não ajuda o usuário final."""
    referencia = "abcdefghijklmnopqrst"          # fictícia, 20 caracteres
    limpo = db.redigir(f"timeout em https://{referencia}.supabase.co")
    assert referencia not in limpo
    assert "timeout em" in limpo


def test_a_guarda_do_ensaio_recusa_producao_sem_publicar_a_referencia(
        monkeypatch, ensaio_declarado):
    """
    O repositório é público: gravar aqui o identificador da instalação
    entrega o alvo a quem varrer o GitHub. A guarda compara por hash e
    continua recusando produção.
    """
    import ensaio_seguranca as ensaio

    referencia = "referenciaficticiadeproducao"
    monkeypatch.setattr(
        ensaio, "_HASH_PROJETO_PRODUCAO",
        hashlib.sha256(referencia.encode()).hexdigest())

    # `_e_producao` compara REFERÊNCIA, não URL: a extração vem antes,
    # e é ela que canonicaliza caixa e IDNA.
    assert ensaio._e_producao(referencia) is True
    assert ensaio._e_producao("umensaioqualquer") is False
    with pytest.raises(ProducaoRecusada):
        ensaio.exigir_ensaio(f"https://{referencia}.supabase.co")
    assert ensaio.exigir_ensaio("https://umensaioqualquer.supabase.co")


def test_o_script_de_ensaio_nao_publica_a_referencia_de_producao():
    """Nenhuma referência de projeto em texto claro no repositório."""
    fonte = (Path(__file__).resolve().parent.parent
             / "scripts" / "ensaio_seguranca.py").read_text()
    assert not re.search(r"\b[a-z]{18,24}\.supabase\.co", fonte), fonte
    assert not re.search(r'PROJETO_PRODUCAO\s*=\s*"[a-z]{15,}"', fonte)


# ---------------------------------------------------------------------------
# Achado 1 — a guarda de produção vale para os TESTES, não só o script
# ---------------------------------------------------------------------------
REF_PRODUCAO_FALSA = "projetoprodfalso"


@pytest.fixture()
def ensaio_declarado(monkeypatch):
    """A allowlist é obrigatória: declara o projeto de ensaio do teste."""
    monkeypatch.setenv("GOVDOCS_ENSAIO_PROJETO",
                       "umensaioqualquer,referenciaficticiadeproducao,"
                       "projetoprodfalso,umensaio,meuensaio")
    return "umensaioqualquer"


@pytest.fixture()
def producao_falsa(monkeypatch):
    """Finge que `projetoprodfalso` é a produção, sem publicar a real."""
    import ensaio_seguranca as ensaio

    monkeypatch.setattr(
        ensaio, "_HASH_PROJETO_PRODUCAO",
        hashlib.sha256(REF_PRODUCAO_FALSA.encode()).hexdigest())
    return ensaio


def test_a_guarda_recusa_producao_tambem_nos_testes(producao_falsa,
                                                    monkeypatch):
    """
    Regressão do achado: a suíte lia GOVDOCS_ENSAIO_URL direto do
    ambiente. Apontada para produção, teria executado contra ela as
    operações de escrita do ensaio.
    """
    monkeypatch.setenv("GOVDOCS_ENSAIO_URL",
                       f"https://{REF_PRODUCAO_FALSA}.supabase.co")
    with pytest.raises(ProducaoRecusada):
        producao_falsa.exigir_ensaio()


@pytest.mark.parametrize("grafia", [
    "https://PROJETOPRODFALSO.supabase.co",       # host todo em maiúsculas
    "https://ProjetoProdFalso.Supabase.Co",       # caixa mista
    "HTTPS://PROJETOPRODFALSO.SUPABASE.CO",       # esquema junto
    "https://projetoprodfalso.SUPABASE.CO",       # só o domínio
])
def test_producao_em_caixa_alta_e_recusada(producao_falsa, ensaio_declarado,
                                           grafia):
    """
    DNS não distingue caixa: `PROJETOPRODFALSO.supabase.co` é o MESMO
    host. A comparação anterior era sensível à caixa, então bastava
    digitar a URL de produção em maiúsculas para a guarda deixar passar.
    """
    with pytest.raises(ProducaoRecusada):
        producao_falsa.exigir_ensaio(grafia)


@pytest.mark.parametrize("url", [
    "",                                            # vazia
    "   ",                                         # só espaço
    "não é url",                                   # lixo
    "http://umensaio.supabase.co",                 # sem TLS
    "ftp://umensaio.supabase.co",                  # esquema errado
    "https://umensaio.supabase.co.",               # trailing dot
    "https://umensaio.supabase.co:5432",           # porta
    "https://umensaio.supabase.co:abc",            # porta inválida
    # montadas em runtime: escritas por extenso, casariam o padrão de
    # e-mail da varredura e sujariam o laudo do patch entregue
    "https://usuario:senha" + "@" + "umensaio.supabase.co",
    "https://banco.prefeitura.gov.br",             # custom domain
    "https://supabase.co",                         # sem referência
    "https://a.b.supabase.co",                     # dois rótulos
    "https://umensaio.supabase.co/rest/v1",        # com caminho
    "https://umensaio.supabase.co?x=1",            # com query
    "https://umensaio.supabase.example.com",       # domínio parecido
    "https://umensaio.supabase.co" + "@" + "malicioso.com",
])
def test_a_guarda_recusa_identidade_nao_comprovada(ensaio_declarado, url):
    """
    Não basta "não ser produção": a identidade do projeto precisa ser
    PROVÁVEL a partir da URL. Um custom domain legítimo também é
    recusado — ele não expõe a referência, e sem referência não há o
    que conferir.
    """
    with pytest.raises(ProducaoRecusada):
        exigir_ensaio(url)


def test_a_guarda_aceita_projeto_declarado(ensaio_declarado):
    assert exigir_ensaio("https://umensaioqualquer.supabase.co")


def test_a_guarda_normaliza_a_caixa_do_ensaio(ensaio_declarado):
    """Caixa alta num projeto legítimo é aceita — o host é o mesmo."""
    assert exigir_ensaio("https://UmEnsaioQualquer.Supabase.Co")


def test_a_allowlist_e_obrigatoria(monkeypatch):
    """
    Ponto 7: enquanto era opcional, a proteção real era só a negação de
    produção — e "não é produção" inclui o projeto de outro município,
    o de outro cliente e o que o operador digitou errado.
    """
    monkeypatch.delenv("GOVDOCS_ENSAIO_PROJETO", raising=False)
    with pytest.raises(ProducaoRecusada) as erro:
        exigir_ensaio("https://umensaioqualquer.supabase.co")
    assert "GOVDOCS_ENSAIO_PROJETO" in str(erro.value)


def test_sem_allowlist_nenhum_cliente_e_construido(monkeypatch):
    """A recusa vem ANTES de qualquer operação, não depois."""
    import ensaio_seguranca as ensaio

    monkeypatch.delenv("GOVDOCS_ENSAIO_PROJETO", raising=False)
    monkeypatch.setenv("GOVDOCS_ENSAIO_URL",
                       "https://umensaioqualquer.supabase.co")
    monkeypatch.setenv("GOVDOCS_ENSAIO_ANON_KEY", "chave-de-teste")

    class _Supabase:
        @staticmethod
        def create_client(*a, **k):
            raise AssertionError("cliente construído sem allowlist")

    monkeypatch.setitem(sys.modules, "supabase", _Supabase)
    with pytest.raises(ProducaoRecusada):
        ensaio.cliente("GOVDOCS_ENSAIO_ANON_KEY")


def test_a_referencia_e_extraida_canonicamente(ensaio_declarado):
    from ensaio_seguranca import referencia_do_projeto

    assert referencia_do_projeto(
        "https://UmEnsaio.SUPABASE.CO") == "umensaio"
    assert referencia_do_projeto("https://banco.prefeitura.gov.br") == ""


def test_allowlist_positiva_recusa_projeto_nao_declarado(monkeypatch):
    """
    Negar produção não basta: existe um universo de projetos que não
    são produção e também não são o ensaio pretendido — o de outro
    município, o de outro cliente.
    """
    monkeypatch.setenv("GOVDOCS_ENSAIO_PROJETO", "meuensaio")
    assert exigir_ensaio("https://meuensaio.supabase.co")
    with pytest.raises(ProducaoRecusada):
        exigir_ensaio("https://ensaiodeoutrapessoa.supabase.co")


def test_allowlist_positiva_aceita_varias_e_ignora_a_caixa(monkeypatch):
    monkeypatch.setenv("GOVDOCS_ENSAIO_PROJETO", " Ensaio1 , ensaio2 ")
    assert exigir_ensaio("https://ENSAIO1.supabase.co")
    assert exigir_ensaio("https://ensaio2.supabase.co")
    with pytest.raises(ProducaoRecusada):
        exigir_ensaio("https://ensaio3.supabase.co")


def test_allowlist_nao_pode_liberar_producao(producao_falsa, monkeypatch):
    """A negação de produção vem ANTES da allowlist, sempre."""
    monkeypatch.setenv("GOVDOCS_ENSAIO_PROJETO", REF_PRODUCAO_FALSA)
    with pytest.raises(ProducaoRecusada):
        producao_falsa.exigir_ensaio(
            f"https://{REF_PRODUCAO_FALSA}.supabase.co")


def test_nenhum_cliente_e_construido_quando_a_guarda_falha(
        monkeypatch, ensaio_declarado):
    """
    A prova que importa: guarda falhando, `create_client` não chega a
    ser chamado. Sem isto, uma exceção lançada tarde demais ainda
    teria aberto conexão com o projeto errado.
    """
    import ensaio_seguranca as ensaio

    chamadas = []

    class _Supabase:
        @staticmethod
        def create_client(*a, **k):
            chamadas.append(a)
            raise AssertionError("cliente construído com a guarda falhando")

    monkeypatch.setitem(sys.modules, "supabase", _Supabase)
    monkeypatch.setenv("GOVDOCS_ENSAIO_ANON_KEY", "chave-de-teste")
    for url in ("https://banco.prefeitura.gov.br",
                "https://umensaio.supabase.co:5432", ""):
        monkeypatch.setenv("GOVDOCS_ENSAIO_URL", url)
        with pytest.raises(ProducaoRecusada):
            ensaio.cliente("GOVDOCS_ENSAIO_ANON_KEY")
    assert chamadas == []


ARQUIVOS_DO_ENSAIO = ("scripts/ensaio_seguranca.py",
                      "tests/test_seguranca_contencao.py")


def _fonte(caminho: str) -> str:
    return (Path(__file__).resolve().parent.parent / caminho).read_text()


def _funcoes_com_chamada(arvore, nome: str) -> list:
    """Funções cujo corpo contém uma chamada a `nome`."""
    encontradas = []
    for no in ast.walk(arvore):
        if not isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for interno in ast.walk(no):
            if (isinstance(interno, ast.Call)
                    and getattr(interno.func, "id", None) == nome):
                encontradas.append(no)
                break
    return encontradas


def test_nenhum_cliente_do_ensaio_escapa_da_guarda():
    """
    Não pode existir caminho que construa cliente sem passar pela
    guarda — nem no script, nem nas fixtures dos testes.

    A conferência é por AST, não por texto: o que importa é a função
    QUE CONSTRÓI o cliente também chamar `exigir_ensaio`, e não a
    guarda aparecer na mesma linha.
    """
    for caminho in ARQUIVOS_DO_ENSAIO:
        arvore = ast.parse(_fonte(caminho))
        guardadas = {id(f) for f in _funcoes_com_chamada(arvore,
                                                         "exigir_ensaio")}
        for funcao in _funcoes_com_chamada(arvore, "create_client"):
            assert id(funcao) in guardadas, (
                f"{caminho}:{funcao.lineno} `{funcao.name}` constrói cliente "
                "sem chamar exigir_ensaio()")


def _statement_de(arvore, alvo):
    """
    Comando MAIS INTERNO que contém o nó.

    O mais externo seria o `def` inteiro, e aí a docstring da função
    entraria na conferência — foi o que fez a primeira versão deste
    teste acusar a si mesma.
    """
    candidatos = [no for no in ast.walk(arvore)
                  if isinstance(no, ast.stmt)
                  and any(interno is alvo for interno in ast.walk(no))]
    return min(candidatos, key=lambda n: len(ast.unparse(n)), default=None)


def test_nenhum_delete_amplo_no_ensaio():
    """
    `delete().neq("id", "")` manda apagar a tabela inteira. Se a
    contenção falhasse, o próprio ensaio destruiria a base que deveria
    estar protegendo — e leria o estrago como sucesso.

    A conferência é por AST: só chamadas REAIS contam. Varrer o texto
    faria o próprio teste casar com os literais que ele procura.
    """
    for caminho in ARQUIVOS_DO_ENSAIO:
        arvore = ast.parse(_fonte(caminho))
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call)
                    and getattr(no.func, "attr", None) == "delete"):
                continue
            comando = ast.unparse(_statement_de(arvore, no))
            assert ".eq('id'" in comando, (
                f"{caminho}:{no.lineno} apaga sem mirar um id exato: "
                f"{comando}")
            for amplo in ("neq", "gt", "gte", "lt", "lte", "like", "ilike"):
                assert f".{amplo}(" not in comando, (
                    f"{caminho}:{no.lineno} delete com filtro amplo "
                    f"`{amplo}`: {comando}")


def test_o_canario_e_unico_por_execucao():
    assert marcador_de_canario() != marcador_de_canario()


def _passa_por_table(no) -> bool:
    """A cadeia de chamadas passa por `.table(...)`? Distingue escrita
    no banco de um `set.update()` qualquer do Python."""
    atual = no
    while isinstance(atual, ast.Call):
        if getattr(atual.func, "attr", None) == "table":
            return True
        atual = getattr(atual.func, "value", None)
        if not isinstance(atual, (ast.Call, ast.Attribute)):
            return False
        if isinstance(atual, ast.Attribute):
            atual = atual.value
    return False


def test_nenhum_teste_de_ensaio_pula_por_preparacao():
    """
    Com o ensaio configurado, skip é resultado falso: some da contagem
    de falhas e não aparece como lacuna. Preparação que não deu certo
    tem de FALHAR.

    O único skip legítimo é o `requer_ensaio` de módulo, que existe
    para a máquina sem ensaio nenhum configurado — e ele é um
    `skipif`, não uma chamada a `pytest.skip`.
    """
    arvore = ast.parse(_fonte("tests/test_seguranca_contencao.py"))
    permitidos = 0
    for no in ast.walk(arvore):
        if not (isinstance(no, ast.Call)
                and getattr(no.func, "attr", None) == "skip"):
            continue
        objeto = getattr(no.func, "value", None)
        if getattr(objeto, "id", "") != "pytest":
            continue
        # O ÚNICO skip legítimo: a máquina não tem ensaio configurado.
        # Ele é sobre a ausência do ambiente, não sobre a preparação
        # falhar — e por isso carrega a marca explícita.
        argumento = no.args[0] if no.args else None
        texto = getattr(argumento, "value", "")
        assert texto == "ensaio não configurado", (
            f"linha {no.lineno}: pytest.skip — use pytest.fail, senão a "
            "preparação falha em silêncio e o relatório sai verde")
        permitidos += 1
    assert permitidos <= 1, f"{permitidos} skips: só um é legítimo"


# Clientes PRIVILEGIADOS escrevem DE VERDADE e por isso só podem tocar
# o objeto descartável. Os demais — anon, sessão de servidor comum —
# escrevem em modo de TENTATIVA: o teste existe justamente para provar
# que a tentativa é recusada, e tentativa recusada não deixa estado.
CLIENTES_PRIVILEGIADOS = ("servidor", "cliente_servidor")


def _receptor_da_cadeia(no) -> str:
    """Nome da variável em que a cadeia `x.table(...)...` começa."""
    atual = no
    while isinstance(atual, ast.Call):
        atual = getattr(atual.func, "value", None)
        if isinstance(atual, ast.Attribute):
            atual = atual.value
    return getattr(atual, "id", "")


def test_o_ensaio_nao_semeia_em_tabela_de_dominio():
    """
    Escrita PRIVILEGIADA só no objeto descartável. Um insert em
    `usuarios` é criar CONTA, e se o teste morrer no meio a conta fica;
    em tabela com FK, a linha nasce órfã.

    Tentativa de escrita por cliente NÃO privilegiado é outra coisa: é
    o próprio teste de isolamento, e precisa mirar a tabela de domínio
    para provar o que promete.
    """
    for caminho in ARQUIVOS_DO_ENSAIO:
        arvore = ast.parse(_fonte(caminho))
        for no in ast.walk(arvore):
            if not (isinstance(no, ast.Call)
                    and getattr(no.func, "attr", None)
                    in ("insert", "update", "upsert")):
                continue
            # só escrita no BANCO: a cadeia precisa passar por .table()
            if not _passa_por_table(no):
                continue
            if _receptor_da_cadeia(no) not in CLIENTES_PRIVILEGIADOS:
                continue          # tentativa de ataque, não semeadura
            comando = ast.unparse(_statement_de(arvore, no))
            assert "TABELA_OBJETO_NOVO" in comando, (
                f"{caminho}:{no.lineno} semeia fora do objeto "
                f"descartável: {comando}")


def test_toda_tentativa_de_escrita_confere_o_estado_depois():
    """
    Tentativa que só olha o status HTTP não prova nada: o PostgREST
    responde 204 a um DELETE que não casou linha e 200 a um UPDATE
    filtrado por RLS. Quem tenta escrever precisa reler depois, com o
    servidor.
    """
    arvore = ast.parse(_fonte("tests/test_seguranca_contencao.py"))
    for no in ast.walk(arvore):
        if not isinstance(no, ast.FunctionDef):
            continue
        if not no.name.startswith("test_"):
            continue
        corpo = ast.unparse(no)
        if "table(" not in corpo:
            continue
        if not any(f".{v}(" in corpo
                   for v in ("insert", "update", "delete")):
            continue
        # a releitura pode vir por `cliente_servidor` (fixture antiga),
        # por `servidor` (cenário de isolamento) ou pelo sondador —
        # o que não pode é confiar no status HTTP e parar por aí
        assert any(marca in corpo for marca in (
            "cliente_servidor", "servidor.table", "_servidor(",
            "sondar_escrita_ponta_a_ponta")), (
            f"{no.name}: tenta escrever sem conferir o estado depois")


# ---------------------------------------------------------------------------
# Achado 2 — veredito de três estados
# ---------------------------------------------------------------------------
class ErroComCodigo(Exception):
    """Erro no formato que o supabase-py entrega: dict com `code`."""

    def __init__(self, code, message=""):
        super().__init__({"code": code, "message": message})
        self.code = code


@pytest.mark.parametrize("mensagem", [
    'permission denied for table usuarios',
    'new row violates row-level security policy for table "processos"',
    'ERROR: 42501: insufficient privilege',
])
def test_so_erro_de_autorizacao_vira_negado(mensagem):
    assert classificar(Exception(mensagem)) == NEGADO, mensagem


def test_codigo_estruturado_de_autorizacao_vira_negado():
    """
    `42501` (insufficient_privilege) é a ÚNICA negação inequívoca por
    código. A lista tem um item só de propósito.
    """
    assert classificar(ErroComCodigo("42501", "denied")) == NEGADO


# ---------------------------------------------------------------------------
# 42P17 — política quebrada não é política que negou
#
# `42P17` é `invalid_object_definition`; em RLS aparece como "infinite
# recursion detected in policy for relation X". A política não decidiu:
# ela é inválida e a avaliação abortou. Contar isso como NEGADO é a
# inversão mais perigosa do ensaio — uma migração que introduzisse
# recursão em TODAS as políticas produziria relatório inteiramente
# "NEGADO" sobre um banco sem contenção nenhuma.
# ---------------------------------------------------------------------------
RECURSAO_DE_POLITICA = (
    'infinite recursion detected in policy for relation "processos"')


def test_recursao_de_politica_nunca_vira_negado():
    assert classificar(
        ErroComCodigo("42P17", RECURSAO_DE_POLITICA)) == INCONCLUSIVO
    assert classificar(
        ErroComCodigo("42p17", RECURSAO_DE_POLITICA)) == INCONCLUSIVO


def test_recursao_sem_codigo_estruturado_tambem_e_inconclusiva():
    """
    Nem todo cliente entrega `code`. A mensagem sozinha menciona
    "policy" e passaria por negação numa leitura por frase — por isso a
    checagem estrutural vem ANTES da de autorização.
    """
    assert classificar(Exception(RECURSAO_DE_POLITICA)) == INCONCLUSIVO
    assert classificar(
        Exception(f"ERROR: 42P17: {RECURSAO_DE_POLITICA}")) == INCONCLUSIVO


def test_42p17_esta_fora_da_lista_de_autorizacao():
    """
    Guarda direta contra o retorno: o código não pode reaparecer entre
    os que provam negação, nem por frase nem por lista.
    """
    import ensaio_seguranca as ensaio

    assert "42p17" not in ensaio.CODIGOS_DE_AUTORIZACAO
    assert "42p17" in ensaio.CODIGOS_ESTRUTURAIS
    assert ensaio.CODIGOS_DE_AUTORIZACAO == frozenset({"42501"}), (
        "só a negação inequívoca prova contenção")


def test_recursao_de_politica_impede_o_contido(capsys):
    """
    O efeito que importa: um ensaio inteiro travado por recursão de
    política não pode terminar em CONTIDO. Antes, cada 42P17 entrava
    como NEGADO e o relatório saía verde.
    """
    veredito = classificar(ErroComCodigo("42P17", RECURSAO_DE_POLITICA))
    total = _veredito({"anon": {"usuarios.select": veredito},
                       "authenticated": {"usuarios.select": veredito}})
    assert total == 2, "recursão de política produziu veredito de contenção"
    saida = capsys.readouterr().out
    assert "CONTIDO" not in saida.replace("NÃO CONTIDO", "")
    assert "INCONCLUSIVO" in saida


@pytest.mark.parametrize("codigo", ["PGRST301", "PGRST302", "PGRST303"])
def test_pgrst30x_e_autenticacao_e_nunca_negado(codigo):
    """
    Correção central do achado: PGRST301 e PGRST303 significam JWT
    ausente, expirado ou sem claim de papel — AUTENTICAÇÃO. Tratá-los
    como negação fazia uma chave vencida provar "contenção
    funcionando": o servidor recusou antes de olhar quem era, e o
    ensaio anotava como se o RLS tivesse barrado.
    """
    assert classificar(ErroComCodigo(codigo, "JWT")) == INCONCLUSIVO, codigo
    assert classificar(Exception(f'{{"code":"{codigo}"}}')) == INCONCLUSIVO


def test_autenticacao_prevalece_sobre_autorizacao():
    """
    Sinais conflitantes: chave inválida produz mensagens que TAMBÉM
    dizem "permission denied". Aí a negação não prova política nenhuma
    — prova que ninguém foi identificado.
    """
    conflitantes = [
        "Invalid API key: permission denied for table usuarios",
        "permission denied — JWT expired",
        '{"code":"PGRST301","message":"permission denied for table x"}',
        "401 Unauthorized: permission denied",
    ]
    for mensagem in conflitantes:
        assert classificar(Exception(mensagem)) == INCONCLUSIVO, mensagem


def test_codigo_estruturado_prevalece_sobre_a_mensagem():
    """
    A substring pode vir de um DADO devolvido pela consulta; o campo
    `code` não.
    """
    erro = ErroComCodigo("PGRST301", "permission denied for table usuarios")
    assert classificar(erro) == INCONCLUSIVO
    erro = ErroComCodigo("42501", "algo que não parece autorização")
    assert classificar(erro) == NEGADO


@pytest.mark.parametrize("mensagem", [
    # rede
    "HTTPSConnectionPool: Max retries exceeded (connection refused)",
    "getaddrinfo failed",
    "Read timed out",
    "SSL: CERTIFICATE_VERIFY_FAILED",
    "503 Service Unavailable",
    "Project is paused",
    # autenticação
    "Invalid API key",
    "JWT expired",
    "No API key found in request",
    # schema
    'column "observacao" does not exist',
    '{"code":"PGRST202","message":"Could not find the function"}',
    "Could not find the table in the schema cache",
    # desconhecido
    "algo completamente inesperado aconteceu",
])
def test_falha_que_nao_e_autorizacao_e_inconclusiva(mensagem):
    """
    O padrão anterior era NEGADO: um DNS quebrado era lido como "a
    contenção funcionou", e o ensaio imprimia CONTIDO sem medir nada.
    """
    assert classificar(Exception(mensagem)) == INCONCLUSIVO, mensagem


def test_leitura_vazia_sem_canario_e_inconclusiva():
    """Tabela vazia e tabela negada devolvem a mesma coisa: nada."""
    import ensaio_seguranca as ensaio

    class _Vazio:
        data: list = []

    class _Alvo:
        def select(self, *_a, **_k): return self
        def limit(self, *_a, **_k): return self
        def execute(self): return _Vazio()

    class _Cliente:
        def table(self, _n): return _Alvo()

    assert ensaio._tentar(_Cliente(), "x", "select", None) == INCONCLUSIVO
    assert ensaio._tentar(_Cliente(), "x", "select", "id-do-canario") == NEGADO


def test_escrita_sem_canario_nao_e_tentada():
    """Sem alvo seguro, medir escrita exigiria apagar dado real."""
    import ensaio_seguranca as ensaio

    class _Explode:
        def table(self, _n):
            raise AssertionError("tentou escrever sem canário")

    for operacao in ("insert", "update", "delete"):
        assert ensaio._tentar(
            _Explode(), "x", operacao, None) == INCONCLUSIVO, operacao


def _veredito(por_papel=None, bloqueadas=(), catalogo=(), escrita=(),
              impedimentos=()):
    import ensaio_seguranca as ensaio

    return ensaio.veredito_final(
        por_papel if por_papel is not None
        else {"anon": {"usuarios.select": NEGADO}},
        list(bloqueadas), list(catalogo), list(escrita), list(impedimentos))


def test_inconclusivo_impede_o_veredito_contido(capsys):
    total = _veredito({"anon": {"usuarios.select": INCONCLUSIVO}})
    assert total == 1
    saida = capsys.readouterr().out
    assert "CONTIDO" not in saida.replace("NÃO CONTIDO", "")
    assert "INCONCLUSIVO não é aprovação" in saida


def test_ausencia_da_conta_authenticated_impede_o_contido(capsys):
    """
    Antes isso era um aviso impresso e o ensaio seguia até CONTIDO —
    sem ter medido o papel mais provável de um ataque real.
    """
    total = _veredito(
        impedimentos=["papel `authenticated` não sondado: conta ausente"])
    assert total == 1
    assert "IMPEDIMENTO" in capsys.readouterr().out


def test_servidor_bloqueado_impede_o_contido(capsys):
    total = _veredito(bloqueadas=["processos"])
    assert total == 1
    assert "QUEBRADO" in capsys.readouterr().out


def test_problema_de_catalogo_impede_o_contido(capsys):
    total = _veredito(catalogo=["grant_de_tabela: usuarios — anon SELECT"])
    assert total == 1
    assert "catálogo" in capsys.readouterr().out


def test_escrita_permitida_impede_o_contido(capsys):
    total = _veredito(escrita=[("delete", PERMITIDO)])
    assert total == 1
    assert "ABERTO" in capsys.readouterr().out


def test_nao_aplicavel_nao_impede_o_contido(capsys):
    """
    Zero bucket de Storage é ausência de ALVO, não de prova. Contar
    como inconclusivo bloqueava o CONTIDO por algo que não é falha — e
    treinava quem lê o relatório a ignorar inconclusivos.
    """
    total = _veredito({"anon": {"usuarios.select": NEGADO,
                                "storage:buckets": NAO_APLICAVEL}})
    assert total == 0
    saida = capsys.readouterr().out
    assert "CONTIDO" in saida
    assert "1 não aplicável" in saida


def test_tudo_negado_e_sem_impedimento_da_contido(capsys):
    """O caminho feliz continua existindo — senão o veredito é inútil."""
    total = _veredito(
        {"anon": {"usuarios.select": NEGADO},
         "authenticated": {"usuarios.select": NEGADO}},
        escrita=[("insert", NEGADO), ("update", NEGADO), ("delete", NEGADO)])
    assert total == 0
    assert "CONTIDO" in capsys.readouterr().out


def test_conta_authenticated_ausente_devolve_motivo(monkeypatch):
    import ensaio_seguranca as ensaio

    monkeypatch.delenv("GOVDOCS_ENSAIO_EMAIL", raising=False)
    monkeypatch.delenv("GOVDOCS_ENSAIO_SENHA", raising=False)
    sessao, motivo = ensaio.cliente_autenticado()
    assert sessao is None
    assert "GOVDOCS_ENSAIO_EMAIL" in motivo


def test_redacao_preserva_a_parte_util_da_mensagem():
    texto = db.redigir("timeout ao conectar em https://x.supabase.co")
    assert "timeout ao conectar" in texto


def test_nenhum_segredo_em_log_ou_excecao(monkeypatch, caplog):
    monkeypatch.setenv("SUPABASE_URL", "https://exemplo.supabase.co")
    monkeypatch.setenv(db.NOME_CHAVE_PUBLICA, CHAVE_FALSA_PUBLICA)
    monkeypatch.setenv(db.NOME_CHAVE_SERVIDOR, CHAVE_FALSA_ATUAL)
    with caplog.at_level(logging.DEBUG):
        db._config()
        db.disponivel()
        db.credencial_de_servidor_presente()
        erro = db._traduzir_erro(Exception("falha de conexão simulada"))
    registrado = caplog.text + str(erro)
    assert CHAVE_FALSA_ATUAL not in registrado
    assert CHAVE_FALSA_PUBLICA not in registrado


def test_erro_de_ia_sai_sanitizado_da_construcao():
    """
    `detalhe` de ErroGeracaoIA vai para a tela E para a auditoria de
    `registrar_geracao` — 401 de OpenAI/Gemini ecoa a chave.
    """
    from src.llm import ErroGeracaoIA

    erro = ErroGeracaoIA(
        "falha", detalhe=_montar("401 para sk-", "proj-",
                        "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345"))
    assert _montar("sk-", "proj-", "ABCDEFGHIJKLMNOPQRSTUVWXYZ012345") \
        not in erro.detalhe


def test_embeddings_indisponiveis_nao_mostram_a_excecao(monkeypatch):
    """
    Regressão do achado: a mensagem era
    `Embeddings indisponíveis ({exc})`, e um 401 da OpenAI ecoa a
    própria chave no corpo do erro. Bastava indexar um arquivo com a
    chave errada para o servidor ver a chave na tela.
    """
    from src import rag

    chave_falsa = _montar("sk-", "proj-",
                          "CHAVEFALSADETESTE0123456789ABCDEF")
    avisos: list[str] = []
    monkeypatch.setattr(rag.st, "warning", avisos.append)
    monkeypatch.setattr(rag, "obter_openai_key", lambda: chave_falsa,
                        raising=False)

    def explode(*_a, **_k):
        raise RuntimeError(
            f"401 Unauthorized: Incorrect API key provided: {chave_falsa}")

    monkeypatch.setattr("src.llm.obter_openai_key", lambda: chave_falsa)
    monkeypatch.setitem(sys.modules, "openai",
                        type(sys)("openai"))
    sys.modules["openai"].OpenAI = explode

    assert rag._gerar_embeddings(["texto"], para_consulta=False) is None
    texto = " ".join(avisos)
    assert chave_falsa not in texto, texto
    assert "401" not in texto, texto
    assert "Referência:" in texto


def test_incidente_de_embeddings_vai_sanitizado_para_o_log(monkeypatch, caplog):
    from src import rag

    chave_falsa = _montar("sk-", "proj-",
                          "CHAVEFALSADETESTE0123456789ABCDEF")
    monkeypatch.setattr(rag.st, "warning", lambda *_a, **_k: None)
    monkeypatch.setattr("src.llm.obter_openai_key", lambda: chave_falsa)

    def explode(*_a, **_k):
        raise RuntimeError(f"401 apikey={chave_falsa}")

    monkeypatch.setitem(sys.modules, "openai", type(sys)("openai"))
    sys.modules["openai"].OpenAI = explode

    with caplog.at_level(logging.ERROR):
        rag._gerar_embeddings(["texto"], para_consulta=False)
    assert chave_falsa not in caplog.text
    assert "rag: embeddings" in caplog.text


def test_erro_de_rag_sai_sanitizado_da_construcao():
    """
    ErroRAG é interpolado com a exceção original em vários pontos, e a
    string vai para a tela E para o trace persistido do RAG.
    """
    from src.rag import ErroRAG

    chave = _montar("sb_", "secret_", "CHAVEFALSADETESTE0123456789")
    assert chave not in str(ErroRAG(f"falha ao gravar: {chave}"))


def test_erros_de_auth_nao_ecoam_a_excecao_bruta():
    mensagem = auth._falha(
        "consultar o banco", Exception(f"PostgREST apikey={JWT_FALSO}"))
    assert JWT_FALSO not in mensagem
    assert "Referência:" in mensagem


# ---------------------------------------------------------------------------
# Grupo 3 — comportamento de `anon` no banco (ensaio; pulado por padrão)
# ---------------------------------------------------------------------------
# Inventário lido das MIGRAÇÕES — nunca escrito à mão, para não
# envelhecer em silêncio (ver scripts/ensaio_seguranca.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from ensaio_seguranca import (  # noqa: E402
    INCONCLUSIVO,
    NAO_APLICAVEL,
    NEGADO,
    PERMITIDO,
    RPC_OBJETO_NOVO,
    RPCS,
    TABELA_OBJETO_NOVO,
    ProducaoRecusada,
    classificar,
    exigir_ensaio,
    marcador_de_canario,
    tabelas_do_inventario,
)

ENSAIO_ANON = os.getenv("GOVDOCS_ENSAIO_ANON_KEY", "")


def _url_de_ensaio() -> str:
    """
    URL do ensaio, SEMPRE pela guarda.

    Os testes de ensaio liam `GOVDOCS_ENSAIO_URL` direto do ambiente. A
    guarda contra produção existia só no script — apontada para
    produção, a suíte teria executado contra ela as mesmas operações
    destrutivas. Devolve "" quando não há ensaio configurado (os testes
    ficam pulados) e PROPAGA a recusa quando a URL é de produção, para
    que o teste falhe em vez de rodar.
    """
    if not os.getenv("GOVDOCS_ENSAIO_URL", "").strip():
        return ""
    return exigir_ensaio()


ENSAIO_URL = _url_de_ensaio()

requer_ensaio = pytest.mark.skipif(
    not (ENSAIO_URL and ENSAIO_ANON),
    reason="ensaio de segurança: defina GOVDOCS_ENSAIO_URL e "
           "GOVDOCS_ENSAIO_ANON_KEY apontando para um projeto de ENSAIO "
           "(nunca produção)",
)

TABELAS_PRIVADAS = tabelas_do_inventario()

# Confirmado por leitura do catálogo de produção em 15/08/2026
# (somente SELECT em pg_tables; nenhuma linha de dado foi lida).
TABELAS_EM_PRODUCAO = 28


def test_o_inventario_cobre_todas_as_tabelas():
    """
    O ensaio anterior sondava 6 tabelas de 28 e ainda assim imprimia
    "CONTIDO". Um inventário incompleto é pior que nenhum: dá por
    fechado o que nunca foi olhado.
    """
    assert len(TABELAS_PRIVADAS) == TABELAS_EM_PRODUCAO, TABELAS_PRIVADAS
    for obrigatoria in ("usuarios", "config_app", "processos", "revisoes"):
        assert obrigatoria in TABELAS_PRIVADAS


def test_as_migracoes_de_contencao_nao_estao_aplicaveis():
    """
    0018/0019/0020 continuam com a extensão .NAO_APLICAR: nenhuma
    ferramenta de migração as executa por engano.
    """
    migracoes = Path(__file__).resolve().parent.parent / "supabase/migrations"
    for numero in ("0018", "0019", "0020"):
        arquivos = list(migracoes.glob(f"{numero}_*"))
        assert arquivos, numero
        for arquivo in arquivos:
            assert arquivo.name.endswith(".NAO_APLICAR"), arquivo.name


def test_a_0019_nao_depende_de_nomes_escritos_a_mao():
    """
    A versão anterior enumerava políticas por nome e teria deixado
    passar `anon_select_geracoes` e `anon_select_tenants`.
    """
    migracoes = Path(__file__).resolve().parent.parent / "supabase/migrations"
    sql = (migracoes / "0019_emergencial_fecha_anon.sql.NAO_APLICAR").read_text()
    assert "from pg_policies" in sql          # políticas pelo catálogo
    assert "from pg_tables" in sql            # tabelas pelo catálogo
    assert "relkind = 'S'" in sql             # sequences
    assert "from pg_proc" in sql              # funções e RPCs
    assert "alter default privileges" in sql  # objetos futuros


def _sql_da_0019() -> str:
    migracoes = Path(__file__).resolve().parent.parent / "supabase/migrations"
    return (migracoes
            / "0019_emergencial_fecha_anon.sql.NAO_APLICAR").read_text()


def test_a_0019_revoga_o_default_execute_de_public():
    """
    O padrão do PostgreSQL concede EXECUTE a PUBLIC, que alcança `anon`.
    Revogar dos papéis nomeados sem revogar de PUBLIC deixaria a porta
    de trás aberta.

    A tentativa continua aqui — mas hoje se sabe que ela NÃO basta, e o
    teste seguinte cobra o que basta.
    """
    sql = _sql_da_0019().lower()
    assert "revoke execute on functions from public" in sql
    for dono in ("postgres", "supabase_admin"):
        assert dono in sql, f"dono {dono} fora do ajuste de default"


def test_a_0019_fecha_a_funcao_nova_com_gatilho_de_evento():
    """
    O que REALMENTE fecha, e foi preciso rodar para descobrir.

    `alter default privileges ... revoke execute on functions from
    public` não impede a próxima função de nascer aberta — conferido em
    PG 16.13 local e, ponta a ponta, num Supabase de verdade, onde
    `anon` chamou pelo PostgREST uma função criada depois da revogação e
    recebeu o resultado. Os Security Advisors não acusam nada disso.

    O gatilho de evento age no momento da criação, em vez de depender de
    um default que o PostgreSQL não aplica.
    """
    sql = _sql_da_0019().lower()
    assert "create event trigger funcao_nasce_fechada" in sql
    assert "ddl_command_end" in sql
    # `create or replace` sobre função existente entra como ALTER: sem
    # cobrir os dois, a substituição reabriria o que a criação fechou
    assert "'create function'" in sql and "'alter function'" in sql
    assert "revoke all on function %s from public, anon" in sql


def test_a_0019_tolera_a_recusa_de_privilegio_sem_abortar():
    """
    No Supabase gerenciado, `alter default privileges for role
    supabase_admin` devolve 42501 — e a 0019, como bloco `begin/commit`,
    abortava INTEIRA: nada de RLS, nada de revoke, o banco seguia aberto
    e o erro não parecia ter relação com o que se tentava fazer.

    O ensaio local não pegava: lá o `supabase_admin` é papel comum.
    """
    sql = _sql_da_0019().lower()
    assert "insufficient_privilege" in sql, (
        "uma recusa de privilégio ainda aborta a migração inteira")
    assert "raise notice" in sql, "recusa engolida não aparece no laudo"


def test_a_0019_nao_confunde_public_com_anon():
    """
    `revoke ... from anon, authenticated` e `revoke ... from public` são
    revogações DIFERENTES. As duas precisam existir para funções.
    """
    sql = _sql_da_0019().lower()
    assert "revoke all on %s from anon, authenticated" in sql
    assert "revoke execute on functions from public" in sql


def test_a_verificacao_da_0019_procura_o_public():
    """
    O bloco de verificação precisa enxergar o PUBLIC, que aparece no
    ACL como `=X` — sem papel à esquerda do `=`.
    """
    sql = _sql_da_0019()
    assert "(^|;)=" in sql, (
        "a consulta de verificação não detecta default privilege de PUBLIC")


def test_os_relatorios_nao_afirmam_streamlit_enviando_secrets():
    """
    Achado 7: os textos diziam que a chave publicável "vai para o
    navegador de qualquer visitante". Streamlit renderiza no servidor e
    não envia `st.secrets` ao cliente. A afirmação errada enfraquece o
    relatório inteiro — quem a reconhece como falsa passa a duvidar do
    resto, que está certo.
    """
    raiz = Path(__file__).resolve().parent.parent
    alvos = [raiz / "docs" / "seguranca-config-app.md",
             raiz / "docs" / "seguranca-achado-p0.md",
             raiz / "supabase" / "migrations"
             / "0018_rls_config_app_e_processos.sql.NAO_APLICAR"]
    permitido = ("recebe a interface", "Isso está errado", "ERRADO",
                 "versão dizia", "dizia-se aqui", "NÃO envia a chave",
                 "nunca é enviado ao cliente")
    for alvo in alvos:
        linhas = alvo.read_text().splitlines()
        for i, linha in enumerate(linhas):
            if "navegador" not in linha:
                continue
            # a menção só vale acompanhada da correção, que pode estar
            # nas linhas vizinhas — o texto é quebrado em 72 colunas
            janela = " ".join(linhas[max(0, i - 4):i + 5])
            assert any(p in janela for p in permitido), f"{alvo.name}: {linha}"


def test_os_relatorios_nao_declaram_comprometimento_provado():
    """
    Achado 7: "chaves comprometidas" e "trate como comprometimento"
    afirmam fato que não foi apurado. Vulnerabilidade confirmada e
    comprometimento consumado são coisas diferentes, e confundi-las
    leva a decisões erradas — inclusive apressadas em produção.
    """
    raiz = Path(__file__).resolve().parent.parent
    alvos = [raiz / "docs" / "seguranca-config-app.md",
             raiz / "supabase" / "migrations"
             / "0018_rls_config_app_e_processos.sql.NAO_APLICAR"]
    proibidos = ("chaves comprometidas",
                 "devem ser consideradas comprometidas",
                 "Trate como comprometimento")
    for alvo in alvos:
        texto = alvo.read_text()
        for proibido in proibidos:
            assert proibido not in texto, f"{alvo.name}: {proibido}"


# ---------------------------------------------------------------------------
# Achado 6 — matriz da 0020
# ---------------------------------------------------------------------------
def _sql_da_0020() -> str:
    migracoes = Path(__file__).resolve().parent.parent / "supabase/migrations"
    return (migracoes
            / "0020_definitiva_supabase_auth_rls.sql.NAO_APLICAR").read_text()


def test_a_0020_cobre_as_28_tabelas():
    """
    Cobertura declarada = cobertura escrita. Tabela que não aparece na
    migração não é "sem risco": é esquecida.
    """
    sql = _sql_da_0020()
    faltando = [t for t in TABELAS_PRIVADAS if t not in sql]
    assert not faltando, f"fora da matriz da 0020: {faltando}"


def test_a_0020_resolve_o_usuario_id_preexistente():
    """
    `processos.usuario_id` existe desde a 0004, sem FK, guardando
    `usuarios.id`. `ADD COLUMN IF NOT EXISTS ... REFERENCES` pula o
    comando inteiro — não cria FK nenhuma — e `usuario_id = auth.uid()`
    não casaria linha alguma, trancando cada servidor para fora dos
    próprios processos.
    """
    sql = _sql_da_0020()
    # coluna NOVA, com FK de verdade
    assert "add column if not exists auth_user_id uuid" in sql
    assert "references auth.users(id)" in sql
    # e o backfill documentado
    assert "set auth_user_id = u.auth_user_id" in sql
    # a armadilha fica registrada para não voltar
    assert "IF NOT EXISTS` pula" in sql or "pula\no comando INTEIRO" in sql
    # nenhuma política nova pode usar a coluna legada
    for linha in sql.splitlines():
        if "using" in linha.lower() or "with check" in linha.lower():
            assert "usuario_id = auth.uid()" not in linha, linha


def test_a_0020_le_por_secretaria_e_nao_tenant_wide():
    """
    A decisão foi por secretaria, com admin alcançando o tenant. Ler
    tenant-wide era o caminho mais curto de escrever a policy, não uma
    escolha.
    """
    sql = _sql_da_0020()
    assert "secretaria_do_jwt" in sql
    assert "pode_ler_processo" in sql
    # a policy de leitura de processos passa pelo predicado, não por
    # uma comparação solta de tenant
    trecho = sql[sql.index('create policy "processos_le"'):]
    trecho = trecho[:trecho.index("create policy", 10)]
    assert "pode_ler_processo" in trecho, trecho


def test_o_predicado_de_leitura_exige_secretaria_ou_admin():
    sql = _sql_da_0020()
    corpo = sql[sql.index("function public.pode_ler_processo"):]
    corpo = corpo[:corpo.index("$$;", corpo.index("as $$"))]
    assert "public.e_admin()" in corpo
    assert "public.secretaria_do_jwt()" in corpo
    assert "public.tenant_do_jwt()" in corpo


def test_toda_escrita_da_0020_tem_with_check():
    """
    UPDATE só com USING deixa pegar uma linha que se enxerga
    legitimamente e reescrevê-la com tenant de outro município.
    """
    sql = _sql_da_0020()
    for bloco in re.split(r"create policy ", sql)[1:]:
        cabecalho = bloco[:bloco.index(";")] if ";" in bloco else bloco
        if " for insert" in cabecalho or " for update" in cabecalho:
            assert "with check" in cabecalho, cabecalho[:200]


def test_a_0020_nao_da_delete_a_authenticated():
    """Exclusão é lógica: a trilha do processo administrativo fica."""
    sql = _sql_da_0020()
    for linha in sql.splitlines():
        if linha.strip().startswith("grant ") and "authenticated" in linha:
            assert "delete" not in linha.lower(), linha
    assert "for delete to authenticated" not in sql


def test_a_0020_mantem_config_app_e_backups_fechados():
    """As três que `authenticated` não pode alcançar de jeito nenhum."""
    sql = _sql_da_0020()
    for tabela in ("config_app", "chunks_referencia_bkp_20260811",
                   "documentos_referencia_bkp_20260811"):
        for linha in sql.splitlines():
            if linha.strip().startswith("grant ") and tabela in linha:
                pytest.fail(f"{tabela} não pode ter grant: {linha}")
        assert f'create policy "{tabela}' not in sql


def test_governanca_eventos_continua_append_only():
    sql = _sql_da_0020()
    for linha in sql.splitlines():
        if "governanca_eventos" in linha and linha.strip().startswith("grant"):
            assert "update" not in linha.lower(), linha
            assert "delete" not in linha.lower(), linha


def test_a_0020_registra_a_decisao_de_escopo():
    """
    A decisão de arquitetura fica no arquivo, não na memória de quem
    escreveu. Sem isso, a próxima pessoa reabre tenant-wide achando que
    ninguém pensou no assunto.
    """
    sql = _sql_da_0020()
    assert "DECISÃO DE ARQUITETURA" in sql
    assert "POR SECRETARIA" in sql


# ---------------------------------------------------------------------------
# P2 — a aprovação não é objeto raiz
#
# `governanca_aprovacoes` guarda `entidade_tipo`/`entidade_id`: ela
# aprova alguma coisa, e é essa coisa que tem secretaria. Conferir só o
# tenant da linha de aprovação deixava um revisor da secretaria A
# registrar evento sobre aprovação da secretaria B — com ator
# verdadeiro, o que torna a trilha convincente e errada ao mesmo tempo.
#
# As provas abaixo são ESTÁTICAS: leem o texto da migração. Elas não
# substituem as provas dinâmicas (que exigem projeto de ensaio) — dizem
# só que a estrutura que as provas dinâmicas exercitam está escrita.
# ---------------------------------------------------------------------------
def _corpo_da_funcao(sql: str, nome: str) -> str:
    """Corpo de `create or replace function public.<nome>`, até o `$$;`."""
    abertura = f"create or replace function public.{nome}"
    assert abertura in sql, f"função ausente na 0020: {nome}"
    trecho = sql[sql.index(abertura):]
    fim = trecho.index("$$;", trecho.index("as $$"))
    return trecho[:fim]


def _sem_comentarios(corpo: str) -> str:
    """Só o código. Comentário que cita uma tabela não consulta tabela."""
    return "\n".join(linha for linha in corpo.splitlines()
                     if not linha.lstrip().startswith("--"))


def test_o_escopo_da_aprovacao_desce_ate_o_artefato():
    """
    O caminho tem de ser percorrido de verdade:
    aprovacoes → versoes → artefatos. Sem o join, a secretaria
    consultada seria a de ninguém.
    """
    corpo = _sem_comentarios(
        _corpo_da_funcao(_sql_da_0020(), "aprovacao_no_escopo"))
    assert "from public.governanca_aprovacoes" in corpo
    assert "join public.governanca_artefatos" in corpo, (
        "a resolução não chega ao artefato — a secretaria vem de onde?")
    assert "from public.governanca_versoes" in corpo
    # a secretaria comparada é a do ALVO, não a da linha de aprovação
    assert "a.secretaria_id into" in corpo or "a.secretaria_id" in corpo


def test_a_matriz_de_tipo_de_aprovacao_e_fechada():
    """
    Tipo desconhecido não é "provavelmente tudo bem". Uma aprovação que
    aponta para algo que não sabemos resolver é justamente o caso em que
    não dá para afirmar escopo nenhum — então recusa.
    """
    corpo = _sem_comentarios(
        _corpo_da_funcao(_sql_da_0020(), "aprovacao_no_escopo"))
    matriz = corpo[corpo.index("if v_tipo"):]
    ramo_final = matriz[matriz.rindex("else"):]
    ramo_final = ramo_final[:ramo_final.index("end if")]
    assert "return false" in ramo_final, (
        f"o `else` da matriz tipo→tabela não recusa: {ramo_final!r}")
    assert "return true" not in ramo_final, ramo_final
    # os tipos aceitos são nomeados um a um
    assert "v_tipo = 'versao'" in matriz
    assert "v_tipo = 'artefato'" in matriz


def test_so_papel_de_alcance_de_tenant_ignora_a_secretaria():
    """
    Proprietário, admin_global e admin_municipal conservam o alcance
    tenant-wide já documentado. Revisor jurídico e publicador ficam
    presos à secretaria do JWT — se entrarem nessa lista, o P2 volta
    por outra porta.
    """
    corpo = _sem_comentarios(
        _corpo_da_funcao(_sql_da_0020(), "papel_alcanca_o_tenant"))
    for papel in ("proprietario", "admin_global", "admin_municipal"):
        assert f"'{papel}'" in corpo, papel
    for papel in ("revisor_juridico", "publicador", "auditor"):
        assert f"'{papel}'" not in corpo, (
            f"{papel} não pode alcançar o tenant inteiro")


def test_o_papel_local_so_passa_com_secretaria_batendo():
    """
    O único `return true` incondicional é o do papel de alcance amplo.
    O caminho do papel local termina numa comparação de secretaria — e
    `null` não pode passar por ela.
    """
    corpo = _sem_comentarios(
        _corpo_da_funcao(_sql_da_0020(), "aprovacao_no_escopo"))
    assert corpo.count("return true") == 1, (
        "mais de um caminho devolve verdadeiro: um deles não confere "
        "secretaria")
    saida = corpo[corpo.rindex("return "):]
    assert "v_sec_alvo is not null" in saida, saida
    assert "v_sec_alvo = p_secretaria" in saida, saida


def test_o_ramo_da_aprovacao_delega_a_resolucao():
    """
    A checagem antiga vivia dentro do `elsif` e olhava só
    `ap.tenant_id`. Se voltar a existir um `exists` sobre
    `governanca_aprovacoes` ali, é a regressão exata do P2.
    """
    corpo = _sem_comentarios(
        _corpo_da_funcao(_sql_da_0020(), "registrar_evento_governanca"))
    ramo = corpo[corpo.index("p_entidade_tipo = 'aprovacao'"):]
    ramo = ramo[:ramo.index("p_entidade_tipo = 'publicacao'")]
    assert "aprovacao_no_escopo" in ramo, ramo
    assert "governanca_aprovacoes" not in ramo, (
        f"o ramo voltou a consultar a aprovação direto: {ramo!r}")
    assert "42501" in ramo, "recusa de escopo tem de ser negação explícita"


def test_a_resolucao_de_escopo_nao_e_executavel_por_anon():
    """
    `aprovacao_no_escopo` é SECURITY DEFINER: ela lê tabelas de
    governança ignorando RLS. Deixá-la aberta a `anon` seria entregar
    um oráculo de existência de artefatos.
    """
    sql = _sql_da_0020()
    for nome, assinatura in (("aprovacao_no_escopo", "(uuid, uuid, uuid, text)"),
                             ("papel_alcanca_o_tenant", "(text)")):
        assert (f"revoke all on function public.{nome}{assinatura}\n  "
                f"from public, anon;" in sql
                or f"revoke all on function public.{nome}{assinatura} "
                   f"from public, anon;" in sql), nome
        concessao = sql[sql.index(f"grant execute on function public.{nome}"):]
        concessao = concessao[:concessao.index(";")]
        assert "anon" not in concessao, concessao
        assert "public" not in concessao.split("to", 1)[1], concessao


def test_o_search_path_da_resolucao_e_fixo():
    """
    SECURITY DEFINER sem `search_path` fixo é elevação sequestrável por
    um schema plantado no caminho de busca.
    """
    sql = _sql_da_0020()
    corpo = _corpo_da_funcao(sql, "aprovacao_no_escopo")
    assert "security definer" in corpo
    assert "set search_path = ''" in corpo


def test_a_0020_usa_app_metadata_e_nunca_user_metadata():
    """
    `user_metadata` é editável pelo próprio usuário: guardar o papel
    ali é escalação de privilégio por construção.
    """
    migracoes = Path(__file__).resolve().parent.parent / "supabase/migrations"
    sql = (migracoes / "0020_definitiva_supabase_auth_rls.sql.NAO_APLICAR"
           ).read_text()
    assert "'app_metadata'" in sql
    # a única menção a user_metadata é a que ADVERTE contra usá-lo
    for linha in sql.splitlines():
        if "user_metadata" in linha:
            assert linha.lstrip().startswith("--"), linha
    assert "with check" in sql.lower()        # escrita também é policiada


@pytest.fixture()
def cliente_anon():
    from supabase import create_client

    return create_client(exigir_ensaio(), ENSAIO_ANON)


@pytest.fixture()
def cliente_servidor():
    """
    Credencial de servidor do ensaio.

    FALHA se ausente, não pula. Com as variáveis de ensaio
    configuradas, um skip aqui significaria que a prova de operação
    legítima simplesmente não aconteceu — e o relatório sairia verde.
    """
    chave = os.getenv("GOVDOCS_ENSAIO_SECRET_KEY", "")
    assert chave, (
        "GOVDOCS_ENSAIO_SECRET_KEY é obrigatória quando o ensaio está "
        "configurado: sem servidor não há como preparar o objeto "
        "descartável nem provar que a operação legítima segue")
    from supabase import create_client

    return create_client(exigir_ensaio(), chave)


@pytest.fixture()
def canario_descartavel(cliente_servidor):
    """
    Canário criado APENAS na tabela descartável do ensaio.

    A versão anterior semeava canário em cada tabela de domínio. Era
    melhor que apagar a tabela inteira, mas ainda errado: um insert em
    `usuarios` é criar CONTA, e se o teste morrer no meio a conta fica.
    Em tabela com FK, a linha nasce órfã.

    Falha de preparação FALHA o teste. Pular esconderia a única coisa
    que o teste tinha para dizer.
    """
    ident = str(uuid.uuid4())
    marcador = marcador_de_canario()
    try:
        cliente_servidor.table(TABELA_OBJETO_NOVO).insert(
            {"id": ident, "observacao": marcador}).execute()
    except Exception as erro:  # noqa: BLE001
        pytest.fail(f"preparação falhou: canário não pôde ser criado em "
                    f"{TABELA_OBJETO_NOVO} ({type(erro).__name__}). "
                    "Crie os objetos do ensaio: `--instrucoes`.")
    try:
        yield ident, marcador
    finally:
        try:
            cliente_servidor.table(TABELA_OBJETO_NOVO).delete() \
                .eq("id", ident).execute()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture()
def catalogo(cliente_servidor):
    """Auditoria de catálogo — a prova de CONFIGURAÇÃO das 28 tabelas."""
    from ensaio_seguranca import auditar_catalogo

    try:
        return auditar_catalogo(cliente_servidor)
    except Exception as erro:  # noqa: BLE001
        pytest.fail(f"preparação falhou: {erro}")


# ---------------------------------------------------------------------------
# Configuração — por catálogo, sem escrever em tabela de domínio
# ---------------------------------------------------------------------------
@requer_ensaio
def test_catalogo_nao_tem_policy_nem_grant_para_anon(catalogo):
    problemas = [a for a in catalogo
                 if a.get("tipo") in ("policy_permissiva", "grant_de_tabela")]
    assert problemas == [], problemas


@requer_ensaio
def test_catalogo_nao_tem_tabela_sem_rls(catalogo):
    assert [a for a in catalogo if a.get("tipo") == "tabela_sem_rls"] == []


@requer_ensaio
def test_catalogo_nao_tem_sequence_aberta(catalogo):
    """
    Verificação REAL de sequence: `USAGE`/`UPDATE` permitem
    nextval/setval, e o PostgREST não expõe nextval para sondar em
    runtime — quem responde é o ACL no catálogo.
    """
    assert [a for a in catalogo if a.get("tipo") == "sequence_aberta"] == []


@requer_ensaio
def test_catalogo_nao_tem_funcao_executavel_por_anon(catalogo):
    assert [a for a in catalogo if a.get("tipo") == "funcao_executavel"] == []


@requer_ensaio
def test_catalogo_nao_tem_default_privilege_aberto(catalogo):
    """A causa da recorrência: objeto futuro nascendo aberto."""
    assert [a for a in catalogo if a.get("tipo") == "default_privilege"] == []


@requer_ensaio
def test_catalogo_cobre_todas_as_tabelas_do_inventario(catalogo):
    """Cobertura declarada = cobertura provada."""
    fechadas = {a["objeto"] for a in catalogo
                if a.get("tipo") == "tabela_fechada"}
    faltando = set(TABELAS_PRIVADAS) - fechadas
    assert not faltando, f"não comprovadas fechadas: {sorted(faltando)}"


# ---------------------------------------------------------------------------
# Comportamento — só no objeto descartável
# ---------------------------------------------------------------------------
@requer_ensaio
@pytest.mark.parametrize("tabela", TABELAS_PRIVADAS)
def test_anon_nao_le_tabela_privada(cliente_anon, catalogo, tabela):
    """
    Leitura pura, sem escrever nada. Resposta vazia só conta como
    negação porque o CATÁLOGO já provou que não há grant nem policy —
    é a combinação que torna a leitura conclusiva sem inserir uma linha
    de mentira em tabela de verdade.
    """
    from ensaio_seguranca import sondar_leitura_de_dominio

    fechada = any(a.get("tipo") == "tabela_fechada"
                  and a.get("objeto") == tabela for a in catalogo)
    veredito = sondar_leitura_de_dominio(cliente_anon, tabela, fechada)
    assert veredito == NEGADO, f"{tabela}: {veredito}"


@requer_ensaio
def test_anon_nao_escreve_no_objeto_descartavel(cliente_anon,
                                                cliente_servidor,
                                                canario_descartavel):
    """
    Prova ponta a ponta de escrita — e o veredito é o ESTADO depois,
    não o status HTTP. O PostgREST responde 204 a um DELETE que não
    casou linha alguma e 200 a um UPDATE filtrado por RLS: os dois
    indistinguíveis de sucesso pelo código de resposta.
    """
    from ensaio_seguranca import sondar_escrita_ponta_a_ponta

    ident, marcador = canario_descartavel
    resultados = sondar_escrita_ponta_a_ponta(
        cliente_anon, cliente_servidor, ident, marcador)
    for operacao, veredito in resultados:
        assert veredito == NEGADO, f"{operacao}: {veredito}"

    sobreviveu = (cliente_servidor.table(TABELA_OBJETO_NOVO)
                  .select("observacao").eq("id", ident).execute()).data
    assert sobreviveu, "anon APAGOU o canário"
    assert sobreviveu[0]["observacao"] == marcador, "anon ALTEROU o canário"


@requer_ensaio
@pytest.mark.parametrize("funcao", sorted(RPCS))
def test_anon_nao_executa_rpc(cliente_anon, funcao):
    """EXECUTE concedido a PUBLIC contorna o RLS das tabelas."""
    try:
        cliente_anon.rpc(funcao, RPCS[funcao]).execute()
        resultado = PERMITIDO
    except Exception as erro:  # noqa: BLE001
        resultado = classificar(erro)
    assert resultado == NEGADO, f"{funcao}: {resultado}"


@requer_ensaio
def test_funcao_nova_nasce_fechada(cliente_anon):
    """
    A prova do `revoke ... on functions from public` nos DEFAULT
    privileges: uma função criada DEPOIS da 0019 não pode ser
    executável por `anon`.

    Revogar EXECUTE das funções existentes não cobre isto — default
    privilege vale para as FUTURAS. Sem a revogação do default, a
    próxima RPC do app nasce aberta.
    """
    try:
        cliente_anon.rpc(RPC_OBJETO_NOVO, {}).execute()
        resultado = PERMITIDO
    except Exception as erro:  # noqa: BLE001
        resultado = classificar(erro)
    assert resultado == NEGADO, (
        f"{RPC_OBJETO_NOVO}: {resultado} — o default EXECUTE ON FUNCTIONS "
        "provavelmente continua concedido a PUBLIC")


@requer_ensaio
def test_storage_sem_bucket_e_nao_aplicavel(cliente_anon):
    """Zero bucket não é "não sei": é "não há o que fechar"."""
    from ensaio_seguranca import _tentar_storage

    assert _tentar_storage(cliente_anon) in (NEGADO, NAO_APLICAVEL)


@requer_ensaio
def test_servidor_continua_operando(cliente_servidor):
    """
    Com a credencial de servidor, as operações legítimas seguem — é o
    que separa "contido" de "quebrado".
    """
    for tabela in ("usuarios", "config_app", "processos"):
        resposta = cliente_servidor.table(tabela).select("id").limit(1) \
            .execute()
        assert hasattr(resposta, "data")   # consultou sem erro de permissão


# ---------------------------------------------------------------------------
# ISOLAMENTO (ensaio) — cenário determinístico, colunas reais
#
# Provar que a política FECHA é diferente de provar que ela ABRE para
# quem deve. O cenário inteiro é criado pela suíte, com as colunas
# reais de cada tabela — a versão anterior dependia de contas que o
# operador criava à mão e montava as linhas com um campo `observacao`
# que não existe em tabela alguma. O PostgREST respondia PGRST204, o
# classificador chamava de INCONCLUSIVO, e o teste falhava por motivo
# errado: um teste de autorização que quebra no schema não mede
# autorização nenhuma.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
from fixtures_ensaio import (  # noqa: E402
    FILHAS_DE_PROCESSO,
    PreparacaoDoEnsaio,
    limpar,
    payload_da_filha,
    preparar,
    sessao,
)

requer_isolamento = pytest.mark.skipif(
    not (ENSAIO_URL and ENSAIO_ANON
         and os.getenv("GOVDOCS_ENSAIO_SECRET_KEY")),
    reason="isolamento: exige GOVDOCS_ENSAIO_URL, _ANON_KEY e _SECRET_KEY "
           "de um projeto de ENSAIO descartável")


@pytest.fixture(scope="module")
def cenario():
    """
    Cenário completo, uma vez por módulo.

    Falha de preparação FALHA os testes — não pula. Um cenário que não
    existe produz relatório verde sobre coisa nenhuma.
    """
    chave = os.getenv("GOVDOCS_ENSAIO_SECRET_KEY", "")
    if not (ENSAIO_URL and ENSAIO_ANON and chave):
        pytest.skip("ensaio não configurado")     # único skip legítimo
    from supabase import create_client

    servidor = create_client(exigir_ensaio(), chave)
    try:
        montado = preparar(servidor)
    except PreparacaoDoEnsaio as erro:
        pytest.fail(f"preparação do ensaio falhou: {erro}")
    try:
        yield montado, servidor
    finally:
        limpar(servidor, montado)


def _como(cenario, rotulo: str):
    montado, _ = cenario
    return sessao(montado.identidades[rotulo])


def _servidor(cenario):
    return cenario[1]


def _tentativa(execucao) -> str:
    """PERMITIDO | NEGADO | INCONCLUSIVO — nunca confunde schema com RLS."""
    try:
        execucao()
        return PERMITIDO
    except Exception as erro:  # noqa: BLE001
        return classificar(erro)


# ---------------------------------------------------------------------------
# Leitura — por secretaria
# ---------------------------------------------------------------------------
@requer_isolamento
def test_titular_le_o_proprio_processo(cenario):
    montado, _ = cenario
    visto = (_como(cenario, "titular").table("processos").select("id")
             .eq("id", montado.processo_do_titular).execute()).data
    assert visto, "titular não leu o próprio processo"


@requer_isolamento
def test_colega_da_mesma_secretaria_le(cenario):
    """Leitura por secretaria: comportamento desejado, não furo."""
    montado, _ = cenario
    visto = (_como(cenario, "colega").table("processos").select("id")
             .eq("id", montado.processo_do_titular).execute()).data
    assert visto, "colega da MESMA secretaria não conseguiu ler"


@requer_isolamento
@pytest.mark.parametrize("rotulo", ["outra_sec", "outro_ten"])
def test_fora_da_secretaria_e_do_tenant_nao_le(cenario, rotulo):
    montado, _ = cenario
    visto = (_como(cenario, rotulo).table("processos").select("id")
             .eq("id", montado.processo_do_titular).execute()).data
    assert not visto, f"{rotulo} LEU o processo"


@requer_isolamento
def test_admin_le_o_tenant_inteiro(cenario):
    montado, _ = cenario
    visto = (_como(cenario, "admin").table("processos").select("id")
             .eq("id", montado.processo_do_titular).execute()).data
    assert visto, "admin do município não leu o processo"


# ---------------------------------------------------------------------------
# Escrita nas filhas — só titular e admin
# ---------------------------------------------------------------------------
@requer_isolamento
@pytest.mark.parametrize("filha", FILHAS_DE_PROCESSO)
def test_colega_nao_escreve_em_filha_de_processo_alheio(cenario, filha):
    """
    O bloqueio corrigido: o `with check` do INSERT usava o predicado de
    LEITURA, então qualquer servidor da secretaria anexava revisão ou
    parecer no processo do colega — com aparência de ter vindo do
    titular.
    """
    montado, servidor = cenario
    payload = payload_da_filha(filha, montado.processo_do_titular,
                               montado.tenant_a)
    antes = len((servidor.table(filha).select("id")
                 .eq("processo_id", montado.processo_do_titular)
                 .execute()).data or [])

    resultado = _tentativa(
        lambda: _como(cenario, "colega").table(filha)
        .insert(payload).execute())

    depois = len((servidor.table(filha).select("id")
                  .eq("processo_id", montado.processo_do_titular)
                  .execute()).data or [])
    assert depois == antes, f"{filha}: o colega ESCREVEU ({antes}→{depois})"
    assert resultado == NEGADO, f"{filha}: {resultado}"


@requer_isolamento
@pytest.mark.parametrize("filha", FILHAS_DE_PROCESSO)
@pytest.mark.parametrize("rotulo", ["titular", "admin"])
def test_titular_e_admin_escrevem_na_filha(cenario, filha, rotulo):
    """
    Fechar não pode virar quebrar. E o positivo também confere o
    ESTADO: um 201 que não gravou linha nenhuma seria lido como
    sucesso.
    """
    montado, servidor = cenario
    payload = payload_da_filha(filha, montado.processo_do_titular,
                               montado.tenant_a)
    antes = len((servidor.table(filha).select("id")
                 .eq("processo_id", montado.processo_do_titular)
                 .execute()).data or [])
    resultado = _tentativa(
        lambda: _como(cenario, rotulo).table(filha).insert(payload).execute())
    depois = len((servidor.table(filha).select("id")
                  .eq("processo_id", montado.processo_do_titular)
                  .execute()).data or [])
    assert resultado == PERMITIDO, f"{rotulo} em {filha}: {resultado}"
    assert depois == antes + 1, (
        f"{rotulo} em {filha}: resposta de sucesso sem linha gravada")


@requer_isolamento
@pytest.mark.parametrize("filha", ["revisoes", "pareceres"])
@pytest.mark.parametrize("rotulo", ["outra_sec", "outro_ten"])
def test_fora_da_secretaria_e_do_tenant_nao_escreve(cenario, filha, rotulo):
    montado, servidor = cenario
    payload = payload_da_filha(filha, montado.processo_do_titular,
                               montado.tenant_a)
    antes = len((servidor.table(filha).select("id")
                 .eq("processo_id", montado.processo_do_titular)
                 .execute()).data or [])
    resultado = _tentativa(
        lambda: _como(cenario, rotulo).table(filha).insert(payload).execute())
    depois = len((servidor.table(filha).select("id")
                  .eq("processo_id", montado.processo_do_titular)
                  .execute()).data or [])
    assert depois == antes, f"{rotulo} ESCREVEU em {filha}"
    assert resultado == NEGADO, f"{rotulo} em {filha}: {resultado}"


@requer_isolamento
def test_ninguem_muda_o_tenant_do_processo(cenario):
    """O caso que o WITH CHECK existe para pegar."""
    montado, servidor = cenario
    _tentativa(lambda: _como(cenario, "titular").table("processos")
               .update({"tenant_id": montado.tenant_b})
               .eq("id", montado.processo_do_titular).execute())
    depois = (servidor.table("processos").select("tenant_id")
              .eq("id", montado.processo_do_titular).execute()).data
    assert depois[0]["tenant_id"] == montado.tenant_a, "tenant foi TROCADO"


@requer_isolamento
def test_servidor_comum_nao_le_config_app(cenario):
    """As três tabelas que `authenticated` não alcança."""
    for tabela in ("config_app", "chunks_referencia_bkp_20260811",
                   "documentos_referencia_bkp_20260811"):
        try:
            dados = (_como(cenario, "titular").table(tabela)
                     .select("*").limit(1).execute()).data
        except Exception as erro:  # noqa: BLE001
            assert classificar(erro) == NEGADO, f"{tabela}: {erro}"
            continue
        assert not dados, f"{tabela}: servidor comum LEU"


# ---------------------------------------------------------------------------
# Trilha de governança — identidade E autoridade
# ---------------------------------------------------------------------------
def _registrar(sessao_do_papel, tipo, entidade_tipo, entidade_id):
    return sessao_do_papel.rpc("registrar_evento_governanca", {
        "p_tipo_evento": tipo, "p_entidade_tipo": entidade_tipo,
        "p_entidade_id": entidade_id, "p_payload": {}}).execute()


@requer_isolamento
def test_usuario_comum_nao_insere_direto_na_trilha(cenario):
    """
    `ator` era coluna comum com INSERT liberado: dava para registrar
    uma aprovação em nome de outra pessoa.
    """
    montado, servidor = cenario
    forjado = str(uuid.uuid4())
    resultado = _tentativa(
        lambda: _como(cenario, "titular").table("governanca_eventos").insert({
            "tenant_id": montado.tenant_a, "ator": forjado,
            "tipo_evento": "aprovacao_registrada",
            "entidade_tipo": "aprovacao",
            "entidade_id": montado.aprovacao, "payload": {}}).execute())
    assert resultado == NEGADO, resultado
    assert not (servidor.table("governanca_eventos").select("id")
                .eq("ator", forjado).execute()).data, "ator FORJADO entrou"


@requer_isolamento
@pytest.mark.parametrize("tipo,entidade", [
    ("aprovacao_registrada", "aprovacao"),
    ("aprovacao_revogada", "aprovacao"),
    ("publicacao_registrada", "publicacao"),
    ("versao_publicada", "versao"),
    ("versao_criada", "versao"),
    ("artefato_criado", "artefato"),
])
def test_usuario_comum_nao_registra_evento_de_governanca(
        cenario, tipo, entidade):
    """
    O bloqueio P1. Derivar `ator` de auth.uid() resolve IMPERSONAÇÃO e
    não resolve AUTORIZAÇÃO: o evento saía com o nome verdadeiro de
    quem o criou, e qualquer conta autenticada podia registrar uma
    aprovação. Atribuição confiável de um ato que a pessoa não podia
    praticar é uma confissão falsa bem assinada.
    """
    montado, _ = cenario
    alvo = getattr(montado, entidade)
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "titular"), tipo, entidade, alvo))
    assert resultado == NEGADO, f"{tipo}: {resultado}"


@requer_isolamento
def test_titular_sem_papel_de_governanca_e_recusado(cenario):
    """
    Ser dono do processo não dá competência de governança. São eixos
    diferentes, e confundi-los é tratar `authenticated` como
    autorização.
    """
    montado, _ = cenario
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "titular"), "artefato_alterado",
                           "artefato", montado.artefato))
    assert resultado == NEGADO, resultado


@requer_isolamento
@pytest.mark.parametrize("rotulo,permitido,proibido", [
    ("revisor_a", ("aprovacao_registrada", "aprovacao"),
     ("publicacao_registrada", "publicacao")),
    ("publicador", ("publicacao_registrada", "publicacao"),
     ("aprovacao_registrada", "aprovacao")),
])
def test_cada_papel_registra_so_os_eventos_da_sua_matriz(
        cenario, rotulo, permitido, proibido):
    """
    Revisor jurídico aprova e não publica; publicador publica e não
    aprova. Sem a matriz, ter QUALQUER papel daria acesso a TODOS os
    atos.
    """
    montado, _ = cenario
    tipo_ok, ent_ok = permitido
    tipo_nao, ent_nao = proibido

    assert _tentativa(
        lambda: _registrar(_como(cenario, rotulo), tipo_ok, ent_ok,
                           getattr(montado, ent_ok))) == PERMITIDO, (
        f"{rotulo} não registrou {tipo_ok}")
    assert _tentativa(
        lambda: _registrar(_como(cenario, rotulo), tipo_nao, ent_nao,
                           getattr(montado, ent_nao))) == NEGADO, (
        f"{rotulo} registrou {tipo_nao}")


@requer_isolamento
def test_auditor_nao_registra_evento_algum(cenario):
    """`auditor` só lê."""
    montado, _ = cenario
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "auditor"), "artefato_criado",
                           "artefato", montado.artefato))
    assert resultado == NEGADO, resultado


@requer_isolamento
def test_entidade_nula_e_recusada(cenario):
    """Nulo pulava a checagem de existência inteira."""
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "admin"), "artefato_criado",
                           "artefato", None))
    assert resultado == NEGADO, resultado


@requer_isolamento
def test_entidade_de_tabela_incompativel_e_recusada(cenario):
    """
    Declarar 'artefato' e passar o id de uma publicação registrava um
    vínculo que não existe.
    """
    montado, _ = cenario
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "admin"), "artefato_criado",
                           "artefato", montado.publicacao))
    assert resultado == NEGADO, resultado


@requer_isolamento
def test_tipo_de_evento_incompativel_com_a_entidade_e_recusado(cenario):
    montado, _ = cenario
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "admin"), "publicacao_registrada",
                           "artefato", montado.artefato))
    assert resultado == NEGADO, resultado


@requer_isolamento
def test_entidade_de_outro_tenant_e_recusada(cenario):
    montado, _ = cenario
    resultado = _tentativa(
        lambda: _registrar(_como(cenario, "admin"), "artefato_criado",
                           "artefato", montado.artefato_outro_tenant))
    assert resultado == NEGADO, resultado


@requer_isolamento
def test_o_caminho_autorizado_grava_ator_do_auth(cenario):
    """
    Fechar a autoridade não pode deixar a trilha sem caminho. Com papel
    na matriz o evento entra — e o `ator` continua saindo de
    `auth.uid()`, nunca de parâmetro.
    """
    montado, servidor = cenario
    admin = _como(cenario, "admin")
    quem_sou = admin.auth.get_user().user.id
    try:
        resposta = _registrar(admin, "artefato_criado", "artefato",
                              montado.artefato)
    except Exception as erro:  # noqa: BLE001
        pytest.fail(f"caminho autorizado falhou: {classificar(erro)}")

    gravado = (servidor.table("governanca_eventos")
               .select("ator,entidade_id").eq("id", resposta.data)
               .execute()).data
    assert gravado, "a função não gravou o evento"
    assert gravado[0]["ator"] == quem_sou, "ator não é o autenticado"
    assert gravado[0]["entidade_id"] == montado.artefato


# ---------------------------------------------------------------------------
# O DESENHO do cenário, conferido sem rede
#
# As provas dinâmicas abaixo pulam quando não há projeto de ensaio — e
# um cenário que perdesse o segundo revisor passaria a pular sem que
# ninguém notasse. Estas duas provas rodam sempre e falham se o desenho
# for desfeito.
# ---------------------------------------------------------------------------
def test_o_desenho_tem_dois_revisores_em_secretarias_diferentes():
    from fixtures_ensaio import DESENHO

    revisores = [(rotulo, secretaria)
                 for rotulo, _, papel_gov, tenant, secretaria in DESENHO
                 if papel_gov == "revisor_juridico" and tenant == "a"]
    assert len(revisores) >= 2, (
        f"um revisor sozinho não prova fronteira de secretaria: {revisores}")
    secretarias = {secretaria for _, secretaria in revisores}
    assert len(secretarias) >= 2, (
        f"os revisores estão todos na mesma secretaria: {revisores}")


def test_o_cenario_tem_uma_trilha_completa_por_fronteira():
    """
    Aprovação solta não exercita resolução de escopo: a RPC precisa
    percorrer aprovação → versão → artefato para achar a secretaria.
    Cada fronteira precisa, então, da trilha INTEIRA.
    """
    import fixtures_ensaio

    for sufixo in ("", "_b", "_outro_tenant"):
        for entidade in ("artefato", "versao", "aprovacao"):
            campo = f"{entidade}{sufixo}"
            assert campo in fixtures_ensaio.Cenario.__dataclass_fields__, campo
    assert ("aprovacao_de_tipo_desconhecido"
            in fixtures_ensaio.Cenario.__dataclass_fields__)


# ---------------------------------------------------------------------------
# P2 — escopo de secretaria na APROVAÇÃO, exercitado de verdade
#
# As provas estáticas leem o texto da migração. Estas leem o
# comportamento do banco: dois revisores jurídicos, mesmo papel,
# secretarias diferentes, sobre a MESMA aprovação. Se as duas
# tentativas dessem o mesmo resultado, o papel estaria sendo confundido
# com a competência local.
#
# `aprovacao_registrada` e `aprovacao_revogada` são testados os dois:
# revogar uma aprovação alheia é o ato mais destrutivo dos dois, e é
# justamente o que uma matriz conferida só no evento "registrada"
# deixaria passar.
# ---------------------------------------------------------------------------
EVENTOS_DE_APROVACAO = ("aprovacao_registrada", "aprovacao_revogada")


def _quem(sessao_do_papel) -> str:
    """O `sub` do JWT — o que a função deve gravar como `ator`."""
    return sessao_do_papel.auth.get_user().user.id


def _eventos(servidor, entidade_id: str, ator: str | None = None) -> list:
    """Trilha gravada para uma entidade, lida com credencial de servidor."""
    consulta = (servidor.table("governanca_eventos")
                .select("id,ator,tipo_evento,entidade_id")
                .eq("entidade_id", entidade_id))
    if ator:
        consulta = consulta.eq("ator", ator)
    return consulta.execute().data


def _recusa_sem_rastro(cenario, rotulo: str, tipo: str, alvo: str) -> None:
    """
    Recusa que NÃO grava. Um NEGADO que ainda assim deixou linha na
    trilha não é contenção: é o mesmo estrago com uma mensagem de erro
    por cima.
    """
    _, servidor = cenario
    sessao_do_papel = _como(cenario, rotulo)
    ator = _quem(sessao_do_papel)
    antes = len(_eventos(servidor, alvo))

    resultado = _tentativa(
        lambda: _registrar(sessao_do_papel, tipo, "aprovacao", alvo))

    assert resultado == NEGADO, f"{rotulo} registrou {tipo}: {resultado}"
    assert not _eventos(servidor, alvo, ator), (
        f"{rotulo} foi recusado e mesmo assim gravou {tipo}")
    assert len(_eventos(servidor, alvo)) == antes, (
        "a trilha da entidade cresceu numa tentativa recusada")


def _registro_valido(cenario, rotulo: str, tipo: str, alvo: str) -> None:
    """
    Caminho autorizado: entra, e entra com o ator do Auth. Fechar o
    escopo não pode fechar a porta de quem deve passar.
    """
    _, servidor = cenario
    sessao_do_papel = _como(cenario, rotulo)
    ator = _quem(sessao_do_papel)
    try:
        resposta = _registrar(sessao_do_papel, tipo, "aprovacao", alvo)
    except Exception as erro:  # noqa: BLE001
        pytest.fail(f"{rotulo} não conseguiu registrar {tipo}: "
                    f"{classificar(erro)}")

    gravado = (servidor.table("governanca_eventos")
               .select("ator,tipo_evento,entidade_id")
               .eq("id", resposta.data).execute()).data
    assert gravado, f"{rotulo}: a função não gravou {tipo}"
    assert gravado[0]["ator"] == ator, "ator não é exatamente o auth.uid()"
    assert gravado[0]["tipo_evento"] == tipo
    assert gravado[0]["entidade_id"] == alvo


@requer_isolamento
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_revisor_nao_alcanca_aprovacao_de_outra_secretaria(cenario, tipo):
    """
    O P2 exato. `revisor_a` tem papel de governança legítimo e lê
    `governanca_aprovacoes` do tenant inteiro — portanto CONHECE o id
    da aprovação da secretaria 2. Conhecer o id não pode ser autorização.
    """
    montado, _ = cenario
    _recusa_sem_rastro(cenario, "revisor_a", tipo, montado.aprovacao_b)


@requer_isolamento
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_a_fronteira_de_secretaria_vale_nos_dois_sentidos(cenario, tipo):
    """
    Simetria. Sem esta prova, o cenário seria compatível com uma regra
    que apenas privilegia a secretaria 1 — e a fronteira não seria uma
    fronteira, seria um favorecimento.
    """
    montado, _ = cenario
    _recusa_sem_rastro(cenario, "revisor_b", tipo, montado.aprovacao)


@requer_isolamento
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_revisor_da_propria_secretaria_registra(cenario, tipo):
    """`revisor_b` é da secretaria 2 e a aprovação é da secretaria 2."""
    montado, _ = cenario
    _registro_valido(cenario, "revisor_b", tipo, montado.aprovacao_b)


@requer_isolamento
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_admin_municipal_alcanca_as_duas_secretarias(cenario, tipo):
    """
    O alcance tenant-wide de `admin_municipal` é decisão registrada na
    0020, não descuido: o admin está lotado na secretaria 1 e ainda
    assim registra sobre a aprovação da 2.
    """
    montado, _ = cenario
    _registro_valido(cenario, "admin", tipo, montado.aprovacao_b)


@requer_isolamento
@pytest.mark.parametrize("rotulo", ["revisor_a", "revisor_b", "admin"])
@pytest.mark.parametrize("tipo", EVENTOS_DE_APROVACAO)
def test_aprovacao_de_outro_tenant_e_recusada_para_todos(cenario, rotulo,
                                                         tipo):
    """
    A fronteira de tenant não cede nem para quem alcança o tenant
    inteiro — alcançar O tenant é diferente de alcançar QUALQUER tenant.
    """
    montado, _ = cenario
    _recusa_sem_rastro(cenario, rotulo, tipo, montado.aprovacao_outro_tenant)


@requer_isolamento
@pytest.mark.parametrize("rotulo", ["revisor_a", "admin"])
def test_aprovacao_de_tipo_desconhecido_e_recusada(cenario, rotulo):
    """
    `governanca_aprovacoes.entidade_tipo` é `text not null` sem CHECK:
    a tabela aceita qualquer string. A matriz tipo→tabela da RPC é
    fechada, então uma aprovação que aponta para algo irresolúvel não
    tem escopo que se possa afirmar — e nem o admin passa.

    Um `else` permissivo aqui seria pior que o P2 original: bastaria
    criar a aprovação com um tipo inventado para contornar a fronteira.
    """
    montado, _ = cenario
    _recusa_sem_rastro(cenario, rotulo, "aprovacao_registrada",
                       montado.aprovacao_de_tipo_desconhecido)


@requer_isolamento
def test_o_publicador_tambem_fica_preso_a_sua_secretaria(cenario):
    """
    A restrição de secretaria vale para todo papel local, não só para o
    revisor. O publicador registra `versao_publicada`, e a versão da
    secretaria 2 não é dele.
    """
    montado, servidor = cenario
    publicador = _como(cenario, "publicador")
    ator = _quem(publicador)
    resultado = _tentativa(
        lambda: _registrar(publicador, "versao_publicada", "versao",
                           montado.versao_b))
    assert resultado == NEGADO, resultado
    assert not _eventos(servidor, montado.versao_b, ator), (
        "publicador recusado gravou mesmo assim")


# ---------------------------------------------------------------------------
# Ponto 3 — a fase B é atômica
# ---------------------------------------------------------------------------
def test_a_fase_b_executa_as_provas_de_isolamento():
    """
    A versão anterior IMPRIMIA `pytest -k isolamento` e seguia para o
    veredito. Comando impresso não é prova: o script podia dizer
    CONTIDO sem que uma única fronteira de `authenticated` tivesse sido
    medida — e é justamente na fase B que `authenticated` passa a ter
    acesso, ou seja, quando medir importa mais.
    """
    import ensaio_seguranca as ensaio

    assert hasattr(ensaio, "executar_provas_de_isolamento")
    fonte = _fonte("scripts/ensaio_seguranca.py")
    bloco = fonte[fonte.index("def executar_provas_de_isolamento"):]
    bloco = bloco[:bloco.index("def veredito_final")]
    assert "subprocess.run" in bloco, "as provas não são EXECUTADAS"
    assert "pytest" in bloco


def test_a_fase_b_transforma_skip_em_impedimento():
    """Skip na fase B é lacuna, não neutralidade."""
    fonte = _fonte("scripts/ensaio_seguranca.py")
    bloco = fonte[fonte.index("def executar_provas_de_isolamento"):]
    bloco = bloco[:bloco.index("def veredito_final")]
    assert "skipped" in bloco
    assert "não admite skip" in bloco
    assert "nenhuma prova de isolamento chegou a passar" in bloco


def test_a_fase_b_incorpora_o_resultado_no_veredito():
    fonte = _fonte("scripts/ensaio_seguranca.py")
    assert "impedimentos.extend(isolamento)" in fonte


@pytest.mark.parametrize("impedimento", [
    "provas de isolamento FALHARAM (exit 1)",
    "2 prova(s) de isolamento PULADA(S) — na fase B o conjunto mínimo "
    "não admite skip",
    "nenhuma prova de isolamento chegou a passar",
    "pytest não encontrado",
])
def test_impedimento_de_isolamento_bloqueia_o_contido(capsys, impedimento):
    total = _veredito(impedimentos=[impedimento])
    assert total >= 1
    saida = capsys.readouterr().out
    assert "IMPEDIMENTO" in saida
    assert "CONTIDO" not in saida.replace("NÃO CONTIDO", "")


def test_a_fase_b_nao_apenas_imprime_comando():
    """Guarda contra a volta do 'execute: pytest ...' decorativo."""
    fonte = _fonte("scripts/ensaio_seguranca.py")
    for linha in fonte.splitlines():
        if "print(" in linha and "pytest tests/" in linha:
            pytest.fail(f"comando impresso no lugar de prova: {linha}")


# ---------------------------------------------------------------------------
# Etapa E — a operação do usuário vai com o JWT do usuário
#
# Enquanto tudo passava por `db._cliente()`, o RLS da 0020 não era
# exercido em lugar nenhum: a credencial de servidor o atravessa por
# definição. Uma política que nunca é avaliada não protege — ela só
# PARECE proteger, o que é pior, porque a matriz de 28 tabelas passa a
# ser lida como garantia.
#
# Estas provas cobrem o que dá para cobrir sem banco: o transporte, o
# vocabulário e a ausência de escrita direta na trilha. A prova de que
# o RLS realmente barra está no ensaio, e o ensaio depende da 0020
# aplicada — que é por que a Etapa E continua ABERTA.
# ---------------------------------------------------------------------------
from src import trilha as _trilha  # noqa: E402


def test_a_trilha_nao_e_escrita_por_insert_direto_em_lugar_algum():
    """
    A regressão que importa. `governanca_eventos` tem de ser escrita
    SÓ pela RPC: `insert` direto não passa por autorização nenhuma —
    estar autenticado bastava para registrar um ato de governança.

    Guarda por AST, sobre todo o `src/`: uma varredura por texto casaria
    o próprio comentário que a descreve.
    """
    raiz = Path(__file__).resolve().parent.parent / "src"
    culpados = []
    for arquivo in raiz.rglob("*.py"):
        arvore = ast.parse(arquivo.read_text())
        for no in ast.walk(arvore):
            if not isinstance(no, ast.Call):
                continue
            metodo = getattr(no.func, "attr", "")
            if metodo not in ("insert", "update", "upsert", "delete"):
                continue
            if "governanca_eventos" in ast.unparse(no.func):
                culpados.append(f"{arquivo.name}: {ast.unparse(no)[:70]}")
    assert not culpados, culpados


def test_o_ator_nao_e_mais_parametro_da_funcao_da_trilha():
    """
    `ator` vinha do chamador — `usuarios.id`, que nem sequer é
    `auth.uid()`. Uma assinatura confiável de um ato que a pessoa não
    praticou é uma confissão falsa bem redigida.

    O parâmetro sumiu daqui também, e não por simetria: um parâmetro
    que o servidor ignora ainda ensina quem lê o código que a
    identidade é do chamador.
    """
    import inspect

    from src import db

    assinatura = inspect.signature(db.registrar_evento_governanca)
    assert "ator" not in assinatura.parameters, assinatura


def test_a_trilha_recusa_sem_sessao_em_vez_de_cair_para_o_servidor(
        monkeypatch):
    """
    A queda silenciosa para o cliente de servidor é o defeito, não a
    solução: ela transforma "não sei quem é" em "sou o servidor, posso
    tudo". Sem sessão, recusa.
    """
    from src import db

    monkeypatch.setattr(db, "cliente_do_usuario", lambda: None)
    chamou_servidor = []
    monkeypatch.setattr(db, "_cliente",
                        lambda: chamou_servidor.append(1))

    with pytest.raises(db.ErroBanco) as erro:
        db.registrar_evento_governanca("versao_publicada", "versao",
                                       str(uuid.uuid4()))
    assert not chamou_servidor, "caiu para o cliente de servidor"
    assert "sessão autenticada" in str(erro.value)


def test_o_cliente_do_usuario_nao_e_construido_sem_token(monkeypatch):
    """Sem token na sessão não há cliente — e não há tentativa de rede."""
    from src import db

    monkeypatch.setattr(db.st, "session_state", {}, raising=False)
    assert db.sessao_do_usuario() is None
    assert db.cliente_do_usuario() is None


def test_o_token_da_sessao_precisa_ser_texto_util(monkeypatch):
    """`""`, None e valores de outro tipo não são sessão."""
    from src import db

    for lixo in ("", None, 0, [], {"token": "x"}):
        monkeypatch.setattr(db.st, "session_state",
                            {db.CHAVE_DA_SESSAO: lixo}, raising=False)
        assert db.sessao_do_usuario() is None, lixo


def test_a_trilha_usa_a_rpc_e_nunca_a_tabela(monkeypatch):
    """
    O caminho positivo: com sessão, a chamada é `rpc(...)` com os
    parâmetros da 0020 — e `ator` NÃO está entre eles.
    """
    from src import db

    chamadas = []

    class _Falso:
        def rpc(self, nome, parametros):
            chamadas.append((nome, parametros))
            return types.SimpleNamespace(
                execute=lambda: types.SimpleNamespace(data="id"))

        def table(self, nome):        # pragma: no cover — não deve rodar
            raise AssertionError(f"a trilha foi pela tabela {nome}")

    monkeypatch.setattr(db, "cliente_do_usuario", _Falso)
    alvo = str(uuid.uuid4())
    db.registrar_evento_governanca("versao_publicada", "versao", alvo,
                                   {"chave": "x"})

    assert len(chamadas) == 1
    nome, parametros = chamadas[0]
    assert nome == "registrar_evento_governanca"
    assert parametros["p_entidade_id"] == alvo
    assert not any("ator" in chave for chave in parametros), parametros


# --- vocabulário: o app e o banco falam a mesma língua ----------------------
def _sql_de_lista(nome_da_funcao: str) -> set[str]:
    """Literais de uma função da 0020 que devolve array de texto."""
    sql = _sql_da_0020()
    corpo = sql[sql.index(f"function public.{nome_da_funcao}"):]
    corpo = corpo[:corpo.index("$$;", corpo.index("as $$"))]
    return set(re.findall(r"'([a-z_]+)'", corpo))


def test_todo_evento_do_app_existe_na_matriz_da_0020():
    """
    A interseção entre os dois vocabulários era VAZIA. O app emitia
    `clausula_published`, `proposta_accepted`; a 0020 conhecia
    `versao_publicada`, `aprovacao_registrada`. Toda chamada seria
    recusada por vocabulário mesmo com o papel certo — e a matriz
    papel→evento, que é o que decide quem pode o quê, não decidia nada.
    """
    do_banco = _sql_de_lista("tipos_de_evento_validos")
    faltando = set(_trilha.EVENTOS) - do_banco
    assert not faltando, f"o app emite e a 0020 não conhece: {faltando}"


def test_a_0020_nao_conhece_evento_que_o_app_nunca_emite():
    """
    O outro sentido. Tipo aceito pelo banco e não produzido por
    ninguém é superfície sem dono: vive na matriz, ninguém o testa, e
    algum dia alguém o usa.
    """
    do_banco = _sql_de_lista("tipos_de_evento_validos")
    sobrando = do_banco - set(_trilha.EVENTOS)
    assert not sobrando, f"a 0020 aceita e o app não emite: {sobrando}"


def test_as_entidades_batem_dos_dois_lados():
    do_banco = _sql_de_lista("entidades_de_evento_validas")
    assert do_banco == set(_trilha.ENTIDADES), (
        f"banco={sorted(do_banco)} app={sorted(_trilha.ENTIDADES)}")


def test_cada_evento_tem_a_mesma_entidade_nos_dois_lados():
    """
    Não basta os dois conjuntos coincidirem: o par evento→entidade tem
    de ser o mesmo. Divergência aqui faz a RPC recusar por vocabulário
    justamente quando o papel está correto.
    """
    sql = _sql_da_0020()
    corpo = sql[sql.index("function public.entidade_do_tipo_de_evento"):]
    corpo = corpo[:corpo.index("$$;", corpo.index("as $$"))]
    pares = dict(re.findall(r"when '([a-z_]+)'\s*then '([a-z_]+)'", corpo))
    assert pares == _trilha.EVENTOS, (
        f"divergentes: "
        f"{set(pares.items()) ^ set(_trilha.EVENTOS.items())}")


def test_nenhum_evento_e_montado_a_partir_do_dado():
    """
    A causa raiz. `f"{tipo_artefato}_rascunho_criado"` produz um evento
    NOVO por tipo de artefato: um vocabulário que depende do dado não
    fecha nunca, e a matriz papel→evento passa a ter buracos que
    ninguém consegue enumerar.

    Guarda por AST: nenhuma f-string chega ao primeiro argumento de
    `registrar_evento_governanca` nem de `_evento`.
    """
    raiz = Path(__file__).resolve().parent.parent / "src"
    culpados = []
    for arquivo in raiz.rglob("*.py"):
        for no in ast.walk(ast.parse(arquivo.read_text())):
            if not isinstance(no, ast.Call) or not no.args:
                continue
            alvo = getattr(no.func, "attr", "") or getattr(no.func, "id", "")
            if alvo not in ("registrar_evento_governanca", "_evento"):
                continue
            if isinstance(no.args[0], ast.JoinedStr):
                culpados.append(f"{arquivo.name}: {ast.unparse(no)[:70]}")
    assert not culpados, culpados


def test_a_transicao_de_estado_e_total():
    """
    A f-string "nunca falhava" — produzia lixo em silêncio. Trocá-la
    por um dicionário parcial trocaria o lixo por uma exceção no meio
    da publicação, o que é pior para quem usa e não melhor para a
    trilha.
    """
    from src import governanca

    for estado in governanca.ESTADOS_ARTEFATO:
        evento = _trilha.evento_da_transicao(estado)
        assert evento in _trilha.EVENTOS, (estado, evento)


def test_a_aprovacao_e_gravada_com_o_tipo_logico(monkeypatch):
    """
    `governanca_aprovacoes.entidade_tipo` gravava `governanca_versoes`,
    o nome da TABELA. A resolução de escopo da 0020 usa matriz fechada
    de tipo→tabela e recusa o que não resolve: toda aprovação criada
    assim viraria uma aprovação sobre a qual ninguém pode registrar
    evento.
    """
    from src import laboratorio

    assert _trilha.TIPO_DA_APROVACAO_DE_VERSAO in _trilha.ENTIDADES
    monkeypatch.setattr(laboratorio.db, "disponivel", lambda: False)
    registro = laboratorio.registrar_aprovacao({"id": "v1"}, "APROVADO")
    assert registro["entidade_tipo"] == "versao", registro


def test_o_documento_da_etapa_e_nomeia_as_excecoes_e_o_que_falta():
    """
    Exceção sem nome é como a situação anterior voltaria. E um
    documento que só lista o que foi feito serve para declarar vitória.
    """
    doc = (Path(__file__).resolve().parent.parent
           / "docs/etapa-e-credencial-de-servidor.md").read_text()
    for operacao in ("_autenticar_legado", "config_app", "rag"):
        assert operacao in doc, operacao
    assert "NÃO está concluída" in doc
    # a consequência de implantar fora de ordem tem de estar escrita:
    # sem isso o documento vira lista de conquistas
    assert "Consequência para a implantação" in doc
    assert "O que falta" in doc
    # e o que falta precisa continuar tendo caixa VAZIA
    assert "- [ ]" in doc, "nenhum débito em aberto? então não falta nada"


# ---------------------------------------------------------------------------
# Etapa E — o login que produz o JWT
#
# Enquanto a autenticação foi a tabela `usuarios` com `senha_hash`
# conferido no Python, NÃO EXISTIA JWT de usuário — e sem JWT toda
# requisição vai com a credencial de servidor, que atravessa o RLS. As
# 28 políticas nunca eram avaliadas. A Etapa E não fechava por falta
# desta peça, não por falta de vontade.
# ---------------------------------------------------------------------------
class _EstadoDaSessao(dict):
    """
    `st.session_state` responde a chave E a atributo. Um dict puro
    quebra no primeiro `st.session_state.usuario`, e o teste falharia
    por motivo errado.
    """

    def __getattr__(self, nome):
        try:
            return self[nome]
        except KeyError:
            raise AttributeError(nome) from None

    def __setattr__(self, nome, valor):
        self[nome] = valor


class _SessaoFalsa:
    """Resposta do `sign_in_with_password` no formato do supabase-py."""

    def __init__(self, token, uid):
        self.session = types.SimpleNamespace(access_token=token)
        self.user = types.SimpleNamespace(id=uid)


def _auth_falso(monkeypatch, resposta=None, erro=None):
    class _Auth:
        def sign_in_with_password(self, _dados):
            if erro is not None:
                raise erro
            return resposta

    monkeypatch.setattr(auth, "_cliente_de_login",
                        lambda: types.SimpleNamespace(auth=_Auth()))


def test_o_login_bem_sucedido_guarda_o_token_na_sessao(monkeypatch, sem_sonda):
    """
    O token é o que `db.cliente_do_usuario()` anexa às requisições
    seguintes. Sem ele guardado, o login por Supabase Auth não muda
    nada: continuaria tudo pela credencial de servidor.
    """
    sessao = _EstadoDaSessao()
    monkeypatch.setattr(auth.st, "session_state", sessao, raising=False)
    monkeypatch.setattr(db.st, "session_state", sessao, raising=False)
    auth.entrar({"id": "u1", "tenant_id": "t1", "_token": "jwt-de-teste"})

    assert sessao[db.CHAVE_DA_SESSAO] == "jwt-de-teste"
    assert db.sessao_do_usuario() == "jwt-de-teste"


def test_o_token_nao_fica_no_dicionario_do_usuario(monkeypatch, sem_sonda):
    """
    `st.session_state.usuario` é lido pela interface inteira. Uma
    credencial ali circula por toda tela que mostre o usuário logado.
    """
    sessao = _EstadoDaSessao()
    monkeypatch.setattr(auth.st, "session_state", sessao, raising=False)
    monkeypatch.setattr(db.st, "session_state", sessao, raising=False)
    auth.entrar({"id": "u1", "tenant_id": "t1", "_token": "jwt-de-teste"})

    assert "_token" not in sessao["usuario"]
    assert "jwt-de-teste" not in str(sessao["usuario"])


def test_sair_apaga_o_token(monkeypatch, sem_sonda):
    """
    Sessão encerrada que deixasse o JWT para trás continuaria
    autorizando requisições.
    """
    sessao = _EstadoDaSessao({db.CHAVE_DA_SESSAO: "jwt-de-teste"})
    monkeypatch.setattr(auth.st, "session_state", sessao, raising=False)
    monkeypatch.setattr(db.st, "session_state", sessao, raising=False)
    auth.sair()

    assert not sessao[db.CHAVE_DA_SESSAO]
    assert db.sessao_do_usuario() is None


def test_senha_errada_no_supabase_nao_cai_para_o_legado(monkeypatch,
                                                        sem_sonda):
    """
    O ponto mais delicado do caminho de transição. Se a conta EXISTE no
    Supabase Auth e a senha não confere, cair para o legado daria ao
    atacante uma segunda tentativa contra outro banco de senhas.
    """
    _auth_falso(monkeypatch, erro=Exception("Invalid login credentials"))
    caiu = []
    monkeypatch.setattr(auth, "_autenticar_legado",
                        lambda *a: caiu.append(1))
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)

    with pytest.raises(auth.ErroAuth):
        auth.autenticar("alguem@exemplo.invalid", "errada")
    assert not caiu, "senha errada no Supabase caiu para o legado"


def test_sem_supabase_auth_configurado_o_legado_atende(monkeypatch,
                                                       sem_sonda):
    """
    A queda de volta existe porque a 0020 ainda não foi aplicada em
    produção — e ela NÃO é silenciosa no que importa: sem token, a
    trilha de governança recusa.
    """
    monkeypatch.setattr(auth, "_cliente_de_login", lambda: None)
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)
    monkeypatch.setattr(auth, "_autenticar_legado",
                        lambda *a: {"id": "u1", "ativo": True})
    monkeypatch.delenv(auth.FLAG_EXIGIR_SUPABASE_AUTH, raising=False)

    usuario = auth.autenticar("alguem", "senha")
    assert usuario["id"] == "u1"
    assert "_token" not in usuario, "login legado não pode forjar token"


def test_a_flag_fecha_a_porta_legada(monkeypatch, sem_sonda):
    """
    O interruptor final da Etapa E. Com ele ligado, quem não tem conta
    no Supabase Auth não entra — nem pela porta dos fundos.
    """
    monkeypatch.setattr(auth, "_cliente_de_login", lambda: None)
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)
    caiu = []
    monkeypatch.setattr(auth, "_autenticar_legado",
                        lambda *a: caiu.append(1))
    monkeypatch.setenv(auth.FLAG_EXIGIR_SUPABASE_AUTH, "1")

    with pytest.raises(auth.ErroAuth) as erro:
        auth.autenticar("alguem", "senha")
    assert not caiu
    assert "Supabase Auth" in str(erro.value)


def test_conta_no_auth_sem_vinculo_institucional_nao_entra(monkeypatch,
                                                           sem_sonda):
    """
    Autenticar não é autorizar. Uma conta do Supabase Auth sem linha em
    `usuarios` não tem tenant, não tem secretaria e não tem papel — e
    deixá-la entrar seria criar um usuário sem vínculo dentro do
    município.
    """
    _auth_falso(monkeypatch, resposta=_SessaoFalsa("jwt", "auth-1"))
    monkeypatch.setattr(auth, "_usuario_por_auth_id", lambda _uid: None)
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)

    with pytest.raises(auth.ErroAuth) as erro:
        auth.autenticar("alguem@exemplo.invalid", "senha")
    assert "vínculo institucional" in str(erro.value)


def test_o_login_do_supabase_usa_a_chave_publicavel(monkeypatch, sem_sonda):
    """
    O login é a única operação anterior à identidade. Fazê-la com a
    credencial de SERVIDOR apagaria a diferença entre "o servidor
    autenticou alguém" e "o servidor decidiu que estava tudo bem".
    """
    import inspect

    fonte = inspect.getsource(auth._cliente_de_login)
    assert "NOME_CHAVE_PUBLICA" in fonte
    assert "NOME_CHAVE_SERVIDOR" not in fonte


def test_usuario_desativado_nao_entra_nem_pelo_supabase(monkeypatch,
                                                        sem_sonda):
    _auth_falso(monkeypatch, resposta=_SessaoFalsa("jwt", "auth-1"))
    monkeypatch.setattr(auth, "_usuario_por_auth_id",
                        lambda _uid: {"id": "u1", "ativo": False})
    monkeypatch.setattr(db, "exigir_operacional", lambda: None)

    with pytest.raises(auth.ErroAuth) as erro:
        auth.autenticar("alguem@exemplo.invalid", "senha")
    assert "desativado" in str(erro.value)
