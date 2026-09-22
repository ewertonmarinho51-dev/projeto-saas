"""
IA simulada no TRANSPORTE HTTP — respostas controladas, custo zero.

    GOVDOCS_IA_SIMULADA=coerente python -m streamlit run app.py

POR QUE NO TRANSPORTE, E NÃO TROCANDO `llm._chamar_openai`

Um dublê posto em `llm._chamar_openai` prova que aquela função foi
desviada. Não prova nada sobre o que vem antes e depois dela — e é
justamente aí que mora o trabalho que o §8 manda conferir:

  * a montagem do prompt (`prompts.montar_prompt`) e o bloco do RAG;
  * o cliente da OpenAI de verdade, com o `max_completion_tokens`, os
    parâmetros por modelo e o laço de retentativa;
  * a leitura de `choices[0].message.content`, o `finish_reason` vazio,
    o `usage` que alimenta a telemetria;
  * a troca de modelo, a queda para o motor seguinte;
  * a injeção da tabela (`planilha.injetar_tabela`) no `[[TABELA_ITENS]]`.

Respondendo no transporte, TODO esse caminho roda de verdade. O que se
troca é só o texto que a rede traria — que é exatamente o que o §8 pede
("respostas simuladas de IA que permitam testar estruturas corretas e
incorretas") e exatamente o que não se pode pagar nesta rodada.

RELAÇÃO COM O BLOQUEIO DO §3

`sem_llm` barra e CONTA tentativas de sair. Este módulo é instalado
DEPOIS dele, então fica por fora: uma chamada simulada é respondida
aqui e nunca chega ao bloqueio. Por isso as duas contagens são
separadas e ambas entram no laudo —

    sem_llm.tentativas()     → chamadas que tentaram sair    (meta: 0)
    ia_simulada.respostas()  → chamadas atendidas por fixture

Se a segunda for zero numa bateria que gerou documentos, o caminho da
IA não foi exercitado, e dizer que foi seria falso.

OS MODOS, E O QUE CADA UM EXISTE PARA REVELAR

  coerente     — devolve os fatos do processo como vieram no prompt. É
                 o controle: o que sair diferente disso no documento
                 exportado foi o sistema que mudou, não o modelo.
  incompleta   — devolve `[PREENCHER: …]`. O sistema precisa ACUSAR a
                 pendência, não publicar o marcador como se fosse texto.
  contraditoria— afirma quantidade e valor que CONTRADIZEM o formulário.
                 O sistema não pode aceitar em silêncio.
  sem_tabela   — omite `[[TABELA_ITENS]]`. Revela se a planilha some sem
                 ninguém reclamar.
  vazia        — devolve conteúdo vazio com `finish_reason=length`, que é
                 o que modelos de raciocínio fazem de verdade. Exercita
                 a troca de modelo e a queda entre motores.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time

MODOS = ("coerente", "incompleta", "contraditoria", "sem_tabela", "vazia")

_trava = threading.Lock()
_respostas: list[dict] = []
_originais: dict = {}

# Caminhos de conversa dos provedores que `llm.py` conhece. Qualquer
# outro caminho no mesmo host (modelos, embeddings) NÃO é simulado: cai
# no bloqueio do §3 e aparece na contagem, que é onde deve aparecer.
_CAMINHOS = ("/chat/completions", "/v1/chat/completions",
             ":generateContent")

_LIVRO = (os.environ.get("GOVDOCS_LIVRO_IA_SIMULADA")
          or "/tmp/govdocs_ia_simulada.jsonl")


def modo() -> str:
    valor = (os.environ.get("GOVDOCS_IA_SIMULADA") or "").strip().lower()
    return valor if valor in MODOS else ""


# ---------------------------------------------------------------------------
# O que o prompt carregava — a evidência de transporte
# ---------------------------------------------------------------------------
_MARCA_FORMULARIO = "=== DADOS DO FORMULÁRIO MATRIZ"

_DOCUMENTOS = (
    ("DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA", "dfd"),
    ("ESTUDO TÉCNICO PRELIMINAR", "etp"),
    ("MAPA DE RISCOS", "mapa_riscos"),
    ("TERMO DE REFERÊNCIA", "tr"),
    ("MINUTA DE EDITAL", "edital"),
)


def _documento_do_prompt(texto: str) -> str:
    alvo = texto.upper()
    for marca, chave in _DOCUMENTOS:
        if marca in alvo:
            return chave
    return "documento"


def _campos_do_prompt(texto: str) -> dict:
    """
    Os pares `- Rótulo: valor` do bloco do Formulário Matriz.

    É leitura do que o SISTEMA mandou, não do que o teste queria mandar.
    A diferença entre os dois é um achado, e só aparece porque este
    módulo lê o prompt em vez de receber os fatos por fora.
    """
    inicio = texto.find(_MARCA_FORMULARIO)
    if inicio < 0:
        return {}
    trecho = texto[inicio:]
    campos: dict[str, str] = {}
    for linha in trecho.splitlines():
        achado = re.match(r"^- ([^:]{2,60}):\s*(.*)$", linha)
        if achado:
            campos.setdefault(achado.group(1).strip(), achado.group(2).strip())
    return campos


def _fato(campos: dict, *rotulos: str) -> str:
    for rotulo in rotulos:
        for chave, valor in campos.items():
            if rotulo.lower() in chave.lower() and valor:
                return valor
    return ""


# ---------------------------------------------------------------------------
# As minutas simuladas
# ---------------------------------------------------------------------------
def _corpo(doc: str, campos: dict, qual: str) -> str:
    objeto = _fato(campos, "objeto") or "(objeto não veio no prompt)"
    orgao = _fato(campos, "órgão", "orgao", "unidade") or "(órgão ausente)"
    justificativa = _fato(campos, "justificativa") or "(justificativa ausente)"

    titulo = {
        "dfd": "DOCUMENTO DE FORMALIZAÇÃO DA DEMANDA",
        "etp": "ESTUDO TÉCNICO PRELIMINAR",
        "mapa_riscos": "MAPA DE RISCOS",
        "tr": "TERMO DE REFERÊNCIA",
    }.get(doc, "DOCUMENTO")

    cabecalho = (
        f"# {titulo}\n\n"
        f"## 1. IDENTIFICAÇÃO\n\n"
        f"Unidade demandante: {orgao}\n\n"
        f"## 2. OBJETO\n\n{objeto}\n\n"
        f"## 3. JUSTIFICATIVA\n\n{justificativa}\n\n"
    )

    if qual == "incompleta":
        return (cabecalho
                + "## 4. ESTIMATIVA DE VALOR\n\n"
                  "[PREENCHER: valor estimado da contratação, que não "
                  "constava do formulário]\n\n"
                  "## 5. RELAÇÃO DE ITENS\n\n[[TABELA_ITENS]]\n")
    if qual == "contraditoria":
        return (cabecalho
                + "## 4. QUANTITATIVOS\n\n"
                  "A presente contratação abrange 7 (sete) itens, no valor "
                  "global estimado de R$ 1,00 (um real).\n\n"
                  "## 5. RELAÇÃO DE ITENS\n\n[[TABELA_ITENS]]\n")
    if qual == "sem_tabela":
        return (cabecalho
                + "## 4. RELAÇÃO DE ITENS\n\nConforme planilha anexa.\n")
    return (cabecalho
            + "## 4. RELAÇÃO DE ITENS\n\n[[TABELA_ITENS]]\n\n"
              "## 5. RESPONSÁVEL PELA DEMANDA\n\n"
              "A demanda será acompanhada pela equipe designada na forma "
              "da portaria vigente.\n")


def _resposta_json(texto: str, vazia: bool) -> dict:
    return {
        "id": f"chatcmpl-simulada-{len(_respostas) + 1}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": "simulada-sem-custo",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant",
                        "content": "" if vazia else texto},
            "finish_reason": "length" if vazia else "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                  "total_tokens": 0},
    }


def _atender(corpo_bruto: bytes) -> tuple[int, dict]:
    try:
        pedido = json.loads(corpo_bruto or b"{}")
    except ValueError:
        pedido = {}
    texto_do_prompt = "\n".join(
        str(m.get("content") or "") for m in pedido.get("messages") or [])

    qual = modo()
    doc = _documento_do_prompt(texto_do_prompt)
    campos = _campos_do_prompt(texto_do_prompt)

    registro = {
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "documento": doc,
        "modo": qual,
        "campos_no_prompt": len(campos),
        "objeto_no_prompt": bool(_fato(campos, "objeto")),
        # NUNCA o prompt inteiro: ele carrega os dados do processo e
        # este registro vira anexo de relatório.
    }
    with _trava:
        _respostas.append(registro)
        # O app roda num processo e o roteiro de teste noutro; sem o
        # livro em disco, quem confere a bateria não enxerga o que o
        # Streamlit atendeu — e "a IA foi exercitada" viraria palavra.
        try:
            with open(_LIVRO, "a", encoding="utf-8") as saida:
                saida.write(json.dumps(registro, ensure_ascii=False) + "\n")
        except OSError:
            pass

    return 200, _resposta_json(_corpo(doc, campos, qual), qual == "vazia")


# ---------------------------------------------------------------------------
# Instalação
# ---------------------------------------------------------------------------
def _e_conversa(url) -> bool:
    caminho = str(getattr(url, "path", "") or "")
    return any(marca in caminho for marca in _CAMINHOS)


def instalar() -> None:
    """Idempotente. Sem modo escolhido, não instala nada."""
    if not modo() or _originais:
        return
    import httpx

    _originais["httpx"] = httpx.HTTPTransport.handle_request

    def guardado(self, request):
        if _e_conversa(request.url):
            codigo, corpo = _atender(request.read())
            return httpx.Response(
                codigo, json=corpo, request=request,
                headers={"content-type": "application/json"})
        return _originais["httpx"](self, request)

    httpx.HTTPTransport.handle_request = guardado


def remover() -> None:
    if "httpx" in _originais:
        import httpx

        httpx.HTTPTransport.handle_request = _originais.pop("httpx")


def respostas() -> list[dict]:
    with _trava:
        return list(_respostas)


def quantas() -> int:
    with _trava:
        return len(_respostas)


def zerar() -> None:
    with _trava:
        _respostas.clear()
