"""
Cotação direta com fornecedor (Lei 14.133/2021, art. 23, § 1º, IV).

"Pesquisa direta com, no mínimo, 3 fornecedores, mediante solicitação
formal de cotação, desde que seja apresentada justificativa da escolha
desses fornecedores e que não tenham sido obtidos os orçamentos com mais
de 6 (seis) meses de antecedência da data de divulgação do edital."

O que este módulo faz é REGISTRAR a cotação recebida, com a trilha que o
inciso exige, e entregá-la à MESMA cesta das demais referências. Ele não
envia e-mail e não cria link para o fornecedor: não há provedor de
mensageria nem área pública configurados, e o § 1º não depende disso —
a solicitação formal pode ser ofício ou e-mail do próprio órgão, cujo
número/data fica registrado aqui.

O comprovante (a proposta assinada) é guardado por IMPRESSÃO: SHA-256,
nome e tamanho. O arquivo continua nos autos do processo; meses depois,
o hash prova que o documento juntado é o mesmo que formou o preço. Não
há armazenamento de arquivo configurado no projeto, e fingir que o
sistema guarda o PDF seria a pior das opções.

Tudo é validado AQUI, no servidor. A tela só coleta campos.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from .modelo import Fonte, NaturezaValor, Referencia, StatusReferencia

FONTE_COTACAO = Fonte(id="cotacao_direta",
                      nome="Cotação direta com fornecedor", tipo="outro")
# 6 meses do inciso IV, contados até a data-base da pesquisa
VALIDADE_DIAS = 180
TAMANHO_MAXIMO_COMPROVANTE = 10 * 1024 * 1024


class ErroCotacao(ValueError):
    """Cotação que não cumpre o inciso IV — com o motivo, para a tela."""


def cnpj_valido(cnpj: str) -> bool:
    digitos = [int(c) for c in str(cnpj or "") if c.isdigit()]
    if len(digitos) != 14 or len(set(digitos)) == 1:
        return False
    for tamanho in (12, 13):
        pesos = list(range(tamanho - 7, 1, -1)) + list(range(9, 1, -1))
        soma = sum(d * p for d, p in zip(digitos[:tamanho], pesos))
        resto = soma % 11
        if digitos[tamanho] != (0 if resto < 2 else 11 - resto):
            return False
    return True


@dataclass(frozen=True)
class Comprovante:
    nome: str
    sha256: str
    bytes: int

    @classmethod
    def de(cls, nome: str, conteudo: bytes) -> "Comprovante":
        if not conteudo:
            raise ErroCotacao("anexe a proposta recebida do fornecedor")
        if len(conteudo) > TAMANHO_MAXIMO_COMPROVANTE:
            raise ErroCotacao("comprovante acima de 10 MB")
        return cls(nome=str(nome or "comprovante")[:120],
                   sha256=hashlib.sha256(conteudo).hexdigest(),
                   bytes=len(conteudo))


def montar(item: dict, *, fornecedor: str, cnpj: str, data_cotacao: date,
           valor_unitario: str | Decimal, unidade: str, solicitacao: str,
           justificativa: str, comprovante: Comprovante,
           data_base: date | None = None,
           registrado_por: str = "") -> Referencia:
    """
    Valida e devolve a `Referencia` da cotação, já SELECIONADA.

    Selecionada porque registrar é o ato humano de revisão: quem anexa a
    proposta e justifica a escolha do fornecedor está incluindo o preço.
    A exclusão continua disponível na revisão, com motivo, como para
    qualquer referência.
    """
    data_base = data_base or date.today()
    digitos = "".join(c for c in str(cnpj or "") if c.isdigit())
    if not cnpj_valido(digitos):
        raise ErroCotacao("CNPJ do fornecedor inválido")
    if not str(fornecedor or "").strip():
        raise ErroCotacao("informe a razão social do fornecedor")
    try:
        valor = Decimal(str(valor_unitario).replace(".", "").replace(",", ".")
                        if "," in str(valor_unitario) else str(valor_unitario))
    except (InvalidOperation, ValueError):
        raise ErroCotacao("valor unitário inválido") from None
    if valor <= 0:
        raise ErroCotacao("valor unitário deve ser maior que zero")
    if data_cotacao > data_base:
        raise ErroCotacao("a data da cotação não pode ser posterior à "
                          "data-base da pesquisa")
    if data_base - data_cotacao > timedelta(days=VALIDADE_DIAS):
        raise ErroCotacao("cotação com mais de 6 meses da data-base "
                          "(art. 23, § 1º, IV, da Lei 14.133)")
    if not str(unidade or "").strip():
        raise ErroCotacao("informe a unidade cotada")
    if len(str(solicitacao or "").strip()) < 5:
        raise ErroCotacao("registre a solicitação formal (nº/data do ofício "
                          "ou e-mail enviado ao fornecedor)")
    if len(str(justificativa or "").strip()) < 15:
        raise ErroCotacao("justifique a escolha deste fornecedor")

    bruto = {
        "origem": FONTE_COTACAO.id,
        "cnpj": digitos,
        "fornecedor": str(fornecedor).strip(),
        "data_cotacao": data_cotacao.isoformat(),
        "valor_unitario": format(valor, "f"),
        "unidade": str(unidade).strip(),
        "solicitacao_formal": str(solicitacao).strip(),
        "justificativa_escolha": str(justificativa).strip(),
        "comprovante": {"nome": comprovante.nome,
                        "sha256": comprovante.sha256,
                        "bytes": comprovante.bytes},
        "registrado_por": registrado_por,
    }
    referencia = Referencia(
        fonte=FONTE_COTACAO,
        # o mesmo documento registrado duas vezes é a MESMA referência
        id_externo=f"cot-{comprovante.sha256[:20]}",
        bruto=bruto,
        descricao_original=str(item.get("descricao") or ""),
        unidade_original=str(unidade).strip(),
        valor_unitario_original=valor,
        natureza_valor=NaturezaValor.PROPOSTA,
        fornecedor=str(fornecedor).strip(),
        ni_fornecedor=digitos,
        data_compra=data_cotacao,
        referencia_externa=str(solicitacao).strip()[:120],
    )
    referencia.status = StatusReferencia.SELECIONADA
    return referencia.com_motivo(
        "cotação direta registrada com solicitação formal, justificativa e "
        f"comprovante (SHA-256 {comprovante.sha256[:12]}…)")


def admissivel(referencia: Referencia) -> bool:
    """
    Cotação gravada que pode compor a cesta: veio deste registro (com
    comprovante e solicitação formal no bruto) e é PROPOSTA. Proposta de
    outra origem — ou sem a trilha — não entra.
    """
    bruto = referencia.bruto or {}
    return (referencia.fonte.id == FONTE_COTACAO.id
            and referencia.natureza_valor is NaturezaValor.PROPOSTA
            and bool((bruto.get("comprovante") or {}).get("sha256"))
            and bool(bruto.get("solicitacao_formal")))


def registrar(pesquisa: dict, item: dict, referencia: Referencia,
              repositorio, *, perfil, ator: str = ""):
    """
    Grava a cotação no item, registra o evento e REFAZ o preço pela cesta
    — o mesmo `cesta.recalcular_e_gravar` da inclusão/exclusão manual.

    A unidade cotada passa pela mesma normalização das fontes oficiais:
    caixa cotada contra item em unidade, sem conteúdo declarado, não vira
    preço por unidade por adivinhação — a cotação é recusada com o motivo.
    """
    from . import cesta, unidades

    unidades.normalizar(referencia, str(item.get("unidade") or ""),
                        unidades.conteudo_declarado(item.get("descricao")))
    if referencia.valor_unitario_normalizado is None:
        raise ErroCotacao(
            "a unidade cotada não converte com prova para a unidade do item "
            f"({referencia.unidade_original} → {item.get('unidade')}); peça a "
            "cotação na unidade do item ou informe o conteúdo da embalagem")
    repositorio.registrar_referencias(str(item["id"]), [referencia])
    estimativa = cesta.recalcular_e_gravar(pesquisa, item, repositorio,
                                           perfil=perfil)
    repositorio.registrar_evento(
        str(pesquisa["id"]), "referencia_incluida", ator=ator or None,
        item_id=str(item["id"]),
        idempotency_key=f"cotacao:{item['id']}:{referencia.id_externo}",
        descricao=(f"Cotação direta de {referencia.fornecedor} registrada "
                   f"no item {int(item.get('numero') or 0):02d}"),
        payload={"origem": FONTE_COTACAO.id, "item_id": str(item["id"]),
                 "referencia": referencia.id_externo,
                 "sha256": referencia.bruto["comprovante"]["sha256"],
                 "cnpj": referencia.ni_fornecedor,
                 "preco_recalculado": None if estimativa.valor_unitario is None
                 else format(estimativa.valor_unitario, "f"),
                 "status_da_cesta": estimativa.status})
    return estimativa
