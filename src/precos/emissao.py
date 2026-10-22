"""
Emissão dos relatórios da pesquisa de preços — a regra, sem tela.

Morava em `src/ui/precos_ui.py`, misturada aos botões do Streamlit. Saiu
para cá (P04d, ADR-006: extração aditiva) porque a API nova emite o MESMO
documento, e regra de emissão duplicada diverge na primeira correção
feita só de um lado. A tela continua chamando estas funções pelos nomes
de antes (`_conteudo_do_relatorio`, `_registrar_emissao`, ...).

A ordem que todo caminho de emissão segue, na tela e no worker da API:

    conferir_cestas ──► ciência (ciencia.exigir) ──► renderizar ──► registrar

* `conferir_cestas` recusa cesta formada antes do teto (auditoria de
  18/10, C-4) — a mensagem diz quais itens e o que fazer;
* a ciência é conferida por quem chama, porque quem é o ator e como se
  pede a confirmação muda entre a tela e a API; a regra é a mesma
  (`precos.ciencia`);
* `renderizar` passa pelo motor institucional que já existe — §33: nada
  de um segundo pipeline de PDF;
* `registrar` grava a emissão da 0029 (hashes, pendências impressas) e o
  evento `relatorio_emitido` na trilha.
"""

from __future__ import annotations

import io
import zipfile

from . import relatorio
from . import repositorio as repo

# A tabela de emissões da 0029 aceita `completo|resumido|analitico|pacote`.
# Sem migração nova: o Relatório de Cotação é o relatório PRINCIPAL e se
# registra como `completo`; o analítico integral, como `analitico`. O nome
# do arquivo e o hash do arquivo distinguem cada emissão.
TIPO_NO_REGISTRO = {"cotacao": "completo",
                    "analitico_integral": "analitico"}

# Acima disto o Relatório Analítico Integral não é gerado: a conversão
# passaria de vários minutos e de centenas de MB de memória no servidor.
# A memória analítica (XLSX) traz o mesmo conteúdo, sem limite prático.
LIMITE_DO_ANALITICO = 15000

# Os tipos do padrão novo (flag do relatório visual), que usam o timbrado
# resolvido pelo vínculo; os do gerador antigo usam o `branding` da tela.
TIPOS_VISUAIS = frozenset({"cotacao", "analitico_integral"})

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document",
    "xlsx": "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet",
    "zip": "application/zip",
}


def precisa_de_marca(*, formato: str, tipo: str) -> bool:
    """O timbrado só é resolvido para quem o usa (é leitura de banco)."""
    return formato != "xlsx" and tipo in TIPOS_VISUAIS


def marca_resolvida() -> dict | None:
    """
    O timbrado do tenant/secretaria pelo MESMO resolvedor das exportações
    do processo: vínculo do usuário, e não escolha de tela. Sem resolução,
    o órgão padrão do município; sem órgão, nenhum.
    """
    from .. import contexto, db

    try:
        resolvido = contexto.identidade_para_exportacao()
        if resolvido is not None:
            return resolvido[0]
        orgaos = db.listar_orgaos()
    except db.ErroBanco:
        return None
    return orgaos[0] if orgaos else None


def total_de_referencias(referencias: dict[str, list[dict]]) -> int:
    return sum(len(v) for v in referencias.values())


def conferir_cestas(pesquisa: dict, itens: list[dict],
                    referencias: dict) -> None:
    """
    Cesta acima do teto não vai para documento (auditoria de 18/10, C-4).
    Todo caminho de emissão passa aqui; a mensagem diz quais itens e o que
    fazer.
    """
    from . import cesta as cesta_mod
    from . import cotacoes
    from .documento_cotacao import ErroDeRenderizacao

    politica = cotacoes.politica_automatica()
    pesquisa_id = str(pesquisa.get("id") or "")
    acima = cesta_mod.itens_acima_do_teto(
        itens, referencias, politica.teto if politica is not None else None,
        decididas_por_humano=lambda item_id: repo.referencias_decididas_por_humano(
            pesquisa_id, item_id))
    if acima:
        raise ErroDeRenderizacao(
            "O relatório não pode ser gerado: a cesta destes itens foi "
            "formada antes do limite de preços e da triagem — "
            + "; ".join(acima)
            + ". Refaça a cotação automática desses itens e gere de novo.")


def renderizar(pesquisa: dict, itens: list[dict], referencias: dict, *,
               formato: str, tipo: str, ciencia_doc: dict | None,
               marca: dict | None = None,
               branding_legado: dict | None = None) -> tuple[bytes, str, str]:
    """
    Gera UM formato, já conferidos a cesta e a ciência. Devolve (bytes,
    nome do arquivo, mimetype).

    `marca` é o timbrado resolvido pelo vínculo (padrão novo);
    `branding_legado`, o que o gerador antigo sempre usou — desligar a
    flag do relatório visual devolve exatamente o comportamento anterior.
    """
    from .. import export

    if formato == "xlsx":
        return (relatorio.xlsx_analitico(pesquisa, itens, referencias),
                relatorio.nome_do_arquivo(pesquisa, "memoria-analitica",
                                          "xlsx"),
                MIME["xlsx"])

    if tipo in TIPOS_VISUAIS:
        from . import documento_cotacao as dc
        from . import relatorio_view

        vista = relatorio_view.projetar(pesquisa, itens, referencias,
                                        branding=marca, ciencia=ciencia_doc)
        if tipo == "analitico_integral":
            return (dc.relatorio_analitico_pdf(vista),
                    relatorio.nome_do_arquivo(
                        pesquisa, "relatorio-analitico-integral", "pdf"),
                    MIME["pdf"])
        docx = dc.relatorio_de_cotacao_docx(vista)
        if formato == "docx":
            return (docx,
                    relatorio.nome_do_arquivo(pesquisa, "relatorio-cotacao",
                                              "docx"),
                    MIME["docx"])
        return (dc.em_pdf(docx, marca, links=dc.links_da_vista(vista)),
                relatorio.nome_do_arquivo(pesquisa, "relatorio-cotacao",
                                          "pdf"),
                MIME["pdf"])

    if tipo == "resumido":
        markdown = relatorio.resumido(pesquisa, itens, referencias,
                                      ciencia=ciencia_doc)
        titulo = "Pesquisa de Preços — Quadro Resumido"
    else:
        markdown = relatorio.completo(pesquisa, itens, referencias,
                                      ciencia=ciencia_doc)
        titulo = "Relatório de Pesquisa de Preços"

    if formato == "docx":
        return (export.gerar_docx(titulo, markdown, branding_legado),
                relatorio.nome_do_arquivo(pesquisa, tipo, "docx"),
                MIME["docx"])
    return (export.gerar_pdf(titulo, markdown, branding_legado),
            relatorio.nome_do_arquivo(pesquisa, tipo, "pdf"),
            MIME["pdf"])


def partes_do_pacote(*, visual: bool,
                     com_integral: bool = False) -> list[tuple[str, str]]:
    """
    §33 — o que entra no ZIP, como (formato, tipo). No padrão novo:
    Relatório de Cotação (PDF) e memória analítica (XLSX); o analítico
    integral só se pedido — gerar o PDF de centenas de páginas sem pedido
    é o custo que o pacote evita.
    """
    if visual:
        partes = [("pdf", "cotacao"), ("xlsx", "analitico")]
        if com_integral:
            partes.append(("pdf", "analitico_integral"))
        return partes
    return [("pdf", "completo"), ("pdf", "resumido"), ("xlsx", "analitico")]


def zipar(arquivos: list[tuple[str, bytes]]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for nome, conteudo in arquivos:
            zf.writestr(nome, conteudo)
    return buffer.getvalue()


def registrar(pesquisa: dict, itens: list[dict], referencias: dict, *,
              tipo: str, formato: str, conteudo: bytes, nome: str,
              ator: str | None, ciencia_doc: dict | None = None
              ) -> tuple[dict, bool]:
    """
    Toda geração entregue vira registro (quem, quando, hashes, pendências).
    Devolve (dados da emissão, se o registro foi gravado). `tipo` é o do
    REGISTRO (`TIPO_NO_REGISTRO` já aplicado).

    Exige a 0029 aplicada: quem chama decide se ela está (a tela pergunta
    a `_colunas_0029`; a API exige a 0029, que está em produção).
    """
    dados = relatorio.dados_da_emissao(
        pesquisa, itens, referencias, tipo=tipo, formato=formato,
        conteudo=conteudo, nome_arquivo=nome)
    registrado = repo.registrar_emissao(str(pesquisa["id"]), dados)
    repo.registrar_evento(
        str(pesquisa["id"]), "relatorio_emitido",
        ator=ator,
        descricao=f"{tipo} ({formato}) — {nome}",
        payload={**{k: dados[k] for k in ("tipo", "formato", "hash_decisorio",
                                          "hash_arquivo", "tamanho_bytes")},
                 **({"ciencia": {"assinatura": ciencia_doc.get("assinatura"),
                                 "alertas": len(ciencia_doc.get("alertas")
                                                or []),
                                 "registrada_em":
                                 ciencia_doc.get("registrada_em")}}
                    if ciencia_doc else {})},
        idempotency_key=f"emissao:{dados['idempotency_key']}")
    return dados, registrado is not None
