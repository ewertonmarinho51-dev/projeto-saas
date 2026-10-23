import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export interface FieldProps {
  label?: ReactNode;
  htmlFor?: string;
  required?: boolean;
  optional?: boolean;
  help?: ReactNode;
  /** Mensagem de erro: substitui a ajuda e fica vermelha. Id: `<htmlFor>-erro`. */
  error?: ReactNode;
  counter?: ReactNode;
  children: ReactNode;
  className?: string;
}

/**
 * Rótulo + controle + ajuda ou erro. Rótulo como pergunta para quem não é
 * da área ("Quem está pedindo"); placeholder começa com "Ex.:".
 */
export function Field({ label, htmlFor, required, optional, help, error, counter, children, className }: FieldProps) {
  return (
    <div className={cx("gc-field", className)}>
      {label && (
        <label className="gc-label" htmlFor={htmlFor}>
          {label}
          {required && (
            <span className="gc-label__req" aria-hidden="true">
              *
            </span>
          )}
          {optional && <span className="gc-label__opt">(opcional)</span>}
        </label>
      )}
      {children}
      {error ? (
        <p className="gc-field-error" id={htmlFor ? `${htmlFor}-erro` : undefined} role="alert">
          <Icon name="warning-circle" />
          {error}
        </p>
      ) : help ? (
        <p className="gc-help" id={htmlFor ? `${htmlFor}-ajuda` : undefined}>
          {help}
        </p>
      ) : null}
      {counter && <span className="gc-counter">{counter}</span>}
    </div>
  );
}
