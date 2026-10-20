"""
Expansão das fontes de preço (pacote de 20/10/2026) — infraestrutura.

As linhas de `tests/fixtures/fontes_precos/` são REAIS, copiadas dos
arquivos oficiais baixados em 20/10/2026 (TCE-RS `2026.csv.zip`, sha256
45ee32c1…; BPS `2026_csv.zip`, sha256 60ed6b06…). A única linha
inventada é a do vencedor pessoa física, com CPF SINTÉTICO, para provar
que CPF não segue adiante.

Nenhum teste usa rede.
"""

from __future__ import annotations

import io
import json
import shutil
import urllib.error
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from src.precos import (arquivos, dedup_fontes, etl_bps, etl_tce_rs,
                        evidencia as ev, fontes_externas, fontes_padrao, pcp)
from src.precos.compras_gov import ComprasGovAdapter
from src.precos.fontes import Consulta, Desfecho
from src.precos.pncp import PNCPAdapter

D = Decimal
FIX = Path(__file__).parent / "fixtures" / "fontes_precos"


def _zip(tmp_path, nome, arquivos_: dict) -> Path:
    caminho = tmp_path / nome
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        for dentro, origem in arquivos_.items():
            z.write(origem, dentro)
    return caminho


@pytest.fixture
def zip_tce(tmp_path):
    return _zip(tmp_path, "2026.csv.zip", {
        "licitacao.csv": FIX / "tce_rs_licitacao.csv",
        "item.csv": FIX / "tce_rs_item.csv"})


@pytest.fixture
def zip_bps(tmp_path):
    return _zip(tmp_path, "2026_csv.zip", {"2026.csv": FIX / "bps_2026.csv"})


# ---------------------------------------------------------------------------
# Registro e travas
# ---------------------------------------------------------------------------
def test_nenhuma_fonte_nova_esta_habilitada_nem_com_a_flag_ligada():
    assert fontes_externas.fontes_habilitadas(flag_ativa=lambda _: True) == []
    for registro in fontes_externas.REGISTRO.values():
        assert registro.licenca != fontes_externas.Licenca.APROVADA
        assert registro.flag.startswith("price_source_")


def test_a_fonte_so_liga_com_licenca_prova_mapeamento_e_flag(monkeypatch):
    base = fontes_externas.REGISTRO["tce_rs"]
    aprovada = fontes_externas.RegistroFonte(
        "tce_rs", base.nome, base.acesso, base.documentacao,
        fontes_externas.Licenca.APROVADA, "teste",
        mapeamento_confirmado=True, prova_licenca="ofício de teste")
    monkeypatch.setitem(fontes_externas.REGISTRO, "tce_rs", aprovada)
    assert fontes_externas.habilitada("tce_rs", flag_ativa=lambda f: f ==
                                      "price_source_tce_rs")
    assert not fontes_externas.habilitada("tce_rs", flag_ativa=lambda _: False)

    def quebra(_):
        raise RuntimeError("sem banco")

    assert not fontes_externas.habilitada("tce_rs", flag_ativa=quebra)
    for falta in ({"prova_licenca": ""}, {"mapeamento_confirmado": False}):
        monkeypatch.setitem(fontes_externas.REGISTRO, "tce_rs",
                            fontes_externas.RegistroFonte(**{
                                **aprovada.__dict__, **falta}))
        assert not fontes_externas.habilitada("tce_rs", flag_ativa=lambda _: True)
    assert not fontes_externas.habilitada("inexistente", flag_ativa=lambda _: True)


def test_as_fontes_da_pesquisa_continuam_compras_gov_e_pncp():
    tipos = [type(f) for f in fontes_padrao()]
    assert tipos == [ComprasGovAdapter, PNCPAdapter]


# ---------------------------------------------------------------------------
# Contrato canônico
# ---------------------------------------------------------------------------
def test_decimal_lido_do_texto_com_a_escala_da_fonte():
    assert ev.ler_decimal("5029.73", formato="ponto") == D("5029.73")
    valor = ev.ler_decimal("1.0393", formato="ponto")
    assert valor == D("1.0393") and str(valor) == "1.0393"
    assert str(ev.ler_decimal("0.0150", formato="ponto") * 3) == "0.0450"
    assert ev.ler_decimal("1.234,5000", formato="br") == D("1234.5000")
    assert ev.ler_decimal("", formato="ponto") is None
    # `Decimal()` sozinho aceitaria expoente, sublinhado e sinal "+"
    for ruim in ("1,234.50", "NaN", "Infinity", "12a", "1.234.567", "1e5",
                 "1_000", "+5"):
        with pytest.raises(ev.ValorInvalido):
            ev.ler_decimal(ruim, formato="ponto")
    for ruim in ("1.234.5", "1e5", "1,2,3"):
        with pytest.raises(ev.ValorInvalido):
            ev.ler_decimal(ruim, formato="br")
    with pytest.raises(ev.ValorInvalido):
        ev.ler_decimal(5029.73, formato="ponto")


def test_cpf_nao_segue_cnpj_segue():
    assert ev.cnpj_ou_nada("J", "42572060000129") == "42572060000129"
    assert ev.cnpj_ou_nada("F", "00000000191") is None
    assert ev.cnpj_ou_nada("J", "00000000191") is None
    assert ev.cnpj_ou_nada("F", "42572060000129") is None


def _evidencia(**kw):
    base = dict(fonte_id="x", registro_id="1", descricao="Pasta AZ",
                unidade="UN", quantidade=D("70"), valor_unitario=D("9.14"),
                valor_total=D("639.80"), tipo_preco=ev.TipoPreco.HOMOLOGADO,
                url_evidencia="https://portal.tce.rs.gov.br/x")
    base.update(kw)
    return ev.conferir(ev.Evidencia(**base))


def test_so_resultado_comprovado_e_validado():
    assert _evidencia().validada
    assert _evidencia(tipo_preco=ev.TipoPreco.PRATICADO).validada
    assert _evidencia(tipo_preco=ev.TipoPreco.ESTIMADO).motivos == [ev.SO_ESTIMADO]
    assert _evidencia(tipo_preco=ev.TipoPreco.PROPOSTA).motivos == \
        [ev.TIPO_NAO_COMPROVADO]
    assert _evidencia(tipo_preco=ev.TipoPreco.DESCONHECIDO).motivos == \
        [ev.TIPO_NAO_COMPROVADO]
    assert ev.TOTAL_INCOERENTE in _evidencia(valor_total=D("700")).motivos
    assert ev.SEM_EVIDENCIA in _evidencia(url_evidencia="http://x").motivos
    assert ev.SEM_UNIDADE in _evidencia(unidade=" ").motivos
    assert ev.PRECO_INVALIDO in _evidencia(valor_unitario=D("0")).motivos
    assert ev.NATUREZA_DO_TIPO[ev.TipoPreco.ESTIMADO].value == "estimado_origem"


# ---------------------------------------------------------------------------
# TCE-RS — linhas reais
# ---------------------------------------------------------------------------
def test_tce_rs_le_o_homologado_real_e_segura_tudo_na_quarentena(zip_tce):
    leitura = etl_tce_rs.Leitura()
    evidencias = {e.registro_id: e for e in etl_tce_rs.ler(zip_tce, leitura=leitura)}
    # garrafa térmica (resultado D) só tem estimado: contada, não materializada
    assert leitura.itens == 5 and leitura.so_estimado == 1
    assert leitura.com_homologado == 4 and leitura.licitacoes == 4
    pasta = evidencias["74000:1:2026:PCE:1:108"]
    assert pasta.valor_unitario == D("9.14") and pasta.quantidade == D("70.00")
    assert pasta.valor_total == D("639.80") and pasta.unidade == "UN"
    assert pasta.orgao == "PM DE BARRA FUNDA" and pasta.fornecedor_cnpj == \
        "42572060000129"
    assert pasta.data_resultado == "2026-02-04" and pasta.resultado == "A"
    assert pasta.url_evidencia.startswith(
        "https://portal.tce.rs.gov.br/aplicprod/f?p=50500:10:")
    assert pasta.atributos["nivel_da_evidencia"] == "licitacao"
    assert pasta.atributos["valor_estimado"] == "9.19"
    # nenhum código de resultado tem significado confirmado: nada validado
    for e in evidencias.values():
        assert e.tipo_preco == ev.TipoPreco.DESCONHECIDO
        assert ev.CODIGO_DESCONHECIDO in e.motivos and not e.validada
    assert len(pasta.hash_linha) == 64


def test_tce_rs_com_o_codigo_confirmado_so_ele_passa(zip_tce, monkeypatch):
    """Quando o leiaute disser o que é "A", só "A" vira homologado — o
    item "R" (lidocaína, Novo Hamburgo) e o vazio continuam presos."""
    monkeypatch.setattr(etl_tce_rs, "RESULTADO_CONFIRMADO",
                        {"A": ev.TipoPreco.HOMOLOGADO})
    evidencias = {e.registro_id: e for e in etl_tce_rs.ler(zip_tce)}
    assert evidencias["74000:1:2026:PCE:1:108"].validada
    lidocaina = evidencias["53400:9:2026:PCE:1:24"]
    assert lidocaina.resultado == "R" and lidocaina.valor_unitario == D("117.97")
    assert not lidocaina.validada and ev.CODIGO_DESCONHECIDO in lidocaina.motivos
    assert not evidencias["54901:28:2026:PCE:6:1"].validada


def test_tce_rs_vencedor_pessoa_fisica_nao_guarda_cpf(zip_tce):
    [e] = [e for e in etl_tce_rs.ler(zip_tce) if e.item == "999"]
    assert e.fornecedor_cnpj is None
    assert "00000000191" not in json.dumps(e.para_registro())


def test_tce_rs_recusa_leiaute_mudado(tmp_path):
    ruim = tmp_path / "licitacao.csv"
    ruim.write_text("CD_ORGAO,NR_LICITACAO\n1,2\n", encoding="utf-8")
    caminho = _zip(tmp_path, "x.zip", {"licitacao.csv": ruim,
                                       "item.csv": FIX / "tce_rs_item.csv"})
    with pytest.raises(ValueError, match="mudou de leiaute"):
        list(etl_tce_rs.ler(caminho))


# ---------------------------------------------------------------------------
# BPS — linhas reais
# ---------------------------------------------------------------------------
def test_bps_e_preco_pago_mas_sem_url_por_registro_nada_valida(zip_bps):
    """Dicionário de 07/04/2026: "Preço pago por unidade do item
    adquirido" — PRATICADO. O que segura é a falta de URL por registro."""
    leitura = etl_bps.Leitura()
    linhas = {e.registro_id: e for e in etl_bps.ler(zip_bps, leitura=leitura)}
    assert leitura.linhas == 5
    pali = linhas["27507687"]
    assert pali.valor_unitario == D("5029.73") and pali.quantidade == D("723")
    assert pali.valor_total == D("3636494.79") and pali.unidade == "FRASCO"
    assert pali.codigo_catalogo == "446467" and pali.data_resultado == "2026-01-09"
    assert pali.atributos["apresentacao"] == "FRASCO 1,00 ML"
    assert str(linhas["27507743"].valor_unitario) == "1.0393"
    assert pali.motivos == [ev.SEM_EVIDENCIA]
    for e in linhas.values():
        assert e.tipo_preco == ev.TipoPreco.PRATICADO
        assert ev.NATUREZA_DO_TIPO[e.tipo_preco].value == "praticado"
        assert ev.TIPO_NAO_COMPROVADO not in e.motivos
        assert ev.SEM_EVIDENCIA in e.motivos and not e.validada


def test_bps_judicial_e_leilao_tem_motivo_proprio(zip_bps):
    linhas = {e.registro_id: e for e in etl_bps.ler(zip_bps)}
    assert ev.COMPRA_JUDICIAL in linhas["27508141"].motivos      # somatropina
    evolocumabe = linhas["27587779"]
    assert {ev.COMPRA_JUDICIAL, ev.MODALIDADE_FORA} <= set(evolocumabe.motivos)
    assert ev.COMPRA_JUDICIAL not in linhas["27507687"].motivos


def test_bps_so_compara_o_mesmo_catmat_na_mesma_unidade(zip_bps):
    linhas = {e.registro_id: e for e in etl_bps.ler(zip_bps)}
    chaves = {i: etl_bps.chave_de_equivalencia(e) for i, e in linhas.items()}
    assert chaves["27507687"] == ("446467", "FRASCO")
    # betametasona (frasco 30 ml) e bezafibrato (comprimido) nunca se fundem
    assert len(set(chaves.values())) == len(chaves)


# ---------------------------------------------------------------------------
# Deduplicação conservadora
# ---------------------------------------------------------------------------
def test_reprocessar_nao_duplica_e_parecido_nao_funde(zip_tce):
    evidencias = list(etl_tce_rs.ler(zip_tce))
    unicas, repetidas = dedup_fontes.deduplicar(evidencias + evidencias)
    assert repetidas == len(evidencias) and len(unicas) == len(evidencias)
    pasta = next(e for e in evidencias if e.item == "108")
    mesma = {"ni_fornecedor": "42.572.060/0001-29",
             "valor_unitario_original": "9.14", "data_compra": "2026-02-20"}
    assert dedup_fontes.possiveis_duplicatas([pasta], [mesma]) == [(pasta, mesma)]
    for diferente in ({**mesma, "valor_unitario_original": "9.15"},
                      {**mesma, "ni_fornecedor": "11111111000111"},
                      {**mesma, "data_compra": "2026-06-20"},
                      {**mesma, "data_compra": None}):
        assert dedup_fontes.possiveis_duplicatas([pasta], [diferente]) == []


# ---------------------------------------------------------------------------
# Arquivo: download e ZIP sem confiança
# ---------------------------------------------------------------------------
HOST_TCE = "dados.tce.rs.gov.br"


def test_url_so_das_fontes_registradas():
    for boa in fontes_externas.REGISTRO["tce_rs"].downloads + \
            fontes_externas.REGISTRO["bps"].downloads:
        assert arquivos.url_permitida(boa)
    for ruim in ("http://dados.tce.rs.gov.br/x.zip",
                 "https://evil.example/x.zip",
                 "https://s3.sa-east-1.amazonaws.com/outro-bucket/x.zip",
                 # credencial embutida, no host CERTO: recusada mesmo assim
                 f"https://user:senha@{HOST_TCE}/x.zip"):
        assert not arquivos.url_permitida(ruim)


class _Resposta(io.BytesIO):
    def __init__(self, corpo: bytes, url: str, cabecalhos=None):
        super().__init__(corpo)
        self._url = url
        self.headers = cabecalhos or {}

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


URL_BPS = fontes_externas.REGISTRO["bps"].downloads[0]


def test_baixar_tenta_de_novo_so_em_5xx_e_grava_o_hash(tmp_path):
    chamadas, dormiu = [], []

    def abrir(req):
        chamadas.append(req.full_url)
        if len(chamadas) == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "x", {}, None)
        return _Resposta(b"conteudo", req.full_url, {"ETag": '"e"'})

    snap = arquivos.baixar(URL_BPS, tmp_path / "a.zip", abrir=abrir,
                           dormir=dormiu.append)
    assert len(chamadas) == 2 and dormiu == [arquivos.RECUO_S]
    assert snap.bytes == 8 and snap.etag == '"e"'
    assert snap.sha256 == arquivos.sha256_do_arquivo(tmp_path / "a.zip")

    def nao_existe(req):
        raise urllib.error.HTTPError(req.full_url, 404, "x", {}, None)

    with pytest.raises(urllib.error.HTTPError):
        arquivos.baixar(URL_BPS, tmp_path / "b.zip", abrir=nao_existe,
                        dormir=dormiu.append)
    assert dormiu == [arquivos.RECUO_S]   # 404 não repete


def test_baixar_recusa_redirecionamento_e_tamanho(tmp_path):
    def fora(req):
        return _Resposta(b"x", "https://evil.example/x.zip")

    with pytest.raises(arquivos.ArquivoRecusado, match="redirecionou"):
        arquivos.baixar(URL_BPS, tmp_path / "a.zip", abrir=fora)

    def grande(req):
        return _Resposta(b"x" * 50, req.full_url, {"Content-Length": "50"})

    with pytest.raises(arquivos.ArquivoRecusado, match="teto"):
        arquivos.baixar(URL_BPS, tmp_path / "b.zip", abrir=grande, maximo=10)

    def mente(req):
        return _Resposta(b"x" * 50, req.full_url)

    with pytest.raises(arquivos.ArquivoRecusado, match="teto"):
        arquivos.baixar(URL_BPS, tmp_path / "c.zip", abrir=mente, maximo=10)
    assert not list(tmp_path.glob("*.parcial"))


def test_zip_hostil_e_recusado(tmp_path):
    def zip_com(nome, dados=b"a;b\n1;2\n"):
        caminho = tmp_path / f"{len(list(tmp_path.iterdir()))}.zip"
        with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr(nome, dados)
        return caminho

    for nome in ("../../evil.csv", "/abs.csv", "C:/x.csv"):
        with pytest.raises(arquivos.ArquivoRecusado, match="inseguro"):
            arquivos.conferir_zip(zip_com(nome))
    with pytest.raises(arquivos.ArquivoRecusado, match="extensão"):
        arquivos.conferir_zip(zip_com("script.py"))
    with pytest.raises(arquivos.ArquivoRecusado, match="taxa"):
        arquivos.conferir_zip(zip_com("bomba.csv", b"0" * 5_000_000))
    link = tmp_path / "link.zip"
    with zipfile.ZipFile(link, "w") as z:
        info = zipfile.ZipInfo("atalho.csv")
        info.external_attr = (0o120777 << 16)
        z.writestr(info, "alvo")
    with pytest.raises(arquivos.ArquivoRecusado, match="simbólico"):
        arquivos.conferir_zip(link)
    assert arquivos.conferir_zip(zip_com("2026.csv"))


# ---------------------------------------------------------------------------
# Portal de Compras Públicas — desconectado
# ---------------------------------------------------------------------------
def test_portal_de_compras_publicas_nao_abre_conexao(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("o adaptador bloqueado não pode abrir rede")

    monkeypatch.setattr("urllib.request.urlopen", proibido)
    adaptador = pcp.PortalComprasPublicasAdapter()
    resultado = adaptador.pesquisar(Consulta(descricao="papel A4"))
    assert resultado.desfecho == Desfecho.FALHA
    assert resultado.falha == pcp.MOTIVO_BLOQUEIO and not resultado.referencias
    assert adaptador.healthcheck() is False


# ---------------------------------------------------------------------------
# Script de bancada
# ---------------------------------------------------------------------------
def test_relatorio_de_staging_nas_linhas_reais(zip_tce, zip_bps):
    import scripts.etl_fontes_precos as etl

    tce = etl.relatorio("tce_rs", zip_tce, amostra=2, termos=["pasta az"])
    assert tce["evidencias"] == 4 and tce["validadas"] == 0
    assert tce["leitura"]["so_estimado"] == 1
    assert tce["quarentena_por_motivo"][ev.CODIGO_DESCONHECIDO] == 4
    assert tce["por_termo"]["pasta az"]["linhas"] == 2
    assert len(tce["amostra"]) == 2 and tce["com_url_oficial"] == 4
    bps = etl.relatorio("bps", zip_bps, amostra=30)
    assert bps["evidencias"] == 5 and bps["validadas"] == 0
    assert len(bps["amostra"]) == 5
    assert "00000000191" not in json.dumps(tce, ensure_ascii=False)
