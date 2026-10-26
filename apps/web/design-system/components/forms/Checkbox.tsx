"use client";

import { useEffect, useRef, type InputHTMLAttributes, type ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface CheckboxProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label?: ReactNode;
  description?: ReactNode;
  /** "Selecionar todos" com parte marcada. */
  indeterminate?: boolean;
  invalid?: boolean;
}

/** Caixa de marcação com rótulo e descrição opcionais. */
export function Checkbox({ label, description, indeterminate, invalid, className, ...rest }: CheckboxProps) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = !!indeterminate;
  }, [indeterminate]);
  const caixa = <input ref={ref} type="checkbox" aria-invalid={invalid || undefined} {...rest} />;
  if (!label) return <span className={cx("gc-check", className)}>{caixa}</span>;
  return (
    <label className={cx("gc-check", className)}>
      {caixa}
      <span className="gc-check__text">
        <span>{label}</span>
        {description && <span className="gc-check__desc">{description}</span>}
      </span>
    </label>
  );
}
