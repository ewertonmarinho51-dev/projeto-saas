import type { Metadata } from "next";
import Link from "next/link";

import { AuthLayout } from "@/design-system";

import { FormularioDeRecuperacao } from "./formulario";

export const metadata: Metadata = { title: "Recuperar acesso" };

export default function Recuperar() {
  return (
    <AuthLayout>
      <div className="gc-auth__title">
        <h1>Recuperar acesso</h1>
        <p className="gc-auth__sub">Enviaremos um link para definir uma nova senha.</p>
      </div>
      <FormularioDeRecuperacao />
      <Link href="/entrar" className="gc-auth__link">
        Voltar para entrar
      </Link>
    </AuthLayout>
  );
}
