import { type NextRequest } from "next/server";

import { atualizarSessao } from "@/lib/supabase/proxy";

/**
 * Toda requisição de página passa aqui: CSP com nonce + sessão.
 *
 * CSP com `nonce` por requisição em vez de `unsafe-inline` para script:
 * o Next aplica o nonce aos próprios scripts quando ele chega no cabeçalho
 * da requisição. Estilo fica com `unsafe-inline` — o Next ainda injeta
 * estilo sem nonce, e CSP de estilo protege muito menos que a de script.
 * `connect-src 'self'`: o navegador não fala com o Supabase nem com a
 * API; tudo passa pelo servidor do web.
 */
export async function proxy(request: NextRequest) {
  const nonce = btoa(crypto.randomUUID());
  const dev = process.env.NODE_ENV !== "production";
  const csp = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${dev ? " 'unsafe-eval'" : ""}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    `connect-src 'self'${dev ? " ws:" : ""}`,
    "frame-ancestors 'none'",
    "form-action 'self'",
    "base-uri 'self'",
    "object-src 'none'",
  ].join("; ");

  const cabecalhos = new Headers(request.headers);
  cabecalhos.set("x-nonce", nonce);
  cabecalhos.set("Content-Security-Policy", csp);

  const resposta = await atualizarSessao(request, cabecalhos);
  resposta.headers.set("Content-Security-Policy", csp);
  return resposta;
}

export const config = {
  matcher: [
    // Tudo menos arquivo estático: a sessão e a CSP valem para páginas e ações.
    "/((?!_next/static|_next/image|favicon|logo-govconect|.*\\.(?:png|svg|ico|webp)$).*)",
  ],
};
