import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Alert, AuthLayout } from "@/design-system";
import { destinoSeguro } from "@/lib/seguranca";
import { supabaseConfigurado } from "@/lib/supabase/config";
import { claimsVerificadas } from "@/lib/supabase/server";

import { FormularioDeEntrada } from "./formulario";

export const metadata: Metadata = { title: "Entrar" };

const AVISOS: Record<string, string> = {
  saiu: "Sessão encerrada.",
  senha: "Senha alterada. Entre com a nova senha.",
};

export default async function Entrar({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const proximo = destinoSeguro(params.proximo);

  // Já autenticado: não mostra o formulário de novo.
  if (supabaseConfigurado() && (await claimsVerificadas())) redirect(proximo);

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
