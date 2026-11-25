"""
SIGTAP — remuneração da Tabela Unificada do SUS, em consulta própria.

A amostra é REAL: as tabelas de nomes inteiras e as linhas de cinco
procedimentos de `tb_procedimento.txt` e `rl_procedimento_modalidade.txt` do
arquivo oficial de 11/2026 (`TabelaUnificada_202611_v2611051737.zip`, sha256
06c074c3…05dad45), com os leiautes do próprio ZIP
(`fixtures/fontes_precos/sigtap_2026_11_amostra.zip`). Os valores conferidos
com a consulta pública do SIGTAP: glicose SA R$ 1,85, consulta especializada
SA R$ 10,00, cesariana SH R$ 395,68 + SP R$ 150,05.

Provas:
* leitura com duas casas implícitas, modalidades e nomes pelos códigos;
* conferências de integridade (canal FTP sem criptografia): nome oficial,
  competência do nome = pedida = a de CADA linha, leiaute embutido igual ao
  esperado, código único e numérico, valor legível;
* importação idempotente, por versão, com recusa de arquivo que encolheu;
* consulta: filtros, código formatado, totais ambulatorial (SA) e
  hospitalar (SH + SP), endereço oficial, e que não é fonte da cesta;
* baixador: só nome oficial, só a competência pedida, teto de tamanho.
"""

from __future__ import annotations

import io
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from src import db, governanca
from src.precos import cotacoes, sigtap, sigtap_servico
from tests.cotacoes_apoio import ligar_banco_falso

AMOSTRA = Path(__file__).parent / "fixtures" / "fontes_precos" / "sigtap_2026_11_amostra.zip"
NOME = "TabelaUnificada_202611_v2611051737.zip"


def _zip(tmp_path: Path, mudar=None, nome: str = NOME) -> Path:
    """A amostra real, regravada; `mudar(arquivos)` altera o conteúdo antes."""
    with zipfile.ZipFile(AMOSTRA) as z:
        conteudo = {n: z.read(n) for n in z.namelist()}
    if mudar:
        mudar(conteudo)
    destino = tmp_path / nome
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for n, dados in conteudo.items():
            z.writestr(n, dados)
    return destino


def _linhas(conteudo: dict, tabela: str) -> list[bytes]:
    return [l for l in conteudo[f"{tabela}.txt"].split(b"\r\n") if l]


def _gravar(conteudo: dict, tabela: str, linhas: list[bytes]) -> None:
    conteudo[f"{tabela}.txt"] = b"\r\n".join(linhas) + b"\r\n"


def _por_codigo(tmp_path, mudar=None, leitura=None) -> dict[str, sigtap.Procedimento]:
    return {p.codigo: p for p in sigtap.ler(_zip(tmp_path, mudar), "2026-11",
                                            leitura=leitura)}


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------
def test_le_valores_com_duas_casas_implicitas_e_os_totais_do_sigtap(tmp_path):
    ps = _por_codigo(tmp_path)
    assert sorted(ps) == ["0101010010", "0202010473", "0301010072", "0301010110",
                          "0411010034"]
    glicose, consulta, cesariana = ps["0202010473"], ps["0301010072"], ps["0411010034"]
    assert (glicose.nome, glicose.valor_sa) == ("DOSAGEM DE GLICOSE", Decimal("1.85"))
    assert consulta.valor_sa == Decimal("10.00")
    assert consulta.nome == "CONSULTA MEDICA EM ATENÇÃO ESPECIALIZADA"   # latin-1
    assert (cesariana.valor_sh, cesariana.valor_sp) == (Decimal("395.68"), Decimal("150.05"))
    # como os relatórios do SIGTAP: total ambulatorial = SA; hospitalar = SH + SP
    assert cesariana.total_hospitalar == Decimal("545.73")
    assert cesariana.total_ambulatorial == Decimal("0.00")
    assert glicose.total_ambulatorial == Decimal("1.85") and glicose.total_hospitalar == 0


def test_modalidades_grupo_e_financiamento_saem_pelo_nome(tmp_path):
    ps = _por_codigo(tmp_path)
    assert ps["0202010473"].modalidades == ("Ambulatorial", "Hospital Dia", "Hospitalar")
    assert ps["0411010034"].modalidades == ("Hospitalar",)
    cesariana = ps["0411010034"]
    assert (cesariana.grupo, cesariana.subgrupo, cesariana.forma_organizacao) == (
        "Procedimentos cirúrgicos", "Cirurgia obstétrica", "Parto")
    assert cesariana.financiamento == "Média e Alta Complexidade (MAC)"
    assert ps["0101010010"].financiamento == "Atenção Básica (PAB)"
    # complexidade e sexo como a fonte codifica: o leiaute não documenta rótulo
    assert (cesariana.complexidade, cesariana.sexo) == ("2", "I")
    assert cesariana.chave == "2026-11:0411010034"


def test_valor_zero_e_dado_da_tabela_nao_recusa(tmp_path):
    leitura = sigtap.Leitura()
    ps = _por_codigo(tmp_path, leitura=leitura)
    assert ps["0101010010"].total_ambulatorial == 0 == ps["0101010010"].total_hospitalar
    assert (leitura.linhas, leitura.validos, leitura.sem_valor) == (5, 5, 2)
    assert leitura.motivos == {} and leitura.versao_arquivo == "2611051737"


def test_numero_da_linha_e_o_do_arquivo(tmp_path):
    ps = _por_codigo(tmp_path)
    assert [ps[c].linha for c in sorted(ps)] == [1, 2, 3, 4, 5]


# ---------------------------------------------------------------------------
# Conferências de integridade
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("nome", [
    "TabelaUnificada_202611.zip", "TabelaUnificada_202611_v26110517.zip",
    "tabelaunificada_202611_v2611051737.zip", "TabelaUnificada_202613_v2611051737.zip",
    "TabelaUnificada_202611_v2611051737.zip.exe",
])
def test_nome_fora_da_publicacao_e_recusado(tmp_path, nome):
    with pytest.raises((sigtap.ArquivoInvalido, ValueError)):
        sigtap.ler(_zip(tmp_path), "2026-11", nome=nome)


def test_competencia_do_nome_tem_de_ser_a_pedida(tmp_path):
    with pytest.raises(sigtap.ArquivoInvalido, match="competência 2026-11"):
        sigtap.ler(_zip(tmp_path), "2026-10")


def test_linha_de_outra_competencia_e_recusada_com_motivo(tmp_path):
    def mudar(c):
        linhas = _linhas(c, "tb_procedimento")
        linhas[1] = linhas[1][:330] + b"202610"
        _gravar(c, "tb_procedimento", linhas)

    leitura = sigtap.Leitura()
    ps = _por_codigo(tmp_path, mudar, leitura)
    assert "0202010473" not in ps and len(ps) == 4
    assert leitura.motivos == {sigtap.SEM_COMPETENCIA: 1}
    assert leitura.recusadas == [{"linha": 2, "codigo": "0202010473",
                                  "motivo": sigtap.SEM_COMPETENCIA}]


def test_codigo_repetido_invalido_e_valor_ilegivel_sao_recusados(tmp_path):
    def mudar(c):
        linhas = _linhas(c, "tb_procedimento")
        linhas.append(linhas[2])                              # repetido
        linhas[0] = b"01010100X0" + linhas[0][10:]            # código inválido
        linhas[1] = linhas[1][:294] + b"00000000018A" + linhas[1][306:]   # SA ilegível
        _gravar(c, "tb_procedimento", linhas)

    leitura = sigtap.Leitura()
    ps = _por_codigo(tmp_path, mudar, leitura)
    assert sorted(ps) == ["0301010072", "0301010110", "0411010034"]
    assert leitura.motivos == {sigtap.CODIGO_INVALIDO: 1, sigtap.VALOR_ILEGIVEL: 1,
                               sigtap.CODIGO_REPETIDO: 1}


@pytest.mark.parametrize("tabela", sorted(sigtap.LEIAUTES))
def test_leiaute_diferente_nao_le_nada(tmp_path, tabela):
    def mudar(c):
        texto = c[f"{tabela}_layout.txt"].decode("latin-1").splitlines()
        coluna = texto[1].split(",")
        coluna[3] = str(int(coluna[3]) + 1)                   # uma posição a mais
        texto[1] = ",".join(coluna)
        c[f"{tabela}_layout.txt"] = "\r\n".join(texto).encode("latin-1")

    with pytest.raises(sigtap.ArquivoInvalido, match=f"leiaute de {tabela} mudou"):
        sigtap.ler(_zip(tmp_path, mudar), "2026-11")


def test_zip_sem_tabela_ou_sem_leiaute_e_recusado(tmp_path):
    with pytest.raises(sigtap.ArquivoInvalido, match="leiaute de tb_rubrica"):
        sigtap.ler(_zip(tmp_path, lambda c: c.pop("tb_rubrica_layout.txt")), "2026-11")
    with pytest.raises(sigtap.ArquivoInvalido, match="tb_procedimento.txt"):
        sigtap.ler(_zip(tmp_path, lambda c: c.pop("tb_procedimento.txt")), "2026-11")


def test_zip_com_executavel_e_recusado_antes_de_ler(tmp_path):
    from src.precos import arquivos

    with pytest.raises(arquivos.ArquivoRecusado):
        sigtap.ler(_zip(tmp_path, lambda c: c.update({"setup.exe": b"MZ"})), "2026-11")


# ---------------------------------------------------------------------------
# Importação por versão
# ---------------------------------------------------------------------------
def test_importa_publica_e_reimportar_nao_duplica(tmp_path):
    armazem, caminho = sigtap.ArmazemEmMemoria(), _zip(tmp_path)
    feito = sigtap.importar(armazem, caminho, competencia="2026-11")
    assert (feito.desfecho, feito.validos, feito.sem_valor) == (sigtap.PUBLICADO, 5, 2)
    assert feito.versao_arquivo == "2611051737" and len(feito.sha256) == 64
    assert len(armazem.registros) == 5
    assert all(l["vigente"] for l in armazem.registros.values())
    versao = armazem.versao_publicada("2026-11")
    assert versao["arquivo"] == NOME and versao["versao_parser"] == sigtap.VERSAO_PARSER
    assert sigtap.importar(armazem, caminho, competencia="2026-11").desfecho == \
        "ja_publicado"
    assert len(armazem.registros) == 5


def test_linha_do_indice_guarda_rastreabilidade(tmp_path):
    armazem = sigtap.ArmazemEmMemoria()
    feito = sigtap.importar(armazem, _zip(tmp_path), competencia="2026-11")
    [linha] = [l for l in armazem.registros.values() if l["codigo"] == "0411010034"]
    assert (linha["valor_sh"], linha["valor_sp"], linha["valor_sa"]) == (
        "395.68", "150.05", "0.00")
    assert linha["arquivo"] == NOME and linha["arquivo_sha256"] == feito.sha256
    assert linha["linha_arquivo"] == 5 and linha["modalidades"] == ["Hospitalar"]
    assert linha["chave_linha"] == "2026-11:0411010034" and len(linha["registro_id"]) == 40
    assert linha["nome_busca"] == "operacao cesariana" and linha["hash_linha"]


def test_versao_nova_da_competencia_substitui_a_anterior_inteira(tmp_path):
    armazem = sigtap.ArmazemEmMemoria()
    sigtap.importar(armazem, _zip(tmp_path), competencia="2026-11")

    def reajuste(c):
        linhas = _linhas(c, "tb_procedimento")
        linhas[1] = linhas[1][:294] + b"000000000190" + linhas[1][306:]
        _gravar(c, "tb_procedimento", linhas)

    pasta = tmp_path / "nova"
    pasta.mkdir()
    nova = _zip(pasta, reajuste, nome="TabelaUnificada_202611_v2611201200.zip")
    feito = sigtap.importar(armazem, nova, competencia="2026-11")
    assert feito.desfecho == sigtap.PUBLICADO and feito.validos_na_versao_anterior == 5
    vigentes = [l for l in armazem.registros.values() if l["vigente"]]
    assert len(vigentes) == 5 and {l["arquivo_sha256"] for l in vigentes} == {feito.sha256}
    [glicose] = sigtap.consultar(armazem.buscar, codigo="0202010473")
    assert glicose["valor_sa"] == "1.90"
    assert glicose["arquivo"] == "TabelaUnificada_202611_v2611201200.zip"
    assert sum(v["vigente"] for v in armazem.versoes.values()) == 1


def test_arquivo_que_encolheu_demais_e_recusado_e_a_versao_anterior_fica(tmp_path):
    armazem = sigtap.ArmazemEmMemoria()
    sigtap.importar(armazem, _zip(tmp_path), competencia="2026-11")
    pasta = tmp_path / "menor"
    pasta.mkdir()
    menor = _zip(pasta, lambda c: _gravar(c, "tb_procedimento", _linhas(c, "tb_procedimento")[:2]),
                 nome="TabelaUnificada_202611_v2611201200.zip")
    feito = sigtap.importar(armazem, menor, competencia="2026-11")
    assert feito.desfecho == sigtap.RECUSADO and "redução" in feito.motivo
    assert {l["arquivo"] for l in armazem.registros.values() if l["vigente"]} == {NOME}
    assert len([l for l in armazem.registros.values() if l["vigente"]]) == 5


def test_arquivo_sem_procedimento_valido_e_recusado(tmp_path):
    armazem = sigtap.ArmazemEmMemoria()
    vazio = _zip(tmp_path, lambda c: _gravar(c, "tb_procedimento", [b"X" * 336]))
    feito = sigtap.importar(armazem, vazio, competencia="2026-11")
    assert feito.desfecho == sigtap.RECUSADO and armazem.registros == {}


# ---------------------------------------------------------------------------
# Consulta
# ---------------------------------------------------------------------------
@pytest.fixture
def importado(tmp_path):
    armazem = sigtap.ArmazemEmMemoria()
    sigtap.importar(armazem, _zip(tmp_path), competencia="2026-11")
    return armazem


def test_consulta_por_termo_descreve_remuneracao_rastreavel(importado):
    [p] = sigtap.consultar(importado.buscar, termo="Operação cesariana")
    assert p["codigo_formatado"] == "04.11.01.003-4"
    assert (p["total_ambulatorial"], p["total_hospitalar"]) == ("0.00", "545.73")
    assert (p["valor_sh"], p["valor_sp"]) == ("395.68", "150.05")
    assert p["natureza"] == "remuneracao_sus" and "não preço de compra" in p["rotulo_natureza"]
    assert p["competencia_exibicao"] == "11/2026" and p["sem_valor"] is False
    assert p["url_arquivo"] == f"ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/{NOME}"
    assert p["linha_arquivo"] == 5


def test_consulta_por_codigo_aceita_a_forma_pontuada(importado):
    [p] = sigtap.consultar(importado.buscar, codigo="02.02.01.047-3")
    assert p["codigo"] == "0202010473" and p["total_ambulatorial"] == "1.85"


def test_consulta_filtra_por_modalidade(importado):
    assert [p["codigo"] for p in sigtap.consultar(
        importado.buscar, termo="glicose", modalidade="Hospitalar")] == ["0202010473"]
    assert sigtap.consultar(importado.buscar, termo="consulta",
                            modalidade="Hospitalar") == []


def test_valor_zero_e_dito_na_consulta(importado):
    [p] = sigtap.consultar(importado.buscar, codigo="0101010010")
    assert p["sem_valor"] is True


@pytest.mark.parametrize("filtros", [
    {"codigo": "123"}, {"codigo": "04110100345"}, {"competencia": "11/2026"},
    {"competencia": "2026-13"}, {"modalidade": "Domiciliar"},
])
def test_filtro_fora_da_regra_nao_vai_ao_indice(filtros):
    chamadas = []
    with pytest.raises(ValueError):
        sigtap.consultar(lambda *a, **k: chamadas.append(a) or [], termo="x", **filtros)
    assert chamadas == []


def test_busca_vazia_nao_vai_ao_indice():
    chamadas = []
    assert sigtap.consultar(lambda *a, **k: chamadas.append(a) or [], termo="  ") == []
    assert chamadas == []


def test_linha_sem_rastreabilidade_nao_chega_a_tela(importado):
    [boa] = [l for l in importado.registros.values() if l["codigo"] == "0411010034"]
    linhas = [{**boa, "arquivo": "outro.zip"}, {**boa, "valor_sh": "-1"},
              {**boa, "valor_sp": "NaN"}, {**boa, "codigo": "41101003"},
              {k: v for k, v in boa.items() if k != "competencia"}, boa]
    assert [p["codigo"] for p in sigtap.consultar(lambda *a, **k: linhas,
                                                   termo="cesariana")] == ["0411010034"]


def test_sigtap_nao_e_fonte_da_cesta_de_compras(monkeypatch):
    ligar_banco_falso(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa", lambda nome: True)
    nomes = [type(f).__name__ for f in cotacoes._fontes_padrao()]
    assert not any("SIGTAP" in n.upper() for n in nomes)
    assert governanca.FLAG_REFERENCIA_SIGTAP == "referencia_sus_sigtap"


def test_repositorio_le_pela_rpc_com_o_token_do_usuario(monkeypatch):
    from src.precos import repositorio as repo

    cliente = ligar_banco_falso(monkeypatch)
    repo.buscar_sigtap(["cesariana"], modalidade="Hospitalar", limite=20)
    [(nome, parametros)] = cliente.rpcs
    assert nome == "precos_sigtap_buscar"
    assert parametros == {"p_termos": ["cesariana"], "p_codigo": None,
                          "p_competencia": None, "p_modalidade": "Hospitalar",
                          "p_limite": 20}


# ---------------------------------------------------------------------------
# Baixador do FTP oficial
# ---------------------------------------------------------------------------
class FTPFalso:
    """Registra o que o baixador pediu; serve `arquivos` por nome."""

    def __init__(self, arquivos: dict[str, bytes], nomes=None):
        self.arquivos, self.nomes, self.pedidos = arquivos, nomes, []

    def __call__(self, host, timeout):
        self.pedidos.append(("conectar", host, timeout))
        return self

    def login(self):
        self.pedidos.append(("login",))

    def cwd(self, pasta):
        self.pedidos.append(("cwd", pasta))

    def nlst(self):
        return list(self.nomes if self.nomes is not None else self.arquivos)

    def retrbinary(self, comando, gravar):
        self.pedidos.append(("retr", comando))
        dados = self.arquivos[comando.removeprefix("RETR ")]
        for i in range(0, len(dados), 4):
            gravar(dados[i:i + 4])

    def close(self):
        self.pedidos.append(("close",))


def test_listagem_so_aceita_nome_oficial_da_competencia_e_ordena_pela_versao():
    nomes = ["TabelaUnificada_202611_v2611051737.zip", "TabelaUnificada_202611_v2611201200.zip",
             "TabelaUnificada_202610_v2610101010.zip", "../TabelaUnificada_202611_v9999999999.zip.exe",
             "LEIA_ME.TXT", "TabelaUnificada_202611_v26110517.zip"]
    ftp = FTPFalso({}, nomes)
    assert sigtap_servico.listar("2026-11", fabrica=ftp) == [
        "TabelaUnificada_202611_v2611201200.zip", "TabelaUnificada_202611_v2611051737.zip"]
    assert ftp.pedidos[:3] == [("conectar", "ftp2.datasus.gov.br", sigtap_servico.TEMPO_LIMITE),
                               ("login",), ("cwd", "/pub/sistemas/tup/downloads/")]
    assert ftp.pedidos[-1] == ("close",)


def test_baixa_so_nome_oficial_e_para_no_teto(tmp_path):
    ftp = FTPFalso({NOME: AMOSTRA.read_bytes()})
    destino = sigtap_servico.baixar(NOME, tmp_path, fabrica=ftp)
    assert destino == tmp_path / NOME and destino.read_bytes() == AMOSTRA.read_bytes()
    assert ("retr", f"RETR {NOME}") in ftp.pedidos

    with pytest.raises(sigtap.ArquivoInvalido):
        sigtap_servico.baixar("../../etc/passwd", tmp_path, fabrica=ftp)
    (tmp_path / "x").mkdir()
    with pytest.raises(sigtap.ArquivoInvalido, match="teto"):
        sigtap_servico.baixar(NOME, tmp_path / "x", fabrica=ftp, teto=10)
    assert not (tmp_path / "x" / NOME).exists()        # parcial não fica


def test_importar_por_linha_de_comando_com_zip_ja_baixado(tmp_path, capsys):
    caminho = _zip(tmp_path)
    assert sigtap_servico.main(["importar", "--zip", str(caminho)]) == 0
    saida = capsys.readouterr().out
    assert '"desfecho": "publicado"' in saida and '"validos": 5' in saida
    assert f"ftp://ftp2.datasus.gov.br/pub/sistemas/tup/downloads/{NOME}" in saida
    with pytest.raises(SystemExit, match="competência 2026-11"):
        sigtap_servico.main(["importar", "--zip", str(caminho), "--competencia", "2026-10"])


def test_armazem_do_banco_exige_credencial_do_ambiente(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    with pytest.raises(SystemExit, match="SUPABASE_SERVICE_KEY"):
        sigtap_servico.armazem_do_banco()


def test_amostra_e_a_publicacao_real():
    """A amostra não foi inventada: leiautes do ZIP oficial, nomes inteiros."""
    with zipfile.ZipFile(AMOSTRA) as z:
        nomes = set(z.namelist())
        assert {f"{t}_layout.txt" for t in sigtap.LEIAUTES} <= nomes
        assert len(z.read("tb_grupo.txt").splitlines()) >= 8
        assert io.BytesIO(z.read("tb_procedimento.txt")).read().count(b"202611") >= 5
