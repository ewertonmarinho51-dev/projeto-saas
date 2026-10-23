import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export interface AccordionItem {
  title: ReactNode;
  content: ReactNode;
  meta?: ReactNode;
  icon?: IconName;
  defaultOpen?: boolean;
}

export interface AccordionProps {
  items: AccordionItem[];
}

/** Detalhe secundário que abre e fecha (details/summary nativo): "Entenda o cálculo", "Detalhes da busca". */
export function Accordion({ items }: AccordionProps) {
  return (
    <div className="gc-accordion">
      {items.map((it, i) => (
        <details key={i} open={it.defaultOpen}>
          <summary>
            <Icon name="caret-right" />
            {it.icon && <Icon name={it.icon} className="gc-accordion__icon" />}
            <span>{it.title}</span>
            {it.meta && <span className="gc-accordion__meta">{it.meta}</span>}
          </summary>
          <div className="gc-accordion__panel">{it.content}</div>
        </details>
      ))}
    </div>
  );
}
