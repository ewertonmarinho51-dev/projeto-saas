import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

/** Linha de tendência: é dado, não ilustração. */
function Faisca({ data }: { data: number[] }) {
  if (data.length < 2) return null;
  const largura = 120;
  const altura = 36;
  const menor = Math.min(...data);
  const maior = Math.max(...data);
  const faixa = maior - menor || 1;
  const pontos = data.map((d, i) => `${(i / (data.length - 1)) * largura},${altura - 3 - ((d - menor) / faixa) * (altura - 6)}`);
  return (
    <svg className="gc-kpi__spark" viewBox={`0 0 ${largura} ${altura}`} preserveAspectRatio="none" aria-hidden="true">
      <polyline
        points={pontos.join(" ")}
        fill="none"
        stroke="var(--accent-brand)"
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

export interface KpiCardProps {
  label: ReactNode;
  value: ReactNode;
  unit?: ReactNode;
  icon?: IconName;
  delta?: ReactNode;
  deltaTone?: "success" | "warning" | "error" | "neutral";
  footnote?: ReactNode;
  /** Série da linha de tendência. */
  trend?: number[];
  compact?: boolean;
  /** Valor longo (dinheiro de muitos dígitos): corpo menor, para o número não partir. */
  dense?: boolean;
  /** No lugar do ícone, no canto. */
  action?: ReactNode;
}

/** Indicador: rótulo, valor grande tabular, tendência opcional, variação e nota. */
export function KpiCard({ label, value, unit, icon, delta, deltaTone = "success", footnote, trend, compact, dense, action }: KpiCardProps) {
  return (
    <section className="gc-card">
      <div className={cx("gc-kpi", compact && "gc-kpi--compact", dense && "gc-kpi--dense")}>
        <div className="gc-kpi__top">
          <span className="gc-kpi__label">{label}</span>
          {icon ? (
            <span className="gc-kpi__icon">
              <Icon name={icon} />
            </span>
          ) : (
            action
          )}
        </div>
        <div className="gc-kpi__value">
          {value}
          {unit && <small>{unit}</small>}
        </div>
        {trend && <Faisca data={trend} />}
        {(delta || footnote) && (
          <div className="gc-kpi__foot">
            {delta && <span className={`gc-badge gc-badge--sm gc-badge--${deltaTone}`}>{delta}</span>}
            {footnote && <span>{footnote}</span>}
          </div>
        )}
      </div>
    </section>
  );
}
