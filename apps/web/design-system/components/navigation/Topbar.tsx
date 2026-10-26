import type { CSSProperties, ReactNode } from "react";

export interface TopbarProps {
  start?: ReactNode;
  end?: ReactNode;
  style?: CSSProperties;
}

/** Barra superior de 64 px da casca: trilha à esquerda; salvamento, GovBot, avisos e avatar à direita. */
export function Topbar({ start, end, style }: TopbarProps) {
  return (
    <header className="gc-topbar" style={style}>
      <div className="gc-topbar__start">{start}</div>
      <div className="gc-topbar__end">{end}</div>
    </header>
  );
}
