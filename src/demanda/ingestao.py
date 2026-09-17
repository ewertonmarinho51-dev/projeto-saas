"""
Do arquivo recebido à origem consolidável.

Uma responsabilidade só: transformar bytes em `Origem`, dizendo com
honestidade o que foi lido e o que não foi. Nada aqui soma, decide ou
adivinha.

Por que PyMuPDF e não o `rag.extrair_texto` do repositório
----------------------------------------------------------
A tentação era reusar `rag.extrair_texto`, que já lê PDF, DOCX e TXT.
Testei antes de decidir, contra os doze arquivos reais: o `pypdf` que
ele usa devolve **zero itens** com o parser escrito para a forma que o
PyMuPDF produz, porque cola a linha inteira num só campo e insere
espaços espúrios no meio das palavras.

Duas coisas saíram daí. O parser passou a aceitar as duas formas — não
ser refém de uma biblioteca é barato e evita zerar a extração inteira em
silêncio numa troca de dependência. E a ingestão ficou com o PyMuPDF,
que preserva a estrutura do quadro: com ele os dois extratores
concordam em nove dos dez arquivos legíveis, e no décimo é o `pypdf` que
perde um item.

PDF de imagem
-------------
SECULT e SEMEL não têm camada de texto — são digitalizações. Não são
extraídos nem adivinhados: voltam com `status=IMAGEM` para a tela dizer
que não foram lidos e pedir providência. É o que o §5 determina, e é o
oposto de deixá-los entrar como "secretaria que não pediu nada".
"""

from __future__ import annotations

import hashlib
import io

from .consolidacao import ILEGIVEL, IMAGEM, LIDO, Origem
from .extracao import extrair_do_texto

# O marcador que todo DFD carrega no cabeçalho de TODA página. É o sinal
# de legibilidade, e não a densidade de texto: densidade é número mágico,
# e um DFD curto e legítimo cairia como "imagem" só por ser curto — o que
# um teste pegou antes de isto chegar à tela.
#
# Nos dois arquivos digitalizados reais o marcador não aparece nenhuma
# vez; nos dez legíveis, aparece em todas as páginas.
_MARCADOR = "FORMALIZAÇÃO DE DEMANDA"

# Só para separar "digitalização" de "PDF de outra coisa" quando o
# marcador falta. Um scan traz a tarja de assinatura e mais nada — cerca
# de 140 caracteres por página.
_TEXTO_DE_SCAN_POR_PAGINA = 200


class ErroIngestao(Exception):
    """O arquivo não pôde ser lido. Nunca vira extração vazia silenciosa."""


def impressao_digital(conteudo: bytes) -> str:
    """
    SHA-256 do arquivo, para o §10.

    É o que permite dizer "este arquivo já entrou" sem comparar nome,
    que muda quando alguém renomeia, nem tamanho, que colide.
    """
    return hashlib.sha256(conteudo).hexdigest()


def texto_do_pdf(conteudo: bytes) -> tuple[str, bool]:
    """
    Devolve (texto, parece_digitalizacao).

    O segundo valor é o que separa "não pediram nada" de "ninguém
    conseguiu ler" — distinção que o §5 exige e que uma extração vazia
    sozinha não carrega.
    """
    import pymupdf

    with pymupdf.open(stream=io.BytesIO(conteudo), filetype="pdf") as doc:
        paginas = [pagina.get_text() for pagina in doc]
        total = len(doc)
    texto = "\n".join(paginas)
    if _MARCADOR in texto:
        return texto, False
    util = sum(len(p.strip()) for p in paginas)
    magro = not total or (util / total) < _TEXTO_DE_SCAN_POR_PAGINA
    return texto, magro


def ler(nome_arquivo: str, conteudo: bytes, *, secretaria: str = "") -> Origem:
    """
    Um arquivo recebido vira uma `Origem`, pronta para consolidar.

    `secretaria` é o rótulo que a tela mostra. Quando não vem, sai do
    ÓRGÃO declarado dentro do documento — nunca do nome do arquivo, que
    o §6 proíbe como fonte de identidade. Ficando vazio, a tela pede
    confirmação humana antes de consolidar.
    """
    if not conteudo:
        return Origem(secretaria=secretaria, arquivo=nome_arquivo,
                      status=ILEGIVEL)

    extensao = nome_arquivo.rsplit(".", 1)[-1].lower() if "." in nome_arquivo else ""
    if extensao != "pdf":
        raise ErroIngestao(
            f"Formato .{extensao or '?'} não suportado nesta etapa — "
            "os Documentos de Formalização de Demanda chegam em PDF.")

    try:
        texto, digitalizacao = texto_do_pdf(conteudo)
    except Exception as exc:  # noqa: BLE001 — PDF corrompido é caso previsto
        raise ErroIngestao(
            f"Não foi possível abrir '{nome_arquivo}'. O arquivo pode estar "
            "corrompido ou protegido por senha.") from exc

    if digitalizacao:
        return Origem(secretaria=secretaria, arquivo=nome_arquivo,
                      hash_arquivo=impressao_digital(conteudo), status=IMAGEM)

    dfds = extrair_do_texto(texto)
    rotulo = secretaria or (dfds[0].orgao_nome if dfds else "")
    return Origem(
        secretaria=rotulo,
        arquivo=nome_arquivo,
        dfds=dfds,
        hash_arquivo=impressao_digital(conteudo),
        status=LIDO if dfds else ILEGIVEL,
    )


def precisa_de_confirmacao(origem: Origem) -> bool:
    """
    A secretaria ficou ambígua?

    §6: ambiguidade pede confirmação ANTES de consolidar. Sem rótulo, a
    quantidade não teria coluna onde entrar — e somar mesmo assim
    esconderia de quem veio o pedido.
    """
    return origem.status == LIDO and not origem.secretaria.strip()


__all__ = ["ErroIngestao", "impressao_digital", "ler",
           "precisa_de_confirmacao", "texto_do_pdf"]
