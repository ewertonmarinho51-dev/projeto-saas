"""
Emissão dos relatórios pela API (P04d): preparo, ciência, pedido, worker,
download.

PostgREST simulado e domínio substituído: aqui se prova a orquestração —
ciência exigida pelo SERVIDOR na hora de gerar, flag ilegível nunca vira
"desligada", quem pode registrar a ciência, idempotência do pedido, o
download só do dono e com o tipo que o worker deu. O ciclo com banco e
Redis reais é `tests_rls/test_rls_relatorios.py`.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from govconect_api import artefatos, coleta, relatorios
from govconect_api.config import carregar
from govconect_api.main import criar_app
from govconect_api.verificador import VerificadorSupabase
from src import db, governanca
from src.precos import ciencia, emissao, relatorio
from src.precos.documento_cotacao import ErroDeRenderizacao

from apoio_jwt import EMISSOR, TENANT_A, USUARIO_A, Emissor, PostgrestFalso

P = "dddddddd-0000-4000-8000-000000000002"
JOB = "abababab-0000-4000-8000-000000000002"
OUTRO = "99999999-0000-4000-8000-000000000009"
ASSINATURA = "a" * 64


class FilaFalsa:
    def __init__(self):
        self.avisos = []

    def enfileirar(self, **aviso):
        self.avisos.append(aviso)


@pytest.fixture
def emissor():
    return Emissor()


@pytest.fixture
def flags(monkeypatch):
    ligadas = {governanca.FLAG_CIENCIA_EMISSAO: True, governanca.FLAG_RELATORIO_VISUAL: True}
    monkeypatch.setattr(db, "flag_ativa", lambda nome: ligadas.get(nome, False))
    return ligadas


@pytest.fixture
def dominio(monkeypatch, flags):
    estado = {"preparo": ciencia.Preparo(pesquisa_id=P, revisao="r1", assinatura=ASSINATURA),
              "registrada": None, "exigir": {"payload": {"assinatura": ASSINATURA}},
              "registros": [], "renderizados": [], "bloqueio": None}
    pesquisa = {"id": P, "tenant_id": TENANT_A, "nome": "Pesquisa", "versao": 1}
    monkeypatch.setattr(relatorios, "_carregar",
                        lambda pid, tenant: (pesquisa, [{"id": "i1", "numero": 1}], {"i1": []}))
    monkeypatch.setattr(relatorio, "identificador_da_versao", lambda *a: "id-decisorio")
    monkeypatch.setattr(ciencia, "pareceres_do_jev", lambda *a: {})
    monkeypatch.setattr(ciencia, "preparar", lambda *a, **k: estado["preparo"])
    monkeypatch.setattr(ciencia, "localizar", lambda *a: estado["registrada"])

    def exigir(*a, **k):
        if estado["exigir"] is None:
            raise ciencia.CienciaNecessaria(estado["preparo"])
        return estado["exigir"]

    def conferir(*a):
        if estado["bloqueio"]:
            raise ErroDeRenderizacao(estado["bloqueio"])

    def renderizar(pesquisa, itens, referencias, *, formato, tipo, ciencia_doc, marca=None,
                   branding_legado=None):
        estado["renderizados"].append((tipo, formato, ciencia_doc))
        return (f"{tipo}-{formato}".encode(), f"rel-{tipo}.{formato}", "x/x")

    def registrar(pesquisa, itens, referencias, **k):
        estado["registros"].append(k)
        return {"hash_decisorio": "h" * 64}, True

    monkeypatch.setattr(ciencia, "exigir", exigir)
    monkeypatch.setattr(ciencia, "registrar",
                        lambda *a, **k: estado.update(ator=k["ator"]) or
                        {"payload": {"registrada_em": "2026-10-22T20:00:00+00:00"}})
    monkeypatch.setattr(emissao, "conferir_cestas", conferir)
    monkeypatch.setattr(emissao, "renderizar", renderizar)
    monkeypatch.setattr(emissao, "registrar", registrar)
    monkeypatch.setattr(emissao, "marca_resolvida", lambda: None)
    return estado


def _banco(dono=USUARIO_A):
    b = PostgrestFalso()
    b.responder("GET", "pesquisas_preco", 200, [{"id": P, "auth_user_id": dono}])
    return b


def _api(emissor, banco, fila=None, deposito=None):
    config = carregar({"APP_ENV": "test", "SUPABASE_URL": "https://exemplo-staging.supabase.co",
                       "SUPABASE_KEY": "chave-publicavel-de-teste", "PRICE_RESEARCH_ENABLED": "1"})
    rest = banco.cliente()
    return TestClient(criar_app(config, rest=rest, fila=fila or FilaFalsa(),
                                deposito=deposito or artefatos.DepositoMemoria(),
                                verificador=VerificadorSupabase(
                                    emissor=EMISSOR, rest=rest, chave_para=emissor.chave_para)),
                      raise_server_exceptions=False)


def _h(emissor, **extra):
    return {"Authorization": f"Bearer {emissor.token()}", **extra}


def _alerta():
    from src.precos.saneamento import Alerta

    return Alerta(item_id="i1", numero=1, descricao="Caneta", referencia_id="r1",
                  valor="12.3456", mediana="2.0000", codigos=["ATIPICO"],
                  mensagem="muito acima da mediana", origem="PNCP — Prefeitura X")


# ---------------------------------------------------------------------------
# Preparo
# ---------------------------------------------------------------------------
def test_preparo_mostra_alertas_em_string_e_quem_pode_ciente(emissor, dominio):
    dominio["preparo"] = ciencia.Preparo(pesquisa_id=P, revisao="r1", assinatura=ASSINATURA,
                                         alertas=[_alerta()])
    r = _api(emissor, _banco()).get(f"/api/v1/precos/pesquisas/{P}/emissao", headers=_h(emissor))
    assert r.status_code == 200, r.text
    corpo = r.json()
    assert corpo["disponivel"] and corpo["requer_ciencia"] and corpo["pode_registrar_ciencia"]
    assert corpo["alertas"][0]["valor"] == {"valor": "12.3456", "exibicao": "R$ 12,35"}
    assert corpo["assinatura"] == ASSINATURA and corpo["ciencia"] is None
    assert ("cotacao", "pdf") in {(o["tipo"], o["formato"]) for o in corpo["opcoes"]}


def test_colega_ve_o_preparo_mas_nao_registra_ciencia(emissor, dominio):
    r = _api(emissor, _banco(dono=OUTRO)).get(f"/api/v1/precos/pesquisas/{P}/emissao",
                                              headers=_h(emissor))
    assert r.status_code == 200 and r.json()["pode_registrar_ciencia"] is False


def test_cesta_acima_do_teto_aparece_como_bloqueio(emissor, dominio):
    dominio["bloqueio"] = "O relatório não pode ser gerado: item 3"
    r = _api(emissor, _banco()).get(f"/api/v1/precos/pesquisas/{P}/emissao", headers=_h(emissor))
    assert r.json()["bloqueio"].startswith("O relatório não pode ser gerado")


def test_flag_ilegivel_e_503_nunca_desligada(emissor, dominio, monkeypatch):
    def quebra(nome):
        raise db.ErroBanco("flags indisponíveis")

    monkeypatch.setattr(db, "flag_ativa", quebra)
    r = _api(emissor, _banco()).get(f"/api/v1/precos/pesquisas/{P}/emissao", headers=_h(emissor))
    assert r.status_code == 503 and r.json()["code"] == "DATABASE_UNAVAILABLE"


def test_gerador_antigo_oferece_os_formatos_antigos(emissor, dominio, flags):
    flags[governanca.FLAG_RELATORIO_VISUAL] = False
    r = _api(emissor, _banco()).get(f"/api/v1/precos/pesquisas/{P}/emissao", headers=_h(emissor))
    pares = {(o["tipo"], o["formato"]) for o in r.json()["opcoes"]}
    assert ("resumido", "pdf") in pares and ("cotacao", "pdf") not in pares


# ---------------------------------------------------------------------------
# Ciência
# ---------------------------------------------------------------------------
URL_CIENCIA = f"/api/v1/precos/pesquisas/{P}/ciencia"


def test_ciencia_registrada_com_o_ator_verificado(emissor, dominio):
    dominio["preparo"] = ciencia.Preparo(pesquisa_id=P, revisao="r1", assinatura=ASSINATURA,
                                         alertas=[_alerta()])
    r = _api(emissor, _banco()).post(URL_CIENCIA, headers=_h(emissor),
                                     json={"assinatura": ASSINATURA})
    assert r.status_code == 201, r.text
    assert dominio["ator"] == USUARIO_A


def test_ciencia_de_cesta_que_mudou_e_409_e_nao_grava(emissor, dominio):
    dominio["preparo"] = ciencia.Preparo(pesquisa_id=P, revisao="r2", assinatura="b" * 64,
                                         alertas=[_alerta()])
    r = _api(emissor, _banco()).post(URL_CIENCIA, headers=_h(emissor),
                                     json={"assinatura": ASSINATURA})
    assert r.status_code == 409 and r.json()["code"] == "CIENCIA_DESATUALIZADA"
    assert "ator" not in dominio


def test_colega_nao_registra_ciencia(emissor, dominio):
    r = _api(emissor, _banco(dono=OUTRO)).post(URL_CIENCIA, headers=_h(emissor),
                                               json={"assinatura": ASSINATURA})
    assert r.status_code == 403 and "ator" not in dominio


@pytest.mark.parametrize("assinatura", ["z" * 64, "A" * 64])
def test_assinatura_fora_do_formato(emissor, dominio, assinatura):
    r = _api(emissor, _banco()).post(URL_CIENCIA, headers=_h(emissor),
                                     json={"assinatura": assinatura})
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Pedido
# ---------------------------------------------------------------------------
URL_REL = f"/api/v1/precos/pesquisas/{P}/relatorios"


def _job(**extra):
    base = {"id": JOB, "tipo": "relatorio_precos", "recurso_id": P, "estado": "queued",
            "feitos": 0, "total": 1, "tentativas": 0, "erro_codigo": "",
            "parametros": {"tipo": "cotacao", "formato": "docx", "com_integral": False},
            "criado_em": "2026-10-22T18:00:00+00:00", "iniciado_em": None,
            "concluido_em": None, "resultado": {}}
    return {**base, **extra}


def test_pedido_cria_job_e_poe_na_fila_de_relatorio(emissor, dominio):
    banco, fila = _banco(), FilaFalsa()
    banco.responder("POST", "api_jobs", 201, [_job()])
    r = _api(emissor, banco, fila).post(URL_REL, headers=_h(emissor, **{"Idempotency-Key": "rel-00001"}),
                                        json={"tipo": "cotacao", "formato": "docx"})
    assert r.status_code == 202, r.text
    criado = [banco.corpo(c) for c in banco.chamadas if c.method == "POST"][0]
    assert criado["tipo"] == "relatorio_precos" and criado["auth_user_id"] == USUARIO_A
    assert criado["parametros"] == {"tipo": "cotacao", "formato": "docx", "com_integral": False}
    (aviso,) = fila.avisos
    assert aviso["tarefa"] == "relatorio" and aviso["job_id"] == JOB


def test_sem_ciencia_ligada_a_api_nao_emite(emissor, dominio, flags):
    flags[governanca.FLAG_CIENCIA_EMISSAO] = False
    banco = _banco()
    r = _api(emissor, banco).post(URL_REL, headers=_h(emissor, **{"Idempotency-Key": "rel-00002"}),
                                  json={"tipo": "cotacao", "formato": "docx"})
    assert r.status_code == 409 and r.json()["code"] == "EMISSION_UNAVAILABLE"
    assert not [c for c in banco.chamadas if c.method == "POST"]


def test_formato_do_outro_gerador_e_recusado(emissor, dominio):
    r = _api(emissor, _banco()).post(URL_REL, headers=_h(emissor, **{"Idempotency-Key": "rel-00003"}),
                                     json={"tipo": "resumido", "formato": "pdf"})
    assert r.status_code == 422


def test_mesma_chave_com_outro_pedido_e_409(emissor, dominio):
    banco = _banco()
    banco.responder("POST", "api_jobs", 409, {"code": "23505", "message": "duplicate"})
    banco.responder("GET", "api_jobs", 200, [_job()])
    r = _api(emissor, banco).post(URL_REL, headers=_h(emissor, **{"Idempotency-Key": "rel-00004"}),
                                  json={"tipo": "analitico", "formato": "xlsx"})
    assert r.status_code == 409 and r.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_mesma_chave_mesmo_pedido_devolve_o_job(emissor, dominio):
    banco, fila = _banco(), FilaFalsa()
    banco.responder("POST", "api_jobs", 409, {"code": "23505", "message": "duplicate"})
    banco.responder("GET", "api_jobs", 200, [_job()])
    r = _api(emissor, banco, fila).post(URL_REL, headers=_h(emissor, **{"Idempotency-Key": "rel-00005"}),
                                        json={"tipo": "cotacao", "formato": "docx"})
    assert r.status_code == 200 and r.headers["Idempotent-Replayed"] == "true"
    assert fila.avisos == []


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------
def _processar(banco, deposito=None, **job):
    banco.responder("GET", "api_jobs", 200, [_job(**job)])
    deposito = deposito or artefatos.DepositoMemoria()
    estado = relatorios.processar_relatorio(
        job_id=JOB, token="t.e.s", tenant_id=TENANT_A, auth_user_id=USUARIO_A,
        secretaria_id=None, usuario_id="", rest=banco.cliente(), deposito=deposito)
    patches = [banco.corpo(c) for c in banco.chamadas if c.method == "PATCH"]
    return estado, patches, deposito


def test_worker_gera_guarda_e_registra(dominio):
    estado, patches, deposito = _processar(PostgrestFalso())
    assert estado == "succeeded"
    final = patches[-1]
    assert final["estado"] == "succeeded" and final["resultado"]["nome"] == "rel-cotacao.docx"
    guardado = deposito.ler(JOB)
    assert guardado.conteudo == b"cotacao-docx"
    assert guardado.mimetype.endswith("wordprocessingml.document")
    (registro,) = dominio["registros"]
    assert registro["tipo"] == "completo" and registro["ator"] == USUARIO_A
    assert dominio["renderizados"][0][2] is not None, "a ciência vai para o documento"


def test_worker_sem_ciencia_nao_gera_nada(dominio):
    dominio["exigir"] = None
    estado, patches, deposito = _processar(PostgrestFalso())
    assert estado == "failed" and patches[-1]["erro_codigo"] == "CIENCIA_REQUIRED"
    assert dominio["renderizados"] == [] and deposito.ler(JOB) is None
    assert dominio["registros"] == []


def test_worker_com_ciencia_desligada_no_meio_do_caminho(dominio, flags):
    flags[governanca.FLAG_CIENCIA_EMISSAO] = False
    estado, patches, _ = _processar(PostgrestFalso())
    assert patches[-1]["erro_codigo"] == "EMISSION_UNAVAILABLE"
    assert dominio["renderizados"] == []


def test_cesta_acima_do_teto_falha_com_a_mensagem_do_dominio(dominio):
    dominio["bloqueio"] = "O relatório não pode ser gerado: item 3: 20 preços na cesta"
    estado, patches, _ = _processar(PostgrestFalso())
    assert patches[-1]["erro_codigo"] == "RENDER_REFUSED"
    assert "item 3" in patches[-1]["resultado"]["mensagem"]


def test_pacote_zipa_as_partes_do_gerador_ativo(dominio):
    estado, _, deposito = _processar(
        PostgrestFalso(), parametros={"tipo": "pacote", "formato": "zip", "com_integral": False})
    assert estado == "succeeded"
    with zipfile.ZipFile(io.BytesIO(deposito.ler(JOB).conteudo)) as zf:
        assert sorted(zf.namelist()) == ["rel-analitico.xlsx", "rel-cotacao.pdf"]


def test_banco_fora_e_transitorio(dominio, monkeypatch):
    def quebra(*a):
        raise db.ErroBanco("conexão")

    monkeypatch.setattr(relatorios, "_carregar", quebra)
    with pytest.raises(coleta.ErroTransitorio):
        _processar(PostgrestFalso())


def test_aviso_repetido_de_job_pronto_nao_gera_de_novo(dominio):
    estado, patches, _ = _processar(PostgrestFalso(), estado="succeeded")
    assert estado == "succeeded" and patches == [] and dominio["renderizados"] == []


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------
def _url_artefato():
    return f"/api/v1/jobs/{JOB}/artefato"


def test_download_do_dono_com_o_tipo_que_o_worker_deu(emissor, dominio):
    deposito = artefatos.DepositoMemoria()
    deposito.guardar(JOB, artefatos.montar("relatório-cotação.docx", b"PK conteudo"))
    banco = PostgrestFalso()
    # `resultado` adulterado pelo dono: o download não o lê.
    banco.responder("GET", "api_jobs", 200, [_job(estado="succeeded",
                                                  resultado={"mimetype": "text/html"})])
    r = _api(emissor, banco, deposito=deposito).get(_url_artefato(), headers=_h(emissor))
    assert r.status_code == 200 and r.content == b"PK conteudo"
    assert r.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "attachment" in r.headers["content-disposition"]
    assert "relat%C3%B3rio-cota%C3%A7%C3%A3o.docx" in r.headers["content-disposition"]
    assert "no-store" in r.headers["cache-control"]


def test_download_de_job_alheio_e_404(emissor, dominio):
    deposito = artefatos.DepositoMemoria()
    deposito.guardar(JOB, artefatos.montar("r.docx", b"x"))
    banco = PostgrestFalso()
    banco.responder("GET", "api_jobs", 200, [])       # o RLS não devolveu
    r = _api(emissor, banco, deposito=deposito).get(_url_artefato(), headers=_h(emissor))
    assert r.status_code == 404


def test_download_expirado_e_410(emissor, dominio):
    banco = PostgrestFalso()
    banco.responder("GET", "api_jobs", 200, [_job(estado="succeeded")])
    r = _api(emissor, banco).get(_url_artefato(), headers=_h(emissor))
    assert r.status_code == 410 and r.json()["code"] == "ARTIFACT_EXPIRED"


def test_download_de_job_em_andamento_e_404(emissor, dominio):
    banco = PostgrestFalso()
    banco.responder("GET", "api_jobs", 200, [_job(estado="running")])
    r = _api(emissor, banco).get(_url_artefato(), headers=_h(emissor))
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Artefato e resultado
# ---------------------------------------------------------------------------
def test_extensao_fora_da_lista_nao_vira_artefato():
    with pytest.raises(ValueError):
        artefatos.montar("pagina.html", b"<script>")


def test_artefato_acima_do_limite(monkeypatch):
    monkeypatch.setattr(artefatos, "LIMITE_BYTES", 10)
    with pytest.raises(artefatos.ArtefatoGrandeDemais):
        artefatos.montar("r.pdf", b"x" * 11)


def test_deposito_expira():
    agora = [1000.0]
    deposito = artefatos.DepositoMemoria(validade_s=60, agora=lambda: agora[0])
    deposito.guardar(JOB, artefatos.montar("r.pdf", b"%PDF"))
    agora[0] += 61
    assert deposito.ler(JOB) is None


def test_resultado_do_job_so_com_campos_conhecidos():
    job = coleta.job_do_banco(_job(resultado={"nome": "r.pdf", "tamanho": 10, "html": "<b>",
                                              "registrado": "sim", "tamanho_falso": True}))
    assert job.resultado == {"nome": "r.pdf", "tamanho": 10}
