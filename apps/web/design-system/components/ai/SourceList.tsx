import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface SourceItem {
  title: ReactNode;
  meta?: ReactNode;
  excerpt?: ReactNode;
  icon?: IconName;
  /** Número da citação — substitui o ícone. */
  n?: number;
  href?: string;
  badge?: ReactNode;
}

export interface SourceListProps {
  items: SourceItem[];
  compact?: boolean;
}

/**
 * Fontes de uma resposta ou documento gerado: lei, registro do PNCP,
 * arquivo da base. Mostra o trecho quando há; liga ao original.
 */
export function SourceList({ items, compact = false }: SourceListProps) {
  return (
    <div className={cx("gc-sources", compact && "gc-sources--compact")}>
      {items.map((s, i) => {
        const miolo = (
          <>
            <span className="gc-source__icon">
              {s.n != null ? <span className="gc-source__num">{s.n}</span> : <Icon name={s.icon ?? "book-open"} />}
            </span>
            <span className="gc-source__body">
              <span className="gc-source__title">{s.title}</span>
              {s.meta && <span className="gc-source__meta">{s.meta}</span>}
              {!compact && s.excerpt && <span className="gc-source__excerpt">{s.excerpt}</span>}
            </span>
            {s.badge}
            {s.href && <Icon name="arrow-square-out" className="gc-source__ext" />}
          </>
        );
        return s.href ? (
          <a key={i} className="gc-source" href={s.href} target="_blank" rel="noreferrer">
            {miolo}
          </a>
        ) : (
          <div key={i} className="gc-source">
            {miolo}
          </div>
        );
      })}
    </div>
  );
}
