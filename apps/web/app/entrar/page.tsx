import type { Metadata } from "next";
import Link from "next/link";
import { redirect } from "next/navigation";

import { Logo, MarcaComNome } from "@/components/marca";
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
    <main id="conteudo" className="grid min-h-[100dvh] md:grid-cols-[1fr_minmax(0,32rem)]">
      {/* Painel de marca: o único lugar com vidro, e só como moldura. */}
      <section
        aria-label="Gov Conect"
        className="relative hidden overflow-hidden border-r border-linha md:block"
        style={{
          background:
            "radial-gradient(60% 50% at 30% 30%, color-mix(in srgb, var(--color-acento) 14%, transparent), transparent), var(--color-canvas)",
        }}
      >
        <div className="flex h-full flex-col justify-between p-12">
          <MarcaComNome />
          <div className="vidro max-w-md rounded-[var(--radius-ui)] p-8">
            <Logo tamanho={72} />
            <p className="mt-6 text-2xl font-semibold leading-snug tracking-tight">
              Planejamento de contratações com revisão humana e preços de fonte verificável.
            </p>
          </div>
          <p className="text-sm text-secundario">Lei 14.133/2021, fase preparatória.</p>
        </div>
      </section>

      <section className="flex items-center justify-center bg-superficie px-4 py-12 sm:px-10">
        <div className="w-full max-w-sm">
          <div className="md:hidden">
            <MarcaComNome />
          </div>
          <h1 className="mt-8 text-2xl font-semibold tracking-tight md:mt-0">Entrar</h1>
          <p className="mt-2 text-sm text-secundario">
            Use a conta criada pelo administrador do seu órgão.
          </p>
          <div className="mt-8">
            {supabaseConfigurado() ? (
              <FormularioDeEntrada proximo={proximo} aviso={aviso} />
            ) : (
              <p role="alert" className="rounded-[var(--radius-ui)] bg-erro-fundo px-4 py-3 text-sm text-erro">
                Autenticação indisponível neste ambiente.
              </p>
            )}
          </div>
          <p className="mt-10 text-xs text-secundario">
            Ao entrar, você concorda com a{" "}
            <Link href="/privacidade" className="underline underline-offset-4 hover:text-texto">
              política de privacidade
            </Link>
            .
          </p>
        </div>
      </section>
    </main>
  );
}
