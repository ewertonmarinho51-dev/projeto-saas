import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import { dataCurta, rotuloEstadoItem, rotuloEstadoPesquisa, rotuloMetodo } from "@/components/precos";
import { cartao } from "@/components/ui";
import { chamarApi, ErroDaApi, precosHabilitado, type PesquisaDePrecos } from "@/lib/api";

export const metadata: Metadata = { title: "Pesquisa de preços" };

const UUID = /^[0-9a-f-]{36}$/i;

export default async function Pesquisa({ params }: { params: Promise<{ id: string }> }) {
  if (!precosHabilitado()) notFound();
  const { id } = await params;
  if (!UUID.test(id)) notFound();

  let p: PesquisaDePrecos;
  try {
    p = (await chamarApi<PesquisaDePrecos>(`/precos/pesquisas/${id}`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }

  return (
    <div className="grid gap-8">
      <Link
        href="/app/precos"
        className="inline-flex items-center gap-2 justify-self-start text-sm text-secundario hover:text-texto"
      >
        <ArrowLeft size={16} weight="bold" aria-hidden />
        Pesquisas de preços
      </Link>

      <div>
        <h1 className="text-2xl font-semibold tracking-tight" data-testid="titulo-pesquisa">
          {p.nome}
        </h1>
        {p.objeto && <p className="mt-2 max-w-[70ch] text-secundario">{p.objeto}</p>}
        <dl className="mt-5 grid gap-x-8 gap-y-3 text-sm sm:grid-cols-4">
          <div>
            <dt className="text-secundario">Situação</dt>
            <dd className="font-medium">{rotuloEstadoPesquisa(p.estado)}</dd>
          </div>
          <div>
            <dt className="text-secundario">Valor global</dt>
            <dd className="font-medium tabular-nums" data-testid="valor-global">
              {p.valor_global?.exibicao ?? "Não calculado"}
            </dd>
          </div>
          <div>
            <dt className="text-secundario">Data-base</dt>
            <dd className="font-medium">{dataCurta(p.data_base) || "Não informada"}</dd>
          </div>
          <div>
            <dt className="text-secundario">Responsável</dt>
            <dd className="font-medium">{p.responsavel || "Não informado"}</dd>
          </div>
        </dl>
      </div>

      <section aria-labelledby="titulo-itens" className="grid gap-3">
        <h2 id="titulo-itens" className="text-lg font-semibold">
          Itens <span className="font-normal text-secundario">({p.itens.length})</span>
        </h2>
        {p.itens.length === 0 ? (
          <p className={`${cartao} px-6 py-10 text-center text-sm text-secundario`}>
            Esta pesquisa ainda não tem itens.
          </p>
        ) : (
          // Rolagem horizontal no celular: tabela de preço não se espreme em
          // cartões — a comparação entre linhas é o que importa.
          <div className={`${cartao} overflow-x-auto`}>
            <table className="w-full min-w-[56rem] text-sm">
              <caption className="sr-only">Itens da pesquisa com preço estimado</caption>
              <thead className="border-b border-linha text-left text-secundario">
                <tr>
                  <th scope="col" className="px-4 py-3 font-medium">Nº</th>
                  <th scope="col" className="px-4 py-3 font-medium">Descrição</th>
                  <th scope="col" className="px-4 py-3 font-medium">Unidade</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Quantidade</th>
                  <th scope="col" className="px-4 py-3 font-medium">Método</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Preço estimado</th>
                  <th scope="col" className="px-4 py-3 text-right font-medium">Total</th>
                  <th scope="col" className="px-4 py-3 font-medium">Situação</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-linha">
                {p.itens.map((i) => (
                  <tr key={i.id} className="transition-colors hover:bg-canvas">
                    <td className="px-4 py-3 font-mono text-secundario">{i.numero}</td>
                    <td className="max-w-[28rem] px-4 py-3">
                      <Link
                        href={`/app/precos/${p.id}/itens/${i.id}`}
                        className="text-texto underline-offset-4 hover:text-acento hover:underline"
                      >
                        {i.descricao}
                      </Link>
                      {i.codigo && (
                        <span className="mt-0.5 block font-mono text-xs text-secundario">
                          {i.tipo_catalogo ?? "Código"} {i.codigo}
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">{i.unidade}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{i.quantidade?.exibicao ?? ""}</td>
                    <td className="px-4 py-3">{rotuloMetodo(i.metodo)}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{i.preco_estimado?.exibicao ?? ""}</td>
                    <td className="px-4 py-3 text-right tabular-nums">{i.preco_total?.exibicao ?? ""}</td>
                    <td className="px-4 py-3 text-secundario">{rotuloEstadoItem(i.estado)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
