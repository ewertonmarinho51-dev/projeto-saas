import type { Metadata } from "next";

import { cartao } from "@/components/ui";

import { FormularioDeSenha } from "./formulario";

export const metadata: Metadata = { title: "Senha" };

export default function Senha() {
  return (
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Senha</h1>
        <p className="mt-1 text-sm text-secundario">
          Ao trocar a senha, as outras sessões abertas são encerradas.
        </p>
      </div>
      <section className={`${cartao} max-w-xl p-6 sm:p-8`}>
        <FormularioDeSenha />
      </section>
    </div>
  );
}
