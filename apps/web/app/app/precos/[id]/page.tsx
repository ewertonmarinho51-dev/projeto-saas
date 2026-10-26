import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeft } from "@phosphor-icons/react/dist/ssr";

import { BotaoDeColeta, ProgressoDaColeta } from "@/components/coleta";
import { PainelDeEmissao, ProgressoDoRelatorio } from "@/components/emissao";
import { AplicarAoProcesso } from "@/components/aplicar-processo";
import { GestaoDaPesquisa, NovoItem } from "@/components/gestao-cotacao";
import { ImportarPlanilha } from "@/components/importar-planilha";
import { dataCurta, rotuloEstadoItem, rotuloEstadoPesquisa, rotuloMetodo } from "@/components/precos";
import { cartao } from "@/components/ui";
import {
  chamarApi,
  ErroDaApi,
  precosHabilitado,
  type PesquisaDePrecos,
  type PreparoDaEmissao,
  type PreviaDaAplicacao,
} from "@/lib/api";

export const metadata: Metadata = { title: "Pesquisa de preços" };

const UUID = /^[0-9a-f-]{36}$/i;

const IMUTAVEIS = new Set(["applied", "archived"]);

export default async function Pesquisa({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const { id } = await params;
  const { job, relatorio, criada, importada, aplicada, duplicada, arquivada, item_retirado } = await searchParams;
  const jobId = typeof job === "string" && UUID.test(job) ? job : null;
  const relatorioId = typeof relatorio === "string" && UUID.test(relatorio) ? relatorio : null;
  if (!UUID.test(id)) notFound();

  let p: PesquisaDePrecos;
  try {
    p = (await chamarApi<PesquisaDePrecos>(`/precos/pesquisas/${id}`)).dados;
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }
  // Aplicar ao processo: a prévia só faz sentido com a pesquisa concluída
  // (ou já aplicada, para dizer isso). Erro na prévia não derruba a página.
  let previa: PreviaDaAplicacao | null = null;
  if (p.estado === "completed" || p.estado === "applied") {
    try {
      previa = (await chamarApi<PreviaDaAplicacao>(`/precos/pesquisas/${id}/aplicacao`)).dados;
    } catch {
      previa = null;
    }
  }
  // A emissão não derruba a página: sem preparo, a seção diz que não deu.
  let preparo: PreparoDaEmissao | null = null;
  if (p.itens.length > 0) {
    try {
      preparo = (await chamarApi<PreparoDaEmissao>(`/precos/pesquisas/${id}/emissao`)).dados;
    } catch {
      preparo = null;
    }
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
        <div className="mt-6 grid gap-3">
          {(criada === "1" || importada === "1" || aplicada === "1" || duplicada === "1" || arquivada === "1" ||
            item_retirado === "1") && (
            <p role="status" className="rounded-[var(--radius-ui)] bg-ok-fundo px-4 py-3 text-sm text-ok">
              {criada === "1"
                ? "Pesquisa criada. Importe a planilha de itens para começar."
                : importada === "1"
                  ? "Planilha importada. Os itens novos estão pendentes de coleta."
                  : duplicada === "1"
                    ? "Pesquisa duplicada: mesmos itens, nenhum preço. A coleta é refeita na nova data-base."
                    : arquivada === "1"
                      ? "Pesquisa arquivada. Nada foi apagado."
                      : item_retirado === "1"
                        ? "Item retirado da pesquisa. Ele continua na trilha."
                        : "Preços aplicados ao processo. Os documentos descartados precisam ser gerados novamente."}
            </p>
          )}
          <GestaoDaPesquisa pesquisa={p.id} editavel={!IMUTAVEIS.has(p.estado)} />
          {jobId && <ProgressoDaColeta jobId={jobId} />}
          {!IMUTAVEIS.has(p.estado) && (
            // Chave nova a cada renderização: um clique (ou o reenvio do
            // formulário) não põe duas coletas na fila — a API devolve o
            // mesmo job para a mesma chave.
            <BotaoDeColeta pesquisa={p.id} chave={`web-coleta-${crypto.randomUUID()}`} />
          )}
        </div>
      </div>

      {!IMUTAVEIS.has(p.estado) && (
        <section aria-labelledby="titulo-importar" className={`${cartao} grid gap-3 p-5`}>
          <h2 id="titulo-importar" className="text-lg font-semibold">
            Importar itens
          </h2>
          <ImportarPlanilha pesquisa={p.id} />
          <details className="group border-t border-linha pt-3" data-testid="incluir-item">
            <summary className="cursor-pointer text-sm font-medium text-acento">Ou inclua um item à mão</summary>
            <div className="mt-4">
              <NovoItem pesquisa={p.id} />
            </div>
          </details>
        </section>
      )}

      <section aria-labelledby="titulo-itens" className="grid gap-3">
        <h2 id="titulo-itens" className="text-lg font-semibold">
          Itens <span className="font-normal text-secundario">({p.itens.length})</span>
        </h2>
        {p.itens.length === 0 ? (
          <p className={`${cartao} px-6 py-10 text-center text-sm text-secundario`}>
            Esta pesquisa ainda não tem itens. Importe a planilha acima.
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

      {p.itens.length > 0 && (
        <section aria-labelledby="titulo-emissao" className="grid gap-3" data-testid="secao-emissao">
          <div>
            <h2 id="titulo-emissao" className="text-lg font-semibold">
              Relatórios
            </h2>
            {preparo && (
              <p className="mt-1 text-sm text-secundario">
                Identificador desta versão do resultado: <span className="font-mono">{preparo.identificador.slice(0, 16)}</span>.
                O mesmo resultado gera sempre o mesmo identificador.
              </p>
            )}
          </div>
          {relatorioId && <ProgressoDoRelatorio jobId={relatorioId} />}
          {preparo ? (
            <PainelDeEmissao pesquisa={p.id} preparo={preparo} chave={`web-rel-${crypto.randomUUID()}`} />
          ) : (
            <p className="text-sm text-secundario">Não foi possível preparar a emissão agora. Recarregue a página em instantes.</p>
          )}
        </section>
      )}

      {(p.estado === "completed" || p.estado === "applied") && (
        <section aria-labelledby="titulo-aplicar" className="grid gap-3" data-testid="secao-aplicar">
          <div>
            <h2 id="titulo-aplicar" className="text-lg font-semibold">
              Aplicar ao processo
            </h2>
            <p className="mt-1 max-w-[65ch] text-sm text-secundario">
              O preço estimado passa a ser o valor da contratação, e é ele que vai para o DFD, o ETP, o TR e o edital.
            </p>
          </div>
          {previa ? (
            <AplicarAoProcesso pesquisa={p.id} previa={previa} />
          ) : (
            <p className="text-sm text-secundario">Não foi possível montar a prévia agora. Recarregue a página em instantes.</p>
          )}
        </section>
      )}
    </div>
  );
}
