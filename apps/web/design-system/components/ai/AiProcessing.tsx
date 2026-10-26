import type { ReactNode } from "react";

import { Icon } from "../core/Icon";

export interface AiProcessingStep {
  label: ReactNode;
  state: "done" | "active" | "pending";
  meta?: ReactNode;
}

export interface AiProcessingProps {
  title?: ReactNode;
  steps: AiProcessingStep[];
  /** 0–100. */
  progress?: number;
  footer?: ReactNode;
}

/** O que a IA está fazendo, passo a passo. Geração longa nunca fica só num spinner. */
export function AiProcessing({ title = "Gerando documento", steps, progress, footer }: AiProcessingProps) {
  return (
    <div className="gc-aiproc" role="status" aria-live="polite">
      <div className="gc-aiproc__head">
        <Icon name="sparkle" weight="fill" />
        {title}
      </div>
      <ul className="gc-aiproc__steps">
        {steps.map((s, i) => (
          <li key={i} className="gc-aiproc__step" data-state={s.state}>
            {s.state === "active" ? (
              <span className="gc-spinner" aria-hidden="true" />
            ) : (
              <Icon name={s.state === "done" ? "check-circle" : "circle"} weight={s.state === "done" ? "fill" : "regular"} />
            )}
            <span>{s.label}</span>
            {s.meta && <span className="gc-aiproc__meta">{s.meta}</span>}
          </li>
        ))}
      </ul>
      {progress != null && (
        <div className="gc-progress gc-progress--sm">
          <div className="gc-progress__track">
            <div className="gc-progress__fill" style={{ width: `${progress}%` }} />
          </div>
        </div>
      )}
      {footer}
    </div>
  );
}
