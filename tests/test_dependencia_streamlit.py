"""
A versão do Streamlit é fixada, e o ambiente roda a que está fixada.

Custou um CI vermelho para chegar aqui. O `requirements.txt` pedia
`streamlit>=1.62.0`, sem teto; a 1.64.0 saiu no meio de um PR, o CI
instalou a versão nova, o ambiente de desenvolvimento continuou na
1.63.0 — e uma prova quebrou no CI enquanto passava aqui, sem que uma
linha do app tivesse mudado.

O problema não é a 1.64 ter mudado uma API. É a mudança ter chegado sem
ninguém decidir. Com o teto fixo, subir de versão vira um ato: alguém
troca o número, roda a suíte, conserta o que quebrou e explica no
commit por quê.

Estas provas são baratas e cobrem o buraco exato: o `requirements.txt`
continua fixo, e o ambiente onde a suíte roda é o do arquivo. A segunda
importa tanto quanto a primeira — fixar a versão e rodar os testes em
outra seria o mesmo estado de antes, com uma aparência melhor.
"""

from __future__ import annotations

import re
from pathlib import Path

import streamlit

REQUISITOS = Path(__file__).resolve().parents[1] / "requirements.txt"


def _linha_do_streamlit() -> str:
    for linha in REQUISITOS.read_text(encoding="utf-8").splitlines():
        limpa = linha.strip()
        if limpa and not limpa.startswith("#") and limpa.lower().startswith("streamlit"):
            return limpa
    raise AssertionError("streamlit não aparece no requirements.txt")


def test_o_streamlit_esta_fixado_e_nao_em_faixa_aberta():
    linha = _linha_do_streamlit()

    assert "==" in linha, (
        f"streamlit precisa estar fixado com '==', está como {linha!r}. "
        "Faixa aberta faz o CI instalar a versão mais nova do dia e "
        "quebrar sem ninguém ter mudado nada."
    )
    assert ">=" not in linha and ">" not in linha


def test_a_versao_instalada_e_a_que_o_arquivo_fixa():
    """
    Fixar no arquivo e rodar a suíte em outra versão seria o mesmo
    estado de antes, com aparência melhor: o CI continuaria sendo o
    primeiro a descobrir a incompatibilidade.
    """
    fixada = re.search(r"==\s*([0-9][^\s#]*)", _linha_do_streamlit())
    assert fixada, "não consegui ler a versão fixada"

    assert streamlit.__version__ == fixada.group(1), (
        f"o arquivo fixa {fixada.group(1)} e este ambiente roda "
        f"{streamlit.__version__}. Rode `pip install -r requirements.txt`."
    )
