import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ConversaDoGovBot } from "@/components/conversa-govbot";
import { PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, govbotHabilitado, type Processo } from "@/lib/api";

export const metadata: Metadata = { title: "GovBot" };

const UUID = /^[0-9a-f-]{36}$/i;

export default async function GovBot({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!govbotHabilitado()) notFound();
  const { processo: id } = await searchParams;

  // O processo do contexto é lido com o token da sessão: fora do acesso é 404,
  // e a API relê de novo a cada pergunta — o id na URL não dá direito a nada.
  let processo: { id: string; rotulo: string } | null = null;
  if (typeof id === "string" && UUID.test(id)) {
    try {
      const p = (await chamarApi<Processo>(`/processos/${id}`)).dados;
      processo = { id: p.id, rotulo: p.nome_exibido || p.objeto || "Processo" };
    } catch (e) {
      if (e instanceof ErroDaApi && e.status === 404) notFound();
      throw e;
    }
  }

  return (
    <>
      <PageHead
        title="GovBot"
        desc="Pergunte sobre o processo e a legislação. Cada resposta indica as fontes da Base de Conhecimento que a sustentam."
      />
      <ConversaDoGovBot processo={processo} />
    </>
  );
}
