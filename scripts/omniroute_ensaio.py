#!/usr/bin/env python3
"""
Valida um OmniRoute EM EXECUÇÃO antes que ele encoste no produto.

Ele confere o que a integração precisa saber e não pode supor: o processo
responde, o `/v1` existe, a lista de modelos vem, a saúde é reportada, e
as rotas que a política crítica exige estão realmente disponíveis nesta
instalação.

POR QUE ISTO EXISTE E NÃO É UM `curl` NO README

Porque os aliases mudam. O OmniRoute publicou 289 versões em sete meses,
e o pedido dizia, com razão: "não presumir que essas rotas continuam
idênticas — descobrir os aliases diretamente na versão instalada". Este
script descobre. Um documento que afirma `auto/coding` envelhece em
silêncio; um script que consulta `/v1/models` não.

ELE NÃO INSTALA NADA E NÃO TOCA NO PRODUTO. Sem OmniRoute rodando, ele
diz isso e sai com 0 — é bancada, não portão de CI.

USO

    .venv/bin/python scripts/omniroute_ensaio.py
    OMNIROUTE_BASE_URL=http://127.0.0.1:20128/v1 \\
        .venv/bin/python scripts/omniroute_ensaio.py

Para subir o gateway (ambiente de DESENVOLVIMENTO, nunca produção):

    npm install -g omniroute     # exige Node >=22.22.2 <23 ou >=24 <27
    omniroute                    # sobe em http://localhost:20128
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

PADRAO = "http://127.0.0.1:20128/v1"
SEGUNDOS = 8

# As rotas que a política de `src/roteamento.py` precisaria encontrar.
# Não são promessas sobre o OmniRoute — são o que ESTE projeto exigiria
# dele, e o ensaio existe para dizer se a versão instalada as tem.
ROTAS_EXIGIDAS = ("auto",)


def _pegar(url: str) -> tuple[int, object]:
    requisicao = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(requisicao, timeout=SEGUNDOS) as r:  # noqa: S310
            corpo = r.read().decode("utf-8", "replace")
            try:
                return r.status, json.loads(corpo)
            except json.JSONDecodeError:
                return r.status, corpo[:400]
    except urllib.error.HTTPError as erro:
        return erro.code, erro.reason
    except Exception as erro:  # noqa: BLE001
        return 0, f"{type(erro).__name__}: {erro}"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=None,
                   help=f"endereço do /v1 (padrão: {PADRAO})")
    args = p.parse_args()

    import os
    base = (args.base_url or os.environ.get("OMNIROUTE_BASE_URL")
            or PADRAO).rstrip("/")
    raiz = base[: -len("/v1")] if base.endswith("/v1") else base

    print(f"ensaiando OmniRoute em {base}\n")

    status, modelos = _pegar(f"{base}/models")
    if status == 0:
        print(f"  /v1/models .............. sem resposta ({modelos})")
        print("\nNenhum OmniRoute respondendo. Nada a ensaiar — e nada "
              "quebrado:\no produto não depende dele. Para subir em "
              "DESENVOLVIMENTO:\n"
              "  npm install -g omniroute && omniroute")
        return 0

    print(f"  /v1/models .............. HTTP {status}")

    ids: list[str] = []
    if isinstance(modelos, dict):
        ids = [m.get("id", "") for m in (modelos.get("data") or [])
               if isinstance(m, dict)]
    print(f"  modelos anunciados ...... {len(ids)}")
    for rota in ROTAS_EXIGIDAS:
        presente = any(i == rota or i.startswith(f"{rota}/") for i in ids)
        print(f"  rota '{rota}' ............. {'presente' if presente else 'AUSENTE'}")

    # Os aliases REAIS desta instalação, que é o ponto do ensaio.
    aliases = sorted({i.split("/")[0] for i in ids if "/" in i})[:20]
    if aliases:
        print(f"  prefixos encontrados .... {', '.join(aliases)}")

    for caminho, rotulo in (("/health", "saúde"), ("/v1/health", "saúde (v1)")):
        status, corpo = _pegar(f"{raiz}{caminho}")
        if status and status != 404:
            resumo = corpo if isinstance(corpo, str) else json.dumps(corpo)[:120]
            print(f"  {caminho:18} ..... HTTP {status} · {resumo}")

    print("\nO que este ensaio NÃO prova: qualidade de resposta, "
          "fidelidade de\nnúmero e valor em documento, ou que um provider "
          "do pool seja aceitável\npara documento de licitação. Isso é "
          "conjunto de avaliação, não health check.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
