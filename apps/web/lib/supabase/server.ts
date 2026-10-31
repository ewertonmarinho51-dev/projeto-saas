import "server-only";

import { createServerClient } from "@supabase/ssr";
import { cookies } from "next/headers";
import { cache } from "react";

import { configSupabase, opcoesDeCookie } from "./config";

/**
 * Cliente Supabase para Server Components, Server Actions e Route
 * Handlers. Sem cache entre requisições: cada uma traz os cookies da
 * própria sessão.
 */
export async function criarClienteServidor() {
  const cookieStore = await cookies();
  const { url, chavePublica } = configSupabase();
  return createServerClient(url, chavePublica, {
    cookieOptions: opcoesDeCookie(),
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(paraGravar) {
        try {
          paraGravar.forEach(({ name, value, options }) =>
            cookieStore.set(name, value, options),
          );
        } catch {
          // Server Component não grava cookie; o proxy renova a sessão.
        }
      },
    },
  });
}

/**
 * Identidade VERIFICADA da requisição, ou null.
 *
 * `getClaims()` confere a assinatura do JWT pelo JWKS do projeto. Nunca
 * `getSession().user`: aquilo é o que está no cookie, e cookie o
 * navegador escreve.
 *
 * `cache` do React dura uma renderização, nunca passa para outra requisição:
 * layout e página conferem a mesma assinatura uma vez só. Fora de
 * renderização (Server Action, rota) não memoriza nada.
 */
export const claimsVerificadas = cache(async () => {
  const supabase = await criarClienteServidor();
  const { data, error } = await supabase.auth.getClaims();
  if (error || !data?.claims) return null;
  return data.claims;
});
