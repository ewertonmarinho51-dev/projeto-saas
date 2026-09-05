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
