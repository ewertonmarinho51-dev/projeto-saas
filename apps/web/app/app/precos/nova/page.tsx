import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { NovaPesquisa } from "@/components/nova-pesquisa";
import { Button, Card, PageHead } from "@/design-system";
import { precosHabilitado } from "@/lib/api";

export const metadata: Metadata = { title: "Nova pesquisa de preços" };

export default function Nova() {
  if (!precosHabilitado()) notFound();
  return (
    <>
      <PageHead
        eyebrow={
          <Button variant="link" size="sm" icon="arrow-left" href="/app/precos" className="justify-self-start">
            Pesquisas de preços
          </Button>
        }
        title="Nova pesquisa de preços"
        desc="Depois de criar, importe a planilha de itens e colete os preços."
      />
      <Card>
        {/* Chave nova a cada renderização: o duplo clique não cria duas. */}
        <NovaPesquisa chave={`web-nova-${crypto.randomUUID()}`} />
      </Card>
    </>
  );
}
