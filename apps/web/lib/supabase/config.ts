/**
 * Configuração pública do Supabase.
 *
 * Só a URL do projeto e a chave PUBLICÁVEL — as duas vão ao navegador de
 * qualquer jeito (são públicas por desenho). A chave de servidor nunca
 * passa por aqui: o web não a conhece. `scripts/verificar-bundle.mjs`
 * reprova o build se um formato de chave de servidor aparecer no pacote.
 */
export function configSupabase() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
  const chavePublica = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";
  if (!url || !chavePublica) {
    // Sem configuração não há como verificar sessão: falha fechada.
    throw new Error("Supabase não configurado (NEXT_PUBLIC_SUPABASE_URL / _PUBLISHABLE_KEY).");
  }
  return { url, chavePublica };
}

/** Configurado? Para as páginas públicas decidirem sem lançar. */
export function supabaseConfigurado(): boolean {
  return Boolean(
    process.env.NEXT_PUBLIC_SUPABASE_URL && process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY,
  );
}

/**
 * Cookie da sessão: `Secure` em produção, `SameSite=Lax`, caminho raiz.
 *
 * Não é `HttpOnly`: o `@supabase/ssr` precisa ler o cookie no cliente
 * quando há cliente de navegador. Este app não usa cliente de navegador
 * (login, logout e dados passam pelo servidor), mas a opção é da
 * biblioteca — por isso NÃO se afirma HttpOnly em lugar nenhum.
 */
export function opcoesDeCookie() {
  return {
    path: "/",
    sameSite: "lax" as const,
    secure: process.env.NODE_ENV === "production",
  };
}
