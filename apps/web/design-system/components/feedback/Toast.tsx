import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export type ToastVariant = "success" | "error" | "warning" | "info";

const ICONES: Record<ToastVariant, IconName> = {
  success: "check-circle",
  error: "warning-octagon",
  warning: "warning",
  info: "info",
};

export interface ToastProps {
  variant?: ToastVariant;
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
  onClose?: () => void;
}

/**
 * Confirmação passageira (canto inferior direito, ~5 s). Nunca para erro
 * que exige ação — aí é Alert.
 */
export function Toast({ variant = "success", title, description, action, onClose }: ToastProps) {
  return (
    <div className={`gc-toast gc-toast--${variant}`} role="status" aria-live="polite">
      <Icon name={ICONES[variant]} weight="fill" />
      <div className="gc-toast__body">
        <span className="gc-toast__title">{title}</span>
        {description && <span className="gc-toast__desc">{description}</span>}
        {action && <span className="gc-toast__action">{action}</span>}
      </div>
      {onClose && (
        <button type="button" className="gc-iconbtn gc-iconbtn--sm gc-toast__close" aria-label="Fechar" onClick={onClose}>
          <Icon name="x" />
        </button>
      )}
    </div>
  );
}

export function ToastStack({ children }: { children: ReactNode }) {
  return <div className="gc-toast-stack">{children}</div>;
}
