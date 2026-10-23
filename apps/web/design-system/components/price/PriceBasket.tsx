import type { ReactNode } from "react";

import { Icon } from "../core/Icon";

export interface PriceBasketItem {
  source: ReactNode;
  detail?: ReactNode;
  value: ReactNode;
}

export interface PriceBasketProps {
  items: PriceBasketItem[];
  onRemove?: (indice: number) => void;
  totalLabel?: ReactNode;
  total?: ReactNode;
}

/** Cesta de preços: referências que entram na estimativa, removíveis, com a estimativa em destaque. */
export function PriceBasket({ items, onRemove, totalLabel = "Estimativa (média)", total }: PriceBasketProps) {
  return (
    <div>
      <div className="gc-basket__list">
        {items.map((it, i) => (
          <div className="gc-basket__item" key={i}>
            <Icon name="check-circle" weight="fill" />
            <span className="gc-basket__name">
              {it.source}
              {it.detail && <small>{it.detail}</small>}
            </span>
            <span className="gc-basket__price">{it.value}</span>
            {onRemove ? (
              <button
                type="button"
                className="gc-iconbtn gc-iconbtn--sm gc-iconbtn--danger"
                aria-label={`Remover ${typeof it.source === "string" ? it.source : "referência"} da cesta`}
                onClick={() => onRemove(i)}
              >
                <Icon name="x" />
              </button>
            ) : (
              <span />
            )}
          </div>
        ))}
      </div>
      {total && (
        <div className="gc-basket__total">
          <span>{totalLabel}</span>
          <strong>{total}</strong>
        </div>
      )}
    </div>
  );
}
