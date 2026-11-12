import type { ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface ProgressBarProps {
  value?: number;
  max?: number;
  label?: ReactNode;
  showValue?: boolean;
  hint?: ReactNode;
  /** `neutral`: progresso parado (falha) — cinza, sem cor de estado. */
  tone?: "accent" | "success" | "warning" | "neutral";
  /** `lg`: trilho de 14 px do painel de carregamento (coleta em lote). */
  size?: "sm" | "md" | "lg";
  /** Sem total conhecido (coleta em andamento). */
  indeterminate?: boolean;
  /** Nome acessível quando o rótulo não é texto (ou não é mostrado). */
  ariaLabel?: string;
}

/** Progresso linear: documento, coleta, envio de arquivo. */
export function ProgressBar({
  value = 0,
  max = 100,
  label,
  showValue = true,
  hint,
  tone = "accent",
  size = "md",
  indeterminate = false,
  ariaLabel,
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      className={cx(
        "gc-progress",
        tone !== "accent" && `gc-progress--${tone}`,
        size !== "md" && `gc-progress--${size}`,
        indeterminate && "gc-progress--indeterminate",
        // Um item de 125 ainda aparece: a barra larga nunca fica "vazia" com progresso real.
        size === "lg" && pct > 0 && !indeterminate && "gc-progress--started",
      )}
    >
      {(label || showValue) && (
        <div className="gc-progress__row">
          <span>{label}</span>
          {showValue && !indeterminate && <span className="gc-progress__value">{Math.round(pct)}%</span>}
        </div>
      )}
      <div
        className="gc-progress__track"
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={max}
        aria-valuenow={indeterminate ? undefined : value}
        aria-label={ariaLabel ?? (typeof label === "string" ? label : undefined)}
      >
        <div className="gc-progress__fill" style={{ width: `${pct}%` }} />
      </div>
      {hint && <span className="gc-progress__hint">{hint}</span>}
    </div>
  );
}
