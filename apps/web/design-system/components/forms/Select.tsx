import type { CSSProperties, SelectHTMLAttributes } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export interface SelectOption {
  value: string;
  label: string;
  disabled?: boolean;
}

export interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  options: (string | SelectOption)[];
  placeholder?: string;
  invalid?: boolean;
  size?: "sm" | "md";
  style?: CSSProperties;
}

/** Select nativo com o visual do sistema: mantém a acessibilidade e o seletor do celular. */
export function Select({ options, placeholder, invalid, size = "md", className, style, ...rest }: SelectProps) {
  const semValor = rest.value === undefined && rest.defaultValue === undefined && placeholder;
  return (
    <div
      className={cx("gc-select", size !== "md" && `gc-select--${size}`, className)}
      style={style}
      data-invalid={invalid || undefined}
    >
      <select aria-invalid={invalid || undefined} defaultValue={semValor ? "" : undefined} {...rest}>
        {placeholder && (
          <option value="" disabled>
            {placeholder}
          </option>
        )}
        {options.map((o) =>
          typeof o === "string" ? (
            <option key={o} value={o}>
              {o}
            </option>
          ) : (
            <option key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </option>
          ),
        )}
      </select>
      <Icon name="caret-down" />
    </div>
  );
}
