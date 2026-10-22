import type { EmailOtpType } from "@supabase/supabase-js";
import { NextResponse, type NextRequest } from "next/server";

import { destinoSeguro } from "@/lib/seguranca";
import { criarClienteServidor } from "@/lib/supabase/server";

/**
 * Retorno do link de e-mail (recuperação de senha).
 *
 * Aceita os dois formatos que o Supabase Auth envia: `code` (PKCE) e
 * `token_hash` + `type`. O destino depois da troca passa por
 * `destinoSeguro` — o link do e-mail também é URL que qualquer um monta.
 */
export async function GET(request: NextRequest) {
  const url = request.nextUrl;
  const proximo = destinoSeguro(url.searchParams.get("proximo"));
  const supabase = await criarClienteServidor();

  const code = url.searchParams.get("code");
  const tokenHash = url.searchParams.get("token_hash");
  const tipo = url.searchParams.get("type") as EmailOtpType | null;

  let ok = false;
  if (code) {
    ok = !(await supabase.auth.exchangeCodeForSession(code)).error;
  } else if (tokenHash && tipo) {
    ok = !(await supabase.auth.verifyOtp({ type: tipo, token_hash: tokenHash })).error;
  }

  // `proximo` já é caminho interno validado; a origem é a da requisição.
  const destino = new URL(ok ? proximo : "/entrar/recuperar?expirado=1", url.origin);
  const resposta = NextResponse.redirect(destino);
  resposta.headers.set("Cache-Control", "private, no-store");
  return resposta;
}
