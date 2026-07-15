"""
Testes do orquestrador do ciclo (Etapa 5 da correção automática):
aprovação, reauditoria obrigatória, limite de ciclos, dado ausente,
falhas explícitas, flag OFF preservando o legado, auditoria semântica
e persistência retomável com isolamento por tenant.
"""

import json

from src import ciclo, db, patches

DOC_COM_PLACEHOLDER = """## 1. OBJETO

Aquisição de material escolar.

## 2. VIGÊNCIA

Contrato válido por placeholder meses.

## 3. VALOR

R$ 100,00 conforme planilha.
"""

DADOS = {"prazo": "12 meses"}


def _chamar_corretor_ok(docs_ref):
    """Fake de IA: devolve um plano válido que corrige o placeholder."""

    def chamar(system, user, finalidade):
        assert finalidade == "corretor"
        payload = json.loads(user[user.find("{"):user.rfind("}") + 1])
        finding = payload["findings"][0]
        bloco = payload["blocosAtuais"][0]
        return json.dumps({"operations": [{
            "findingId": finding["findingId"],
            "documentId": finding["documentId"],
            "op": "replace", "path": bloco["path"],
            "expectedOldHash": bloco["hash"],
            "newValue": "Contrato válido por 12 (doze) meses.",
            "sourceIds": finding["sourceIds"] or [],
            "reason": "corrige texto provisório",
            "expectedImpact": "vigência definitiva",
        }], "unresolvedFindings": []})

    return chamar


# ---------------------------------------------------------------------------
# caminho feliz (T01/T08) e reauditoria obrigatória
# ---------------------------------------------------------------------------
def test_ciclo_corrige_reaudita_e_aprova():
    docs = {"memo": DOC_COM_PLACEHOLDER}
    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=_chamar_corretor_ok(docs),
        aplicar_patches=True, reauditoria_semantica=False)

    assert resultado["status"] == "APPROVED"
    assert resultado["ciclos"] == 1 and resultado["versao"] == 2
    assert "12 (doze) meses" in resultado["documentos"]["memo"]
    assert docs["memo"] == DOC_COM_PLACEHOLDER  # original intocado
    assert len(resultado["relatorios"]) == 2  # inicial + reauditoria
    assert resultado["relatorios"][-1]["status"] == "APPROVED"
    estados = [e["para"] for e in resultado["eventos"]]
    assert estados == [
        "REVIEWING", "REVIEW_COMPLETED", "CORRECTION_PLANNING",
        "CORRECTING", "CORRECTION_APPLIED", "REVALIDATING", "APPROVED",
    ]


def test_documento_ja_limpo_aprova_sem_ciclos():
    resultado = ciclo.executar_ciclo(
        {"memo": "## 1. OBJETO\n\nAquisição de canetas.\n"}, DADOS,
        chamar=None, aplicar_patches=True, reauditoria_semantica=False)
    assert resultado["status"] == "APPROVED"
    assert resultado["ciclos"] == 0 and resultado["planos"] == []


# ---------------------------------------------------------------------------
# flag OFF preserva o legado (T20)
# ---------------------------------------------------------------------------
def test_flag_de_aplicacao_desligada_nao_toca_nos_documentos():
    docs = {"memo": DOC_COM_PLACEHOLDER}

    def explode(*_a, **_k):
        raise AssertionError("flag OFF não pode chamar IA")

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=explode,
        aplicar_patches=False, reauditoria_semantica=False)
    assert resultado["status"] == "REVIEW_COMPLETED"
    assert resultado["documentos"] == docs
    assert resultado["planos"] == [] and resultado["ciclos"] == 0


# ---------------------------------------------------------------------------
# dado ausente (T03) e regressão introduzida pelo corretor (T09)
# ---------------------------------------------------------------------------
def test_dado_ausente_para_em_waiting_com_campos_pontuais():
    docs = {"memo": DOC_COM_PLACEHOLDER.replace(
        "placeholder meses", "[PREENCHER: prazo de vigência] ")}
    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=None,
        aplicar_patches=True, reauditoria_semantica=False)
    assert resultado["status"] == "WAITING_REQUIRED_DATA"
    assert resultado["campos_requeridos"] == [{
        "documento": "memo", "campo": "prazo de vigência",
        "findingId": resultado["relatorios"][-1]["findings"][0]["findingId"],
    }]
    assert resultado["documentos"] == docs  # nada aplicado


def test_regressao_do_corretor_e_detectada_na_reauditoria():
    """O 'corretor' resolve o placeholder mas introduz [PREENCHER]."""
    docs = {"memo": DOC_COM_PLACEHOLDER}

    def chamar(system, user, finalidade):
        payload = json.loads(user[user.find("{"):user.rfind("}") + 1])
        finding = payload["findings"][0]
        bloco = payload["blocosAtuais"][0]
        return json.dumps({"operations": [{
            "findingId": finding["findingId"],
            "documentId": finding["documentId"],
            "op": "replace", "path": bloco["path"],
            "expectedOldHash": bloco["hash"],
            "newValue": "Contrato válido por [PREENCHER: prazo] meses.",
            "sourceIds": [], "reason": "r", "expectedImpact": "i",
        }], "unresolvedFindings": []})

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=False)
    # a reauditoria obrigatória pega a regressão e pede o dado ao humano
    assert resultado["status"] == "WAITING_REQUIRED_DATA"
    assert resultado["ciclos"] == 1
    assert len(resultado["relatorios"]) == 2


# ---------------------------------------------------------------------------
# limite de ciclos (T10) e falhas explícitas (T11)
# ---------------------------------------------------------------------------
def test_limite_de_tres_ciclos_bloqueia():
    """Corretor que 'corrige' devolvendo outro placeholder para sempre."""
    docs = {"memo": DOC_COM_PLACEHOLDER}
    chamadas = []

    def chamar(system, user, finalidade):
        chamadas.append(1)
        payload = json.loads(user[user.find("{"):user.rfind("}") + 1])
        finding = payload["findings"][0]
        bloco = payload["blocosAtuais"][0]
        return json.dumps({"operations": [{
            "findingId": finding["findingId"],
            "documentId": finding["documentId"],
            "op": "replace", "path": bloco["path"],
            "expectedOldHash": bloco["hash"],
            "newValue": f"Contrato placeholder v{len(chamadas)}.",
            "sourceIds": [], "reason": "r", "expectedImpact": "i",
        }], "unresolvedFindings": []})

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=False)
    assert resultado["status"] == "BLOCKED_MAX_CYCLES"
    assert resultado["ciclos"] == 3
    assert len(resultado["relatorios"]) == 4  # inicial + 3 reauditorias


def test_falha_do_corretor_vira_estado_explicito():
    docs = {"memo": DOC_COM_PLACEHOLDER}

    def chamar(*_a, **_k):
        return "resposta sem JSON nenhum"

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=False)
    assert resultado["status"] == "CORRECTION_FAILED"
    assert resultado["documentos"] == docs  # sem fallback silencioso


# ---------------------------------------------------------------------------
# auditoria semântica (flag_reauditoria)
# ---------------------------------------------------------------------------
def test_auditoria_semantica_critica_bloqueia_para_humano():
    docs = {"memo": "## 1. OBJETO\n\nAquisição de canetas.\n"}

    def chamar(system, user, finalidade):
        assert finalidade == "auditor"
        return json.dumps({"findings": [{
            "documentId": "memo", "severity": "CRITICAL",
            "descricao": "valor global diverge entre DFD e TR",
            "evidencia": ["R$ 100 vs R$ 900"],
            "regraViolada": "coerência entre documentos",
        }]})

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=True)
    assert resultado["status"] == "BLOCKED_BY_CONFLICT"
    f = resultado["relatorios"][0]["findings"][-1]
    assert f["categoria"] == "semantica" and not f["autoCorrectable"]


def test_falha_da_auditoria_semantica_nao_derruba_a_revisao():
    """
    A auditoria semântica é OPCIONAL: se a IA falhar/demorar, o ciclo
    segue com a auditoria determinística — nunca vira REVIEW_FAILED
    (regressão do falso "auditoria indisponível").
    """
    docs = {"memo": "## 1. OBJETO\n\nAquisição de canetas.\n"}  # limpo

    def chamar(*_a, **_k):
        return "quebrou"  # resposta inválida = ErroCorrecao no auditor

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=True)
    # documento limpo + semântica indisponível → aprovado assim mesmo
    assert resultado["status"] == "APPROVED"
    assert resultado["relatorios"][0].get("semantica_indisponivel") is True


def test_timeout_da_semantica_com_findings_deterministicos_prossegue():
    """IA fora do ar não impede a correção dos findings determinísticos."""
    docs = {"memo": DOC_COM_PLACEHOLDER}
    chamadas = {"n": 0}

    def chamar(system, user, finalidade):
        if finalidade == "auditor":
            raise ciclo.llm.ErroGeracaoIA("timeout: demorou demais")
        chamadas["n"] += 1
        return _chamar_corretor_ok(docs)(system, user, finalidade)

    resultado = ciclo.executar_ciclo(
        docs, DADOS, chamar=chamar,
        aplicar_patches=True, reauditoria_semantica=True)
    # o placeholder determinístico foi corrigido apesar da IA de auditoria
    assert resultado["status"] == "APPROVED"
    assert "12 (doze) meses" in resultado["documentos"]["memo"]
    assert all(r.get("semantica_indisponivel") for r in resultado["relatorios"])


# ---------------------------------------------------------------------------
# persistência retomável (T19) e isolamento por tenant (T13)
# ---------------------------------------------------------------------------
def _banco_fake(monkeypatch):
    jobs: dict[str, dict] = {}

    def criar(processo_id, snapshot, relatorio, idempotency_key=""):
        job = {
            "id": f"rev-{len(jobs) + 1}", "processo_id": processo_id,
            "tenant_id": db.tenant_atual(), "status": "REVIEW_QUEUED",
            "ciclo": 0, "versao_atual": 1, "snapshots": [snapshot],
            "relatorios": [relatorio] if relatorio else [],
            "planos": [], "diffs": [], "eventos": [],
            "idempotency_key": idempotency_key,
        }
        jobs[job["id"]] = job
        return dict(job)

    def por_chave(chave):
        return next((dict(j) for j in jobs.values()
                     if j["idempotency_key"] == chave), None)

    def atualizar(revisao_id, **campos):
        jobs[revisao_id].update(campos)
        return dict(jobs[revisao_id])

    monkeypatch.setattr(db, "disponivel", lambda: True)
    monkeypatch.setattr(db, "criar_revisao", criar)
    monkeypatch.setattr(db, "obter_revisao_por_chave", por_chave)
    monkeypatch.setattr(db, "atualizar_revisao", atualizar)
    return jobs


def test_persistencia_grava_e_retoma_sem_repetir_ia(monkeypatch):
    jobs = _banco_fake(monkeypatch)
    monkeypatch.setattr(db, "flag_ativa",
                        lambda n: n == patches.FLAG_APLICACAO)
    docs = {"memo": DOC_COM_PLACEHOLDER}
    etapas = []

    r1 = ciclo.executar_com_persistencia(
        docs, DADOS, "proc-1", chamar=_chamar_corretor_ok(docs),
        ao_progresso=etapas.append)
    assert r1["status"] == "APPROVED"
    assert "12 (doze) meses" in r1["documentos"]["memo"]
    assert etapas[0] == "analisando" and "corrigindo" in etapas
    job = list(jobs.values())[0]
    assert job["status"] == "APPROVED"
    assert job["eventos"]

    def explode(*_a, **_k):
        raise AssertionError("retomada não pode repetir IA")

    r2 = ciclo.executar_com_persistencia(
        docs, DADOS, "proc-1", chamar=explode)
    assert r2["status"] == r1["status"]
    assert r2["documentos"] == r1["documentos"]
    assert len(jobs) == 1  # mesmo job (idempotência por processo+conteúdo)


def test_job_de_outro_tenant_nao_e_retomado(monkeypatch):
    revisao = {"id": "rev-x", "tenant_id": "outro-tenant",
               "status": "APPROVED"}
    assert ciclo.revisao_do_tenant(revisao) is None
    revisao["tenant_id"] = db.tenant_atual()
    assert ciclo.revisao_do_tenant(revisao) == revisao
