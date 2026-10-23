import type { ReactNode } from "react";

import { Icon } from "../core/Icon";

export interface DocumentViewerProps {
  name: string;
  meta?: ReactNode;
  badges?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  height?: number | string;
}

/**
 * Prévia de documento: barra do arquivo sobre a página de papel. Trecho
 * gerado por IA vai em `<span className="gc-mark-ai">`; trecho que pede
 * revisão, em `gc-mark-review`.
 */
export function DocumentViewer({ name, meta, badges, actions, children, height }: DocumentViewerProps) {
  return (
    <div className="gc-docviewer" style={height ? { height } : undefined}>
      <div className="gc-docviewer__bar">
        <span className="gc-file__icon">
          <Icon name="file-text" />
        </span>
        <span className="gc-docviewer__name">
          <strong>{name}</strong>
          {meta && <span>{meta}</span>}
        </span>
        {badges}
        {actions}
      </div>
      <div className="gc-docviewer__stage">
        <article className="gc-docviewer__page">{children}</article>
      </div>
    </div>
  );
}
