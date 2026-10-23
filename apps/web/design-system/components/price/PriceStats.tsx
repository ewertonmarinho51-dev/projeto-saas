import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export interface PriceStat {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
  help?: string;
  /** O método efetivamente adotado. */
  highlight?: boolean;
}

export interface PriceStatsProps {
  items: PriceStat[];
}

/** Estatística das referências válidas de um item: nº, menor, média, mediana, maior, CV. */
export function PriceStats({ items }: PriceStatsProps) {
  return (
    <div className="gc-pstats">
      {items.map((s, i) => (
        <div key={i} className={cx("gc-pstat", s.highlight && "gc-pstat--highlight")}>
          <span className="gc-pstat__label">
            {s.label}
            {s.help && (
              <span title={s.help} className="gc-pstat__help">
                <Icon name="info" size={12} label={s.help} />
              </span>
            )}
          </span>
          <span className="gc-pstat__value">{s.value}</span>
          {s.hint && <span className="gc-pstat__hint">{s.hint}</span>}
        </div>
      ))}
    </div>
  );
}
