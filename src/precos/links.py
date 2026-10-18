"""
Links de uma referência de preço — fonte, contratação e dados técnicos.

Revisão 02 (06_FONTES_E_LINKS). O relatório anterior apontava os 24
links do PDF para `dadosabertos.compras.gov.br/.../1_consultarMaterial`:
consulta técnica em JSON, não a página da contratação. Aqui os três
endereços ficam SEPARADOS e nenhum é fabricado:

* `fonte_url` — o site público da fonte (complemento, nunca "Consulta");
* `contratacao_url` — a página pública DESSA contratação, montada só a
  partir de identificador oficial da própria referência, por rota
  conferida no portal (abaixo);
* `dados_url` — o endpoint técnico (JSON) que devolve o registro. Serve à
  memória analítica; nunca é apresentado como a contratação.

Rotas conferidas em 17/10/2026, abrindo a página no navegador e
comparando órgão, número e item com o registro da API:

* Compras.gov.br — `acompanhamento-compra?compra=<idCompra>`: o
  `idCompra` (UASG + modalidade + número + ano, 17 dígitos) abriu
  "Pregão Eletrônico Nº 2/2026 (SRP) — UASG 929842 — Câmara Municipal de
  Vereadores de Santa Maria", com o item 7 "Papel para impressão", o
  mesmo da referência 9298420500002202600007;
* PNCP — `pncp.gov.br/app/editais/<cnpj>/<ano>/<sequencial>`: o controle
  90483058000126-1-000078/2025 abriu o "Edital nº 0013/2025 — Município
  de Caseiros", com o mesmo id de contratação.

Ata e outros documentos: só quando a fonte entrega o endereço do
documento. Nenhuma das fontes atuais entrega — então não há link de ata
(nunca botão falso). Nada aqui faz rede: o PDF não consulta a internet.

Auditoria de 18/10/2026 (C-2): a API devolve `idCompra` como NÚMERO
JSON, e o zero inicial das UASG que começam com 0 (060001, 092601...)
some — `6000105001912026`, 16 dígitos. 300 das 5.741 referências de
produção ficavam sem link e o PDF dizia "Não disponível na fonte", o que
era falso. A própria fonte guarda o identificador certo em `idCompraItem`,
que vem como TEXTO (`0600010500191202600193`); `id_compra_oficial` usa
esse campo, ou a UASG, e só quando os dois concordam com o número.
Conferido no portal: `06000105001912026` abriu o Pregão 191/2026 do STM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlparse

FONTE_COMPRAS = "https://www.gov.br/compras/pt-br"
FONTE_PNCP = "https://pncp.gov.br/app/editais"
ACOMPANHAMENTO_COMPRA = ("https://cnetmobile.estaleiro.serpro.gov.br/"
                         "comprasnet-web/public/compras/acompanhamento-compra"
                         "?compra={id_compra}")
CONTRATACAO_PNCP = "https://pncp.gov.br/app/editais/{cnpj}/{ano}/{sequencial}"

ID_COMPRA = re.compile(r"^\d{17}$")
ID_COMPRA_ITEM = re.compile(r"^\d{22}$")
CONTROLE_PNCP = re.compile(r"^(\d{14})-\d+-(\d{1,6})/(\d{4})$")

# Hosts aceitos em qualquer link impresso: só os oficiais acima.
HOSTS_PERMITIDOS = frozenset({
    "cnetmobile.estaleiro.serpro.gov.br", "pncp.gov.br", "www.gov.br",
    "dadosabertos.compras.gov.br"})

NAO_DISPONIVEL = "Não disponível na fonte"


@dataclass(frozen=True)
class Links:
    fonte_url: str | None = None
    fonte_rotulo: str = ""
    contratacao_url: str | None = None
    # o que a página é, para o rótulo do link no documento
    contratacao_rotulo: str = ""
    dados_url: str | None = None
    # número oficial impresso (idCompra ou controle PNCP) — é sobre ele
    # que o PDF grava o link. Impresso MESMO sem link: é o que permite
    # localizar a contratação à mão.
    identificacao: str = ""
    # quem comprou, como o portal identifica: "UASG 110120 — ABIN/GSI/PR"
    unidade_compradora: str = ""


def seguro(url: str | None) -> str | None:
    """https e host oficial conhecido — o resto não vira link."""
    if not url:
        return None
    partes = urlparse(str(url))
    if partes.scheme != "https" or partes.username or partes.password:
        return None
    if (partes.hostname or "").lower() not in HOSTS_PERMITIDOS:
        return None
    return str(url)


def controle_pncp(texto) -> tuple[str, str, str] | None:
    """(cnpj, ano, sequencial sem zeros) de "CNPJ-1-SEQ/ANO", ou None."""
    achado = CONTROLE_PNCP.match(str(texto or "").strip())
    if not achado:
        return None
    cnpj, sequencial, ano = achado.groups()
    return cnpj, ano, str(int(sequencial))


def contratacao_pncp(texto) -> str | None:
    controle = controle_pncp(texto)
    if controle is None:
        return None
    cnpj, ano, sequencial = controle
    return CONTRATACAO_PNCP.format(cnpj=cnpj, ano=ano, sequencial=sequencial)


def acompanhamento_compra(id_compra) -> str | None:
    texto = str(id_compra or "").strip()
    return ACOMPANHAMENTO_COMPRA.format(id_compra=texto) \
        if ID_COMPRA.match(texto) else None


def id_compra_oficial(bruto: dict, referencia_externa=None) -> str:
    """
    O `idCompra` de 17 dígitos, só com o que a fonte entregou.

    Ordem: o número já com 17 dígitos; o prefixo de `idCompraItem` (texto,
    22 dígitos) quando representa o MESMO número; a UASG com zero inicial
    quando o número começa por ela sem o zero. Fora disso, "" — nunca um
    número completado por palpite.
    """
    bruto = bruto or {}
    compra = str(bruto.get("idCompra") or referencia_externa or "").strip()
    if not compra.isdigit():
        return ""
    if ID_COMPRA.match(compra):
        return compra
    item = bruto.get("idCompraItem")
    if isinstance(item, str) and ID_COMPRA_ITEM.match(item.strip()):
        prefixo = item.strip()[:17]
        if int(prefixo) == int(compra):
            return prefixo
    uasg = str(bruto.get("codigoUasg") or "").strip()
    if (len(compra) < 17 and uasg.isdigit() and uasg.startswith("0")
            and compra.zfill(17).startswith(uasg)):
        return compra.zfill(17)
    return ""


def unidade_compradora(bruto: dict) -> str:
    """'UASG 110120 — NOME', quando a fonte traz o código."""
    bruto = bruto or {}
    codigo = str(bruto.get("codigoUasg") or "").strip()
    nome = " ".join(str(bruto.get("nomeUasg") or "").split())
    if not codigo:
        return ""
    return f"UASG {codigo}" + (f" — {nome}" if nome else "")


def resolver(linha: dict) -> Links:
    """Os links verificáveis de UMA referência gravada (sem rede)."""
    from . import compras_gov
    from . import pncp as pncp_mod

    bruto = linha.get("bruto") or {}
    fid = str(linha.get("fonte_id") or "")
    if fid == "compras_gov_precos":
        compra = id_compra_oficial(bruto, linha.get("referencia_externa"))
        url = acompanhamento_compra(compra)
        cru = str(bruto.get("idCompra") or linha.get("referencia_externa")
                  or "").strip()
        return Links(
            fonte_url=FONTE_COMPRAS, fonte_rotulo="Compras.gov.br",
            contratacao_url=url,
            contratacao_rotulo="Acompanhar contratação (Compras.gov.br)"
            if url else "",
            dados_url=seguro(compras_gov.url_de_verificacao(bruto)),
            identificacao=compra or cru,
            unidade_compradora=unidade_compradora(bruto))
    if fid == "compras_gov_itens":
        controle = (bruto.get("numeroControlePNCPCompra")
                    or bruto.get("idContratacaoPNCP")
                    or linha.get("referencia_externa"))
        url = contratacao_pncp(controle)
        return Links(
            fonte_url=FONTE_PNCP, fonte_rotulo="PNCP",
            contratacao_url=url,
            contratacao_rotulo="Contratação no PNCP" if url else "",
            dados_url=seguro(compras_gov.url_de_verificacao(bruto)),
            identificacao=" ".join(str(controle or "").split()),
            unidade_compradora=unidade_compradora(bruto))
    if fid == "pncp":
        url = seguro(pncp_mod.url_de_verificacao(bruto))
        return Links(
            fonte_url=FONTE_PNCP, fonte_rotulo="PNCP", contratacao_url=url,
            contratacao_rotulo="Contratação no PNCP" if url else "",
            identificacao=" ".join(
                str(bruto.get("numeroControlePNCP") or "").split()))
    return Links()


def eh_tecnico(url: str | None) -> bool:
    """Endpoint de dados (JSON), que não pode ser rotulado de contratação."""
    if not url:
        return False
    partes = urlparse(url)
    return (partes.hostname or "") == "dadosabertos.compras.gov.br" or \
        "/api/" in partes.path