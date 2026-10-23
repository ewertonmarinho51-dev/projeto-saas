import type { InputHTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface SwitchProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  labelPosition?: "start" | "end";
}

/** Liga/desliga que vale na hora (preferência, filtro). Em formulário enviado, use Checkbox. */
export function Switch({ label, labelPosition = "end", className, ...rest }: SwitchProps) {
  return (
    <label className={cx("gc-switch", className)}>
      {labelPosition === "start" && <span>{label}</span>}
      <input type="checkbox" role="switch" {...rest} />
      {labelPosition === "end" && label && <span>{label}</span>}
    </label>
  );
}
