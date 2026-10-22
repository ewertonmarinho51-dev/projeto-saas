import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowSquareOut } from "@phosphor-icons/react/dist/ssr";

import { dataCurta, rotuloNatureza, rotuloStatusReferencia } from "@/components/precos";
import { cartao } from "@/components/ui";
import { chamarApi, ErroDaApi, precosHabilitado, type ReferenciaDePreco } from "@/lib/api";

export const metadata: Metadata = { title: "Referências do item" };

const UUID = /^[0-9a-f-]{36}$/i;

export default async function Referencias({
  params,
}: {
  params: Promise<{ id: string; itemId: string }>;
}) {
  if (!precosHabilitado()) notFound();
  const { id, itemId } = await params;
  if (!UUID.test(id) || !UUID.test(itemId)) notFound();

  let refs: ReferenciaDePreco[];
  try {
    refs = (await chamarApi<ReferenciaDePreco[]>(`/precos/pesquisas/${id}/itens/${itemId}/referencias`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  return (
    <div className="grid gap-6">
      <Link
        href={`/app/precos/${id}`}
        className="inline-flex items-center gap-2 justify-self-start text-sm text-secundario hover:text-texto"
      >
        <ArrowLeft size={16} weight="bold" aria-hidden />
        Voltar à pesquisa
      </Link>
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Referências de preço</h1>
        <p className="mt-1 text-sm text-secundario">
          Cada valor com a origem que permite conferi-lo. Só aparece link para portal oficial.
        </p>
      </div>

      {refs.length === 0 ? (
        <p className={`${cartao} px-6 py-10 text-center text-sm text-secundario`}>
          Nenhuma referência coletada para este item.
        </p>
      ) : (
        <ul className="grid gap-3">
          {refs.map((r) => (
            <li key={r.id} className={`${cartao} grid gap-3 p-5 sm:grid-cols-[1fr_auto]`} data-testid="referencia">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                  <span className="font-medium">{r.fonte}</span>
                  <span className="text-secundario">{rotuloNatureza(r.natureza_valor)}</span>
                  <span
                    className={`rounded-[var(--radius-ui)] px-2 py-0.5 text-xs ${
                      r.status === "selected" ? "bg-ok-fundo text-ok" : r.status === "rejected" ? "bg-erro-fundo text-erro" : "bg-canvas text-secundario"
                    }`}
                  >
                    {rotuloStatusReferencia(r.status)}
                  </span>
                </p>
                <p className="mt-2 text-sm">{r.descricao_original}</p>
                <p className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-secundario">
                  {r.orgao && <span>{r.orgao}</span>}
                  {(r.municipio || r.uf) && <span>{[r.municipio, r.uf].filter(Boolean).join("/")}</span>}
                  {r.data_compra && <span>Compra em {dataCurta(r.data_compra)}</span>}
                  <span>Coletada em {dataCurta(r.coletado_em)}</span>
                  {r.identificacao && <span className="font-mono">{r.identificacao}</span>}
                </p>
                {r.motivos.length > 0 && (
                  <p className="mt-2 text-xs text-secundario">Observações: {r.motivos.join(", ")}</p>
                )}
                {r.link_contratacao && (
                  <a
                    href={r.link_contratacao}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-3 inline-flex items-center gap-1.5 text-sm text-acento underline-offset-4 hover:text-acento-forte hover:underline"
                  >
                    {r.rotulo_contratacao || "Ver na fonte"}
                    <ArrowSquareOut size={14} weight="bold" aria-hidden />
                  </a>
                )}
              </div>
              <div className="text-right sm:min-w-[10rem]">
                <p className="text-lg font-semibold tabular-nums">
                  {r.valor_unitario_normalizado?.exibicao ?? r.valor_unitario_original?.exibicao ?? ""}
                </p>
                <p className="text-xs text-secundario">por {r.unidade_normalizada ?? r.unidade_original ?? "unidade"}</p>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
