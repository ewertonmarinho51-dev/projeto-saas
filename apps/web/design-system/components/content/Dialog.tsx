"use client";

import { useEffect, useId, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface DialogProps {
  open?: boolean;
  onClose?: () => void;
  title: ReactNode;
  description?: ReactNode;
  icon?: IconName;
  tone?: "default" | "danger" | "warning";
  size?: "sm" | "md" | "lg";
  footer?: ReactNode;
  children?: ReactNode;
  /** Posiciona no pai posicionado mais próximo, não na janela (vitrine, prévia). */
  contained?: boolean;
}

/**
 * Diálogo modal para confirmação e formulário curto. Esc e clique fora
 * fecham. Rodapé: secundário (Cancelar) à esquerda do primário.
 */
export function Dialog({
  open = true,
  onClose,
  title,
  description,
  icon,
  tone = "default",
  size = "md",
  footer,
  children,
  contained = false,
}: DialogProps) {
  // Id único: com dois diálogos na tela, o aria-labelledby não pode colidir.
  const tituloId = useId();
  useEffect(() => {
    if (!open || !onClose) return;
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", esc);
    return () => document.removeEventListener("keydown", esc);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className={cx("gc-overlay", contained && "gc-overlay--contained")}
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose?.();
      }}
    >
      <div role="dialog" aria-modal="true" aria-labelledby={tituloId} className={cx("gc-dialog", size !== "md" && `gc-dialog--${size}`)}>
        <div className="gc-dialog__head">
          {icon && (
            <span className={cx("gc-dialog__icon", tone !== "default" && `gc-dialog__icon--${tone}`)}>
              <Icon name={icon} />
            </span>
          )}
          <div className="gc-dialog__titles">
            <h2 id={tituloId} className="gc-dialog__title">
              {title}
            </h2>
            {description && <p className="gc-dialog__desc">{description}</p>}
          </div>
          {onClose && (
            <button type="button" className="gc-iconbtn gc-iconbtn--sm gc-dialog__close" aria-label="Fechar" onClick={onClose}>
              <Icon name="x" />
            </button>
          )}
        </div>
        {children && <div className="gc-dialog__body">{children}</div>}
        {footer && <div className="gc-dialog__foot">{footer}</div>}
      </div>
    </div>
  );
}
