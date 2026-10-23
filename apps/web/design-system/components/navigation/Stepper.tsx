import { Icon } from "../core/Icon";

export type StepState = "done" | "current" | "todo" | "error";

export interface StepItem {
  label: string;
  meta?: string;
  /** Sem estado, ele sai de `current`. */
  state?: StepState;
}

export interface StepperProps {
  steps: StepItem[];
  /** Índice da etapa atual. */
  current?: number;
  /** Etapa concluída vira botão para voltar. */
  onStepClick?: (indice: number) => void;
  ariaLabel?: string;
}

const LEITURA: Record<StepState, string> = {
  done: "(concluída)",
  current: "(etapa atual)",
  error: "(com pendência)",
  todo: "",
};

/**
 * Etapas na horizontal: fase preparatória (Demanda → DFD → ETP → Mapa de
 * Riscos → TR → Edital) ou pesquisa de preços. O estado vai em ícone e
 * texto para leitor de tela, nunca só na cor.
 */
export function Stepper({ steps, current = 0, onStepClick, ariaLabel = "Etapas" }: StepperProps) {
  return (
    <ol className="gc-stepper" aria-label={ariaLabel}>
      {steps.map((s, i) => {
        const estado: StepState = s.state ?? (i < current ? "done" : i === current ? "current" : "todo");
        const ponto = (
          <span className="gc-step__dot">
            {estado === "done" ? <Icon name="check" /> : estado === "error" ? <Icon name="exclamation-mark" /> : i + 1}
          </span>
        );
        return (
          <li key={i} className="gc-step" data-state={estado} aria-current={estado === "current" ? "step" : undefined}>
            {onStepClick && estado === "done" ? (
              <button type="button" className="gc-step__btn" onClick={() => onStepClick(i)}>
                {ponto}
              </button>
            ) : (
              ponto
            )}
            <span className="gc-step__label">{s.label}</span>
            {s.meta && <span className="gc-step__meta">{s.meta}</span>}
            <span className="gc-sr-only">{LEITURA[estado]}</span>
          </li>
        );
      })}
    </ol>
  );
}
