import type { AriaRole, ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export type AlertVariant = "info" | "success" | "warning" | "error" | "neutral";

const ICONES: Record<AlertVariant, IconName> = {
  info: "info",
  success: "check-circle",
  warning: "warning",
  error: "warning-octagon",
  neutral: "info",
};

export interface AlertProps {
  variant?: AlertVariant;
  title?: ReactNode;
  children?: ReactNode;
  icon?: IconName;
  actions?: ReactNode;
  onClose?: () => void;
  compact?: boolean;
  /** Padrão: alert para erro, status para o resto. */
  role?: AriaRole;
}

/**
 * Mensagem em linha. info = contexto; success = feito; warning = pede
 * atenção mas não bloqueia; error = bloqueia. Sempre ícone e texto.
 */
export function Alert({ variant = "info", title, children, icon, actions, onClose, compact = false, role }: AlertProps) {
  return (
    <div
      className={cx("gc-alert", `gc-alert--${variant}`, compact && "gc-alert--compact")}
      role={role ?? (variant === "error" ? "alert" : "status")}
    >
      <Icon name={icon ?? ICONES[variant]} weight="fill" />
      <div className="gc-alert__body">
        {title && <p className="gc-alert__title">{title}</p>}
        {children && <div className="gc-alert__desc">{children}</div>}
        {actions && <div className="gc-alert__actions">{actions}</div>}
      </div>
      {onClose && (
        <button type="button" className="gc-iconbtn gc-iconbtn--sm gc-alert__close" aria-label="Fechar aviso" onClick={onClose}>
          <Icon name="x" />
        </button>
      )}
    </div>
  );
}
