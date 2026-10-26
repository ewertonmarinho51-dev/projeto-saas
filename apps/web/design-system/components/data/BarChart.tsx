import { formatarReais } from "../../lib/formato";

export interface BarChartDatum {
  label: string;
  value: number;
  /** Cor da série; padrão: --chart-1 … --chart-5 em rodízio. */
  color?: string;
}

export interface BarChartProps {
  data: BarChartDatum[];
  max?: number;
  format?: (n: number) => string;
  axis?: boolean;
  ticks?: number;
}

/** Barras horizontais (preço unitário por fonte). Toda barra leva o valor escrito: cor nunca é o único sinal. */
export function BarChart({ data, max, format = formatarReais, axis = true, ticks = 5 }: BarChartProps) {
  const teto = max || Math.max(...data.map((d) => d.value)) * 1.1 || 1;
  return (
    <div className="gc-bars" role="img" aria-label={data.map((d) => `${d.label}: ${format(d.value)}`).join("; ")}>
      {data.map((d, i) => (
        <div className="gc-bars__row" key={i}>
          <span className="gc-bars__label" title={d.label}>
            {d.label}
          </span>
          <span className="gc-bars__track">
            <span
              className="gc-bars__fill"
              style={{ width: `${(d.value / teto) * 100}%`, background: d.color ?? `var(--chart-${(i % 5) + 1})` }}
            />
          </span>
          <span className="gc-bars__value">{format(d.value)}</span>
        </div>
      ))}
      {axis && (
        <div className="gc-bars__row" aria-hidden="true">
          <span />
          <span className="gc-bars__axis">
            {Array.from({ length: ticks + 1 }, (_, i) => (
              <span key={i}>{Math.round((teto / ticks) * i).toLocaleString("pt-BR")}</span>
            ))}
          </span>
          <span />
        </div>
      )}
    </div>
  );
}
