import type { ProcessStatus } from "@/design-system";

/**
 * Cor e ícone do `StatusBadge` para a situação que a API devolve. A
 * situação em si é decidida no domínio (`src/processos.py`, pesquisa de
 * preços na 0021); aqui só se escolhe a aparência, e o rótulo mostrado é
 * sempre o texto da API. Situação desconhecida cai em "em andamento",
 * neutra, com o texto como veio.
 */
const DO_PROCESSO: Record<string, ProcessStatus> = {
  "Em elaboração": "em_elaboracao",
  "Aguardando pesquisa de preços": "pendente",
  "Em revisão": "em_revisao",
  Concluído: "concluido",
  Arquivado: "arquivado",
};

const DA_PESQUISA: Record<string, ProcessStatus> = {
  draft: "rascunho",
  queued: "em_andamento",
  running: "em_andamento",
  partial: "pendente",
  review: "em_revisao",
  completed: "concluido",
  applied: "aplicado",
  archived: "arquivado",
  failed: "erro",
};

const DO_ITEM: Record<string, ProcessStatus> = {
  pending: "pendente",
  searching: "em_andamento",
  matching: "em_andamento",
  review: "em_revisao",
  complete: "concluido",
  incomplete: "pendente",
  error: "erro",
};

export const situacaoDoItem = (estado: string): ProcessStatus => DO_ITEM[estado] ?? "em_andamento";

export const situacaoDoProcesso = (status: string): ProcessStatus => DO_PROCESSO[status] ?? "em_andamento";

export const situacaoDaPesquisa = (estado: string): ProcessStatus => DA_PESQUISA[estado] ?? "em_andamento";

/** Os rótulos exatos de `src/processos.py`, para contar no painel. */
export const STATUS = {
  aguardandoPrecos: "Aguardando pesquisa de preços",
  emRevisao: "Em revisão",
  concluido: "Concluído",
  arquivado: "Arquivado",
} as const;
