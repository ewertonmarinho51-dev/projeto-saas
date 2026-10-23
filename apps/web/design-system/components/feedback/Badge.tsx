import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export type BadgeVariant = "neutral" | "brand" | "info" | "success" | "warning" | "error" | "solid";

export interface BadgeProps {
  variant?: BadgeVariant;
  size?: "sm" | "md" | "lg";
  icon?: IconName;
  dot?: boolean;
  /** Caixa alta: só selo minúsculo ("AVALIAÇÃO PRELIMINAR"). */
  caps?: boolean;
  square?: boolean;
  children: ReactNode;
  className?: string;
}

/** Rótulo compacto para status, contagem, nome de fonte e categoria. */
export function Badge({ variant = "neutral", size = "md", icon, dot, caps, square, children, className }: BadgeProps) {
  return (
    <span
      className={cx(
        "gc-badge",
        `gc-badge--${variant}`,
        size !== "md" && `gc-badge--${size}`,
        caps && "gc-badge--caps",
        square && "gc-badge--square",
        className,
      )}
    >
      {dot && <span className="gc-badge__dot" />}
      {icon && <Icon name={icon} />}
      {children}
    </span>
  );
}
