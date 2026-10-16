"""
Perfil normativo da pesquisa de preços.

A Lei nº 14.133/2021 é a base para todos. A IN SEGES/ME nº 65/2021 **não
é** norma municipal automática: ela tem âmbito próprio, e cada ente pode
ter regulamento local. Tratar a IN 65 como se valesse para todo tenant
seria erro jurídico embutido no código.

Por isso a regra vive aqui, versionada e nomeada — nunca enterrada em
texto solto da interface (§3 do prompt do módulo). Trocar de perfil muda
o comportamento do motor, e a pesquisa registra sob qual perfil foi feita.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PerfilNormativo:
    """
    Regras que o perfil impõe ao motor de formação de preço.

    Cada campo existe porque muda uma decisão do cálculo — não há campo
    decorativo.
    """

    id: str
    nome: str
    base_legal: str

    # Quantas referências o perfil considera suficientes. Abaixo disso a
    # pesquisa do item é INCOMPLETA, não concluída.
    minimo_referencias: int = 3

    # O perfil admite concluir com menos, mediante justificativa
    # registrada? A IN 65 admite em hipóteses específicas; o padrão da
    # Lei 14.133 pura é exigir a justificativa também.
    admite_menos_com_justificativa: bool = True

    # Teto da mediana: quando a estimativa se apoia EXCLUSIVAMENTE em
    # parâmetro de sistema oficial, o valor estimado não pode superar a
    # mediana da amostra. É a restrição do art. 6º da IN 65/2021.
    teto_da_mediana_em_sistema_oficial: bool = False

    # Métodos que o perfil autoriza para a estimativa.
    metodos_permitidos: tuple[str, ...] = ("media", "mediana", "menor")

    # Ordem de prioridade das fontes (§12). O motor não escolhe por
    # preço: escolhe por prioridade normativa e comparabilidade.
    prioridade_de_fontes: tuple[str, ...] = (
        "sistema_oficial", "contratacao_similar", "outro")

    observacoes: tuple[str, ...] = field(default_factory=tuple)

    # Onde o perfil apoia a exceção à regra dos três — vai para a memória
    # e para o relatório junto da justificativa. Texto, não juízo: o
    # sistema registra a base que o perfil declara; quem decide é a
    # autoridade competente.
    fundamento_excecao: str = ""

    # Citação que acompanha o motivo de uma referência desconsiderada.
    fundamento_desconsideracao: str = ""

    # Dispositivo cujos incisos enquadram a ORIGEM de cada preço (painel
    # oficial, contratação similar, cotação direta…). Ver `enquadramento`.
    base_dos_incisos: str = "Lei nº 14.133/2021, art. 23, § 1º"

    def conclui_com(self, quantidade: int) -> bool:
        return quantidade >= self.minimo_referencias


LEI_14133 = PerfilNormativo(
    id="lei_14133",
    nome="Lei nº 14.133/2021 (base)",
    base_legal="Lei nº 14.133/2021, art. 23",
    minimo_referencias=3,
    admite_menos_com_justificativa=True,
    teto_da_mediana_em_sistema_oficial=False,
    observacoes=(
        "Perfil base. O ente pode ter regulamento próprio que restrinja "
        "métodos ou exija parâmetros adicionais.",
    ),
    fundamento_excecao=(
        "Lei nº 14.133/2021, art. 23, com justificativa nos autos — "
        "confira o regulamento local do ente"),
    fundamento_desconsideracao=(
        "análise crítica dos preços coletados (Lei nº 14.133/2021, art. 23)"),
)

IN_65_2021 = PerfilNormativo(
    id="in_65_2021",
    nome="IN SEGES/ME nº 65/2021",
    base_legal="IN SEGES/ME nº 65/2021, arts. 5º e 6º",
    minimo_referencias=3,
    admite_menos_com_justificativa=True,
    teto_da_mediana_em_sistema_oficial=True,
    observacoes=(
        "Aplicável quando o ente a adota como referência. Não é norma "
        "municipal automática.",
        "Com estimativa apoiada exclusivamente em sistema oficial de "
        "preços, o valor estimado não supera a mediana da amostra.",
    ),
    fundamento_excecao="IN SEGES/ME nº 65/2021, art. 6º, § 5º",
    base_dos_incisos="IN SEGES/ME nº 65/2021, art. 5º",
    fundamento_desconsideracao="IN SEGES/ME nº 65/2021, art. 3º, VI",
)

PERFIS = {p.id: p for p in (LEI_14133, IN_65_2021)}
PADRAO = LEI_14133


def obter(perfil_id: str | None) -> PerfilNormativo:
    """
    Perfil pelo id, com o base como padrão.

    Id desconhecido cai no perfil base em vez de levantar: uma pesquisa
    não pode parar porque alguém digitou um perfil que não existe — mas o
    relatório sempre diz sob qual perfil ela correu.
    """
    return PERFIS.get((perfil_id or "").strip(), PADRAO)


# ---------------------------------------------------------------------------
# Enquadramento da origem de cada referência (dossiê BP, tema 7b)
#
# Os incisos da Lei nº 14.133/2021, art. 23, § 1º (e da IN 65/2021, art.
# 5º, com a mesma numeração) dizem DE ONDE pode vir o parâmetro: I painel
# oficial de preços; II contratações similares da Administração; IV
# pesquisa direta com fornecedores. O mapa é pelo ADAPTER que coletou, e
# não pelo `fonte_tipo` — o PNCP entra como `sistema_oficial` na prioridade
# da cesta, mas o que ele entrega é o resultado de UMA contratação, que é
# contratação similar (II). É enquadramento SUGERIDO pela origem técnica do
# dado; a conferência jurídica é de quem assina a pesquisa.
# ---------------------------------------------------------------------------
INCISO_POR_FONTE = {
    "compras_gov_precos": "I",
    "compras_gov_itens": "II",
    "pncp": "II",
    "cotacao_direta": "IV",
}
INCISO_POR_TIPO = {"sistema_oficial": "I", "contratacao_similar": "II"}


def inciso_da_fonte(fonte_id: str | None, fonte_tipo: str | None) -> str | None:
    return (INCISO_POR_FONTE.get(str(fonte_id or ""))
            or INCISO_POR_TIPO.get(str(fonte_tipo or "")))


def enquadramento(fonte_id: str | None, fonte_tipo: str | None,
                  perfil: PerfilNormativo | None = None) -> str:
    """'inciso I (Lei nº 14.133/2021, art. 23, § 1º)' ou 'sem enquadramento'."""
    perfil = perfil or PADRAO
    inciso = inciso_da_fonte(fonte_id, fonte_tipo)
    if inciso is None:
        return "sem enquadramento automático — confira a origem"
    return f"inciso {inciso} ({perfil.base_dos_incisos})"
