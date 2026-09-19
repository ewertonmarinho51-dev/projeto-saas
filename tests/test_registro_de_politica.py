"""
O registro de geração responde SOB QUAL POLÍTICA o documento saiu.

POR QUE ESTE ARQUIVO EXISTE

Em 19/09/2026 o operador ligou `OMNIROUTE_ROUTING_ENABLED` em produção e
pediu confirmação do efeito. Não havia como dar: `geracoes` guardava
motor, modelo, duração, tokens, status e fallback — e nada sobre a
política em vigor. "Este edital foi gerado sob a política?" só podia ser
respondido por dedução, olhando o motor e supondo.

Dedução não é trilha de auditoria. Um edital vira ato administrativo.

E havia um detalhe que torna o buraco mais constrangedor: a função que
devolve exatamente esses campos, `ai_gateway.telemetria`, já existia e
NÃO ERA CHAMADA EM LUGAR NENHUM. Foi escrita e nunca ligada.

O QUE ESTAS PROVAS FIXAM

1. o registro carrega a política, e ela é a de verdade (o rótulo decide);
2. ela reflete o estado REAL do interruptor, não um valor fixo;
3. ela NÃO carrega conteúdo — nem prompt, nem resposta, nem chave;
4. auditoria nunca derruba geração: se a telemetria explodir, o
   documento sai mesmo assim;
5. o banco sem a 0026 não perde o `rag_trace` junto.
"""

from __future__ import annotations

import pytest

from src import ai_gateway, db, llm, roteamento

# A fixture abaixo troca `db.registrar_geracao_bd` por um no-op em TODA
# prova deste arquivo, e a prova do degrau precisa da função de verdade.
# Guardar a referência no import é o jeito honesto: a alternativa seria
# a fixture "pular" um teste por nome, que é o tipo de exceção que
# ninguém lembra de revisar.
_PERSISTIR_DE_VERDADE = db.registrar_geracao_bd


@pytest.fixture(autouse=True)
def _sessao_limpa(monkeypatch):
    """Sem banco: `registrar_geracao` persiste best-effort e aqui não deve."""
    monkeypatch.setattr(db, "registrar_geracao_bd", lambda registro: None)


def _registrar(doc_key: str, motor: str = "openai") -> dict:
    import time

    return llm.registrar_geracao(doc_key, motor, time.time(), "ok")


# ---------------------------------------------------------------------------
# 1) A política entra no registro, e é a da TAREFA
# ---------------------------------------------------------------------------
def test_o_registro_de_um_edital_diz_sob_qual_politica_ele_saiu():
    registro = _registrar("edital")
    politica = registro["roteamento"]

    assert politica["task_type"] == roteamento.GERACAO_DE_DOCUMENTO
    assert politica["routing_policy"] == roteamento.PROCUREMENT_HIGH_ACCURACY
    assert politica["critica"] is True
    assert politica["provider"] == "openai"


def test_a_politica_registrada_muda_com_a_tarefa():
    """
    Um valor fixo passaria na prova acima. Só comparar duas tarefas de
    grupos diferentes mostra que o campo está mesmo sendo derivado.
    """
    edital = _registrar("edital")["roteamento"]
    classificacao = _registrar("classificacao")["roteamento"]

    assert edital["routing_policy"] != classificacao["routing_policy"]
    assert classificacao["critica"] is False


def test_rotulo_desconhecido_nao_vira_tarefa_critica_no_registro():
    """
    A regra de `roteamento` vale também aqui: desconhecido cai no grupo
    mais permissivo. Um rótulo novo não pode ganhar criticidade por
    acidente só porque passou pelo registro.
    """
    politica = _registrar("rotulo_que_ninguem_declarou")["roteamento"]
    assert politica["critica"] is False
    assert politica["routing_policy"] == roteamento.CHEAP


# ---------------------------------------------------------------------------
# 2) O campo reflete o INTERRUPTOR, que é a pergunta que originou tudo
# ---------------------------------------------------------------------------
def test_o_registro_distingue_politica_ligada_de_desligada(monkeypatch):
    """
    É ESTA a prova que fecha o buraco. Sem ela, o campo poderia gravar
    sempre a mesma coisa e a pergunta do operador — "o roteamento estava
    em vigor quando este edital foi gerado?" — continuaria sem resposta.
    """
    monkeypatch.delenv(ai_gateway.VAR_ROTEAMENTO, raising=False)
    assert _registrar("edital")["roteamento"]["routing_enabled"] is False

    monkeypatch.setenv(ai_gateway.VAR_ROTEAMENTO, "true")
    assert _registrar("edital")["roteamento"]["routing_enabled"] is True


def test_o_registro_diz_se_passou_por_gateway(monkeypatch):
    monkeypatch.delenv(ai_gateway.VAR_GATEWAY, raising=False)
    monkeypatch.delenv(ai_gateway.VAR_BASE_URL, raising=False)
    assert _registrar("edital")["roteamento"]["gateway"] == "direto"


# ---------------------------------------------------------------------------
# 3) SEM CONTEÚDO — a regra que vale para tudo que é persistido
# ---------------------------------------------------------------------------
def test_a_politica_registrada_nao_carrega_conteudo_nem_chave(monkeypatch):
    """
    O registro vai para o banco e para o log. Prompt, resposta e chave
    não entram — e medir isso aqui, no caminho do registro, é diferente
    de medir em `telemetria` isolada: é aqui que o dado é persistido.
    """
    monkeypatch.setattr(llm, "_ultimo_uso", {"modelo": "gpt-5-mini"})
    politica = _registrar("edital")["roteamento"]

    esperados = {"rotulo", "task_type", "routing_policy", "critica",
                 "motores_do_grupo", "provider", "gateway", "routing_enabled"}
    assert set(politica) == esperados, (
        "campo novo na telemetria — confira que não é conteúdo antes de "
        "acrescentá-lo a esta lista")

    texto = repr(politica).lower()
    for proibido in ("sk-", "prompt", "system", "user_prompt", "api_key",
                     "secret", "bearer"):
        assert proibido not in texto, f"{proibido!r} vazou para o registro"


# ---------------------------------------------------------------------------
# 4) AUDITORIA NUNCA DERRUBA GERAÇÃO
# ---------------------------------------------------------------------------
def test_telemetria_quebrada_nao_impede_o_registro(monkeypatch):
    """
    Se `telemetria` levantar, o documento sai sem o campo — não deixa de
    sair. Auditoria que derruba a coisa auditada é pior que auditoria
    nenhuma, e é a mesma decisão que a persistência best-effort já tomou.
    """
    def explodir(*_a, **_k):
        raise RuntimeError("telemetria caiu")

    monkeypatch.setattr(ai_gateway, "telemetria", explodir)
    registro = _registrar("edital")

    assert registro["roteamento"] == {}
    assert registro["documento"] == "edital"
    assert registro["status"] == "ok"


# ---------------------------------------------------------------------------
# 5) O DEGRAU: banco sem a 0026 não pode levar o rag_trace junto
# ---------------------------------------------------------------------------
def _db_que_recusa(colunas_ausentes: set[str]):
    """Dublê de PostgREST que recusa insert citando coluna inexistente."""
    tentativas: list[dict] = []

    class Tabela:
        def insert(self, linha):
            tentativas.append(linha)
            faltando = colunas_ausentes & set(linha)
            if faltando:
                raise RuntimeError(
                    f"column {sorted(faltando)[0]!r} does not exist")
            return self

        def execute(self):
            return self

    return Tabela(), tentativas


def test_banco_sem_a_0026_grava_o_rag_trace_do_mesmo_jeito(monkeypatch):
    """
    O degrau existe por isto. Um único fallback "tenta com tudo, senão
    tenta pelado" faria um banco sem a 0026 perder TAMBÉM o `rag_trace`
    — a correção de um buraco de auditoria teria aberto outro.
    """
    tabela, tentativas = _db_que_recusa({"roteamento"})
    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "tenant_atual", lambda: "t-1")
    monkeypatch.setattr(db, "_cliente", lambda: type(
        "C", (), {"table": staticmethod(lambda _n: tabela)})())

    _PERSISTIR_DE_VERDADE({
        "documento": "edital", "motor": "openai", "status": "ok",
        "rag_trace": {"fontes": ["lei-14133"]},
        "roteamento": {"routing_enabled": True},
    })

    assert len(tentativas) == 2, "o insert não degradou em degraus"
    assert "roteamento" in tentativas[0]
    gravada = tentativas[-1]
    assert "roteamento" not in gravada
    assert gravada["rag_trace"] == {"fontes": ["lei-14133"]}, (
        "o rag_trace foi descartado junto com a coluna nova")
