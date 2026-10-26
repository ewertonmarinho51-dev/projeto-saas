import type { CSSProperties, InputHTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "size" | "prefix"> {
  icon?: IconName;
  /** Ex.: "R$". */
  prefix?: ReactNode;
  /** Ex.: "UN", ou um botão (mostrar senha). */
  suffix?: ReactNode;
  size?: "sm" | "md" | "lg";
  invalid?: boolean;
  /** Mostra o "x" de limpar quando há valor. */
  clearable?: boolean;
  onClear?: () => void;
  /** Estilo do contêiner (largura num layout). */
  style?: CSSProperties;
}

/** Texto de uma linha, com ícone, prefixo/sufixo e os estados inválido e somente leitura. */
export function Input({
  icon,
  prefix,
  suffix,
  size = "md",
  invalid,
  disabled,
  readOnly,
  clearable,
  onClear,
  className,
  style,
  ...rest
}: InputProps) {
  return (
    <div
      className={cx("gc-input", size !== "md" && `gc-input--${size}`, className)}
      style={style}
      data-invalid={invalid || undefined}
      data-disabled={disabled || undefined}
      data-readonly={readOnly || undefined}
    >
      {icon && <Icon name={icon} />}
      {prefix && <span className="gc-input__affix">{prefix}</span>}
      <input disabled={disabled} readOnly={readOnly} aria-invalid={invalid || undefined} {...rest} />
      {clearable && rest.value ? (
        <button type="button" className="gc-input__clear" aria-label="Limpar" onClick={onClear}>
          <Icon name="x" size={14} />
        </button>
      ) : null}
      {suffix && <span className="gc-input__affix">{suffix}</span>}
    </div>
  );
}
