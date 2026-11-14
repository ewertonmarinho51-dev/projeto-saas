/**
 * Filtros e página da triagem na URL (pacote de 14/11/2026, RF-06/RF-07):
 * o estado mora na URL — voltar, recarregar e compartilhar mantêm a
 * página e os filtros. A URL é validada aqui; o que não passa é ignorado
 * (a API valida de novo e devolve 422).
 */

export const TAMANHOS = [10, 20, 50] as const;
export type Tamanho = (typeof TAMANHOS)[number];
export const SITUACOES = ["cesta", "fora", "atencao"] as const;
export const ORDENS = ["valor_asc", "valor_desc", "data_desc"] as const;

export type FiltrosDaTriagem = {
  pagina: number;
  por_pagina: Tamanho;
  situacao?: (typeof SITUACOES)[number];
  fonte?: string;
  uf?: string;
  preco_min?: string;
  preco_max?: string;
  desde?: string;
  ate?: string;
  q?: string;
  ordem: (typeof ORDENS)[number];
  modo: "lista" | "mapa";
};

type Busca = Record<string, string | string[] | undefined>;

const um = (v: string | string[] | undefined) => (Array.isArray(v) ? v[0] : v)?.trim() || undefined;
const DATA = /^\d{4}-\d{2}-\d{2}$/;
const PRECO = /^\d{1,12}([.,]\d{1,4})?$/;

export function lerFiltros(busca: Busca): FiltrosDaTriagem {
  const pagina = Number(um(busca.pagina));
  const tamanho = Number(um(busca.por_pagina));
  const situacao = um(busca.situacao);
  const ordem = um(busca.ordem);
  const fonte = um(busca.fonte);
  const uf = um(busca.uf)?.toUpperCase();
  const preco = (v?: string) => (v && PRECO.test(v) ? v.replace(",", ".") : undefined);
  const data = (v?: string) => (v && DATA.test(v) ? v : undefined);
  return {
    pagina: Number.isInteger(pagina) && pagina >= 1 && pagina <= 100_000 ? pagina : 1,
    por_pagina: (TAMANHOS as readonly number[]).includes(tamanho) ? (tamanho as Tamanho) : 20,
    situacao: (SITUACOES as readonly string[]).includes(situacao ?? "") ? (situacao as FiltrosDaTriagem["situacao"]) : undefined,
    fonte: fonte && /^[A-Za-z0-9_.-]{1,60}$/.test(fonte) ? fonte : undefined,
    uf: uf && /^[A-Z]{2}$/.test(uf) ? uf : undefined,
    preco_min: preco(um(busca.preco_min)),
    preco_max: preco(um(busca.preco_max)),
    desde: data(um(busca.desde)),
    ate: data(um(busca.ate)),
    q: um(busca.q)?.slice(0, 120),
    ordem: (ORDENS as readonly string[]).includes(ordem ?? "") ? (ordem as FiltrosDaTriagem["ordem"]) : "valor_asc",
    modo: um(busca.modo) === "mapa" ? "mapa" : "lista",
  };
}

const CHAVES_DA_API = ["pagina", "por_pagina", "situacao", "fonte", "uf", "preco_min", "preco_max", "desde", "ate", "q", "ordem"] as const;

/** A consulta da API (sempre paginada). */
export function paraApi(f: FiltrosDaTriagem): string {
  const p = new URLSearchParams();
  for (const k of CHAVES_DA_API) {
    const v = f[k];
    if (v !== undefined && v !== "") p.set(k, String(v));
  }
  return p.toString();
}

/** Algum filtro além de página/tamanho/ordem/modo? */
export function temFiltro(f: FiltrosDaTriagem): boolean {
  return Boolean(f.situacao || f.fonte || f.uf || f.preco_min || f.preco_max || f.desde || f.ate || f.q);
}

/**
 * O link da página com mudanças. Valor padrão some da URL; mudar filtro ou
 * tamanho volta à página 1 (a página 7 de outro conjunto não existe).
 */
export function paraUrl(base: string, f: FiltrosDaTriagem, mudancas: Partial<FiltrosDaTriagem> & { aba?: string } = {}): string {
  const voltaAPrimeira = Object.keys(mudancas).some((k) => k !== "pagina" && k !== "modo" && k !== "aba");
  const novo: FiltrosDaTriagem = { ...f, ...(voltaAPrimeira ? { pagina: 1 } : {}), ...mudancas };
  const p = new URLSearchParams();
  if (mudancas.aba) p.set("aba", mudancas.aba);
  for (const k of CHAVES_DA_API) {
    const v = novo[k];
    if (v === undefined || v === "") continue;
    if ((k === "pagina" && v === 1) || (k === "por_pagina" && v === 20) || (k === "ordem" && v === "valor_asc")) continue;
    p.set(k, String(v));
  }
  if (novo.modo === "mapa") p.set("modo", "mapa");
  const q = p.toString();
  return q ? `${base}?${q}` : base;
}
