import Link from "next/link";

import { Alert, AuthLayout, Button, buttonClasses, Icon } from "@/design-system";
import { metadados } from "@/components/site";
import { destinoSeguro } from "@/lib/seguranca";
import { supabaseConfigurado } from "@/lib/supabase/config";
import { claimsVerificadas } from "@/lib/supabase/server";

import { sair } from "./acoes";
import { FormularioDeEntrada } from "./formulario";

export const metadata = metadados("/entrar");

const AVISOS: Record<string, string> = {
  saiu: "Sessão encerrada.",
  senha: "Senha alterada. Entre com a nova senha.",
};

const SESSAO_RECUSADA = "Não foi possível confirmar sua sessão. Saia e entre de novo.";

export default async function Entrar({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const proximo = destinoSeguro(params.proximo);
  const sessao = supabaseConfigurado() ? await claimsVerificadas() : null;

  // Já autenticado: a pessoa decide. Redirecionar aqui deixaria quem quer
  // trocar de conta sem caminho, e ela nem veria o que aconteceu.
  if (sessao) {
    return (
      <AuthLayout>
        <div className="gc-auth__title">
          <h1>Você já está conectado</h1>
          <p className="gc-auth__sub">
            Sessão de{" "}
            <span data-testid="sessao-email">{typeof sessao.email === "string" ? sessao.email : "conta sem e-mail"}</span>.
          </p>
        </div>
        {params.sessao && (
          <Alert variant="warning" compact>
            {SESSAO_RECUSADA}
          </Alert>
        )}
        {/* Carga inteira de propósito: `proximo` pode ser o editor, cuja CSP
            só vale em carregamento de documento (ver `proxy.ts`). */}
        <a className={buttonClasses({ size: "lg", block: true })} href={proximo}>
          Continuar no aplicativo
          <Icon name="arrow-right" />
        </a>
        <form action={sair} className="grid">
          <input type="hidden" name="proximo" value={proximo} />
          <Button type="submit" variant="secondary" size="lg" block icon="sign-out">
            Sair / trocar de conta
          </Button>
        </form>
      </AuthLayout>
    );
  }

  const aviso = params.saiu ? AVISOS.saiu : params.senha ? AVISOS.senha : null;

  return (
    <AuthLayout>
      <div className="gc-auth__title">
        <h1>Entrar</h1>
        <p className="gc-auth__sub">Use a conta criada pelo administrador do seu órgão.</p>
      </div>
      {supabaseConfigurado() ? (
        <FormularioDeEntrada proximo={proximo} aviso={aviso} />
      ) : (
        <Alert variant="error" title="Autenticação indisponível neste ambiente." />
      )}
      <p className="gc-auth__legal">
        Ao entrar, você concorda com a <Link href="/privacidade">política de privacidade</Link>.
      </p>
    </AuthLayout>
  );
}
