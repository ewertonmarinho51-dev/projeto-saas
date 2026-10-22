"""
Ponto de entrada do servidor: `uvicorn govconect_api.asgi:app`.

A configuração é lida AQUI, na subida. Configuração inválida derruba o
processo antes de aceitar a primeira conexão — é o comportamento certo
para um servidor que não sabe se pode autorizar alguém.
"""

from .main import criar_app

app = criar_app()
