import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface CardProps extends Omit<HTMLAttributes<HTMLElement>, "title"> {
  title?: ReactNode;
  subtitle?: ReactNode;
  eyebrow?: ReactNode;
  actions?: ReactNode;
  footer?: ReactNode;
  children?: ReactNode;
  elevated?: boolean;
  interactive?: boolean;
  selected?: boolean;
  sunken?: boolean;
  /** Borda sob o cabeçalho. */
  divided?: boolean;
  /** Corpo sem padding (tabela, lista). */
  flush?: boolean;
}

/**
 * Superfície base: branca, borda de 1 px, raio de 12 px. Cabeçalho
 * (sobretítulo, título, subtítulo, ações), corpo e rodapé. Nunca cartão só
 * com borda colorida à esquerda.
 */
export function Card({
  title,
  subtitle,
  eyebrow,
  actions,
  footer,
  children,
  elevated,
  interactive,
  selected,
  sunken,
  divided,
  flush,
  className,
  ...rest
}: CardProps) {
  const temCabecalho = Boolean(title || subtitle || eyebrow || actions);
  return (
    <section
      className={cx(
        "gc-card",
        elevated && "gc-card--elevated",
        interactive && "gc-card--interactive",
        selected && "gc-card--selected",
        sunken && "gc-card--sunken",
        className,
      )}
      {...rest}
    >
      {temCabecalho && (
        <div className={cx("gc-card__header", divided && "gc-card__header--divided")}>
          <div className="gc-card__titles">
            {eyebrow && <span className="gc-card__eyebrow">{eyebrow}</span>}
            {title && <h3 className="gc-card__title">{title}</h3>}
            {subtitle && <p className="gc-card__subtitle">{subtitle}</p>}
          </div>
          {actions && <div className="gc-card__actions">{actions}</div>}
        </div>
      )}
      {children != null && (
        <div className={cx("gc-card__body", flush && "gc-card__body--flush", !temCabecalho && !flush && "gc-card__body--solo")}>
          {children}
        </div>
      )}
      {footer && <div className="gc-card__footer">{footer}</div>}
    </section>
  );
}
