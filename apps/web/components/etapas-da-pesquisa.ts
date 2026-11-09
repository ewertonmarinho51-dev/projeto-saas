import type { StepItem } from "@/design-system";

/** Âncoras das seções da página da pesquisa — o destino de cada etapa. */
export const SECAO = {
  importar: "importar-itens",
  coleta: "coleta",
  itens: "itens",
  relatorios: "relatorios",
} as const;

const NOMES = ["Definir itens", "Coletar preços", "Triagem", "Mapa de preços", "Relatório final"];

/**
 * As etapas da referência (Definir itens → Coletar → Triagem → Mapa →
 * Relatório), lidas do estado que a API devolve.
 *
 * Etapa já passada leva de volta à SEÇÃO dela nesta página — navegação,
 * não transição. A máquina de estados (`src/precos/estados.py`) não tem
 * "voltar de etapa": refazer item é reabrir o item (na página dele), e
 * mexer numa pesquisa concluída ou aplicada é criar uma revisão nova
 * ("Nova revisão", logo abaixo do fluxo). O link só leva até onde esses
 * atos já moram.
 *
 * `editavel` diz se a importação e a coleta estão na página: aplicada ou
 * arquivada, elas somem, e "Definir itens"/"Coletar preços" levam à
 * tabela de itens, que continua lá.
 */
export function etapasDaPesquisa(estado: string, itens: number, concluidos: number, editavel: boolean): StepItem[] {
  const atual =
    itens === 0
      ? 0
      : estado === "queued" || estado === "running"
        ? 1
        : concluidos < itens
          ? 2
          : estado === "completed"
            ? 4
            : estado === "applied"
              ? 5
              : 3;
  const destinos = [
    editavel ? SECAO.importar : SECAO.itens,
    editavel ? SECAO.coleta : SECAO.itens,
    // Triagem é item a item, e a tabela é o mapa: preço estimado e total.
    SECAO.itens,
    SECAO.itens,
    SECAO.relatorios,
  ];
  return NOMES.map((label, i) => ({
    label,
    state: estado === "failed" && i === 1 ? "error" : i < atual ? "done" : i === atual ? "current" : "todo",
    meta: i === 2 && itens > 0 ? `${concluidos} de ${itens} itens` : undefined,
    href: i < atual ? `#${destinos[i]}` : undefined,
  }));
}
