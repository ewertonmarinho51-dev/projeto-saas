import type { MetadataRoute } from "next";

import { PAGINAS, SITE_URL } from "@/components/site";

/** Só as páginas públicas: a área do sistema (/app) fica fora do mapa e do índice. */
export default function sitemap(): MetadataRoute.Sitemap {
  return PAGINAS.map((p) => ({
    url: `${SITE_URL}${p.caminho === "/" ? "" : p.caminho}`,
    changeFrequency: "monthly",
    priority: p.prioridade,
  }));
}
