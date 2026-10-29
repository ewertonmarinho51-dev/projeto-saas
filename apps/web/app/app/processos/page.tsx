import type { Metadata } from "next";

import { FormularioDeProcesso } from "@/components/form-processo";
import { TabelaDeProcessos } from "@/components/tabela-processos";
import { Button, Card, EmptyState, PageHead } from "@/design-system";
import { chamarApi, type Modulos, type Pagina, type Processo } from "@/lib/api";

import { criarProcesso } from "./acoes";

export const metadata: Metadata = { title: "Processos" };

export default async function Processos({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const params = await searchParams;
  const cursor = typeof params.cursor === "string" ? params.cursor : "";
  const consulta = new URLSearchParams({ limit: "20" });
  if (cursor) consulta.set("cursor", cursor);
  const [{ dados }, modulos] = await Promise.all([
    chamarApi<Pagina<Processo>>(`/processos?${consulta}`),
    // Módulo opcional: falha aqui só esconde o atalho do menu de linha.
    chamarApi<Modulos>("/modulos")
      .then((r) => r.dados)
      .catch((): Modulos => ({ consolidar_demandas: false })),
  ]);

  return (
    <>
      <PageHead
        title="Processos"
        desc="Os processos de contratação do órgão, do mais recente ao mais antigo, com o andamento de cada documento."
        actions={
          <Button icon="plus" href="#novo">
            Novo processo
          </Button>
        }
      />

      <Card
        flush
        footer={
          (cursor || dados.proximo_cursor) && (
            <div className="flex flex-wrap justify-between gap-3">
              {cursor ? (
                <Button size="sm" variant="ghost" icon="arrow-left" href="/app/processos">
                  Voltar ao início da lista
                </Button>
              ) : (
                <span />
              )}
              {dados.proximo_cursor && (
                <Button
                  size="sm"
                  variant="secondary"
                  iconRight="arrow-right"
                  href={`/app/processos?cursor=${encodeURIComponent(dados.proximo_cursor)}`}
                >
                  Próxima página
                </Button>
              )}
            </div>
          )
        }
      >
        {dados.itens.length > 0 ? (
          <TabelaDeProcessos processos={dados.itens} consolidar={modulos.consolidar_demandas} />
        ) : (
          <EmptyState
            title={cursor ? "Não há mais processos." : "Nenhum processo no seu órgão ainda."}
            description={cursor ? undefined : "Comece registrando o órgão e o objeto da contratação, logo abaixo."}
          />
        )}
      </Card>

      <Card
        id="novo"
        title="Novo processo"
        subtitle="O município e a secretaria vêm da sua conta. Os documentos vêm depois."
        divided
        className="scroll-mt-20"
      >
        <div className="max-w-xl">
          <FormularioDeProcesso
            acao={criarProcesso}
            rotuloDoBotao="Criar processo"
            ocultos={{ chave: `web-${crypto.randomUUID()}` }}
          />
        </div>
      </Card>
    </>
  );
}
