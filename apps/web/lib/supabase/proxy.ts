import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

import { opcoesDeCookie } from "./config";

/**
 * Renova a sessão a cada requisição e barra `/app` sem identidade.
 *
 * Segue o padrão da documentação do `@supabase/ssr` para Next 16: nada
 * entre `createServerClient` e `getClaims()`, e a resposta devolvida é a
 * MESMA que recebeu os cookies renovados — trocar o objeto faz o navegador
 * e o servidor discordarem da sessão.
 *
 * Esta é a primeira camada. A segunda é o layout de `/app`, que verifica
 * de novo no servidor; a terceira é a API, que verifica o token sozinha;
 * a quarta é o RLS. Nenhuma confia na anterior.
 */
export async function atualizarSessao(request: NextRequest, cabecalhos: Headers) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const chave = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  const privada = request.nextUrl.pathname === "/app" || request.nextUrl.pathname.startsWith("/app/");

  let resposta = NextResponse.next({ request: { headers: cabecalhos } });
  if (!url || !chave) {
    // Sem Supabase, área privada não abre. Página pública segue.
    return privada ? redirecionarParaEntrar(request) : resposta;
  }

  const supabase = createServerClient(url, chave, {
    cookieOptions: opcoesDeCookie(),
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(paraGravar, cabecalhosDeCache) {
        paraGravar.forEach(({ name, value }) => request.cookies.set(name, value));
        // `cabecalhos` foi copiado antes da renovação. Sem isto, o servidor
        // renderiza com o token vencido e tenta renovar de novo, com um
        // refresh que acabou de ser gasto: a sessão cairia no meio do uso.
        cabecalhos.set("cookie", request.cookies.toString());
        resposta = NextResponse.next({ request: { headers: cabecalhos } });
        paraGravar.forEach(({ name, value, options }) =>
          resposta.cookies.set(name, value, options),
        );
        // Cache-Control/Expires/Pragma que a biblioteca manda aplicar:
        // resposta com Set-Cookie de sessão não pode ir para cache algum.
        Object.entries(cabecalhosDeCache ?? {}).forEach(([k, v]) => resposta.headers.set(k, v));
      },
    },
  });

  const { data } = await supabase.auth.getClaims();

  if (!data?.claims && privada) {
    return redirecionarParaEntrar(request, resposta);
  }
  return resposta;
}

function redirecionarParaEntrar(request: NextRequest, base?: NextResponse) {
  const destino = request.nextUrl.clone();
  destino.pathname = "/entrar";
  destino.search = "";
  destino.searchParams.set("proximo", request.nextUrl.pathname + request.nextUrl.search);
  const redirecionamento = NextResponse.redirect(destino);
  // Leva os cookies que a renovação possa ter limpado (sessão vencida).
  base?.cookies.getAll().forEach((c) => redirecionamento.cookies.set(c));
  redirecionamento.headers.set("Cache-Control", "private, no-store");
  return redirecionamento;
}
