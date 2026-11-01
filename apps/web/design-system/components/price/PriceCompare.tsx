import type { DispersionScale } from "./PriceDispersion";

export interface PriceCompareRow {
  label: string;
  /** "4 preços · 3 na cesta". */
  meta?: string;
  min: number;
  max: number;
  median: number;
  /** Textos prontos do servidor: o navegador só posiciona. */
  labels: { min: string; max: string; median: string; cv?: string };
}

export interface PriceCompareProps {
  rows: PriceCompareRow[];
  /** O mesmo eixo do gráfico de dispersão, para as linhas serem comparáveis. */
  scale: DispersionScale;
  ariaLabel: string;
}

/**
 * Grupos de preços (fonte, UF) lado a lado num eixo linear comum: a barra vai
 * do menor ao maior preço do grupo e o traço marca a mediana. O número exato
 * fica escrito em cada linha; cor nunca é o único sinal.
 */
export function PriceCompare({ rows, scale, ariaLabel }: PriceCompareProps) {
  const pos = (v: number) => ((v - scale.min) / (scale.max - scale.min)) * 100;
  const resumo = rows
    .map((r) => `${r.label}: mediana ${r.labels.median}, de ${r.labels.min} a ${r.labels.max}`)
    .join("; ");
  return (
    <figure className="gc-pcomp">
      <div className="gc-pcomp__rows" role="img" aria-label={`${ariaLabel}. ${resumo}`}>
        {rows.map((r) => (
          <div className="gc-pcomp__row" key={r.label}>
            <span className="gc-pcomp__label">
              <span title={r.label}>{r.label}</span>
              {r.meta && <small>{r.meta}</small>}
            </span>
            <span className="gc-pcomp__rail">
              <span className="gc-pcomp__range" style={{ left: `${pos(r.min)}%`, width: `${pos(r.max) - pos(r.min)}%` }} />
              <span className="gc-pcomp__median" style={{ left: `${pos(r.median)}%` }} />
            </span>
            <span className="gc-pcomp__value">
              {r.labels.median}
              <small>
                {r.labels.min} a {r.labels.max}
                {r.labels.cv ? ` · CV ${r.labels.cv}` : ""}
              </small>
            </span>
          </div>
        ))}
      </div>
      <figcaption className="gc-pcomp__legend">
        <span>
          <span className="gc-pcomp__swatch" />
          Do menor ao maior preço
        </span>
        <span>
          <span className="gc-pcomp__swatch gc-pcomp__swatch--median" />
          Mediana do grupo
        </span>
        <span className="gc-pcomp__scale">
          Eixo de {scale.ticks[0]?.label} a {scale.ticks[scale.ticks.length - 1]?.label}
        </span>
      </figcaption>
    </figure>
  );
}
