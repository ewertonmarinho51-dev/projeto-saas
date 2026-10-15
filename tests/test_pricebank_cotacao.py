"""
Cotação direta com fornecedor (Gate 5, COT-01) — dados SINTÉTICOS.

Os CNPJs são os exemplos de validação de dígito amplamente usados em
documentação (11.222.333/0001-81, 11.444.777/0001-61), não fornecedores
reais. Nenhuma rede e nenhum envio de mensagem.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from src import db
from src.precos import busca, cesta, cotacao, perfil, relatorio
from src.precos import repositorio as repo
from src.precos.estados import EstadoItem
from src.precos.modelo import NaturezaValor, Referencia
from tests.conftest import ClientePrecosFalso
from tests.test_pricebank_ponta_a_ponta import ITEM, _homologada
from tests.test_precos_fase4 import FONTE_OFICIAL, _FonteFalsa

CNPJ_A = "11.222.333/0001-81"
CNPJ_B = "11.444.777/0001-61"
HOJE = date(2026, 10, 15)


def _comprovante(texto=b"%PDF-1.4 proposta sintetica"):
    return cotacao.Comprovante.de("proposta.pdf", texto)


def _montar(**mudancas):
    campos = dict(fornecedor="Papelaria Exemplo Ltda", cnpj=CNPJ_A,
                  data_cotacao=HOJE - timedelta(days=10),
                  valor_unitario="24,00", unidade="UNIDADE",
                  solicitacao="Ofício nº 12/2026, de 01/10/2026",
                  justificativa="Fornecedor do ramo com sede no município",
                  comprovante=_comprovante(), data_base=HOJE)
    campos.update(mudancas)
    return cotacao.montar(ITEM, **campos)


def test_cnpj_por_digito_verificador():
    assert cotacao.cnpj_valido(CNPJ_A) and cotacao.cnpj_valido(CNPJ_B)
    assert not cotacao.cnpj_valido("11.222.333/0001-82")
    assert not cotacao.cnpj_valido("11111111111111")


def test_cotacao_valida_vira_proposta_selecionada_com_trilha():
    ref = _montar()
    assert ref.natureza_valor is NaturezaValor.PROPOSTA
    assert ref.valor_unitario_original == Decimal("24.00")
    assert ref.bruto["comprovante"]["sha256"] == _comprovante().sha256
    assert ref.ni_fornecedor == "11222333000181"
    assert cotacao.admissivel(ref)


@pytest.mark.parametrize("mudanca,motivo", [
    ({"cnpj": "123"}, "CNPJ"),
    ({"valor_unitario": "0"}, "maior que zero"),
    ({"valor_unitario": "abc"}, "inválido"),
    ({"data_cotacao": HOJE - timedelta(days=181)}, "6 meses"),
    ({"data_cotacao": HOJE + timedelta(days=1)}, "posterior"),
    ({"solicitacao": ""}, "solicitação formal"),
    ({"justificativa": "porque sim"}, "justifique"),
    ({"fornecedor": " "}, "razão social"),
])
def test_cotacao_fora_do_inciso_iv_e_recusada(mudanca, motivo):
    with pytest.raises(cotacao.ErroCotacao, match=motivo):
        _montar(**mudanca)


def test_sem_comprovante_e_recusada():
    with pytest.raises(cotacao.ErroCotacao, match="anexe"):
        cotacao.Comprovante.de("x.pdf", b"")


def test_proposta_sem_trilha_ou_de_outra_origem_nao_compoe_cesta():
    ref = _montar()
    sem_trilha = Referencia(fonte=ref.fonte, id_externo="x", bruto={},
                            natureza_valor=NaturezaValor.PROPOSTA)
    de_fora = Referencia(fonte=FONTE_OFICIAL, id_externo="y", bruto=ref.bruto,
                         natureza_valor=NaturezaValor.PROPOSTA)
    assert not cotacao.admissivel(sem_trilha)
    assert not cotacao.admissivel(de_fora)


def _pesquisa_com_duas(monkeypatch):
    cliente = ClientePrecosFalso()
    monkeypatch.setattr(db, "cliente_do_usuario", lambda: cliente)
    fonte = _FonteFalsa(FONTE_OFICIAL, [_homologada("r0", "20.00"),
                                        _homologada("r1", "22.00")])
    coleta = busca.coletar(dict(ITEM, id="c", numero=1), [fonte])
    salvo = cesta.salvar_consulta_como_pesquisa(
        repositorio=repo, nome="duas oficiais", item=ITEM, coleta=coleta,
        selecionados={r.chave_dedupe for r, _ in coleta.referencias},
        perfil=perfil.LEI_14133, auth_user_id="u1")
    pesquisa = repo.obter_pesquisa(salvo["pesquisa_id"])
    [item] = repo.listar_itens(salvo["pesquisa_id"])
    return cliente, pesquisa, item


def test_terceira_cotacao_fecha_a_cesta_e_entra_no_relatorio(monkeypatch):
    cliente, pesquisa, item = _pesquisa_com_duas(monkeypatch)
    assert item["estado"] == EstadoItem.INCOMPLETO.value

    estimativa = cotacao.registrar(pesquisa, item, _montar(), repo,
                                   perfil=perfil.LEI_14133, ator="u1")
    assert estimativa.valor_unitario == Decimal("22.00")   # (20+22+24)/3
    [item] = repo.listar_itens(str(pesquisa["id"]))
    assert item["estado"] == EstadoItem.EM_REVISAO.value
    assert Decimal(str(item["preco_total"])) == Decimal("2200.00")

    eventos = [e for e in cliente.tabelas["pesquisa_preco_eventos"]
               if e["payload"].get("origem") == "cotacao_direta"]
    assert len(eventos) == 1 and eventos[0]["payload"]["sha256"]

    referencias = {str(item["id"]): repo.listar_referencias(str(item["id"]))}
    texto = relatorio.completo(pesquisa, [item], referencias)
    assert "Papelaria Exemplo Ltda" in texto
    assert "art. 23, § 1º, IV" in texto
    assert _comprovante().sha256 in texto


def test_mesmo_comprovante_registrado_duas_vezes_nao_duplica(monkeypatch):
    cliente, pesquisa, item = _pesquisa_com_duas(monkeypatch)
    cotacao.registrar(pesquisa, item, _montar(), repo, perfil=perfil.LEI_14133)
    [item] = repo.listar_itens(str(pesquisa["id"]))
    cotacao.registrar(pesquisa, item, _montar(), repo, perfil=perfil.LEI_14133)
    cotacoes = [r for r in cliente.tabelas["pesquisa_preco_referencias"]
                if r["fonte_id"] == "cotacao_direta"]
    assert len(cotacoes) == 1


def test_unidade_cotada_sem_conversao_comprovada_e_recusada(monkeypatch):
    _, pesquisa, item = _pesquisa_com_duas(monkeypatch)
    with pytest.raises(cotacao.ErroCotacao, match="não converte"):
        cotacao.registrar(pesquisa, item, _montar(unidade="CAIXA"), repo,
                          perfil=perfil.LEI_14133)
