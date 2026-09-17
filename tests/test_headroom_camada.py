"""
A camada Headroom, guardada onde ela pode virar problema.

O Headroom é ferramenta de DESENVOLVIMENTO, igual ao Cartographer e ao
Setup Advisor. As provas aqui são as mesmas três perguntas de sempre:

  1. ele vazou para o produto?
  2. ele entrou no deploy?
  3. a telemetria continua desligada?

A quarta é específica dele e vale por todas: o bench precisa funcionar
SEM o Headroom instalado. Um script de bancada que quebra o CI quando a
dependência não está lá transforma uma ferramenta opcional em requisito
pela porta dos fundos.

O que estas provas NÃO fazem: medir compressão. Isso é
`scripts/headroom_bench.py`, que é bancada e roda à mão — número de
compressão muda a cada versão do Headroom, e um teto disso no CI viraria
falha vermelha por motivo alheio ao repositório.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 1) A fronteira
# ---------------------------------------------------------------------------
def test_o_produto_nao_importa_headroom():
    """
    Nenhum módulo de `src/` conhece o Headroom.

    Medido antes de decidir: a prosa jurídica em português, o texto de
    DFD, o código e o SQL deste projeto comprimem **0%**. O único corpus
    do produto que o Headroom de fato comprime é a planilha de 210 itens
    — 41% de economia, ao preço de 463 números e 185 códigos de item
    apagados. Essa planilha vira a tabela oficial do DFD, do TR e do
    edital.

    Por isso a fronteira não é preferência de estilo: é o resultado da
    medição, e esta prova é o que impede alguém de atravessá-la por
    achar que economia de token é sempre boa.
    """
    vazamentos = []
    for arquivo in sorted((RAIZ / "src").rglob("*.py")):
        texto = arquivo.read_text()
        for marca in ("headroom", "Headroom", "HEADROOM"):
            if marca in texto:
                vazamentos.append(f"{arquivo.relative_to(RAIZ)}: {marca}")

    assert vazamentos == [], (
        "o Headroom vazou para o pipeline que gera documento de "
        f"licitação: {vazamentos}")


def test_o_headroom_nao_entrou_no_deploy():
    """
    `requirements.txt` é o que o Streamlit Cloud instala.

    O pacote base puxa litellm, tiktoken, ast-grep-cli, pydantic,
    opentelemetry-api, rich, click e tomlkit. Nenhum deles tem o que
    fazer no processo que atende o servidor público na tela.
    """
    requisitos = (RAIZ / "requirements.txt").read_text().lower()
    assert "headroom" not in requisitos, (
        "headroom-ai entrou em requirements.txt — ele é dependência de "
        "DESENVOLVIMENTO, instalada à mão com "
        '`pip install "headroom-ai[mcp]"`')


# ---------------------------------------------------------------------------
# 2) A configuração
# ---------------------------------------------------------------------------
def test_a_telemetria_do_headroom_nasce_desligada():
    """
    O beacon do Headroom é LIGADO POR PADRÃO.

    Ele não manda prompt nem código — manda ratios, IDs de modelo e
    arquitetura. Mas a regra desta casa é não mandar nada, e uma regra
    que depende de alguém lembrar de exportar a variável não é regra.
    Por isso as duas chaves ficam no `.mcp.json` versionado.
    """
    config = json.loads((RAIZ / ".mcp.json").read_text())
    headroom = config["mcpServers"]["headroom"]
    ambiente = headroom.get("env") or {}
    assert ambiente.get("HEADROOM_BEACON") == "off", (
        "a telemetria do Headroom voltou ao padrão, que é LIGADO")
    assert ambiente.get("DO_NOT_TRACK") == "1", (
        "a convenção DO_NOT_TRACK saiu da configuração")


def test_o_headroom_e_declarado_como_processo_local():
    """
    `stdio` local, e não um endpoint remoto: é o que garante que o
    conteúdo comprimido não sai da máquina.
    """
    config = json.loads((RAIZ / ".mcp.json").read_text())
    headroom = config["mcpServers"]["headroom"]
    assert headroom.get("command") == "headroom"
    assert "url" not in headroom, (
        "o Headroom passou a apontar para um serviço remoto — o conteúdo "
        "deixaria a máquina")


# ---------------------------------------------------------------------------
# 3) O bench não pode virar requisito
# ---------------------------------------------------------------------------
def test_o_bench_sobrevive_sem_o_headroom_instalado():
    """
    Bancada, não portão.

    O bench roda à mão quando alguém atualiza o Headroom. Se ele
    quebrasse sem a dependência, uma ferramenta opcional viraria
    requisito pela porta dos fundos — e o CI ficaria vermelho por causa
    de um pacote que o projeto decidiu NÃO ter.
    """
    script = RAIZ / "scripts" / "headroom_bench.py"
    assert script.exists()

    # Simular a ausência exige BLOQUEAR o import, não isolar o
    # interpretador: `-I` ignora o site-packages do USUÁRIO e o
    # PYTHONPATH, e não o site-packages do venv — que é justamente onde
    # o `headroom` está quando alguém já o instalou. A primeira versão
    # desta prova usava `-I` e media o oposto do que prometia.
    bloqueio = (
        "import sys, runpy\n"
        "class Bloqueio:\n"
        "    def find_module(self, nome, caminho=None):\n"
        "        return None\n"
        "    def find_spec(self, nome, caminho=None, alvo=None):\n"
        "        if nome == 'headroom' or nome.startswith('headroom.'):\n"
        "            raise ImportError('headroom bloqueado pela prova')\n"
        "        return None\n"
        "sys.meta_path.insert(0, Bloqueio())\n"
        f"runpy.run_path({str(script)!r}, run_name='__main__')\n"
    )
    saida = subprocess.run(  # noqa: S603
        [sys.executable, "-c", bloqueio],
        capture_output=True, text=True, timeout=180, cwd=RAIZ)

    assert saida.returncode == 0, (
        f"o bench quebrou sem o headroom: {saida.stderr[-800:]}")
    assert "não instalado" in saida.stdout, (
        "sem a dependência o bench deveria dizer isso e sair limpo; "
        f"disse: {saida.stdout[:300]}")


def test_o_bench_recusa_numero_que_nao_mediu():
    """
    A guarda contra o relatório tranquilo e vazio.

    A primeira versão deste bench leu `original_tokens`/
    `compressed_tokens` — nomes tirados da documentação, não da versão
    instalada, que expõe `tokens_before`/`tokens_after`. O resultado foi
    uma tabela inteira de zeros que ainda assim imprimia "nenhuma perda
    de literalidade": verdade vazia, porque nada tinha sido medido.

    `_numero` levanta em vez de cair para zero. Esta prova garante que
    ele continue levantando.
    """
    sys.path.insert(0, str(RAIZ / "scripts"))
    import headroom_bench as hb

    class SemOCampo:
        pass

    try:
        hb._numero(SemOCampo(), "tokens_before")
    except SystemExit as erro:
        assert "tokens_before" in str(erro)
    else:
        raise AssertionError(
            "_numero aceitou um resultado sem o campo: um contrato "
            "quebrado do CompressResult viraria medição de zero")


def test_o_bench_conhece_os_literais_que_o_projeto_protege():
    """
    A lista de literais é o critério de reprovação do bench. Se ela
    encolher, o bench passa a aprovar compressão que apaga dado —
    exatamente o que ele existe para pegar.
    """
    sys.path.insert(0, str(RAIZ / "scripts"))
    import headroom_bench as hb

    obrigatorios = {"valor monetário", "número", "data", "artigo de lei",
                    "código de item", "identificador", "link"}
    assert obrigatorios <= set(hb.LITERAIS), (
        f"literais protegidos sumiram: {obrigatorios - set(hb.LITERAIS)}")

    # E ela precisa MORDER: um texto com valor e artigo, comprimido a
    # ponto de perdê-los, tem que acusar.
    original = ("Item 130219, quantidade 1.070,0000 UN, valor R$ 12.345,67, "
                "nos termos do art. 25 da Lei nº 14.133/2021, em 03/09/2026.")
    mutilado = "Item ...,  valor ..., nos termos da lei, em data recente."
    achado = hb.perdas(original, mutilado)
    for rotulo in ("valor monetário", "artigo de lei", "código de item", "data"):
        assert rotulo in achado, f"a detecção não pegou {rotulo}"
