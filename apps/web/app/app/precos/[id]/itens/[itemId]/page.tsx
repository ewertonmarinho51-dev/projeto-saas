import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { dataCurta, naCesta, rotuloEstadoItem, rotuloMetodo } from "@/components/precos";
import { AnaliseDoItem } from "@/components/analise-item";
import { AtoNoItem } from "@/components/ato-item";
import { BuscaDoItem, DesfazerRetirada, EdicaoDoItem, ProgressoDaBusca } from "@/components/gestao-cotacao";
import { situacaoDoItem } from "@/components/situacao";
import { NavegadorDeItens, TriagemDoItem } from "@/components/triagem-item";
import { Alert, Badge, Button, Card, DataList, PageHead, PriceBasket, PriceStats, StatusBadge } from "@/design-system";
import {
  chamarApi,
  ErroDaApi,
  precosHabilitado,
  type AlertaDePreco,
  type EstatisticasDoItem,
  type PesquisaDePrecos,
  type ReferenciaDePreco,
} from "@/lib/api";

export const metadata: Metadata = { title: "Referências do item" };

const UUID = /^[0-9a-f-]{36}$/i;

const AVISOS: Record<string, string> = {
  retirada: "Preço retirado da cesta. Estimativa recalculada.",
  incluida: "Preço incluído na cesta. Estimativa recalculada.",
  desfeita: "Retirada desfeita: o preço voltou à cesta.",
  mantida: "Preço mantido. A decisão ficou registrada.",
};

const IMUTAVEIS = new Set(["applied", "archived"]);

export default async function Referencias({
  params,
  searchParams,
}: {
  params: Promise<{ id: string; itemId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  if (!precosHabilitado()) notFound();
  const { id, itemId } = await params;
  const { cesta, item: atoNoItem, ref, busca } = await searchParams;
  if (!UUID.test(id) || !UUID.test(itemId)) notFound();

  let refs: ReferenciaDePreco[];
  let pesquisa: PesquisaDePrecos;
  let alertas: AlertaDePreco[];
  let analise: EstatisticasDoItem | null;
  try {
    // Duas leituras em paralelo: as referências e o item (revisão e preço
    // atuais). A revisão é a que vai no If-Match de cada botão da cesta.
    [refs, pesquisa, alertas, analise] = await Promise.all([
      chamarApi<ReferenciaDePreco[]>(`/precos/pesquisas/${id}/itens/${itemId}/referencias`).then((r) => r.dados),
      chamarApi<PesquisaDePrecos>(`/precos/pesquisas/${id}`).then((r) => r.dados),
      // Os alertas não derrubam a página: sem eles, a cesta segue igual.
      chamarApi<AlertaDePreco[]>(`/precos/pesquisas/${id}/itens/${itemId}/alertas`)
        .then((r) => r.dados)
        .catch(() => [] as AlertaDePreco[]),
      // A análise também não: sem ela, some só o painel.
      chamarApi<EstatisticasDoItem>(`/precos/pesquisas/${id}/itens/${itemId}/estatisticas`)
        .then((r) => r.dados)
        .catch(() => null),
    ]);
  } catch (e) {
    if (e instanceof ErroDaApi && e.status === 404) notFound();
    throw e;
  }
  const item = pesquisa.itens.find((i) => i.id === itemId);
  if (!item) notFound();
  const editavel = !IMUTAVEIS.has(pesquisa.estado);
  const desfazivel = cesta === "retirada" && typeof ref === "string" && UUID.test(ref) && editavel ? ref : null;
  const aviso =
    desfazivel
      ? undefined
      : atoNoItem === "editado"
        ? "Item salvo."
        : typeof cesta === "string"
      ? AVISOS[cesta]
      : atoNoItem === "concluido"
        ? "Item concluído."
        : atoNoItem === "reaberto"
          ? "Item reaberto para revisão."
          : undefined;

  const escolhidas = refs.filter(naCesta);

  return (
    <>
      <PageHead
        eyebrow={
          <span className="flex flex-wrap items-center gap-2">
            <Button variant="link" size="sm" icon="arrow-left" href={`/app/precos/${id}`}>
              Voltar à pesquisa
            </Button>
            <StatusBadge status={situacaoDoItem(item.estado)} label={rotuloEstadoItem(item.estado)} size="sm" />
          </span>
        }
        title={item.descricao}
        desc="Cada valor com a origem que permite conferi-lo. Só aparece link para portal oficial."
      />

      <Card>
        <DataList
          stacked
          items={[
            { label: "Item", value: `${item.numero} de ${pesquisa.itens.length}`, numeric: true },
            { label: "Quantidade", value: `${item.quantidade?.exibicao ?? "—"} ${item.unidade}`, numeric: true },
            { label: "Método", value: rotuloMetodo(item.metodo) || "Não definido" },
            {
              label: "Preço estimado",
              value: <span data-testid="preco-do-item">{item.preco_estimado?.exibicao ?? "não calculado"}</span>,
              numeric: true,
            },
            { label: "Total do item", value: item.preco_total?.exibicao ?? "—", numeric: true },
          ]}
        />
      </Card>

      {desfazivel && <DesfazerRetirada pesquisa={id} item={itemId} referencia={desfazivel} revisao={item.revisao} />}
      {aviso && <Alert variant="success" title={aviso} />}

      <div className="grid items-start gap-5 xl:grid-cols-[calc(var(--space-16)*4)_minmax(0,1fr)_calc(var(--space-16)*4.75)]">
        <Card title="Itens" flush actions={<Badge size="sm">{pesquisa.itens.length}</Badge>} className="hidden xl:block">
          <div className="px-2 pb-3">
            <NavegadorDeItens pesquisa={id} itens={pesquisa.itens} atual={item.id} />
          </div>
        </Card>

        <div className="grid min-w-0 gap-4">
          <h2>Triagem das referências</h2>
          {typeof busca === "string" && UUID.test(busca) && <ProgressoDaBusca jobId={busca} />}
          <TriagemDoItem pesquisa={id} item={item} referencias={refs} alertas={alertas} editavel={editavel} />
          {analise && <AnaliseDoItem dados={analise} />}
          {editavel && item.estado !== "complete" && (
            // Chave nova a cada renderização: reenviar não põe duas buscas na fila.
            <BuscaDoItem
              pesquisa={id}
              item={item.id}
              termo={item.descricao}
              uf={item.uf ?? ""}
              chave={`web-busca-${crypto.randomUUID()}`}
            />
          )}
          {editavel && <EdicaoDoItem key={item.revisao} pesquisa={id} item={item} />}
        </div>

        <div className="grid gap-4 xl:sticky xl:top-[calc(var(--topbar-height)+var(--space-4))]">
          <Card title="Cesta de preços" subtitle="Referências que entram no cálculo." actions={<Badge variant="brand" size="sm">{escolhidas.length}</Badge>}>
            {escolhidas.length > 0 ? (
              <PriceBasket
                items={escolhidas.map((r) => ({
                  source: r.fonte,
                  detail: [r.orgao, dataCurta(r.data_compra ?? r.coletado_em)].filter(Boolean).join(" · "),
                  value: r.valor_unitario_normalizado?.exibicao ?? r.valor_unitario_original?.exibicao ?? "",
                }))}
                totalLabel={`Estimativa${item.metodo ? ` (${rotuloMetodo(item.metodo).toLowerCase()})` : ""}`}
                total={item.preco_estimado?.exibicao ?? "não calculado"}
              />
            ) : (
              <p className="gc-help">Nenhuma referência na cesta.</p>
            )}
          </Card>
          <PriceStats
            items={[
              {
                label: "Preço estimado",
                value: item.preco_estimado?.exibicao ?? "—",
                highlight: true,
                hint: item.metodo ? `Método: ${rotuloMetodo(item.metodo)}` : "Método não definido",
              },
              {
                label: "Total do item",
                value: item.preco_total?.exibicao ?? "—",
                hint: `${item.quantidade?.exibicao ?? "—"} ${item.unidade}`,
              },
              { label: "Na cesta", value: escolhidas.length, hint: `de ${refs.length} coletadas` },
            ]}
          />
          {/* `key` pelo estado: concluir troca o formulário por reabrir, e um
              componente novo nasce com a ação certa e sem o erro anterior. */}
          <AtoNoItem key={item.estado} pesquisa={id} item={item.id} revisao={item.revisao} estado={item.estado} />
        </div>
      </div>
    </>
  );
}