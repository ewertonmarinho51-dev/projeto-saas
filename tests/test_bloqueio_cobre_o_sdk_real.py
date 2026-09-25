"""
O bloqueio do §3 cobre a biblioteca que o SDK REALMENTE usa?

O BURACO QUE ESTA PROVA FECHA

`sem_llm` interceptava `httpx`. Em 25/09/2026 a bateria reprovou na CI
com `falha na comunicação`, e a causa não era o teste: a **`openai` 3.x
deixou de usar `httpx` e passou a usar `httpx2`** — mesma API, outro
nome. O guarda ficou cego para o SDK inteiro.

O que sobrava era a camada de DNS. E ela já é sabidamente derrotada por
`HTTPS_PROXY` (ver o cabeçalho de `scripts/sem_llm.py`), que é a
configuração desta máquina e de boa parte das redes corporativas. Ou
seja: numa máquina com proxy e `openai` 3.x, **nada barrava** — o
critério "chamadas pagas = 0" teria sido afirmado sem ninguém o estar
cumprindo.

E não era hipótese distante: `requirements.txt` pede
`openai>=1.40.0`, sem teto. Bastava reinstalar.

POR QUE A PROVA DESCOBRE A BIBLIOTECA EM VEZ DE SABÊ-LA

Uma prova que conferisse `"httpx2" in _BIBLIOTECAS_HTTP` só repetiria a
lista escrita à mão — e passaria no dia em que a `openai` 4.x migrar
para outra coisa, exatamente como a lista passou até ontem.

Aqui a pergunta é feita ao SDK: de qual biblioteca a classe do cliente
dele herda? A resposta é o fato; a lista do `sem_llm` é a promessa. A
prova compara as duas.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "bloqueio_de_custo"))

import ia_simulada  # noqa: E402
import sem_llm  # noqa: E402


def _biblioteca_http_do_cliente(cliente) -> str:
    """
    O módulo raiz da classe HTTP de onde o cliente do SDK herda.

    `openai.OpenAI()._client` é um `SyncHttpxClientWrapper`, e o nome
    não diz de quem ele herda — foi por isso que a migração passou
    despercebida. A MRO diz.
    """
    for classe in type(cliente).__mro__:
        raiz = classe.__module__.split(".")[0]
        if raiz not in ("openai", "builtins", "typing"):
            return raiz
    return ""


def _cliente_http_da_openai():
    import openai

    return openai.OpenAI(api_key="nao-e-credencial")._client


def test_o_sdk_da_openai_usa_biblioteca_que_o_bloqueio_conhece():
    biblioteca = _biblioteca_http_do_cliente(_cliente_http_da_openai())
    assert biblioteca, "não consegui descobrir a biblioteca HTTP do SDK"
    assert biblioteca in sem_llm._BIBLIOTECAS_HTTP, (  # noqa: SLF001
        f"a `openai` instalada fala HTTP por `{biblioteca}`, que o "
        f"bloqueio do §3 não conhece {sem_llm._BIBLIOTECAS_HTTP}. "  # noqa: SLF001
        "Acrescente o nome à lista — senão a próxima bateria sai para a "
        "rede achando que está contida.")


def test_a_mesma_biblioteca_e_conhecida_pela_ia_simulada():
    """
    As duas listas precisam andar juntas. Se só o bloqueio conhecer a
    biblioteca nova, a bateria não sai para a rede — ela simplesmente
    não roda, porque nada atende.
    """
    biblioteca = _biblioteca_http_do_cliente(_cliente_http_da_openai())
    assert biblioteca in ia_simulada._BIBLIOTECAS_HTTP  # noqa: SLF001


def test_instalar_cobre_TODAS_as_bibliotecas_presentes():
    """
    Cobrir uma e deixar outra é pior que não cobrir nenhuma: o guarda
    existe, responde que sim, e o SDK sai pela porta da outra.
    """
    sem_llm.remover()
    try:
        sem_llm.instalar()
        assert sem_llm.bibliotecas_cobertas() == \
            sem_llm.bibliotecas_descobertas()
        assert sem_llm.ativo()
    finally:
        sem_llm.remover()


def test_o_bloqueio_barra_a_chamada_do_SDK_de_verdade(monkeypatch):
    """
    A prova que decide, e a única que teria pegado a migração: não uma
    requisição que eu monto, mas a que o SDK faz.
    """
    import openai

    sem_llm.zerar()
    sem_llm.instalar()
    try:
        cliente = openai.OpenAI(api_key="nao-e-credencial", max_retries=0)
        with pytest.raises(Exception):
            cliente.chat.completions.create(
                model="modelo-que-nao-existe",
                messages=[{"role": "user", "content": "oi"}])
        assert sem_llm.tentativas() > 0, (
            "a chamada do SDK não foi barrada nem contada — o §3 seria "
            "afirmado sem estar sendo cumprido")
        assert any(evento["caminho"].endswith("/chat/completions")
                   for evento in sem_llm.relatorio())
    finally:
        sem_llm.remover()
        sem_llm.zerar()


def test_a_ia_simulada_atende_a_chamada_do_SDK_de_verdade(monkeypatch):
    """O outro lado: a fixture responde ao SDK, não só a mim."""
    monkeypatch.setenv("GOVDOCS_IA_SIMULADA", "coerente")
    import openai

    sem_llm.zerar()
    ia_simulada.zerar()
    sem_llm.instalar()
    ia_simulada.instalar()
    try:
        ia_simulada.autoteste()
        cliente = openai.OpenAI(api_key="nao-e-credencial", max_retries=0)
        resposta = cliente.chat.completions.create(
            model="qualquer",
            messages=[{"role": "user", "content": "Elabore o DFD"}])
        assert resposta.choices[0].message.content
        assert sem_llm.tentativas() == 0, (
            "a fixture atendeu, mas alguma requisição ainda tentou sair")
    finally:
        ia_simulada.remover()
        sem_llm.remover()
        ia_simulada.zerar()
        sem_llm.zerar()
