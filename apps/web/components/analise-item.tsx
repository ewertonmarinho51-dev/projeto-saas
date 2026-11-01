import { Accordion, Alert, Card, DataTable, KpiCard, PriceCompare, PriceDispersion, type DispersionValue } from "@/design-system";
import { rotuloMetodo } from "@/components/precos";
import type { EscalaDoGrafico, EstatisticasDoItem, GrupoDePrecos, ResumoDaSerie } from "@/lib/api";

type Ponto = EstatisticasDoItem["pontos"][number];

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

const COLUNAS_DOS_PRECOS = [
  { key: "origem", label: "Origem" },
  { key: "valor", label: "Preço unitário", align: "right" as const },
  { key: "mediana", label: "Sobre a mediana", align: "right" as const },
  { key: "situacao", label: "Situação" },
];

const SITUACAO: Record<NonNullable<DispersionValue["state"]>, string> = {
  valid: "Na cesta",
  attention: "Exige conferência",
  discrepant: "Discrepante",
  excluded: "Fora do cálculo",
};

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

function estado(p: Ponto): DispersionValue["state"] {
  if (p.fora_da_faixa.length > 0) return "discrepant";
  if (p.status === "warning") return "attention";
  return p.na_cesta ? "valid" : "excluded";
}

const origem = (p: Ponto) => [p.fonte, p.uf].filter(Boolean).join(" · ");

function eixo(escala: EscalaDoGrafico) {
  // Número só para POSICIONAR; o texto de cada marca vem pronto.
  return {
    min: Number(escala.minimo.valor),
    max: Number(escala.maximo.valor),
    ticks: escala.marcas.map((m) => ({ value: Number(m.valor), label: m.exibicao })),
  };
}

function valores(pontos: Ponto[]): DispersionValue[] {
  return pontos.map((p) => ({
    label: origem(p),
    value: Number(p.valor.valor),
    display: p.valor.exibicao,
    state: estado(p),
    extreme: p.extremo === "menor" ? "low" : p.extremo === "maior" ? "high" : undefined,
    note: p.sobre_a_mediana ? `${p.sobre_a_mediana.exibicao} sobre a mediana` : undefined,
  }));
}

function ponta(pontos: Ponto[], qual: Ponto["extremo"], reserva: string | undefined): string {
  const achados = pontos.filter((p) => p.extremo === qual);
  if (achados.length === 0) return reserva ?? "—";
  const [p] = achados;
  const outros = achados.length > 1 ? ` e mais ${achados.length - 1}` : "";
  return `${p.valor.exibicao} · ${origem(p)}${outros}`;
}

/** O gráfico principal: eixo linear inteiro, com média, mediana e extremos nomeados. */
export function GraficoDaSerie({ dados }: { dados: EstatisticasDoItem }) {
  const { cesta, coletadas } = dados;
  return (
    <PriceDispersion
      values={valores(dados.pontos)}
      median={cesta ? Number(cesta.mediana.valor) : undefined}
      mean={cesta ? Number(cesta.media.valor) : undefined}
      band={
        cesta?.faixa_usual
          ? [Number(cesta.faixa_usual.minimo.valor), Number(cesta.faixa_usual.maximo.valor)]
          : undefined
      }
      scale={dados.escala ? eixo(dados.escala) : undefined}
      labels={{
        median: cesta?.mediana.exibicao,
        mean: cesta?.media.exibicao,
        band: cesta?.faixa_usual
          ? [cesta.faixa_usual.minimo.exibicao, cesta.faixa_usual.maximo.exibicao]
          : undefined,
        scale: [
          ponta(dados.pontos, "menor", coletadas?.menor.exibicao),
          ponta(dados.pontos, "maior", coletadas?.maior.exibicao),
        ],
      }}
    />
  );
}

function DetalheDaFaixaCentral({ dados }: { dados: EstatisticasDoItem }) {
  const { recorte, cesta } = dados;
  if (!recorte || !cesta) return null;
  const escala = eixo(recorte.escala);
  const dentro = dados.pontos.filter((p) => {
    const v = Number(p.valor.valor);
    return v >= escala.min && v <= escala.max;
  });
  const fora = recorte.abaixo + recorte.acima;
  const noRecorte = (v: string) => Number(v) >= escala.min && Number(v) <= escala.max;
  return (
    <section className="grid gap-2 border-t border-linha pt-4" aria-labelledby="analise-recorte">
      <h4 id="analise-recorte">Detalhe da faixa central</h4>
      <p className="gc-help">
        Eixo ampliado de {recorte.escala.minimo.exibicao} a {recorte.escala.maximo.exibicao}, só para ler os preços próximos.{" "}
        {fora === 1 ? "1 preço fica" : `${fora} preços ficam`} fora deste recorte
        {recorte.abaixo > 0 && recorte.acima > 0
          ? ` (${recorte.abaixo} abaixo e ${recorte.acima} acima)`
          : recorte.acima > 0
            ? " (acima)"
            : " (abaixo)"}
        : o gráfico acima mostra a série inteira.
      </p>
      <PriceDispersion
        values={valores(dentro)}
        median={noRecorte(cesta.mediana.valor) ? Number(cesta.mediana.valor) : undefined}
        mean={noRecorte(cesta.media.valor) ? Number(cesta.media.valor) : undefined}
        scale={escala}
        legend={false}
        labels={{
          median: cesta.mediana.exibicao,
          mean: cesta.media.exibicao,
          scale: [recorte.escala.minimo.exibicao, recorte.escala.maximo.exibicao],
        }}
      />
    </section>
  );
}

function linhasDaComparacao(grupos: GrupoDePrecos[]) {
  return grupos.map((g) => ({
    label: g.rotulo,
    meta: `${g.resumo.quantidade === 1 ? "1 preço" : `${g.resumo.quantidade} preços`} · ${g.na_cesta} na cesta`,
    min: Number(g.resumo.menor.valor),
    max: Number(g.resumo.maior.valor),
    median: Number(g.resumo.mediana.valor),
    labels: {
      min: g.resumo.menor.exibicao,
      max: g.resumo.maior.exibicao,
      median: g.resumo.mediana.exibicao,
      cv: g.resumo.quantidade > 1 ? g.resumo.coeficiente_variacao.exibicao : undefined,
    },
  }));
}

function Indicadores({ dados, metodo }: { dados: EstatisticasDoItem; metodo: string | null }) {
  const { cesta, coletadas } = dados;
  if (!cesta || !coletadas) return null;
  const adotado = (codigo: string) => (metodo === codigo ? { delta: "Método adotado", deltaTone: "neutral" as const } : {});
  const noTopo = (qual: "menor" | "maior") => dados.pontos.filter((p) => p.extremo === qual && p.na_cesta)[0];
  const maior = noTopo("maior");
  const sinalDoMaior = maior?.sobre_a_mediana?.exibicao;
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 2xl:grid-cols-6" data-testid="indicadores-da-serie">
      <KpiCard compact label="Na cesta" value={cesta.quantidade} unit={`de ${coletadas.quantidade}`} footnote="preços com valor" />
      <KpiCard
        compact
        label="Menor da cesta"
        value={cesta.menor.exibicao}
        footnote={cesta.menor.valor === coletadas.menor.valor ? noTopo("menor")?.fonte : `Coletadas: ${coletadas.menor.exibicao}`}
      />
      <KpiCard
        compact
        label="Média"
        value={cesta.media.exibicao}
        trend={dados.tendencia.length > 0 ? dados.tendencia.map((v) => Number(v.valor)) : undefined}
        footnote={dados.tendencia.length > 0 ? "preços da cesta por data de compra" : `Desvio padrão ${cesta.desvio_padrao.exibicao}`}
        {...adotado("media")}
      />
      <KpiCard compact label="Mediana" value={cesta.mediana.exibicao} footnote="metade dos preços abaixo, metade acima" {...adotado("mediana")} />
      <KpiCard
        compact
        label="Maior da cesta"
        value={cesta.maior.exibicao}
        delta={sinalDoMaior ? `${sinalDoMaior} sobre a mediana` : undefined}
        deltaTone={maior && maior.fora_da_faixa.length > 0 ? "warning" : "neutral"}
        footnote={cesta.maior.valor === coletadas.maior.valor ? maior?.fonte : `Coletadas: ${coletadas.maior.exibicao}`}
      />
      <KpiCard
        compact
        label="Coeficiente de variação"
        value={cesta.quantidade > 1 ? cesta.coeficiente_variacao.exibicao : "—"}
        delta={DISPERSAO[cesta.dispersao]}
        deltaTone={cesta.dispersao === "dispersa" ? "warning" : cesta.dispersao === "homogenea" ? "success" : "neutral"}
        footnote={`Limite ${dados.limite_dispersao.exibicao}`}
      />
    </div>
  );
}

/**
 * Análise da série de um item: indicadores da cesta, dispersão de tudo o que
 * foi coletado e a comparação por fonte e por UF, no mesmo eixo. Toda conta
 * vem da API (`/estatisticas`); aqui só se escolhe onde cada texto aparece.
 */
export function AnaliseDoItem({ dados, metodo = null }: { dados: EstatisticasDoItem; metodo?: string | null }) {
  const { cesta, coletadas, escala } = dados;
  if (!coletadas || !escala) {
    return (
      <Card title="Análise da série">
        <p className="gc-help">Nenhuma referência com valor normalizado ainda.</p>
      </Card>
    );
  }
  const eixoComum = eixo(escala);
  return (
    <div className="grid gap-5" data-testid="analise-da-serie">
      <Indicadores dados={dados} metodo={metodo} />
      {!cesta && <p className="gc-help">A cesta está vazia: os números abaixo são de todas as coletadas.</p>}

      {cesta?.dispersao === "dispersa" && (
        <Alert variant="warning" title="Série dispersa">
          O coeficiente de variação da cesta é {cesta.coeficiente_variacao.exibicao}, acima de{" "}
          {dados.limite_dispersao.exibicao}. Confira os preços sinalizados antes de concluir o item.
        </Alert>
      )}

      <Card
        title="Análise da série"
        subtitle={`Estatística descreve os preços; a estimativa segue o método ${metodo ? `do item (${rotuloMetodo(metodo).toLowerCase()})` : "do item"}. Eixo linear, do menor ao maior coletado.`}
      >
        <div className="grid gap-5">
          <GraficoDaSerie dados={dados} />
          <DetalheDaFaixaCentral dados={dados} />
        </div>
      </Card>

      <div className="grid gap-5 xl:grid-cols-2">
        <Card title="Comparação por fonte" subtitle="Mesmo eixo do gráfico acima.">
          <PriceCompare ariaLabel="Preços por fonte" scale={eixoComum} rows={linhasDaComparacao(dados.por_fonte)} />
        </Card>
        <Card title="Comparação por UF" subtitle="Mesmo eixo do gráfico acima.">
          <PriceCompare ariaLabel="Preços por UF" scale={eixoComum} rows={linhasDaComparacao(dados.por_uf)} />
        </Card>
      </div>

      <Accordion
        items={[
          {
            title: "Números por fonte",
            meta: `${dados.por_fonte.length}`,
            content: <DataTable compact caption="Preços por fonte" columns={colunas("Fonte")} rows={linhas(dados.por_fonte)} />,
          },
          {
            title: "Números por UF",
            meta: `${dados.por_uf.length}`,
            content: <DataTable compact caption="Preços por UF" columns={colunas("UF")} rows={linhas(dados.por_uf)} />,
          },
          {
            title: "Todos os preços do gráfico",
            meta: `${dados.pontos.length}`,
            content: (
              <DataTable
                compact
                caption="Preços do gráfico de dispersão"
                columns={COLUNAS_DOS_PRECOS}
                rows={dados.pontos.map((p) => ({
                  id: p.referencia_id,
                  origem: origem(p),
                  valor: p.valor.exibicao,
                  mediana: p.sobre_a_mediana?.exibicao ?? "—",
                  situacao: SITUACAO[estado(p) ?? "valid"],
                }))}
              />
            ),
          },
        ]}
      />

      {dados.sem_valor > 0 && (
        <p className="gc-help">
          {dados.sem_valor === 1
            ? "1 referência sem valor normalizado ficou fora da conta."
            : `${dados.sem_valor} referências sem valor normalizado ficaram fora da conta.`}
        </p>
      )}
    </div>
  );
}
