"""
Índice do PNCP (0042) pelo caminho do WORKER, contra a pilha real.

O worker não tem credencial de servidor: lê o índice com o JWT do usuário,
pela RPC `precos_pncp_buscar` (security invoker), sob o RLS de verdade. O
lote automático grava a referência homologada com a origem da compra
(publicador e link do PNCP) e a RPC não devolve a linha invalidada na
revisita.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, timedelta

import pytest

CONTROLE = "04873600000115-1-000173/2026"


def _bruto(numero: int, valor: float, quantidade: float, data: str) -> dict:
    return {
        "contratacao": {
            "numeroControlePNCP": CONTROLE,
            "linkSistemaOrigem": "https://licitanet.com.br/sessao/201882",
            "usuarioNome": "Licitanet Licitações Eletrônicas LTDA",
            "modalidadeNome": "Pregão - Eletrônico",
            "orgaoEntidade": {"cnpj": "04873600000115",
                              "razaoSocial": "MUNICIPIO DE AUGUSTO CORREA"},
            "unidadeOrgao": {"ufSigla": "PA", "municipioNome": "Augusto Corrêa"}},
        "item": {"numeroItem": numero, "descricao": "Gasolina Comum",
                 "unidadeMedida": "Litros", "quantidade": quantidade,
                 "materialOuServico": "M", "criterioJulgamentoNome": "Menor preço",
                 "situacaoCompraItem": 2, "situacaoCompraItemNome": "Homologado"},
        "resultado": {"sequencialResultado": 1, "niFornecedor": "48619057000108",
                      "tipoPessoa": "PJ", "nomeRazaoSocialFornecedor": "AUTO POSTO",
                      "valorUnitarioHomologado": valor,
                      "quantidadeHomologada": quantidade,
                      "valorTotalHomologado": valor * quantidade,
                      "dataResultado": data}}


@pytest.fixture
def indice_semeado(pilha):
    import psycopg

    data = (date.today() - timedelta(days=10)).isoformat()
    with psycopg.connect(pilha.dsn, autocommit=True) as c:
        c.execute("insert into public.precos_pncp_contratacoes (numero_controle, uf, estado) "
                  "values (%s, 'PA', 'coletada') on conflict do nothing", (CONTROLE,))
        for numero, valor, vigente in ((1, 7.6, True), (2, 9.9, False)):
            c.execute(
                "insert into public.precos_pncp_resultados (id_externo, numero_controle, "
                "numero_item, descricao, descricao_busca, unidade, quantidade, valor_unitario, "
                "valor_total, data_resultado, uf, plataforma, bruto, hash_linha, versao_coletor, "
                "vigente) values (%s,%s,%s,'Gasolina Comum','gasolina comum','Litros',1000,%s,"
                "%s,%s,'PA','Licitanet',%s::jsonb,'h','v',%s) on conflict (id_externo) do nothing",
                (f"{CONTROLE}#{numero}#1", CONTROLE, numero, valor, valor * 1000, data,
                 json.dumps(_bruto(numero, valor, 1000.0, data)), vigente))
        a1 = pilha.contas["a1"]
        pid = str(c.execute(
            "insert into public.pesquisas_preco (tenant_id, secretaria_id, auth_user_id, nome, "
            "estado, idempotency_key) values (%s,%s,%s,'Lote PNCP','draft',%s) returning id",
            (a1.tenant_id, a1.secretaria_id, a1.auth_user_id, uuid.uuid4().hex)).fetchone()[0])
        c.execute("insert into public.pesquisa_preco_itens (pesquisa_id, tenant_id, numero, "
                  "descricao, unidade, quantidade) values (%s,%s,1,'GASOLINA COMUM','LITRO',100)",
                  (pid, a1.tenant_id))
    return pid


def test_lote_automatico_le_o_indice_com_o_jwt_do_usuario(pilha, indice_semeado):
    import psycopg

    from govconect_api.coleta import processar_job
    from govconect_api.supabase_rest import ClienteRest
    from src.precos import portais, repositorio
    from src.precos.pncp_indice import PNCPIndice

    from test_rls_coleta import _api, _h

    api = _api(pilha)
    a1 = pilha.contas["a1"]
    r = api.post(f"/api/v1/precos/pesquisas/{indice_semeado}/coleta", headers=_h(a1),
                 json={"modo": "automatico"})
    assert r.status_code == 202, r.text
    (aviso,) = api.app.state.fila.avisos
    final = processar_job(rest=ClienteRest(pilha.url, pilha.anon),
                          fontes=[PNCPIndice(repositorio.buscar_indice_pncp)], **aviso)
    assert final == "succeeded"
    with psycopg.connect(pilha.dsn) as c:
        linhas = c.execute(
            "select r.id_externo, r.valor_unitario_original, r.natureza_valor, r.bruto "
            "from public.pesquisa_preco_referencias r join public.pesquisa_preco_itens i "
            "on i.id = r.item_id where i.pesquisa_id = %s", (indice_semeado,)).fetchall()
    # a vigente entrou; a invalidada na revisita, não
    assert [l[0] for l in linhas] == [f"{CONTROLE}#1#1"]
    assert float(linhas[0][1]) == 7.6 and linhas[0][2] == "homologado"
    assert portais.atribuir("pncp", linhas[0][3]).rotulo == "Origem Licitanet · Coleta via PNCP"
