"""API HTTP do Gov Conect (FastAPI). Convive com o Streamlit; ver main.py."""

import os

# Antes de qualquer `import src...`: o `db.py` do domínio usa o Streamlit
# no app e um substituto puro aqui (`src/streamlit_opcional.py`). Sem esta
# linha, num ambiente com o Streamlit instalado, a API o carregaria.
os.environ.setdefault("GOVDOCS_SEM_STREAMLIT", "1")
