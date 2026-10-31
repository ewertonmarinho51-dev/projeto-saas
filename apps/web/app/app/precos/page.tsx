import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { dataCurta, rotuloEstadoPesquisa } from "@/components/precos";
import { situacaoDaPesquisa } from "@/components/situacao";
import { Button, Card, EmptyState, Icon, PageHead, StatusBadge } from "@/design-system";
import { chamarApi, ErroDaApi, precosHabilitado, type Pagina, type ResumoPesquisa } from "@/lib/api";

export const metadata: Metadata = { title: "Pesquisas de preços" };

export default async function Pesquisas({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const params = await searchParams;
  const cursor = typeof params.cursor === "string" ? params.cursor : "";
  const consulta = new URLSearchParams({ limit: "20" });
  if (cursor) consulta.set("cursor", cursor);

  let dados: Pagina<ResumoPesquisa>;
  try {
    dados = (await chamarApi<Pagina<ResumoPesquisa>>(`/precos/pesquisas?${consulta}`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  return (
    <>
      <PageHead
        title="Pesquisas de preços"
        desc="As pesquisas do seu órgão, com fonte verificável para cada preço."
        actions={
          <Button icon="plus" href="/app/precos/nova">
            Nova pesquisa
          </Button>
        }
      />

      <Card
        flush
        footer={
          (cursor || dados.proximo_cursor) && (
            <div className="flex flex-wrap justify-between gap-3">
              {cursor ? (
                <Button size="sm" variant="ghost" icon="arrow-left" href="/app/precos">
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
                  href={`/app/precos?cursor=${encodeURIComponent(dados.proximo_cursor)}`}
                >
                  Próxima página
                </Button>
              )}
            </div>
          )
        }
      >
        {dados.itens.length > 0 ? (
          <ul className="divide-y divide-linha">
            {dados.itens.map((p) => (
              <li key={p.id}>
                <Link
                  prefetch={false}
                  href={`/app/precos/${p.id}`}
                  className="group grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-5 gap-y-2 px-5 py-3.5 text-texto no-underline transition-colors hover:bg-[var(--surface-hover)] hover:text-texto md:grid-cols-[minmax(0,1fr)_auto_var(--space-4)]"
                >
                  <span className="grid min-w-0 gap-1">
                    <span className="truncate font-[number:var(--weight-medium)]">{p.nome}</span>
                    <span className="flex flex-wrap gap-x-4 gap-y-1 text-[length:var(--gc-fs-sm)] text-secundario">
                      <span className="gc-num">Valor global {p.valor_global?.exibicao ?? "não calculado"}</span>
                      <span>Atualizada em {dataCurta(p.atualizado_em)}</span>
                    </span>
                  </span>
                  <StatusBadge status={situacaoDaPesquisa(p.estado)} label={rotuloEstadoPesquisa(p.estado)} />
                  <Icon
                    name="caret-right"
                    className="hidden text-[color:var(--text-tertiary)] transition-transform group-hover:translate-x-0.5 md:block"
                  />
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon="currency-circle-dollar"
            title={cursor ? "Não há mais pesquisas." : "Nenhuma pesquisa de preços no seu órgão."}
            description={cursor ? undefined : "Crie uma pesquisa e importe a planilha de itens: o sistema busca referências em fontes oficiais."}
          />
        )}
      </Card>
    </>
  );
}
