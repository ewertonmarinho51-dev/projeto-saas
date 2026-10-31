import { NextRequest } from "next/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { atualizarSessao } from "../lib/supabase/proxy";

/**
 * Renovação do token no proxy. A biblioteca é falsa aqui: o que se prova é
 * o que `atualizarSessao` faz com o resultado dela. Sessão real é o
 * `e2e/sessao.spec.ts`.
 */
const biblioteca = vi.hoisted(() => ({
  renovar: null as null | Array<{ name: string; value: string; options: Record<string, unknown> }>,
  claims: { sub: "conta" } as { sub: string } | null,
}));

vi.mock("@supabase/ssr", () => ({
  createServerClient: (
    _url: string,
    _chave: string,
    opcoes: { cookies: { setAll: (c: unknown[], h: Record<string, string>) => void } },
  ) => ({
    auth: {
      getClaims: async () => {
        if (biblioteca.renovar) opcoes.cookies.setAll(biblioteca.renovar, { "Cache-Control": "private, no-store" });
        return { data: biblioteca.claims ? { claims: biblioteca.claims } : null };
      },
    },
  }),
}));

function pedido(caminho: string, cookie = "sb-x-auth-token=vencido") {
  return new NextRequest(`https://govconect.test${caminho}`, { headers: { cookie } });
}

beforeEach(() => {
  process.env.NEXT_PUBLIC_SUPABASE_URL = "https://exemplo.supabase.invalid";
  process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "chave-publicavel-de-teste";
  biblioteca.renovar = null;
  biblioteca.claims = { sub: "conta" };
});

describe("atualizarSessao", () => {
  it("o token renovado chega ao servidor na mesma requisição, não só ao navegador", async () => {
    biblioteca.renovar = [{ name: "sb-x-auth-token", value: "renovado", options: { path: "/" } }];
    const entrada = pedido("/app/processos");
    const resposta = await atualizarSessao(entrada, new Headers(entrada.headers));

    expect(resposta.cookies.get("sb-x-auth-token")?.value).toBe("renovado");
    const repassado = resposta.headers.get("x-middleware-request-cookie") ?? "";
    expect(repassado).toContain("sb-x-auth-token=renovado");
    expect(repassado).not.toContain("vencido");
  });

  it("resposta com cookie renovado não vai para cache", async () => {
    biblioteca.renovar = [{ name: "sb-x-auth-token", value: "renovado", options: {} }];
    const entrada = pedido("/app");
    const resposta = await atualizarSessao(entrada, new Headers(entrada.headers));
    expect(resposta.headers.get("cache-control")).toContain("no-store");
  });

  it("sem identidade, /app vai ao login e leva o destino", async () => {
    biblioteca.claims = null;
    const entrada = pedido("/app/processos?q=obra");
    const resposta = await atualizarSessao(entrada, new Headers(entrada.headers));
    expect(resposta.status).toBe(307);
    const destino = new URL(resposta.headers.get("location") ?? "");
    expect(destino.pathname).toBe("/entrar");
    expect(destino.searchParams.get("proximo")).toBe("/app/processos?q=obra");
  });

  it("página pública não redireciona ninguém: nem sem sessão, nem com", async () => {
    for (const claims of [null, { sub: "conta" }]) {
      biblioteca.claims = claims;
      for (const caminho of ["/", "/entrar"]) {
        const entrada = pedido(caminho);
        const resposta = await atualizarSessao(entrada, new Headers(entrada.headers));
        expect(resposta.headers.get("location")).toBeNull();
      }
    }
  });
});
