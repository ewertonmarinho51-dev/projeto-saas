"""
Instala o bloqueio de chamadas pagas ANTES de o app existir.

O Python importa `sitecustomize` automaticamente na subida do
interpretador, antes de qualquer `import` do programa. É o único ponto
em que dá para garantir que nenhum cliente HTTP do Streamlit, do
`openai` ou do `google-genai` foi criado sem o guarda no lugar.

Pôr o `sem_llm.instalar()` dentro do `app.py` não teria a mesma força:
bastaria um módulo importado antes dele abrir um cliente e guardar a
referência do transporte original para que o patch chegasse tarde.

Este diretório existe só para ser posto no `PYTHONPATH` do processo do
Streamlit durante a bateria de auditoria (§3). Ele não entra em
produção, e não é importado por nenhum módulo de `src/`.
"""

import os
import sys

if os.environ.get("GOVDOCS_BLOQUEAR_LLM", "1") not in ("0", "false", "off"):
    import pathlib

    _scripts = str(pathlib.Path(__file__).resolve().parent.parent)
    if _scripts not in sys.path:
        sys.path.insert(0, _scripts)
    try:
        import sem_llm

        sem_llm.instalar()
    except Exception as _erro:  # noqa: BLE001
        # Falhar aqui derrubaria o interpretador inteiro por um motivo
        # obscuro. Melhor gritar na saída de erro: a bateria confere
        # `sem_llm.tentativas()` no fim e a ausência do bloqueio
        # aparece lá como contagem impossível de conciliar.
        print(f"AVISO: bloqueio de chamadas pagas NÃO instalado: {_erro}",
              file=sys.stderr, flush=True)
