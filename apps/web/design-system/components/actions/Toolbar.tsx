import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface ToolbarProps extends HTMLAttributes<HTMLDivElement> {
  /** Sem fundo nem borda. */
  plain?: boolean;
  children: ReactNode;
}

/** Grupo horizontal de ações acima de tabela e documento. `ToolbarSpacer` empurra o resto para a direita. */
export function Toolbar({ plain = false, children, className, ...rest }: ToolbarProps) {
  return (
    <div role="toolbar" className={cx("gc-toolbar", plain && "gc-toolbar--plain", className)} {...rest}>
      {children}
    </div>
  );
}

export function ToolbarSeparator() {
  return <span className="gc-toolbar__sep" aria-hidden="true" />;
}

export function ToolbarSpacer() {
  return <span className="gc-toolbar__spacer" />;
}
