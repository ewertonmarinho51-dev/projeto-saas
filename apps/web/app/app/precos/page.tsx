import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { CaretRight } from "@phosphor-icons/react/dist/ssr";

import { dataCurta, rotuloEstadoPesquisa } from "@/components/precos";
import { cartao } from "@/components/ui";
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
    <div className="grid gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pesquisas de preços</h1>
        <p className="mt-1 text-sm text-secundario">
          Consulta das pesquisas do seu órgão. Coleta e edição da cesta chegam na próxima etapa.
        </p>
      </div>

      {dados.itens.length > 0 ? (
        <ul className="divide-y divide-linha overflow-hidden rounded-[var(--radius-ui)] border border-linha bg-superficie">
          {dados.itens.map((p) => (
            <li key={p.id}>
              <Link
                href={`/app/precos/${p.id}`}
                className="group grid grid-cols-[1fr_auto] items-center gap-4 px-5 py-4 transition-colors hover:bg-canvas"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium">{p.nome}</p>
                  <p className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-secundario">
                    <span className="text-texto">{rotuloEstadoPesquisa(p.estado)}</span>
                    <span>Valor global {p.valor_global?.exibicao ?? "não calculado"}</span>
                    <span>Atualizada em {dataCurta(p.atualizado_em)}</span>
                  </p>
                </div>
                <CaretRight size={16} weight="bold" aria-hidden className="text-secundario" />
              </Link>
            </li>
          ))}
        </ul>
      ) : (
        <p className={`${cartao} px-6 py-10 text-center text-sm text-secundario`}>
          {cursor ? "Não há mais pesquisas." : "Nenhuma pesquisa de preços no seu órgão."}
        </p>
      )}

      <div className="flex gap-4 text-sm">
        {cursor && (
          <Link href="/app/precos" className="text-acento underline-offset-4 hover:underline">
            Voltar ao início da lista
          </Link>
        )}
        {dados.proximo_cursor && (
          <Link
            href={`/app/precos?cursor=${encodeURIComponent(dados.proximo_cursor)}`}
            className="text-acento underline-offset-4 hover:underline"
          >
            Próxima página
          </Link>
        )}
      </div>
    </div>
  );
}
