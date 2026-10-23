import { cx } from "../../lib/cx";

export interface SpinnerProps {
  size?: "md" | "lg";
  label?: string;
  accent?: boolean;
}

/** Carregamento sem total, com nome acessível. Geração longa de IA usa AiProcessing, não spinner. */
export function Spinner({ size = "md", label = "Carregando", accent = true }: SpinnerProps) {
  return (
    <span role="status" className="gc-spinner-wrap">
      <span className={cx("gc-spinner", size === "lg" && "gc-spinner--lg", accent && "gc-spinner--accent")} aria-hidden="true" />
      <span className="gc-sr-only">{label}</span>
    </span>
  );
}
