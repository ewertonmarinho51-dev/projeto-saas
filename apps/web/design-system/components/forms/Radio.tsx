"use client";

import { useState, type InputHTMLAttributes, type ReactNode } from "react";

import { cx } from "../../lib/cx";

export interface RadioProps extends Omit<InputHTMLAttributes<HTMLInputElement>, "type"> {
  label: ReactNode;
  description?: ReactNode;
}

/** Escolha única. Até 5 opções, prefira RadioGroup; acima disso, Select. */
export function Radio({ label, description, className, ...rest }: RadioProps) {
  return (
    <label className={cx("gc-check", className)}>
      <input type="radio" {...rest} />
      <span className="gc-check__text">
        <span>{label}</span>
        {description && <span className="gc-check__desc">{description}</span>}
      </span>
    </label>
  );
}

export interface RadioOption {
  value: string;
  label: string;
  description?: string;
  disabled?: boolean;
}

export interface RadioGroupProps {
  name: string;
  options: (string | RadioOption)[];
  /** Controlado; `null` = nada escolhido ainda. */
  value?: string | null;
  defaultValue?: string;
  onChange?: (valor: string) => void;
  legend?: ReactNode;
  /** Opções lado a lado. */
  row?: boolean;
}

export function RadioGroup({ name, options, value, defaultValue, onChange, legend, row = false }: RadioGroupProps) {
  const [interno, setInterno] = useState(defaultValue);
  const atual = value === undefined ? interno : value;
  return (
    <fieldset className={cx("gc-choice-group", row && "gc-choice-group--row")}>
      {legend && <legend className="gc-label gc-choice-group__legend">{legend}</legend>}
      {options.map((o) => {
        const op = typeof o === "string" ? { value: o, label: o } : o;
        return (
          <Radio
            key={op.value}
            name={name}
            value={op.value}
            label={op.label}
            description={"description" in op ? op.description : undefined}
            disabled={"disabled" in op ? op.disabled : undefined}
            checked={atual === op.value}
            onChange={() => {
              setInterno(op.value);
              onChange?.(op.value);
            }}
          />
        );
      })}
    </fieldset>
  );
}
