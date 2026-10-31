import Link from "next/link";
import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export type ButtonVariant = "primary" | "secondary" | "subtle" | "ghost" | "link" | "danger" | "danger-subtle";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** sm 32 px (tabela, barra), md 40 px (padrão), lg 44 px (formulário, login). */
  size?: "sm" | "md" | "lg";
  icon?: IconName;
  iconRight?: IconName;
  loading?: boolean;
  block?: boolean;
  /** Vira link (`next/link`) com a aparência de botão. */
  href?: string;
  /**
   * Com `href`: carrega a página inteira, sem a navegação interna do Next. Para
   * rota cujos cabeçalhos de documento importam (a CSP só vale na carga da página).
   */
  reloadDocument?: boolean;
  children?: ReactNode;
}

/** Classes do botão, para quem precisa da aparência sem o componente (ex.: `<Link>` em server component). */
export function buttonClasses({
  variant = "primary",
  size = "md",
  block = false,
  className,
}: Pick<ButtonProps, "variant" | "size" | "block" | "className"> = {}): string {
  return cx("gc-btn", `gc-btn--${variant}`, size !== "md" && `gc-btn--${size}`, block && "gc-btn--block", className);
}

/**
 * Botão de ação. Um primário por região da tela; secundário para ações
 * paralelas; subtle/ghost para pouca ênfase; danger só na confirmação
 * destrutiva — e o rótulo repete o objeto ("Excluir processo", não "Sim").
 * Rótulo é verbo, em caixa de frase.
 */
export function Button({
  variant = "primary",
  size = "md",
  icon,
  iconRight,
  loading = false,
  block = false,
  disabled,
  href,
  reloadDocument = false,
  type = "button",
  className,
  children,
  ...rest
}: ButtonProps) {
  const classes = buttonClasses({ variant, size, block, className });
  const miolo = (
    <>
      {loading ? <span className="gc-spinner" aria-hidden="true" /> : icon ? <Icon name={icon} /> : null}
      {children}
      {iconRight && !loading ? <Icon name={iconRight} /> : null}
    </>
  );
  if (href && reloadDocument) {
    return (
      <a href={href} className={classes} aria-disabled={disabled || undefined}>
        {miolo}
      </a>
    );
  }
  if (href) {
    return (
      <Link href={href} className={classes} aria-disabled={disabled || undefined}>
        {miolo}
      </Link>
    );
  }
  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || loading}
      data-loading={loading || undefined}
      aria-busy={loading || undefined}
      {...rest}
    >
      {miolo}
    </button>
  );
}
