import type { ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface TooltipProps {
  content: ReactNode;
  placement?: "top" | "bottom";
  /** Quebra linha (até 260 px) em vez de uma linha só. */
  wrap?: boolean;
  /** Força aberto (vitrine, documentação). */
  open?: boolean;
  children: ReactNode;
}

/**
 * Dica curta no hover e no foco, para botão só de ícone e sigla. Nunca
 * ponha informação essencial só no tooltip.
 */
export function Tooltip({ content, placement = "top", wrap = false, open, children }: TooltipProps) {
  return (
    <span className="gc-tooltip">
      {children}
      <span
        role="tooltip"
        data-open={open ? "true" : undefined}
        className={cx(
          "gc-tooltip__bubble",
          placement === "bottom" && "gc-tooltip__bubble--bottom",
          wrap && "gc-tooltip__bubble--wrap",
        )}
      >
        {content}
      </span>
    </span>
  );
}
