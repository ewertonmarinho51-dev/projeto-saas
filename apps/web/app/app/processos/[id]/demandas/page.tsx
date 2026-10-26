import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { ConsolidarDemandas } from "@/components/consolidar-demandas";
import { Alert, Breadcrumbs, PageHead } from "@/design-system";
import { chamarApi, ErroDaApi, type Modulos, type Processo } from "@/lib/api";

export const metadata: Metadata = { title: "Consolidar demandas" };

export default async function PaginaDeDemandas({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/i.test(id)) notFound();

  let processo: Processo;
  let modulos: Modulos;
  try {
    [processo, modulos] = await Promise.all([
      chamarApi<Processo>(`/processos/${id}`).then((r) => r.dados),
      chamarApi<Modulos>("/modulos").then((r) => r.dados),
    ]);
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }
  // Módulo desligado para quem está logado: a tela não existe (o mesmo
  // `modulo_disponivel_aqui` do menu do Streamlit).
  if (!modulos.consolidar_demandas) notFound();

  return (
    <div className="grid gap-6">
      <Breadcrumbs
        items={[
          { label: "Processos", href: "/app/processos" },
          { label: processo.nome_exibido, href: `/app/processos/${id}` },
          { label: "Consolidar demandas" },
        ]}
      />
      <PageHead
        title="Consolidar demandas"
        desc="Junte os pedidos das secretarias numa tabela só, com a conta de cada item conferível, e aplique à planilha do processo."
      />
      <Alert variant="info" compact>
        Aplicar troca a lista de itens do processo pela tabela consolidada. O preço não vem daqui: os valores unitários
        ficam em branco para a pesquisa de preços.
      </Alert>
      <ConsolidarDemandas processo={id} versao={processo.versao} />
    </div>
  );
}
