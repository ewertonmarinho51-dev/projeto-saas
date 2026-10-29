import type { MetadataRoute } from "next";

import { SITE_URL } from "@/components/site";

// Lido na requisição, não no build: a origem vem de GOVCONECT_SITE_URL, que é
// do ambiente de execução (a mesma imagem serve produção e homologação).
export const dynamic = "force-dynamic";

/**
 * Buscadores leem o site público; a área autenticada, o retorno do login
 * e a vitrine interna ficam de fora (e já exigem sessão ou dão 404).
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/app", "/app/", "/auth/", "/entrar/recuperar", "/design-system"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
    host: SITE_URL,
  };
}
