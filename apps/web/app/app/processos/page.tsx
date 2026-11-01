import type { Metadata } from "next";
import { Suspense } from "react";

import { EsqueletoDeLista } from "@/components/esqueletos";
import { FormularioDeProcesso } from "@/components/form-processo";
import { TabelaDeProcessos } from "@/components/tabela-processos";
import { Button, Card, EmptyState, Field, Input, PageHead } from "@/design-system";
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
  // A busca é do BANCO, sobre todos os processos que a pessoa pode ver —
  // nunca um filtro na página já carregada.
  const q = typeof params.q === "string" ? params.q.trim().slice(0, 100) : "";
  const consulta = new URLSearchParams({ limit: "20" });
  if (cursor) consulta.set("cursor", cursor);
  if (q) consulta.set("q", q);

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

      <form role="search" method="get" action="/app/processos" className="flex flex-wrap items-end gap-3">
        <Field label="Buscar processos" htmlFor="busca-processos" className="min-w-0 flex-1 basis-64">
          <Input
            id="busca-processos"
            name="q"
            type="search"
            icon="magnifying-glass"
            defaultValue={q}
            maxLength={100}
            placeholder="Nome, órgão ou objeto"
          />
        </Field>
        <Button type="submit" variant="secondary">
          Buscar
        </Button>
        {q && (
          <Button variant="ghost" href="/app/processos">
            Limpar busca
          </Button>
        )}
      </form>

      <Suspense key={consulta.toString()} fallback={<EsqueletoDeLista />}>
        <ListaDaBusca consulta={consulta.toString()} q={q} cursor={cursor} />
      </Suspense>

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

/** A tabela e a paginação: a leitura do banco, fora do caminho do cabeçalho. */
async function ListaDaBusca({ consulta, q, cursor }: { consulta: string; q: string; cursor: string }) {
  const lista = (extra: Record<string, string> = {}) => {
    const busca = new URLSearchParams({ ...(q ? { q } : {}), ...extra }).toString();
    return busca ? `/app/processos?${busca}` : "/app/processos";
  };
  const [{ dados }, modulos] = await Promise.all([
    chamarApi<Pagina<Processo>>(`/processos?${consulta}`),
    // Módulo opcional: falha aqui só esconde o atalho do menu de linha.
    chamarApi<Modulos>("/modulos")
      .then((r) => r.dados)
      .catch((): Modulos => ({ consolidar_demandas: false })),
  ]);

  return (
    <Card
      flush
      footer={
        (cursor || dados.proximo_cursor) && (
          <div className="flex flex-wrap justify-between gap-3">
            {cursor ? (
              <Button size="sm" variant="ghost" icon="arrow-left" href={lista()}>
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
                href={lista({ cursor: dados.proximo_cursor })}
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
          icon={q ? "magnifying-glass" : undefined}
          title={
            q
              ? `Nenhum processo com “${q}”.`
              : cursor
                ? "Não há mais processos."
                : "Nenhum processo no seu órgão ainda."
          }
          description={
            q
              ? "A busca olha o nome, o órgão e o objeto de todos os processos que você pode ver."
              : cursor
                ? undefined
                : "Comece registrando o órgão e o objeto da contratação, logo abaixo."
          }
        />
      )}
    </Card>
  );
}
