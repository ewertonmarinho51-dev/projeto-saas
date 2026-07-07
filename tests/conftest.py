"""Garante que a raiz do projeto esteja no sys.path.

O AppTest executa app.py no processo do pytest; sem isto, `from src
import ...` falha quando o pytest é invocado como binário (`pytest`),
que — ao contrário de `python -m pytest` — não inclui o diretório
atual no sys.path.
"""

import sys
from pathlib import Path

RAIZ = str(Path(__file__).resolve().parent.parent)
if RAIZ not in sys.path:
    sys.path.insert(0, RAIZ)
