"""
Homologação com EVIDÊNCIA: nenhum motor entra no grupo crítico por decreto.

`PROCUREMENT_HIGH_ACCURACY` decide quem pode gerar DFD, ETP, TR, Mapa de
Riscos, edital e ARP — documentos que um agente público assina e publica.
Acrescentar um nome àquela tupla é barato demais para o peso que tem: são
nove caracteres, passam despercebidos numa revisão, e a partir dali o
modelo novo gera edital.

Estas provas transformam a homologação em fato conferível: para estar no
grupo, ou o motor tem um relatório APROVADO em `docs/homologacao/`, ou
está na lista de incumbentes — que é curta, nomeada e justificada aqui.

Gerar o relatório é `scripts/homologacao_modelo.py`, que exige chave de
API e roda a cadeia inteira sobre um caso real de 210 itens.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src import roteamento

RAIZ = Path(__file__).resolve().parent.parent
RELATORIOS = RAIZ / "docs" / "homologacao"

# ---------------------------------------------------------------------------
# O INCUMBENTE
#
# `openai` está no grupo sem relatório, e isso é registrado em vez de
# escondido: a suíte inteira de documentos deste projeto — as provas de
# estrutura, as de conteúdo, as do PDF institucional, os casos reais de
# 210 itens — foi construída e conferida com ele. A homologação dele é
# HISTÓRICA, e a evidência é o repositório.
#
# A lista é deliberadamente de UM item. O segundo nome aqui precisa de
# uma discussão, não de um commit — senão "incumbente" vira a porta dos
# fundos que este arquivo existe para fechar.
# ---------------------------------------------------------------------------
INCUMBENTES = ("openai",)


def _relatorio(motor: str) -> dict | None:
    alvo = RELATORIOS / f"{motor}.json"
    if not alvo.exists():
        return None
    return json.loads(alvo.read_text())


@pytest.mark.parametrize(
    "motor", roteamento.MOTORES_DO_GRUPO[roteamento.PROCUREMENT_HIGH_ACCURACY])
def test_motor_de_documento_oficial_tem_evidencia(motor):
    """
    A prova que impede a homologação por decreto.

    Se alguém acrescentar um motor ao grupo sem rodar
    `scripts/homologacao_modelo.py --gravar`, esta prova falha e diz
    exatamente o que fazer.
    """
    if motor in INCUMBENTES:
        return

    relatorio = _relatorio(motor)
    assert relatorio is not None, (
        f"'{motor}' está em PROCUREMENT_HIGH_ACCURACY sem relatório de "
        f"homologação. Rode:\n"
        f"    .venv/bin/python scripts/homologacao_modelo.py "
        f"--motor {motor} --gravar\n"
        f"e comite o relatório junto com a mudança da tupla.")

    assert relatorio.get("aprovado") is True, (
        f"o relatório de '{motor}' está REPROVADO: "
        f"{relatorio.get('motivo')}")


@pytest.mark.parametrize(
    "motor", roteamento.MOTORES_DO_GRUPO[roteamento.PROCUREMENT_HIGH_ACCURACY])
def test_relatorio_cobre_a_cadeia_inteira(motor):
    """
    Um relatório que mediu só o DFD não homologa o edital.

    O edital é o documento mais exigente da cadeia — ele herda o TR
    inteiro como contexto, e é onde a perda de um valor tem a pior
    consequência. Aprovar pelo elo mais fácil seria medir o que não
    importa.
    """
    relatorio = _relatorio(motor)
    if relatorio is None:
        return  # incumbente, ou ausência já acusada pela prova anterior

    medidos = {r["documento"] for r in relatorio.get("resultados", [])}
    faltando = {"dfd", "etp", "tr", "edital"} - medidos
    assert not faltando, (
        f"o relatório de '{motor}' não cobre {sorted(faltando)} — "
        "homologação parcial não homologa o edital")


def test_relatorio_aprovado_nao_admite_perda_de_literal():
    """
    O critério não pode afrouxar sem alguém notar.

    Um relatório 'aprovado' com literais perdidos significaria que o
    script mudou de opinião sobre o que é aprovação — e é essa a opinião
    que protege número, valor, data e artigo num documento assinado.
    """
    if not RELATORIOS.exists():
        pytest.skip("nenhum relatório de homologação ainda")

    for arquivo in sorted(RELATORIOS.glob("*.json")):
        relatorio = json.loads(arquivo.read_text())
        if not relatorio.get("aprovado"):
            continue
        perdidos = sum(r.get("literais_perdidos", 0)
                       for r in relatorio.get("resultados", []))
        assert perdidos == 0, (
            f"{arquivo.name} está aprovado com {perdidos} literal(is) "
            "perdido(s) — o critério afrouxou")


def test_o_incumbente_e_um_so():
    """
    "Incumbente" é exceção, e exceção que cresce vira regra. Um nome novo
    aqui precisa de discussão, não de commit.
    """
    assert INCUMBENTES == ("openai",), (
        "a lista de incumbentes mudou: ela é a porta que dispensa "
        "relatório, e alargá-la esvazia a homologação")


def test_o_script_de_homologacao_existe_e_se_explica():
    """
    A mensagem de erro das provas acima manda rodar um script. Se ele não
    existir, a orientação vira beco sem saída.
    """
    script = RAIZ / "scripts" / "homologacao_modelo.py"
    assert script.exists()
    texto = script.read_text()
    assert "--gravar" in texto
    assert "PROCUREMENT_HIGH_ACCURACY" in texto


def test_o_veredito_reprova_o_que_tem_que_reprovar():
    """
    A função que decide aprovação, medida direto.

    Os três casos de reprovação são os três jeitos de um relatório
    parecer bom sem ser: a geração nem rodou, rodou pela metade, ou
    rodou inteira e perdeu um número. O terceiro é o perigoso — é o
    único em que sai um documento com aparência de pronto.
    """
    import sys as _sys
    _sys.path.insert(0, str(RAIZ / "scripts"))
    import homologacao_modelo as hm

    completa = [{"documento": d, "status": "ok", "literais_perdidos": 0}
                for d in hm.CADEIA]
    aprovado, _ = hm.veredito(completa)
    assert aprovado is True

    # 1) a geração falhou
    aprovado, motivo = hm.veredito([{"documento": "dfd", "status": "erro",
                                     "erro": "sem chave"}])
    assert aprovado is False and "falhou" in motivo

    # 2) parou no meio — homologar pelo elo mais fácil não homologa o edital
    aprovado, motivo = hm.veredito(completa[:2])
    assert aprovado is False and "cadeia" in motivo

    # 3) rodou inteira e perdeu UM literal. Um basta.
    quase = [dict(r) for r in completa]
    quase[-1]["literais_perdidos"] = 1
    aprovado, motivo = hm.veredito(quase)
    assert aprovado is False, (
        "um único valor perdido num edital é outro valor licitado")
    assert "literal" in motivo


def test_o_caso_de_avaliacao_e_real_e_grande():
    """
    Um modelo que acerta "3 itens de papelaria" e erra numa planilha de
    210 linhas com códigos de seis dígitos não está homologado — está sem
    ter sido testado. O caso precisa ter tamanho.
    """
    import sys as _sys
    _sys.path.insert(0, str(RAIZ / "scripts"))
    import homologacao_modelo as hm

    dados = hm.caso_real()
    assert len(dados["itens"]) >= 200
    assert dados["valor_estimado"] > 0

    # E os literais precisam estar realmente lá dentro, senão a
    # conferência mede um conjunto vazio e aprova qualquer coisa.
    entrada = hm._entrada_literal(dados)
    assert len(entrada["código de item"]) >= 100, (
        "o caso perdeu os códigos de item: a conferência de literalidade "
        "passaria a aprovar por vacuidade")
