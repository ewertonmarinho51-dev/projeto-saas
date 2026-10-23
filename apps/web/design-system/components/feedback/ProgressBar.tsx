import type { ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface ProgressBarProps {
  value?: number;
  max?: number;
  label?: ReactNode;
  showValue?: boolean;
  hint?: ReactNode;
  tone?: "accent" | "success" | "warning";
  size?: "sm" | "md";
  /** Sem total conhecido (coleta em andamento). */
  indeterminate?: boolean;
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
}: ProgressBarProps) {
  const pct = Math.max(0, Math.min(100, (value / max) * 100));
  return (
    <div
      className={cx(
        "gc-progress",
        tone !== "accent" && `gc-progress--${tone}`,
        size === "sm" && "gc-progress--sm",
        indeterminate && "gc-progress--indeterminate",
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
        aria-label={typeof label === "string" ? label : undefined}
      >
        <div className="gc-progress__fill" style={{ width: `${pct}%` }} />
      </div>
      {hint && <span className="gc-progress__hint">{hint}</span>}
    </div>
  );
}
