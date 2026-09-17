#!/usr/bin/env python3
"""
Recusa escrita de agente em arquivo de segredo. Roda como PreToolUse.

POR QUE ISTO EXISTE, e não é zelo genérico: este repositório tem um
arquivo de credencial na RAIZ (`contas-auth.json`). Hoje o que o protege
é o `.gitignore` — e `.gitignore` impede o commit, não a escrita. Um
`Write` de agente sobrescreve o arquivo sem passar por lugar nenhum onde
o ignore opine, e um `Read` seguido de eco em relatório publica o
conteúdo sem nunca tocar em git.

O gancho é PRÉ, não pós, porque depois de escrito o dano já existe: o
segredo pode ter ido para a saída do modelo, para o log da sessão, ou
para a transcrição. Bloquear depois é registrar o acidente.

CONTRATO DO CLAUDE CODE
  entrada: JSON em stdin, com `tool_name` e `tool_input`;
  saída  : código 2 bloqueia a chamada e devolve o stderr ao agente;
           qualquer outro código deixa passar.

FALHA ABERTA, DE PROPÓSITO. Se o JSON vier torto, se um campo mudar de
nome numa versão futura do Claude Code, se este arquivo tiver um bug —
a resposta é liberar, não travar. Um gancho de proteção que quebra o
desenvolvimento inteiro quando ele próprio falha é arrancado na semana
seguinte, e aí a proteção deixa de existir de verdade. A contenção real
dos segredos é o `.gitignore`, a `varredura_segredos.py` e o fato de
nenhum deles estar versionado; isto aqui é a camada de cima.
"""

from __future__ import annotations

import fnmatch
import json
import os
import sys

# Os padrões são casados contra o NOME do arquivo e contra o caminho
# relativo — `secrets.toml` sozinho é ambíguo demais para casar por nome
# em qualquer lugar, e `.streamlit/secrets.toml` é o alvo de verdade.
PADROES_DE_NOME = (
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "contas-auth*.json",
    "credentials.json",
    "service-account*.json",
    "secrets.y*ml",
)

# O `*` no fim não é preguiça: `secrets.toml.bak`, `secrets.toml.old` e
# `secrets.toml.2` são o arquivo de segredo com outro nome, e são
# exatamente os que aparecem quando alguém está "só fazendo uma cópia
# antes de mexer". As EXCECOES abaixo é que separam o `.example`.
PADROES_DE_CAMINHO = (
    ".streamlit/secrets.toml*",
    "*/.streamlit/secrets.toml*",
)

# `secrets.toml.example` é o MODELO versionado, sem valor nenhum dentro,
# e existe justamente para ser editado e lido. Bloqueá-lo ensinaria que
# o gancho implica em falsos positivos — e um gancho em que ninguém
# acredita é pior que gancho nenhum.
EXCECOES = (
    "*.example",
    "*.example.*",
    "*.sample",
    "*.template",
)

FERRAMENTAS_DE_ESCRITA = ("Write", "Edit", "MultiEdit", "NotebookEdit")


def _alvo(entrada: dict) -> str:
    dados = entrada.get("tool_input") or {}
    if not isinstance(dados, dict):
        return ""
    for chave in ("file_path", "filePath", "path", "notebook_path"):
        valor = dados.get(chave)
        if isinstance(valor, str) and valor:
            return valor
    return ""


def e_segredo(caminho: str) -> bool:
    if not caminho:
        return False
    nome = os.path.basename(caminho)

    # `lstrip("./")` seria o bug óbvio aqui, e a prova o pegou: lstrip
    # recebe um CONJUNTO de caracteres, então `.streamlit/secrets.toml`
    # viraria `streamlit/secrets.toml` — e o padrão `.streamlit/...`
    # deixaria de casar justamente no arquivo de segredo mais importante
    # do projeto. `removeprefix` tira o prefixo, que é o que se queria.
    relativo = caminho.replace(os.sep, "/")
    while relativo.startswith("./"):
        relativo = relativo.removeprefix("./")

    if any(fnmatch.fnmatch(nome, p) for p in EXCECOES):
        return False
    if any(fnmatch.fnmatch(nome, p) for p in PADROES_DE_NOME):
        return True
    return any(fnmatch.fnmatch(relativo, p) for p in PADROES_DE_CAMINHO)


def main() -> int:
    try:
        entrada = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 — falha aberta, ver o cabeçalho
        return 0

    if entrada.get("tool_name") not in FERRAMENTAS_DE_ESCRITA:
        return 0

    caminho = _alvo(entrada)
    if not e_segredo(caminho):
        return 0

    # A mensagem vai para o AGENTE, não para o humano. Ela precisa dizer
    # o que fazer em vez de só negar, senão a próxima tentativa é a mesma
    # com outro nome de ferramenta.
    print(
        f"Escrita recusada em `{caminho}`: é arquivo de segredo.\n"
        "Nada de credencial entra em commit, log, fixture ou relatório "
        "neste projeto.\n"
        "Se precisa de um valor novo ali, peça ao operador para editar à "
        "mão. Se precisa de um exemplo, use o `.example` versionado.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
