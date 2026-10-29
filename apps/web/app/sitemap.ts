import type { MetadataRoute } from "next";

import { PAGINAS, SITE_URL } from "@/components/site";

// Lido na requisição, não no build: a origem vem de GOVCONECT_SITE_URL, que é
// do ambiente de execução (a mesma imagem serve produção e homologação).
export const dynamic = "force-dynamic";

/** Só as páginas públicas: a área do sistema (/app) fica fora do mapa e do índice. */
export default function sitemap(): MetadataRoute.Sitemap {
  return PAGINAS.map((p) => ({
    url: `${SITE_URL}${p.caminho === "/" ? "" : p.caminho}`,
    changeFrequency: "monthly",
    priority: p.prioridade,
  }));
}
