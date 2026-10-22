"""
Exporta o OpenAPI v1 para `openapi.v1.json`, o contrato versionado.

    python -m govconect_api.contrato > openapi.v1.json

`tests/test_contrato_openapi.py` reprova quando o código e o arquivo
divergem: mudança de contrato passa a aparecer no diff do PR, onde o
frontend e quem revisa conseguem vê-la.
"""

import json

from .config import carregar
from .main import criar_app


def gerar() -> str:
    app = criar_app(carregar({"APP_ENV": "test"}))
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2,
                      sort_keys=True) + "\n"


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(gerar())
