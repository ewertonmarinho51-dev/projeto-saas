import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export type Severity = "blocking" | "warning" | "info";

const GRAVIDADE: Record<Severity, { icone: IconName; rotulo: string }> = {
  blocking: { icone: "prohibit", rotulo: "Impede a emissão" },
  warning: { icone: "warning", rotulo: "Atenção" },
  info: { icone: "info", rotulo: "Informativo" },
};

export interface ValidationIssue {
  severity: Severity;
  title: ReactNode;
  detail?: ReactNode;
  item?: string;
  action?: string;
}

export interface ValidationSummaryProps {
  issues: ValidationIssue[];
  title?: string;
  onAction?: (issue: ValidationIssue) => void;
}

/**
 * Conferência antes de emitir: separa o que impede a emissão do aviso e
 * da nota, cada um apontando o item e o conserto. A gravidade vai sempre
 * escrita, não só na cor.
 */
export function ValidationSummary({ issues, title = "Verificação antes da emissão", onAction }: ValidationSummaryProps) {
  const bloqueios = issues.filter((i) => i.severity === "blocking").length;
  const avisos = issues.filter((i) => i.severity === "warning").length;
  return (
    <section className="gc-issues" aria-label={title}>
      <header className="gc-issues__head">
        <span className="gc-issues__title">{title}</span>
        <span className="gc-issues__badges">
          {bloqueios > 0 ? (
            <span className="gc-badge gc-badge--error">
              <Icon name="prohibit" />
              {bloqueios} {bloqueios === 1 ? "impedimento" : "impedimentos"}
            </span>
          ) : (
            <span className="gc-badge gc-badge--success">
              <Icon name="check" />
              Sem impedimentos
            </span>
          )}
          {avisos > 0 && (
            <span className="gc-badge gc-badge--warning">
              <Icon name="warning" />
              {avisos} {avisos === 1 ? "aviso" : "avisos"}
            </span>
          )}
        </span>
      </header>
      <ul className="gc-issues__list">
        {issues.map((it, i) => {
          const s = GRAVIDADE[it.severity];
          return (
            <li key={i} className="gc-issue" data-severity={it.severity}>
              <Icon name={s.icone} weight="fill" />
              <span className="gc-issue__body">
                <span className="gc-issue__title">{it.title}</span>
                {it.detail && <span className="gc-issue__detail">{it.detail}</span>}
                <span className="gc-issue__sev">
                  {s.rotulo}
                  {it.item && ` · ${it.item}`}
                </span>
              </span>
              {it.action && (
                <button type="button" className="gc-btn gc-btn--secondary gc-btn--sm" onClick={() => onAction?.(it)}>
                  {it.action}
                </button>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
