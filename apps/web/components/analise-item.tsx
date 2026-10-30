import { Alert, Card, DataTable, PriceDispersion, PriceStats, type DispersionValue } from "@/design-system";
import type { EstatisticasDoItem, GrupoDePrecos, ResumoDaSerie } from "@/lib/api";

const DISPERSAO: Record<ResumoDaSerie["dispersao"], string> = {
  homogenea: "Série homogênea",
  dispersa: "Série dispersa",
  insuficiente: "Poucos preços para medir",
};

const colunas = (grupo: string) => [
  { key: "rotulo", label: grupo },
  { key: "precos", label: "Preços", align: "right" as const },
  { key: "na_cesta", label: "Na cesta", align: "right" as const },
  { key: "menor", label: "Menor", align: "right" as const },
  { key: "mediana", label: "Mediana", align: "right" as const },
  { key: "maior", label: "Maior", align: "right" as const },
  { key: "cv", label: "CV", align: "right" as const },
];

function linhas(grupos: GrupoDePrecos[]) {
  return grupos.map((g) => ({
    id: g.rotulo,
    rotulo: g.rotulo,
    precos: g.resumo.quantidade,
    na_cesta: g.na_cesta,
    menor: g.resumo.menor.exibicao,
    mediana: g.resumo.mediana.exibicao,
    maior: g.resumo.maior.exibicao,
    cv: g.resumo.quantidade > 1 ? g.resumo.coeficiente_variacao.exibicao : "—",
  }));
}

function estado(p: EstatisticasDoItem["pontos"][number]): DispersionValue["state"] {
  if (p.fora_da_faixa.length > 0) return "discrepant";
  if (p.status === "warning") return "attention";
  return p.na_cesta ? "valid" : "excluded";
}

/**
 * Análise da série de um item: números da cesta, dispersão de tudo o que foi
 * coletado e a comparação por fonte e por UF. Toda conta vem da API
 * (`/estatisticas`); aqui só se escolhe onde cada texto aparece.
 */
export function AnaliseDoItem({ dados }: { dados: EstatisticasDoItem }) {
  const { cesta, coletadas } = dados;
  if (!coletadas) {
    return (
      <Card title="Análise da série">
        <p className="gc-help">Nenhuma referência com valor normalizado ainda.</p>
      </Card>
    );
  }
  return (
    <Card title="Análise da série" subtitle="Estatística descreve os preços; a estimativa segue o método do item.">
      <div className="grid gap-5">
        {cesta ? (
          <PriceStats
            items={[
              { label: "Na cesta", value: cesta.quantidade, hint: `de ${coletadas.quantidade} com valor` },
              { label: "Menor", value: cesta.menor.exibicao },
              { label: "Média", value: cesta.media.exibicao },
              { label: "Mediana", value: cesta.mediana.exibicao },
              { label: "Maior", value: cesta.maior.exibicao },
              {
                label: "Coeficiente de variação",
                value: cesta.quantidade > 1 ? cesta.coeficiente_variacao.exibicao : "—",
                hint: DISPERSAO[cesta.dispersao],
                help: `Desvio padrão amostral dividido pela média. Acima de ${dados.limite_dispersao.exibicao}, a série é considerada dispersa.`,
              },
            ]}
          />
        ) : (
          <p className="gc-help">A cesta está vazia: os números abaixo são de todas as coletadas.</p>
        )}

        {cesta?.dispersao === "dispersa" && (
          <Alert variant="warning" title="Série dispersa">
            O coeficiente de variação da cesta é {cesta.coeficiente_variacao.exibicao}, acima de{" "}
            {dados.limite_dispersao.exibicao}. Confira os preços sinalizados antes de concluir o item.
          </Alert>
        )}

        <PriceDispersion
          values={dados.pontos.map((p) => ({
            label: [p.fonte, p.uf].filter(Boolean).join(" · "),
            // Número só para POSICIONAR o ponto; o texto exibido vem pronto.
            value: Number(p.valor.valor),
            display: p.valor.exibicao,
            state: estado(p),
          }))}
          median={cesta ? Number(cesta.mediana.valor) : undefined}
          band={
            cesta?.faixa_usual
              ? [Number(cesta.faixa_usual.minimo.valor), Number(cesta.faixa_usual.maximo.valor)]
              : undefined
          }
          labels={{
            median: cesta?.mediana.exibicao,
            band: cesta?.faixa_usual
              ? [cesta.faixa_usual.minimo.exibicao, cesta.faixa_usual.maximo.exibicao]
              : undefined,
            scale: [coletadas.menor.exibicao, coletadas.maior.exibicao],
          }}
        />

        <section className="grid gap-2" aria-labelledby="analise-por-fonte">
          <h4 id="analise-por-fonte">Comparação por fonte</h4>
          <DataTable compact caption="Preços por fonte" columns={colunas("Fonte")} rows={linhas(dados.por_fonte)} />
        </section>
        <section className="grid gap-2" aria-labelledby="analise-por-uf">
          <h4 id="analise-por-uf">Mapa por UF</h4>
          <DataTable compact caption="Preços por UF" columns={colunas("UF")} rows={linhas(dados.por_uf)} />
        </section>

        {dados.sem_valor > 0 && (
          <p className="gc-help">
            {dados.sem_valor === 1
              ? "1 referência sem valor normalizado ficou fora da conta."
              : `${dados.sem_valor} referências sem valor normalizado ficaram fora da conta.`}
          </p>
        )}
      </div>
    </Card>
  );
}
