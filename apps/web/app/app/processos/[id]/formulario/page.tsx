import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { FormularioMatriz } from "@/components/formulario-matriz";
import { Button, PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, type Formulario, type Processo } from "@/lib/api";

export const metadata: Metadata = { title: "Dados da demanda" };

export default async function PaginaDoFormulario({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const { salvo, demanda } = await searchParams;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();

  let processo: Processo;
  let formulario: Formulario;
  try {
    [processo, formulario] = await Promise.all([
      chamarApi<Processo>(`/processos/${id}`).then((r) => r.dados),
      chamarApi<Formulario>(`/processos/${id}/formulario`).then((r) => r.dados),
    ]);
  } catch (e) {
    // 404 também para processo de outro município: não confirma que existe.
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  return (
    <div className="grid gap-6">
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href={`/app/processos/${id}`} className="justify-self-start">
            {processo.nome_exibido}
          </Button>
        }
        title="Dados da demanda"
        desc="Preencha as informações essenciais para iniciar o planejamento da contratação. Os documentos vêm depois."
      />
      {/* key: depois de salvar, a página volta com a versão nova e o estado da tela recomeça dela. */}
      <FormularioMatriz key={formulario.versao} processo={id} formulario={formulario} aviso={
          salvo === "1"
            ? "Rascunho salvo."
            : typeof demanda === "string" && /^\d+$/.test(demanda)
              ? `Demanda consolidada aplicada: ${demanda} itens na planilha. Preencha os preços e confira os demais dados.`
              : null
        } />
    </div>
  );
}
