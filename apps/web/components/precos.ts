import type { DesfechoDoLote, ItemDePesquisa } from "@/lib/api";

/**
 * Períodos da busca de preços, como o servidor escolhe num portal de
 * cotação. O teto é 1 ano: a IN 65/2021 (art. 5º, II) admite contratações
 * similares do último ano — a API recusa acima de 365
 * (`execucao.JANELA_MAXIMA_DIAS`). "Último ano" é o padrão.
 */
export const JANELA_PADRAO_DIAS = 365;
export const JANELAS_DA_BUSCA: { value: string; label: string }[] = [
  { value: "30", label: "Últimos 30 dias" },
  { value: "60", label: "Últimos 60 dias" },
  { value: "90", label: "Últimos 90 dias" },
  { value: "120", label: "Últimos 120 dias" },
  { value: "180", label: "Últimos 180 dias" },
  { value: String(JANELA_PADRAO_DIAS), label: "Último ano" },
];

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

/** O que já está na cesta, pela regra do domínio: selecionada ou mantida com atenção. */
export const naCesta = (r: { status: string }) => r.status === "selected" || r.status === "warning";

/**
 * Cor do rótulo de equivalência (`src/precos/equivalencia.py`): só o que
 * entra sozinho na cesta é verde; similar pede o servidor; incompatível é erro.
 */
export function varianteDaEquivalencia(rotulo: string | undefined): "success" | "warning" | "error" | "neutral" {
  if (rotulo === "mesmo item" || rotulo === "equivalente comprovado") return "success";
  if (rotulo === "similar para revisão") return "warning";
  if (rotulo === "incompatível") return "error";
  return "neutral";
}

/** Rótulos do desfecho do lote (`cotacoes.DESFECHOS`), na ordem do resumo. */
export const DESFECHOS_DO_LOTE: [DesfechoDoLote, string][] = [
  ["pronto_para_revisao", "Pronto para revisão"],
  ["revisar_similaridade", "Revisar similaridade"],
  ["revisar_cv", "Revisar CV"],
  ["amostra_insuficiente", "Amostra insuficiente"],
  ["sem_referencia_compativel", "Sem referência compatível"],
  ["consulta_parcial", "Consulta parcial"],
  ["falha_tecnica", "Falha técnica"],
  ["ja_resolvido", "Já resolvido"],
];

/**
 * Ordem da lista: primeiro o que exige atenção do servidor (falha, sem
 * referência, amostra curta, CV, similaridade), depois as propostas aptas,
 * por último o concluído. Dentro de cada grupo, a ordem da planilha.
 */
const PESO_DA_PENDENCIA: Record<string, number> = {
  falha_tecnica: 0,
  consulta_parcial: 1,
  sem_referencia_compativel: 2,
  amostra_insuficiente: 3,
  revisar_cv: 4,
  revisar_similaridade: 5,
};

export function prioridadeDoItem(
  item: Pick<ItemDePesquisa, "estado" | "preco_estimado" | "revisao_cv" | "pendencia" | "apta" | "numero">,
): [number, number, number] {
  if (item.estado === "complete") return [3, 0, item.numero];
  if (item.apta) return [2, 0, item.numero];
  if (itemPendente(item)) return [0, PESO_DA_PENDENCIA[item.pendencia ?? ""] ?? 6, item.numero];
  return [1, 0, item.numero];
}

export function ordenarPorAtencao<T extends Parameters<typeof prioridadeDoItem>[0]>(itens: T[]): T[] {
  return [...itens].sort((a, b) => {
    const [x, y] = [prioridadeDoItem(a), prioridadeDoItem(b)];
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2];
  });
}

/** Rótulo curto da pendência do item na lista ("" quando não há). */
export function rotuloDaPendencia(item: Pick<ItemDePesquisa, "estado" | "pendencia" | "apta">): string {
  if (item.estado === "complete") return "";
  if (item.apta) return "Proposta apta";
  return DESFECHOS_DO_LOTE.find(([chave]) => chave === item.pendencia)?.[1] ?? "";
}

/**
 * Pendente = ainda sem preço proposto defensável: o mesmo critério do
 * "Reprocessar pendentes" no servidor (`execucao.precisa_de_reprocesso`).
 * Concluído nunca é pendente.
 */
export function itemPendente(item: Pick<ItemDePesquisa, "estado" | "preco_estimado" | "revisao_cv">): boolean {
  if (item.estado === "complete") return false;
  if (["pending", "searching", "matching", "error", "incomplete"].includes(item.estado)) return true;
  return !item.preco_estimado || !!item.revisao_cv;
}

/** O comparativo depois do rótulo ("conferido: …; diverge: …"), ou "". */
export function comparativoDaEquivalencia(detalhe: string | undefined): string {
  const partes = (detalhe ?? "").split(" — ");
  return partes.length > 1 ? partes.slice(1).join(" · ") : "";
}
