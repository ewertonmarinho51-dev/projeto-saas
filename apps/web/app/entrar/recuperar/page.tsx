import type { Metadata } from "next";
import Link from "next/link";

import { MarcaComNome } from "@/components/marca";

import { FormularioDeRecuperacao } from "./formulario";

export const metadata: Metadata = { title: "Recuperar acesso" };

export default function Recuperar() {
  return (
    <main id="conteudo" className="flex min-h-[100dvh] items-center justify-center bg-superficie px-4 py-12">
      <div className="w-full max-w-sm">
        <MarcaComNome />
        <h1 className="mt-8 text-2xl font-semibold tracking-tight">Recuperar acesso</h1>
        <p className="mt-2 text-sm text-secundario">
          Enviaremos um link para definir uma nova senha.
        </p>
        <div className="mt-8">
          <FormularioDeRecuperacao />
        </div>
        <Link
          href="/entrar"
          className="mt-8 inline-block text-sm text-acento underline-offset-4 hover:text-acento-forte hover:underline"
        >
          Voltar para entrar
        </Link>
      </div>
    </main>
  );
}
