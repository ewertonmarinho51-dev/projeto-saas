import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft, ArrowSquareOut } from "@phosphor-icons/react/dist/ssr";

import { dataCurta, rotuloNatureza, rotuloStatusReferencia } from "@/components/precos";
import { AcaoNaCesta } from "@/components/acao-cesta";
import { AtoNoItem } from "@/components/ato-item";
import { cartao } from "@/components/ui";
import {
  chamarApi,
  ErroDaApi,
  precosHabilitado,
  type PesquisaDePrecos,
  type ReferenciaDePreco,
} from "@/lib/api";

export const metadata: Metadata = { title: "Referências do item" };

const UUID = /^[0-9a-f-]{36}$/i;

const AVISOS: Record<string, string> = {
  retirada: "Preço retirado da cesta. Estimativa recalculada.",
  incluida: "Preço incluído na cesta. Estimativa recalculada.",
};

export default async function Referencias({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; itemId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const { id, itemId } = await params;
  const { cesta, item: atoNoItem } = await searchParams;
  if (!UUID.test(id) || !UUID.test(itemId)) notFound();

  let refs: ReferenciaDePreco[];
  let pesquisa: PesquisaDePrecos;
  try {
    // Duas leituras em paralelo: as referências e o item (revisão e preço
    // atuais). A revisão é a que vai no If-Match de cada botão da cesta.
    [refs, pesquisa] = await Promise.all([
      chamarApi<ReferenciaDePreco[]>(`/precos/pesquisas/${id}/itens/${itemId}/referencias`).then((r) => r.dados),
      chamarApi<PesquisaDePrecos>(`/precos/pesquisas/${id}`).then((r) => r.dados),
    ]);
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }
  const item = pesquisa.itens.find((i) => i.id === itemId);
  if (!item) notFound();
  const aviso =
    typeof cesta === "string"
      ? AVISOS[cesta]
      : atoNoItem === "concluido"
        ? "Item concluído."
        : atoNoItem === "reaberto"
          ? "Item reaberto para revisão."
          : undefined;

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
        <h1 className="text-2xl font-semibold tracking-tight">{item.descricao}</h1>
        <p className="mt-1 text-sm text-secundario">
          Cada valor com a origem que permite conferi-lo. Só aparece link para portal oficial.
        </p>
        <p className="mt-3 text-sm">
          Preço estimado{" "}
          <span className="font-semibold tabular-nums" data-testid="preco-do-item">
            {item.preco_estimado?.exibicao ?? "não calculado"}
          </span>
        </p>
      </div>

      {aviso && (
        <p role="status" className="rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok">
          {aviso}
        </p>
      )}

      {/* `key` pelo estado: concluir troca o formulário por reabrir, e um
          componente novo nasce com a ação certa e sem o erro anterior. */}
      <AtoNoItem key={item.estado} pesquisa={id} item={item.id} revisao={item.revisao} estado={item.estado} />

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
                <div className="mt-3 flex justify-end">
                  {item.estado === "complete" ? (
                    <p className="text-xs text-secundario">Item concluído: reabra para alterar a cesta.</p>
                  ) : (
                  <AcaoNaCesta
                    pesquisa={id}
                    item={itemId}
                    referencia={r.id}
                    revisao={item.revisao}
                    naCesta={r.status === "selected" || r.status === "warning"}
                  />
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
