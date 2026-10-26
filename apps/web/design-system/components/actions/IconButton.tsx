import type { ButtonHTMLAttributes } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: IconName;
  /** Obrigatório: vira aria-label e title. */
  label: string;
  variant?: "ghost" | "secondary" | "primary" | "danger";
  size?: "sm" | "md" | "lg";
}

/** Botão quadrado só de ícone. O nome acessível é obrigatório. */
export function IconButton({ icon, label, variant = "ghost", size = "md", className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        "gc-iconbtn",
        variant !== "ghost" && `gc-iconbtn--${variant}`,
        size !== "md" && `gc-iconbtn--${size}`,
        className,
      )}
      {...rest}
    >
      <Icon name={icon} />
    </button>
  );
}
