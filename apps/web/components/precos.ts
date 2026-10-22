/**
 * Rótulos dos códigos que a API devolve (os mesmos CHECKs da 0021).
 * Código desconhecido aparece como veio: esconder seria pior que mostrar.
 */
const ESTADO_PESQUISA: Record<string, string> = {
  draft: "Rascunho",
  queued: "Na fila",
  running: "Coletando",
  partial: "Coleta parcial",
  review: "Em revisão",
  completed: "Concluída",
  applied: "Aplicada ao processo",
  archived: "Arquivada",
  failed: "Falhou",
};

const ESTADO_ITEM: Record<string, string> = {
  pending: "Pendente",
  searching: "Buscando",
  matching: "Comparando",
  review: "Em revisão",
  complete: "Concluído",
  incomplete: "Incompleto",
  error: "Erro",
};

const METODO: Record<string, string> = {
  media: "Média",
  mediana: "Mediana",
  menor: "Menor preço",
  manual: "Manual",
};

const STATUS_REFERENCIA: Record<string, string> = {
  candidate: "Candidata",
  selected: "Na cesta",
  rejected: "Excluída",
  warning: "Atenção",
  manual_review: "Revisão manual",
};

const NATUREZA: Record<string, string> = {
  praticado: "Preço praticado",
  homologado: "Homologado",
  contratado: "Contratado",
  adjudicado: "Adjudicado",
  estimado_origem: "Estimado na origem",
  proposta: "Proposta",
  outro: "Outro",
};

const rotulo = (mapa: Record<string, string>) => (codigo: string | null | undefined) =>
  codigo ? (mapa[codigo] ?? codigo) : "";

export const rotuloEstadoPesquisa = rotulo(ESTADO_PESQUISA);
export const rotuloEstadoItem = rotulo(ESTADO_ITEM);
export const rotuloMetodo = rotulo(METODO);
export const rotuloStatusReferencia = rotulo(STATUS_REFERENCIA);
export const rotuloNatureza = rotulo(NATUREZA);

/** Data ISO (aaaa-mm-dd ou carimbo) para dd/mm/aaaa, sem passar por fuso. */
export function dataCurta(valor: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor ?? "");
  return m ? `${m[3]}/${m[2]}/${m[1]}` : "";
}
