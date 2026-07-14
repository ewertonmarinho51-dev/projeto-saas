"""
Testes dos fatos canônicos (Fase 2 do pacote V5): extração
determinística do formulário, versionamento com substituição
(KQ-005), divergências documentais (KQ-004), shadow mode sem
persistência e sincronização com o banco.
"""

import streamlit as st

from src import db, fatos, governanca

DADOS = {
    "orgao": "Secretaria Municipal de Educação",
    "responsavel": "Maria Souza, Diretora",
    "objeto": "Aquisição de material escolar",
    "modelo_execucao": "Sistema de Registro de Preços (SRP)",
    "prazo": "Contratação necessária até março/2027",
    "valor_estimado": 45000.0,
    "itens": [
        {"descricao": "Caneta azul", "quantidade": 100, "unidade": "un",
         "valor_unitario": 2.5},
    ],
    "justificativa": "Prosa longa que NÃO deve virar fato.",
    "riscos": "Risco de atraso.",
}


def _por_path(lista):
    return {f["path"]: f for f in lista}


# ---------------------------------------------------------------------------
# extração determinística
# ---------------------------------------------------------------------------
def test_extracao_mapeia_fatos_materiais_com_fonte():
    mapa = _por_path(fatos.extrair_do_formulario(DADOS, "p1"))
    assert mapa["procedimento.srp"]["valor"] is True
    assert mapa["objeto.natureza"]["valor"] == "BENS"
    assert mapa["valor.total"]["valor"] == 45000.0
    assert mapa["itens[0].quantidade"]["valor"] == 100.0
    assert mapa["prazo.descricao"]["fonte"] == "formulario:prazo"
    assert all(f["fonte"] for f in mapa.values())


def test_natureza_derivada_da_execucao():
    obra = dict(DADOS, modelo_execucao="Obra / serviço de engenharia")
    servico = dict(DADOS, modelo_execucao="Serviço de execução continuada")
    assert _por_path(fatos.extrair_do_formulario(obra))[
        "objeto.natureza"]["valor"] == "OBRAS_ENGENHARIA"
    mapa = _por_path(fatos.extrair_do_formulario(servico))
    assert mapa["objeto.natureza"]["valor"] == "SERVICOS"
    assert mapa["procedimento.execucao_continuada"]["valor"] is True
    assert mapa["procedimento.srp"]["valor"] is False


def test_prosa_nao_vira_fato():
    paths = set(_por_path(fatos.extrair_do_formulario(DADOS)))
    assert not any("justificativa" in p or "riscos" in p for p in paths)


def test_extracao_e_deterministica():
    a = fatos.extrair_do_formulario(DADOS, "p1")
    b = fatos.extrair_do_formulario(DADOS, "p1")
    assert [f["hash"] for f in a] == [f["hash"] for f in b]


# ---------------------------------------------------------------------------
# versionamento (KQ-005: mudança invalida somente o fato afetado)
# ---------------------------------------------------------------------------
def test_versionamento_insere_substitui_e_preserva():
    existentes = [
        {"id": "f-valor", "path": "valor.total", "valor": 45000.0,
         "versao": 1, "status": "confirmado"},
        {"id": "f-srp", "path": "procedimento.srp", "valor": True,
         "versao": 1, "status": "confirmado"},
    ]
    novos = fatos.extrair_do_formulario(
        dict(DADOS, valor_estimado=50000.0), "p1")
    inserir, substituir = fatos.planejar_versionamento(novos, existentes)

    mapa = _por_path(inserir)
    # valor mudou: v2 aponta a anterior e ela será substituída
    assert mapa["valor.total"]["versao"] == 2
    assert mapa["valor.total"]["substitui"] == "f-valor"
    assert mapa["valor.total"]["status"] == "extraido"  # reconfirmação
    assert substituir == ["f-valor"]
    # srp não mudou: preserva a versão confirmada
    assert "procedimento.srp" not in mapa
    # paths inéditos entram como versão 1
    assert mapa["objeto.descricao"]["versao"] == 1


# ---------------------------------------------------------------------------
# divergências documentais (KQ-004 semente)
# ---------------------------------------------------------------------------
def test_valor_ausente_em_todos_os_documentos_gera_divergencia():
    lista = fatos.extrair_do_formulario(DADOS, "p1")
    docs = {"dfd": "## 1. OBJETO\n\nSem valores aqui.\n"}
    divergencias = fatos.divergencias_documentais(lista, docs)
    assert any(d["path"] == "valor.total" for d in divergencias)

    docs_ok = {"dfd": "## 7. VALOR\n\nEstimado em R$ 45.000,00.\n"}
    assert not [d for d in fatos.divergencias_documentais(lista, docs_ok)
                if d["path"] == "valor.total"]


def test_prazo_localizado_por_bloco_nao_diverge():
    lista = fatos.extrair_do_formulario(DADOS, "p1")
    docs = {"dfd": "## 8. PERÍODO\n\nContratação necessária até "
                   "março/2027, prioridade alta. Estimado em R$ 45.000,00.\n"}
    assert fatos.divergencias_documentais(lista, docs) == []


# ---------------------------------------------------------------------------
# shadow (flag OFF) e sincronização (flag ON)
# ---------------------------------------------------------------------------
def test_flag_desligada_roda_em_shadow_sem_persistir(monkeypatch, caplog):
    monkeypatch.setattr(fatos.db, "flag_ativa", lambda n: False)

    def explode(*_a, **_k):
        raise AssertionError("shadow não pode persistir")

    monkeypatch.setattr(fatos.db, "salvar_fatos", explode)
    st.session_state.pop("_fatos_cache", None)
    with caplog.at_level("INFO", logger="govdocs.fatos"):
        resultado = fatos.processar_na_tela(DADOS, {"dfd": "texto"}, "p1")
    assert resultado is None
    assert any("shadow" in r.message for r in caplog.records)


def test_flag_ligada_sincroniza_e_substitui(monkeypatch):
    banco: dict[str, dict] = {}

    def salvar(lista):
        for i, fato in enumerate(lista):
            registro = {**fato, "id": f"f{len(banco) + i}"}
            banco[registro["id"]] = registro
        return list(banco.values())

    def listar(processo_id, apenas_vigentes=True):
        vistos = list(banco.values())
        if apenas_vigentes:
            vistos = [f for f in vistos if f["status"] != "substituido"]
        return vistos

    def atualizar(fato_id, **campos):
        banco[fato_id].update(campos)

    monkeypatch.setattr(fatos.db, "flag_ativa",
                        lambda n: n == governanca.FLAG_FATOS)
    monkeypatch.setattr(fatos.db, "disponivel", lambda: True)
    monkeypatch.setattr(fatos.db, "salvar_fatos", salvar)
    monkeypatch.setattr(fatos.db, "listar_fatos", listar)
    monkeypatch.setattr(fatos.db, "atualizar_fato", atualizar)

    st.session_state.pop("_fatos_cache", None)
    r1 = fatos.processar_na_tela(DADOS, {}, "p1")
    assert r1 is not None
    assert _por_path(r1["fatos"])["valor.total"]["valor"] == 45000.0

    # valor muda no formulário → nova versão + anterior substituída
    st.session_state.pop("_fatos_cache", None)
    r2 = fatos.processar_na_tela(
        dict(DADOS, valor_estimado=60000.0), {}, "p1")
    vigente = _por_path(r2["fatos"])["valor.total"]
    assert vigente["valor"] == 60000.0 and vigente["versao"] == 2
    substituidos = [f for f in banco.values()
                    if f["status"] == "substituido"]
    assert len(substituidos) == 1


def test_confirmar_todos_so_altera_extraidos(monkeypatch):
    registros = [
        {"id": "a", "status": "extraido"},
        {"id": "b", "status": "confirmado"},
    ]
    alterados = []
    monkeypatch.setattr(fatos.db, "listar_fatos",
                        lambda p, apenas_vigentes=True: registros)
    monkeypatch.setattr(
        fatos.db, "atualizar_fato",
        lambda fato_id, **c: alterados.append((fato_id, c)))
    assert fatos.confirmar_todos("p1", "u1") == 1
    assert alterados == [("a", {"status": "confirmado",
                                "confirmado_por": "u1"})]
