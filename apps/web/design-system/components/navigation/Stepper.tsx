import { Icon } from "../core/Icon";

export type StepState = "done" | "current" | "todo" | "error";

export interface StepItem {
  label: string;
  meta?: string;
  /** Sem estado, ele sai de `current`. */
  state?: StepState;
  /**
   * Destino da etapa (ex.: `#itens`). Etapa concluída com destino vira
   * link de verdade para voltar a ela — funciona em componente de
   * servidor, sem JavaScript. Etapa atual ou futura ignora o destino.
   */
  href?: string;
}

export interface StepperProps {
  steps: StepItem[];
  /** Índice da etapa atual. */
  current?: number;
  /** Etapa concluída vira botão para voltar. Quem tem `href` vira link. */
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
 *
 * Só a etapa JÁ PASSADA é clicável: voltar a ela é navegar, não mudar o
 * estado de nada. O alvo do clique leva o rótulo junto — o nome acessível
 * é "Triagem (concluída)", não um ícone de check mudo.
 */
export function Stepper({ steps, current = 0, onStepClick, ariaLabel = "Etapas" }: StepperProps) {
  return (
    <ol className="gc-stepper" aria-label={ariaLabel}>
      {steps.map((s, i) => {
        const estado: StepState = s.state ?? (i < current ? "done" : i === current ? "current" : "todo");
        const conteudo = (
          <>
            <span className="gc-step__dot" aria-hidden="true">
              {estado === "done" ? <Icon name="check" /> : estado === "error" ? <Icon name="exclamation-mark" /> : i + 1}
            </span>
            <span className="gc-step__label">{s.label}</span>
            {LEITURA[estado] && <span className="gc-sr-only"> {LEITURA[estado]}</span>}
          </>
        );
        const volta = estado === "done";
        return (
          <li key={i} className="gc-step" data-state={estado} aria-current={estado === "current" ? "step" : undefined}>
            {volta && s.href ? (
              <a className="gc-step__btn" href={s.href}>
                {conteudo}
              </a>
            ) : volta && onStepClick ? (
              <button type="button" className="gc-step__btn" onClick={() => onStepClick(i)}>
                {conteudo}
              </button>
            ) : (
              <span className="gc-step__corpo">{conteudo}</span>
            )}
            {s.meta && <span className="gc-step__meta">{s.meta}</span>}
          </li>
        );
      })}
    </ol>
  );
}
