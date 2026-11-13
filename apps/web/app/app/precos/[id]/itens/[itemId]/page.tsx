import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { dataCurta, naCesta, rotuloEstadoItem, rotuloMetodo } from "@/components/precos";
import { AbasDoItem } from "@/components/abas-do-item";
import { AnaliseDoItem, GraficoDaSerie } from "@/components/analise-item";
import { AtoNoItem } from "@/components/ato-item";
import { CestaDoItem, ConcluirEAvancar, ContagemNaCesta, PrecoConfirmado } from "@/components/cesta-do-item";
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
  const { cesta, item: atoNoItem, ref, busca, aba, termo } = await searchParams;
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
  const marcadas = Object.fromEntries(refs.map((r) => [r.id, naCesta(r)]));

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
              value: <PrecoConfirmado inicial={item.preco_estimado?.exibicao ?? "não calculado"} />,
              numeric: true,
            },
            { label: "Total do item", value: item.preco_total?.exibicao ?? "—", numeric: true },
          ]}
        />
      </Card>

      {desfazivel && <DesfazerRetirada pesquisa={id} item={itemId} referencia={desfazivel} revisao={item.revisao} />}
      {aviso && <Alert variant="success" title={aviso} />}

      {/* A análise pede a largura da página: fica fora da grade de três colunas. */}
      <AbasDoItem
        inicial={aba === "analise" ? "analise" : "triagem"}
        referencias={refs.length}
        analise={
          analise ? (
            <AnaliseDoItem dados={analise} metodo={item.metodo} />
          ) : (
            <Alert variant="neutral" compact>
              Não foi possível montar a análise agora. Recarregue a página em instantes.
            </Alert>
          )
        }
        triagem={
          // Desktop (xl): Itens | busca e triagem | Cesta, as laterais presas
          // ao rolar. Abaixo disso, os três blocos em sequência, na mesma
          // ordem. A lista de itens rola dentro do cartão: com centenas de
          // itens ela não empurra a busca para longe nem estica a página.
          <CestaDoItem key={item.revisao} pesquisa={id} item={item.id} revisao={item.revisao} marcadas={marcadas}>
          <div className="grid items-start gap-5 xl:grid-cols-[calc(var(--space-16)*4)_minmax(0,1fr)_calc(var(--space-16)*4.75)]">
        <Card
          title="Itens"
          flush
          actions={<Badge size="sm">{pesquisa.itens.length}</Badge>}
          className="min-w-0 xl:sticky xl:top-[calc(var(--topbar-height)+var(--space-4))]"
          data-testid="cartao-itens"
        >
          <div className="px-2 pb-3 [--gc-itemnav-max:calc(var(--space-16)*4)] xl:[--gc-itemnav-max:calc(100dvh-var(--topbar-height)-var(--space-16)*2)]">
            <NavegadorDeItens pesquisa={id} itens={pesquisa.itens} atual={item.id} />
          </div>
        </Card>

        <div className="grid min-w-0 gap-4">
          {/* A busca vem PRIMEIRO, como no Banco de Preços: o servidor escolhe
              o termo, pesquisa e só então tria o que voltou. Embaixo da
              triagem ela parecia um passo esquecido. */}
          {editavel && item.estado !== "complete" && (
            // Chave nova a cada renderização: reenviar não põe duas buscas na fila.
            <BuscaDoItem
              pesquisa={id}
              item={item.id}
              termo={typeof termo === "string" && termo.trim() ? termo.trim().slice(0, 300) : item.descricao}
              uf={item.uf ?? ""}
              chave={`web-busca-${crypto.randomUUID()}`}
            />
          )}
          {typeof busca === "string" && UUID.test(busca) && <ProgressoDaBusca jobId={busca} />}
          <h2 id="triagem">Triagem das referências</h2>
          {item.revisao_cv && (
            <Alert
              variant="warning"
              title={
                item.revisao_cv.cv
                  ? `Revisão necessária: coeficiente de variação da série proposta em ${item.revisao_cv.cv} (limite de ${item.revisao_cv.limite})`
                  : "Revisão necessária: coeficiente de variação indisponível"
              }
            >
              <span data-testid="revisao-cv">
                {item.revisao_cv.cv
                  ? `A cotação automática encontrou ${item.revisao_cv.sugeridas} referência(s), mas a série de ${item.revisao_cv.quantidade} preços ficou dispersa demais para entrar na cesta sozinha.`
                  : `A cotação automática encontrou ${item.revisao_cv.sugeridas} referência(s), mas a série proposta tem menos de dois preços válidos.`}{" "}
                Elas estão abaixo como pendentes: confira a origem e inclua na cesta as que representam o item.
                {escolhidas.length === 0 && " Enquanto a cesta estiver vazia, o preço estimado fica pendente."}
              </span>
            </Alert>
          )}
          {analise?.coletadas && (
            <Card title="Dispersão das referências" actions={<Badge variant="warning" caps size="sm">Avaliação preliminar</Badge>}>
              <GraficoDaSerie dados={analise} />
            </Card>
          )}
          <TriagemDoItem pesquisa={id} item={item} referencias={refs} alertas={alertas} editavel={editavel} />
          {editavel && <EdicaoDoItem key={item.revisao} pesquisa={id} item={item} />}
        </div>

        <div className="grid min-w-0 gap-4 xl:sticky xl:top-[calc(var(--topbar-height)+var(--space-4))]">
          <Card
            title="Cesta de preços"
            subtitle="Referências que entram no cálculo."
            actions={<Badge variant="brand" size="sm"><ContagemNaCesta marcadas={marcadas} /></Badge>}
            data-testid="cartao-cesta"
          >
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
                value: <PrecoConfirmado inicial={item.preco_estimado?.exibicao ?? "—"} />,
                highlight: true,
                hint: item.metodo ? `Método: ${rotuloMetodo(item.metodo)}` : "Método não definido",
              },
              {
                label: "Total do item",
                value: item.preco_total?.exibicao ?? "—",
                hint: `${item.quantidade?.exibicao ?? "—"} ${item.unidade}`,
              },
              { label: "Na cesta", value: <ContagemNaCesta marcadas={marcadas} />, hint: `de ${refs.length} coletadas` },
            ]}
          />
          {/* Concluir e seguir para o próximo item a concluir; item concluído
              só se reabre, com motivo. */}
          {editavel && item.estado !== "complete" ? (
            <ConcluirEAvancar
              pesquisa={id}
              item={item.id}
              itens={pesquisa.itens.map((i) => ({ id: i.id, numero: i.numero, estado: i.estado }))}
            />
          ) : (
            <AtoNoItem key={item.estado} pesquisa={id} item={item.id} revisao={item.revisao} estado={item.estado} />
          )}
        </div>
          </div>
          </CestaDoItem>
        }
      />
    </>
  );
}