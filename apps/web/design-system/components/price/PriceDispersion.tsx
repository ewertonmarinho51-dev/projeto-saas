import { formatarReais } from "../../lib/formato";

export type DispersionState = "valid" | "attention" | "discrepant" | "excluded";

export interface DispersionValue {
  label?: string;
  value: number;
  state?: DispersionState;
  /** Valor já formatado pelo servidor; com ele, `format` não é chamado para o ponto. */
  display?: string;
}

/**
 * Textos prontos (dinheiro formatado no servidor). Com eles o navegador só
 * POSICIONA: nenhum valor exibido nasce de conta feita aqui, e a escala
 * mostra o menor e o maior coletados em vez das pontas com folga.
 */
export interface DispersionLabels {
  median?: string;
  band?: [string, string];
  scale?: [string, string];
}

export interface PriceDispersionProps {
  values: DispersionValue[];
  median?: number;
  /** Faixa de aceitação [mínimo, máximo] da regra de triagem. */
  band?: [number, number];
  format?: (n: number) => string;
  labels?: DispersionLabels;
  legend?: boolean;
}

const ROTULO: Record<DispersionState, string> = {
  valid: "Na cesta",
  attention: "Exige conferência",
  discrepant: "Discrepante",
  excluded: "Fora do cálculo",
};

const ORDEM: DispersionState[] = ["valid", "attention", "discrepant", "excluded"];

/**
 * Todas as referências de um item num eixo de preço: mediana, faixa de
 * referência e cada ponto com a forma do seu estado (círculo = na cesta,
 * anel = conferência, triângulo = discrepante, anel cinza = fora). Forma
 * e legenda, nunca só cor.
 */
export function PriceDispersion({ values, median, band, format = formatarReais, labels, legend = true }: PriceDispersionProps) {
  const texto = (v: DispersionValue) => v.display ?? format(v.value);
  const vs = values.map((v) => v.value);
  const baixo = Math.min(...vs, band ? band[0] : Infinity);
  const alto = Math.max(...vs, band ? band[1] : -Infinity);
  const folga = (alto - baixo) * 0.08 || 1;
  const min = baixo - folga;
  const max = alto + folga;
  const pos = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  return (
    <figure className="gc-disp">
      <div
        className="gc-disp__plot"
        role="img"
        aria-label={values.map((v) => `${v.label ?? ""} ${texto(v)} — ${ROTULO[v.state ?? "valid"]}`).join("; ")}
      >
        <div className="gc-disp__axis" />
        {band && (
          <div
            className="gc-disp__band"
            style={{ left: pos(band[0]), width: `calc(${pos(band[1])} - ${pos(band[0])})` }}
            title={`Faixa de referência: ${labels?.band?.[0] ?? format(band[0])} a ${labels?.band?.[1] ?? format(band[1])}`}
          />
        )}
        {median != null && (
          <div className="gc-disp__median" style={{ left: pos(median) }}>
            <span>Mediana {labels?.median ?? format(median)}</span>
          </div>
        )}
        {values.map((v, i) => (
          <span
            key={i}
            className="gc-disp__dot"
            data-state={v.state ?? "valid"}
            style={{ left: pos(v.value) }}
            title={`${v.label ? `${v.label} · ` : ""}${texto(v)} · ${ROTULO[v.state ?? "valid"]}`}
          />
        ))}
      </div>
      <div className="gc-disp__scale">
        <span>{labels?.scale ? `Menor ${labels.scale[0]}` : format(min)}</span>
        <span>{labels?.scale ? `Maior ${labels.scale[1]}` : format(max)}</span>
      </div>
      {legend && (
        <figcaption className="gc-disp__legend">
          {ORDEM.filter((s) => values.some((v) => (v.state ?? "valid") === s)).map((s) => (
            <span key={s}>
              <span className="gc-disp__dot gc-disp__dot--static" data-state={s} />
              {ROTULO[s]}
            </span>
          ))}
          {band && (
            <span>
              <span className="gc-disp__swatch" />
              Faixa de referência
            </span>
          )}
        </figcaption>
      )}
    </figure>
  );
}
