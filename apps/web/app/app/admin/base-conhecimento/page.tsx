import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { BaseDeConhecimentoTela } from "@/components/base-conhecimento";
import { PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, type BaseDeConhecimento, type Identidade } from "@/lib/api";

export const metadata: Metadata = { title: "Base de Conhecimento" };

export default async function PaginaDaBaseDeConhecimento() {
  const eu = (await chamarApi<Identidade>("/me")).dados;
  if (eu.papel !== "admin") notFound();

  let base: BaseDeConhecimento;
  try {
    base = (await chamarApi<BaseDeConhecimento>("/admin/base-conhecimento")).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 403) notFound();
    throw e;
  }

  return (
    <div className="grid gap-6">
      <PageHead
        title="Base de Conhecimento"
        desc="O acervo que fundamenta a IA: o que estiver aqui pode ser citado nos documentos deste município."
      />
      <BaseDeConhecimentoTela base={base} />
    </div>
  );
}
