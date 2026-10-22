"""
A suíte da RAIZ é a do app Streamlit; a da API mora em `apps/api` e
roda de dentro dela, com as dependências dela (job `api` do CI).

Sem esta linha, `python -m pytest -q` na raiz desceria em
`apps/api/tests`, tentaria importar o FastAPI — que o app Streamlit não
instala — e a suíte antiga quebraria por um motivo que não é dela.
"""

collect_ignore = ["apps"]
