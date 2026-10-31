import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { GestaoDeUsuariosTela } from "@/components/admin-usuarios";
import { PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, minhaIdentidade, type GestaoDeUsuarios } from "@/lib/api";

export const metadata: Metadata = { title: "Usuários" };

export default async function PaginaDeUsuarios() {
  const eu = await minhaIdentidade();
  if (eu.papel !== "admin") notFound();

  let dados: GestaoDeUsuarios;
  try {
    dados = (await chamarApi<GestaoDeUsuarios>("/admin/usuarios")).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 403) notFound();
    throw e;
  }

  return (
    <div className="grid gap-6">
      <PageHead
        title="Usuários"
        desc="Quem acessa o sistema por este município, com qual papel e de qual secretaria."
      />
      <GestaoDeUsuariosTela dados={dados} />
    </div>
  );
}
