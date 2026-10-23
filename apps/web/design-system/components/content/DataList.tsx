import { Fragment, type ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface DataListItem {
  label: ReactNode;
  value: ReactNode;
  /** Dinheiro e quantidade: algarismos tabulares. */
  numeric?: boolean;
}

export interface DataListProps {
  items: DataListItem[];
  /** Blocos rótulo-sobre-valor (resumo de página) em vez de duas colunas. */
  stacked?: boolean;
}

/** Lista chave–valor: duas colunas para detalhe de registro; `stacked` para resumo (Situação · Valor global · Data-base). */
export function DataList({ items, stacked = false }: DataListProps) {
  return (
    <dl className={cx("gc-dl", stacked && "gc-dl--stacked")}>
      {items.map((it, i) =>
        stacked ? (
          <div key={i}>
            <dt>{it.label}</dt>
            <dd className={it.numeric ? "gc-num" : undefined}>{it.value}</dd>
          </div>
        ) : (
          <Fragment key={i}>
            <dt>{it.label}</dt>
            <dd className={it.numeric ? "gc-num" : undefined}>{it.value}</dd>
          </Fragment>
        ),
      )}
    </dl>
  );
}
