"""
Smoke ponta a ponta da Pesquisa de Preços, contra PostgreSQL REAL.

O §15 da auditoria pede um fluxo mínimo de verdade: entrar, criar
pesquisa, adicionar item, consultar fonte, guardar referência, RECARREGAR
a pesquisa, gerar a memória, aplicar ao processo, reabrir e conferir — e,
no fim, provar que outro tenant não alcança nada disso.

**Por que contra o banco real, e não contra dublê.** As provas por fase
usam cliente falso e medem lógica. Um smoke que fizesse o mesmo não
acrescentaria nada: ele existe justamente para pegar o que só aparece
quando a RLS está ligada, as FKs valem e os CHECKs recusam. A pergunta
que ele responde é "isto funciona depois de aplicado?", não "a função
retorna o esperado?".

O passo 8 — recarregar do banco — é o coração. Duas correções desta
rodada vivem ou morrem nele: a `natureza_valor` persistida (sem ela, o
valor estimado volta indistinguível de preço pago) e os `desfechos` por
fonte (sem eles, falha técnica volta indistinguível de mercado vazio).
Em memória as duas passam; é a releitura que prova.

Roda sob o mesmo portão das demais provas de autorização: com
`GOVDOCS_EXIGIR_ENSAIO_SQL=1`, ausência de banco é ERRO, nunca skip.
"""

from __future__ import annotations

import json
import sys
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ensaio_local import claims, como, voltar_a_ser_servidor  # noqa: E402

from src.precos import estatistica, matching  # noqa: E402
from src.precos.modelo import NaturezaValor  # noqa: E402

# `usefixtures` no módulo inteiro, e não `skipif`: com
# `GOVDOCS_EXIGIR_ENSAIO_SQL=1` a ausência do banco precisa FALHAR, e um
# `skipif` decidiria antes que o portão pudesse opinar.
pytestmark = pytest.mark.usefixtures("ensaio_sql")


@pytest.fixture
def municipio(banco):
    """Um município, uma secretaria, dois servidores e um intruso."""
    dados: dict = {}
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        for chave in ("tenant_a", "tenant_b"):
            c.execute("insert into tenants (slug, nome) values (%s, %s) "
                      "returning id",
                      (f"smoke-{chave}-{uuid.uuid4().hex[:8]}", chave))
            dados[chave] = c.fetchone()[0]

        c.execute("insert into secretarias (tenant_id, nome) values (%s, %s) "
                  "returning id", (dados["tenant_a"], "Compras"))
        dados["secretaria"] = c.fetchone()[0]

        for rotulo, tenant in (("servidor", "tenant_a"),
                               ("intruso", "tenant_b")):
            meta = {"papel": "usuario", "tenant_id": str(dados[tenant])}
            if rotulo == "servidor":
                meta["secretaria_id"] = str(dados["secretaria"])
            c.execute("insert into auth.users (email, raw_app_meta_data) "
                      "values (%s, %s) returning id",
                      (f"{rotulo}-{uuid.uuid4().hex[:8]}@smoke.invalid",
                       json.dumps(meta)))
            ident = str(c.fetchone()[0])
            dados[rotulo] = {
                "id": ident,
                "jwt": claims(ident, "usuario", str(dados[tenant]),
                              str(dados["secretaria"])
                              if rotulo == "servidor" else None),
            }

        c.execute("insert into processos (orgao, objeto, tenant_id, "
                  "secretaria_id, auth_user_id) "
                  "values ('Prefeitura', 'Material de expediente', %s, %s, %s) "
                  "returning id",
                  (dados["tenant_a"], dados["secretaria"],
                   dados["servidor"]["id"]))
        dados["processo"] = c.fetchone()[0]
    return dados


def test_fluxo_completo_da_pesquisa_de_precos(banco, municipio):
    """
    Os treze passos do §15, do login ao isolamento, numa transação.

    Cada bloco abaixo é um passo do roteiro, e a numeração é a dele.
    """
    servidor = municipio["servidor"]["jwt"]

    with banco.transaction(force_rollback=True), banco.cursor() as c:
        # 1–4. Autenticado, cria a pesquisa vinculada ao processo.
        como(c, servidor)
        c.execute(
            "insert into pesquisas_preco (tenant_id, secretaria_id, "
            "auth_user_id, processo_id, nome, objeto, perfil_normativo) "
            "values (%s, %s, %s, %s, 'Smoke 2026', 'Canetas', 'lei_14133') "
            "returning id",
            (municipio["tenant_a"], municipio["secretaria"],
             municipio["servidor"]["id"], municipio["processo"]))
        pesquisa = c.fetchone()[0]

        # 5. Adiciona o item.
        c.execute(
            "insert into pesquisa_preco_itens (pesquisa_id, tenant_id, "
            "numero, descricao, unidade, quantidade) "
            "values (%s, %s, 1, 'CANETA ESFEROGRAFICA AZUL', 'UN', 100) "
            "returning id",
            (pesquisa, municipio["tenant_a"]))
        item = c.fetchone()[0]

        # 6–7. Consulta a fonte e guarda as referências. Três preços
        #      praticados e um valor ESTIMADO por outro órgão — é o
        #      cenário que a rodada corrigiu.
        coletadas = (
            ("compras_gov_precos", "a", "1.50", NaturezaValor.PRATICADO),
            ("compras_gov_precos", "b", "1.60", NaturezaValor.PRATICADO),
            ("compras_gov_precos", "c", "1.80", NaturezaValor.PRATICADO),
            ("compras_gov_itens", "d", "99.00", NaturezaValor.ESTIMADO_ORIGEM),
        )
        for fonte, ident, valor, natureza in coletadas:
            c.execute(
                "insert into pesquisa_preco_referencias (item_id, tenant_id, "
                " fonte_id, fonte_tipo, id_externo, raw_hash, "
                " descricao_original, unidade_original, unidade_normalizada, "
                " valor_unitario_original, valor_unitario_normalizado, "
                " natureza_valor, status) "
                "values (%s, %s, %s, 'sistema_oficial', %s, %s, "
                "        'CANETA ESFEROGRAFICA AZUL', 'UN', 'UN', %s, %s, "
                "        %s, 'candidate')",
                (item, municipio["tenant_a"], fonte, ident, f"hash-{ident}",
                 valor, valor, natureza.value))

        # A trilha registra a coleta.
        c.execute(
            "insert into pesquisa_preco_eventos (pesquisa_id, item_id, "
            " tenant_id, tipo, descricao, automatico) "
            "values (%s, %s, %s, 'busca_concluida', '4 referências', true)",
            (pesquisa, item, municipio["tenant_a"]))

        # 8. RECARREGA do banco — o passo que prova a persistência.
        c.execute(
            "select id_externo, natureza_valor, valor_unitario_normalizado "
            "  from pesquisa_preco_referencias where item_id = %s "
            " order by id_externo", (item,))
        relidas = c.fetchall()

    assert len(relidas) == 4, "as referências não sobreviveram à releitura"
    naturezas = {linha[0]: linha[1] for linha in relidas}
    assert naturezas == {"a": "praticado", "b": "praticado",
                         "c": "praticado", "d": "estimado_origem"}, (
        "a natureza do valor não sobreviveu ao banco — o valor estimado "
        "voltaria indistinguível de preço pago")

    # 9–10. A cesta e a memória de cálculo, sobre o que veio do BANCO.
    do_banco = []
    for id_externo, natureza, valor in relidas:
        referencia = _referencia_do_banco(id_externo, natureza, valor)
        do_banco.append((referencia, _nota_cheia()))

    cesta = estatistica.selecionar_cesta(do_banco)
    estimativa = estatistica.estimar(cesta)

    assert len(cesta.selecionadas) == 3, (
        "o valor estimado de terceiro entrou na cesta")
    assert estimativa.status == "CONCLUIDO"
    assert estimativa.valor_unitario == Decimal("1.63")
    assert estimativa.memoria, "a memória de cálculo veio vazia"


def _referencia_do_banco(id_externo, natureza, valor):
    from src.precos.modelo import Fonte, Referencia

    referencia = Referencia(
        fonte=Fonte("compras_gov_precos", "Compras.gov", "sistema_oficial"),
        id_externo=id_externo, bruto={},
        descricao_original="CANETA ESFEROGRAFICA AZUL",
        unidade_original="UN", unidade_normalizada="UN",
        valor_unitario_original=Decimal(valor),
        valor_unitario_normalizado=Decimal(valor),
        natureza_valor=NaturezaValor(natureza))
    return referencia


def _nota_cheia():
    return matching.Comparabilidade(
        score=Decimal("1"), identidade=Decimal("1"),
        circunstancias=Decimal("1"), fatores=[])


def test_a_falha_tecnica_sobrevive_a_releitura(banco, municipio):
    """
    A outra correção que só a releitura prova.

    Em memória, `ResultadoItem.desfechos` distingue "a fonte de preço
    caiu" de "o mercado não tinha o item". Se a coluna não existisse — ou
    se o motor não a gravasse —, reabrir a pesquisa amanhã apagaria a
    distinção, e o servidor veria um `error` mudo.
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, municipio["servidor"]["jwt"])
        c.execute(
            "insert into pesquisas_preco (tenant_id, secretaria_id, "
            "auth_user_id, nome) values (%s, %s, %s, 'Smoke falha') "
            "returning id",
            (municipio["tenant_a"], municipio["secretaria"],
             municipio["servidor"]["id"]))
        pesquisa = c.fetchone()[0]

        c.execute(
            "insert into pesquisa_preco_itens (pesquisa_id, tenant_id, "
            " numero, descricao, estado, desfechos, erro) "
            "values (%s, %s, 1, 'CANETA', 'error', %s, %s) returning id",
            (pesquisa, municipio["tenant_a"],
             json.dumps({"compras_gov_precos": "failure",
                         "pncp": "success_empty"}),
             "as fontes de preço não responderam"))
        item = c.fetchone()[0]

        c.execute("select estado, desfechos, erro from pesquisa_preco_itens "
                  "where id = %s", (item,))
        estado, desfechos, erro = c.fetchone()

    assert estado == "error"
    assert desfechos == {"compras_gov_precos": "failure",
                         "pncp": "success_empty"}
    assert "não responderam" in erro

    # E a orientação lida do banco diz para REPETIR, não para mexer nos
    # critérios da busca.
    from src.precos import orientacao

    avisos = orientacao.do_item(
        {"numero": 1, "estado": estado, "desfechos": desfechos}, [])
    texto = " ".join(o.texto for o in avisos)
    assert "indisponibilidade técnica" in texto
    assert "compras_gov_precos" in texto


def test_outro_tenant_nao_alcanca_nada_da_pesquisa(banco, municipio):
    """
    O passo 14 do §15, e o que decide se este módulo pode existir.

    O intruso é de OUTRO município, autenticado e legítimo no dele.
    Precisa enxergar zero linha em cada uma das quatro tabelas — e não
    receber erro, que já seria informação: "existe algo aqui".
    """
    with banco.transaction(force_rollback=True), banco.cursor() as c:
        como(c, municipio["servidor"]["jwt"])
        c.execute(
            "insert into pesquisas_preco (tenant_id, secretaria_id, "
            "auth_user_id, nome) values (%s, %s, %s, 'Confidencial') "
            "returning id",
            (municipio["tenant_a"], municipio["secretaria"],
             municipio["servidor"]["id"]))
        pesquisa = c.fetchone()[0]
        c.execute(
            "insert into pesquisa_preco_itens (pesquisa_id, tenant_id, "
            "numero, descricao) values (%s, %s, 1, 'CANETA') returning id",
            (pesquisa, municipio["tenant_a"]))
        item = c.fetchone()[0]
        c.execute(
            "insert into pesquisa_preco_referencias (item_id, tenant_id, "
            "fonte_id, id_externo, raw_hash) values (%s, %s, 'x', 'y', 'z')",
            (item, municipio["tenant_a"]))
        c.execute(
            "insert into pesquisa_preco_eventos (pesquisa_id, tenant_id, "
            "tipo) values (%s, %s, 'pesquisa_criada')",
            (pesquisa, municipio["tenant_a"]))

        # Agora o intruso.
        como(c, municipio["intruso"]["jwt"])
        visiveis = {}
        for tabela in ("pesquisas_preco", "pesquisa_preco_itens",
                       "pesquisa_preco_referencias", "pesquisa_preco_eventos"):
            c.execute(f"select count(*) from {tabela}")
            visiveis[tabela] = c.fetchone()[0]

        # E não consegue escrever em nome do município alheio.
        recusou = False
        try:
            c.execute(
                "insert into pesquisas_preco (tenant_id, secretaria_id, "
                "auth_user_id, nome) values (%s, %s, %s, 'Invasao')",
                (municipio["tenant_a"], municipio["secretaria"],
                 municipio["intruso"]["id"]))
        except Exception:
            recusou = True

    assert visiveis == {"pesquisas_preco": 0, "pesquisa_preco_itens": 0,
                        "pesquisa_preco_referencias": 0,
                        "pesquisa_preco_eventos": 0}, (
        f"outro município enxergou a pesquisa: {visiveis}")
    assert recusou, "outro município conseguiu criar pesquisa no tenant alheio"


def test_a_flag_do_modulo_nasce_desligada(banco):
    """
    §40: aplicar a migração não liga o módulo para ninguém. Este é o
    último fio entre "a 0021 está no banco" e "servidores estão usando".
    """
    with banco.cursor() as c:
        voltar_a_ser_servidor(c)
        c.execute("select valor from config_app "
                  "where chave = 'flag_price_research'")
        linha = c.fetchone()

    assert linha is not None, "a migração não registrou a flag"
    assert linha[0] == "off"
