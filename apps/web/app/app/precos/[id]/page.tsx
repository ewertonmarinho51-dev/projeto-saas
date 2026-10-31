import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { BotaoDeColeta, ProgressoDaColeta } from "@/components/coleta";
import { PainelDeEmissao, ProgressoDoRelatorio } from "@/components/emissao";
import { AplicarAoProcesso } from "@/components/aplicar-processo";
import { FechamentoDaPesquisa, GestaoDaPesquisa, NovoItem } from "@/components/gestao-cotacao";
import { ImportarPlanilha } from "@/components/importar-planilha";
import { dataCurta, rotuloEstadoItem, rotuloEstadoPesquisa, rotuloMetodo } from "@/components/precos";
import { situacaoDaPesquisa, situacaoDoItem } from "@/components/situacao";
import {
  Alert,
  Badge,
  Button,
  Card,
  DataList,
  EmptyState,
  PageHead,
  StatusBadge,
  Stepper,
  TableContainer,
  type StepItem,
} from "@/design-system";
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
  const { job, relatorio, criada, importada, aplicada, duplicada, arquivada, item_retirado, concluida, revisao } = await searchParams;
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
  // A emissão também não derruba: sem preparo, a seção diz que não deu.
  const [previa, preparo] = await Promise.all([
    p.estado === "completed" || p.estado === "applied"
      ? chamarApi<PreviaDaAplicacao>(`/precos/pesquisas/${id}/aplicacao`).then((r) => r.dados).catch(() => null)
      : null,
    p.itens.length > 0
      ? chamarApi<PreparoDaEmissao>(`/precos/pesquisas/${id}/emissao`).then((r) => r.dados).catch(() => null)
      : null,
  ]);

  const aviso =
    criada === "1"
      ? "Pesquisa criada. Importe a planilha de itens para começar."
      : importada === "1"
        ? "Planilha importada. Os itens novos estão pendentes de coleta."
        : duplicada === "1"
          ? "Pesquisa duplicada: mesmos itens, nenhum preço. A coleta é refeita na nova data-base."
          : arquivada === "1"
            ? "Pesquisa arquivada. Nada foi apagado."
            : item_retirado === "1"
              ? "Item retirado da pesquisa. Ele continua na trilha."
              : concluida === "1"
                ? "Cotação concluída. Agora ela pode ser aplicada ao processo."
                : revisao === "1"
                  ? "Revisão criada: esta é a versão nova, editável. A anterior ficou guardada."
                  : aplicada === "1"
                    ? "Preços aplicados ao processo. Os documentos descartados precisam ser gerados novamente."
                    : null;
  const concluidos = p.itens.filter((i) => i.estado === "complete").length;

  return (
    <>
      <PageHead
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Button variant="link" size="sm" icon="arrow-left" href="/app/precos">
              Pesquisas de preços
            </Button>
            <StatusBadge status={situacaoDaPesquisa(p.estado)} label={rotuloEstadoPesquisa(p.estado)} size="sm" />
            <Badge variant="neutral" size="sm">
              Lei nº 14.133/2021, art. 23
            </Badge>
          </span>
        }
        title={<span data-testid="titulo-pesquisa">{p.nome}</span>}
        desc={p.objeto || undefined}
      />

      <Card>
        <DataList
          stacked
          items={[
            { label: "Itens", value: p.itens.length, numeric: true },
            { label: "Itens concluídos", value: `${concluidos} de ${p.itens.length}`, numeric: true },
            {
              label: "Valor global",
              value: <span data-testid="valor-global">{p.valor_global?.exibicao ?? "Não calculado"}</span>,
              numeric: true,
            },
            { label: "Data-base", value: dataCurta(p.data_base) || "Não informada" },
            { label: "Responsável", value: p.responsavel || "Não informado" },
          ]}
        />
      </Card>

      <Card>
        <Stepper ariaLabel="Etapas da pesquisa de preços" steps={etapas(p.estado, p.itens.length, concluidos)} />
      </Card>

      {aviso && <Alert variant="success" title={aviso} />}
      <GestaoDaPesquisa pesquisa={p.id} editavel={!IMUTAVEIS.has(p.estado)} />
      <FechamentoDaPesquisa
        pesquisa={p.id}
        estado={p.estado}
        itens={p.itens.length}
        faltam={p.itens.length - concluidos}
      />
      {jobId && <ProgressoDaColeta jobId={jobId} />}
      {!IMUTAVEIS.has(p.estado) && (
        // Chave nova a cada renderização: um clique (ou o reenvio do
        // formulário) não põe duas coletas na fila — a API devolve o
        // mesmo job para a mesma chave.
        <BotaoDeColeta pesquisa={p.id} chave={`web-coleta-${crypto.randomUUID()}`} />
      )}

      {!IMUTAVEIS.has(p.estado) && (
        <section aria-labelledby="titulo-importar" className="gc-card">
          <div className="gc-card__header gc-card__header--divided">
            <div className="gc-card__titles">
              <h2 id="titulo-importar" className="gc-card__title">
                Importar itens
              </h2>
              <p className="gc-card__subtitle">A planilha do modelo, conferida antes de gravar.</p>
            </div>
          </div>
          <div className="gc-card__body grid gap-3">
            <ImportarPlanilha pesquisa={p.id} />
            <details className="group border-t border-linha pt-3" data-testid="incluir-item">
              <summary className="cursor-pointer text-[length:var(--gc-fs-sm)] font-[number:var(--weight-medium)] text-acento">
                Ou inclua um item à mão
              </summary>
              <div className="mt-4">
                <NovoItem pesquisa={p.id} />
              </div>
            </details>
          </div>
        </section>
      )}

      <section aria-labelledby="titulo-itens" className="gc-card">
        <div className="gc-card__header">
          <div className="gc-card__titles">
            <h2 id="titulo-itens" className="gc-card__title">
              Itens <Badge size="sm">{p.itens.length}</Badge>
            </h2>
            <p className="gc-card__subtitle">Abra um item para ver as referências, a cesta e a origem de cada preço.</p>
          </div>
        </div>
        <div className="gc-card__body gc-card__body--flush">
          {p.itens.length === 0 ? (
            <EmptyState
              icon="tray"
              title="Esta pesquisa ainda não tem itens."
              description="Importe a planilha acima ou inclua um item à mão."
            />
          ) : (
            // Rolagem horizontal no celular: tabela de preço não se espreme em
            // cartões — a comparação entre linhas é o que importa.
            <TableContainer>
              <table className="gc-table" style={{ minWidth: "calc(var(--space-16) * 14)" }}>
                <caption className="gc-sr-only">Itens da pesquisa com preço estimado</caption>
                <thead>
                  <tr>
                    <th scope="col">Nº</th>
                    <th scope="col">Descrição</th>
                    <th scope="col">Unidade</th>
                    <th scope="col" data-align="right">
                      Quantidade
                    </th>
                    <th scope="col">Método</th>
                    <th scope="col" data-align="right">
                      Preço estimado
                    </th>
                    <th scope="col" data-align="right">
                      Total
                    </th>
                    <th scope="col">Situação</th>
                  </tr>
                </thead>
                <tbody>
                  {p.itens.map((i) => (
                    <tr key={i.id}>
                      <td className="gc-mono text-secundario">{i.numero}</td>
                      <td className="max-w-[calc(var(--space-16)*7)]">
                        <Link
                          href={`/app/precos/${p.id}/itens/${i.id}`}
                          className="font-[number:var(--weight-medium)] text-texto no-underline hover:underline"
                        >
                          {i.descricao}
                        </Link>
                        {i.codigo && (
                          <span className="gc-table__sub gc-mono">
                            {i.tipo_catalogo ?? "Código"} {i.codigo}
                          </span>
                        )}
                      </td>
                      <td>{i.unidade}</td>
                      <td data-align="right" className="gc-num">
                        {i.quantidade?.exibicao ?? ""}
                      </td>
                      <td>{rotuloMetodo(i.metodo)}</td>
                      <td data-align="right" className="gc-num">
                        {i.preco_estimado?.exibicao ?? ""}
                      </td>
                      <td data-align="right" className="gc-num">
                        {i.preco_total?.exibicao ?? ""}
                      </td>
                      <td>
                        <StatusBadge status={situacaoDoItem(i.estado)} label={rotuloEstadoItem(i.estado)} size="sm" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableContainer>
          )}
        </div>
      </section>

      {p.itens.length > 0 && (
        <section aria-labelledby="titulo-emissao" className="gc-card" data-testid="secao-emissao">
          <div className="gc-card__header gc-card__header--divided">
            <div className="gc-card__titles">
              <h2 id="titulo-emissao" className="gc-card__title">
                Relatórios
              </h2>
              {preparo && (
                <p className="gc-card__subtitle">
                  Identificador desta versão do resultado:{" "}
                  <span className="gc-mono">{preparo.identificador.slice(0, 16)}</span>. O mesmo resultado gera sempre o
                  mesmo identificador.
                </p>
              )}
            </div>
          </div>
          <div className="gc-card__body grid gap-3">
            {relatorioId && <ProgressoDoRelatorio jobId={relatorioId} />}
            {preparo ? (
              <PainelDeEmissao pesquisa={p.id} preparo={preparo} chave={`web-rel-${crypto.randomUUID()}`} />
            ) : (
              <Alert variant="neutral" compact>
                Não foi possível preparar a emissão agora. Recarregue a página em instantes.
              </Alert>
            )}
          </div>
        </section>
      )}

      {(p.estado === "completed" || p.estado === "applied") && (
        <section aria-labelledby="titulo-aplicar" className="gc-card" data-testid="secao-aplicar">
          <div className="gc-card__header gc-card__header--divided">
            <div className="gc-card__titles">
              <h2 id="titulo-aplicar" className="gc-card__title">
                Aplicar ao processo
              </h2>
              <p className="gc-card__subtitle">
                O preço estimado passa a ser o valor da contratação, e é ele que vai para o DFD, o ETP, o TR e o edital.
              </p>
            </div>
          </div>
          <div className="gc-card__body">
            {previa ? (
              <AplicarAoProcesso pesquisa={p.id} previa={previa} />
            ) : (
              <Alert variant="neutral" compact>
                Não foi possível montar a prévia agora. Recarregue a página em instantes.
              </Alert>
            )}
          </div>
        </section>
      )}
    </>
  );
}

/**
 * As etapas da referência (Definir itens → Coletar → Triagem → Mapa →
 * Relatório), lidas do estado que a API devolve — indicador, não
 * navegação: cada etapa é uma seção desta página.
 */
function etapas(estado: string, itens: number, concluidos: number): StepItem[] {
  const atual =
    itens === 0 ? 0 : estado === "queued" || estado === "running" ? 1 : concluidos < itens ? 2 : estado === "completed" ? 4 : estado === "applied" ? 5 : 3;
  const nomes = ["Definir itens", "Coletar preços", "Triagem", "Mapa de preços", "Relatório final"];
  return nomes.map((label, i) => ({
    label,
    state: estado === "failed" && i === 1 ? "error" : i < atual ? "done" : i === atual ? "current" : "todo",
    meta: i === 2 && itens > 0 ? `${concluidos} de ${itens} itens` : undefined,
  }));
}