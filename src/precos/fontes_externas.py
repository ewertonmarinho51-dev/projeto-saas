"""
Registro das fontes de preço NOVAS — e a trava que as mantém desligadas.

Pacote de expansão das fontes (20/10/2026). Compras.gov e PNCP NÃO estão
aqui: continuam em `fontes_padrao()` como sempre. Este registro é das
fontes que ainda não podem alimentar a cesta.

Uma fonte só fica `habilitada` com as TRÊS coisas ao mesmo tempo:

1. a flag `price_source_<id>` ligada em `config_app` (default OFF);
2. `licenca == APROVADA` — e isto mora NO CÓDIGO, versionado, não na
   tabela que o painel edita: ligar a flag pela tela não basta para pôr
   em produção dado cujo reúso ninguém autorizou;
3. `mapeamento_confirmado` — colunas, códigos e etapa do preço conferidos
   no dicionário/leiaute oficial da fonte.

Nenhuma fonte deste arquivo cumpre as três hoje. Mudar `licenca` para
APROVADA exige o documento da autorização citado em `prova_licenca`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Licenca(str, Enum):
    NAO_AVALIADA = "NAO_AVALIADA"
    EM_NEGOCIACAO = "EM_NEGOCIACAO"
    PENDENTE_JURIDICO = "PENDENTE_JURIDICO"
    APROVADA = "APROVADA"
    NEGADA = "NEGADA"


class Acesso(str, Enum):
    ZIP_CSV = "zip_csv"
    ZIP_JSON = "zip_json"
    API_COM_CHAVE = "api_com_chave"
    SEM_CANAL = "sem_canal"          # só consulta pública em tela


@dataclass(frozen=True)
class RegistroFonte:
    id: str
    nome: str
    acesso: Acesso
    documentacao: str
    licenca: Licenca
    # o que se sabe da licença, com data — nunca "presumida"
    nota_licenca: str
    mapeamento_confirmado: bool = False
    prova_licenca: str = ""
    # URLs de arquivo oficial conferidas na página da própria fonte
    downloads: tuple[str, ...] = ()
    pendencia: str = ""

    @property
    def flag(self) -> str:
        return f"price_source_{self.id}"


REGISTRO: dict[str, RegistroFonte] = {r.id: r for r in (
    RegistroFonte(
        "tce_rs", "TCE-RS — LicitaCon (dados abertos)", Acesso.ZIP_CSV,
        "https://dados.tce.rs.gov.br/dataset/licitacoes-consolidado-2026",
        Licenca.NAO_AVALIADA,
        "20/10/2026: CKAN do TCE-RS sem licença no dataset nem no recurso "
        "(license_id vazio); dados declarados de responsabilidade de cada "
        "entidade, não analisados pelo TCE",
        downloads=("https://dados.tce.rs.gov.br/dados/licitacon/licitacao/"
                   "ano/2026.csv.zip",),
        pendencia="licença de reúso em SaaS; leiaute oficial com o "
                  "significado de TP_RESULTADO_ITEM, CD_TIPO_FASE_ATUAL e "
                  "CD_TIPO_MODALIDADE (o PDF 1.4 citado no dataset devolve "
                  "404 em 20/10/2026)"),
    RegistroFonte(
        "bps", "Ministério da Saúde — Banco de Preços em Saúde",
        Acesso.ZIP_CSV, "https://dadosabertos.saude.gov.br/dataset/bps",
        Licenca.NAO_AVALIADA,
        "20/10/2026: página do dataset com license_id vazio",
        downloads=("https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/"
                   "BPS/csv/2026_csv.zip",
                   "https://s3.sa-east-1.amazonaws.com/ckan.saude.gov.br/"
                   "BPS/json/2026_json.zip"),
        pendencia="licença; decidir se arquivo oficial + co_seq_bps basta "
                  "como evidência (o arquivo não traz URL por registro). A "
                  "etapa do preço está no dicionário: preço pago "
                  "(Metadados_BPS_07_04_2026.pdf)"),
    RegistroFonte(
        "pcp", "Portal de Compras Públicas — API de parceiros",
        Acesso.API_COM_CHAVE,
        "https://bibliotecapcp.zendesk.com/hc/pt-br/articles/4593611793690",
        Licenca.NAO_AVALIADA,
        "exige PublicKey e termo; nenhuma chave nem endpoint de itens "
        "confirmados",
        pendencia="PublicKey, documentação dos recursos de itens e "
                  "resultados, termo de reúso"),
    *(RegistroFonte(i, n, Acesso.SEM_CANAL, d, Licenca.NAO_AVALIADA,
                    "sem API de leitura de preços unitários confirmada",
                    pendencia="pedido de documentação/parceria (ver "
                              "docs/fontes-precos/D_PENDENCIAS_ACESSO.md)")
      for i, n, d in (
          ("licitanet", "LICITANET", "https://licitanet.com.br/"),
          ("bll", "BLL Compras", "https://bll.org.br/"),
          ("bnc", "BNC", "https://bnc.org.br/"),
          ("comprasbr", "Compras BR", "https://comprasbr.com.br/"),
          ("bbmnet", "BBMNET", "https://bbmnet.com.br/"),
          ("tcm_pa", "TCM-PA — Mural de Licitações",
           "https://www.tcm.pa.gov.br/mural-de-licitacoes/"),
          ("licitar_digital", "Licitar Digital",
           "https://licitardigital.com.br/"))),
)}


def habilitada(fonte_id: str, *, flag_ativa=None) -> bool:
    """As três travas. Sem banco (ou erro ao ler a flag): desligada."""
    registro = REGISTRO.get(fonte_id)
    if registro is None:
        return False
    if registro.licenca != Licenca.APROVADA or not registro.prova_licenca \
            or not registro.mapeamento_confirmado:
        return False
    if flag_ativa is None:
        from .. import db

        flag_ativa = db.flag_ativa
    try:
        return bool(flag_ativa(registro.flag))
    except Exception:  # noqa: BLE001 — leitura de flag nunca liga fonte
        return False


def fontes_habilitadas(*, flag_ativa=None) -> list[str]:
    return [i for i in REGISTRO if habilitada(i, flag_ativa=flag_ativa)]
