"use client";

import { useState, type CSSProperties, type InputHTMLAttributes } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export interface SearchFieldProps
  extends Omit<InputHTMLAttributes<HTMLInputElement>, "size" | "value" | "onChange" | "type" | "style"> {
  value?: string;
  onChange?: (valor: string) => void;
  placeholder?: string;
  /** Dica de atalho ("/"), mostrada quando o campo está vazio. */
  shortcut?: string;
  size?: "sm" | "md" | "lg";
  style?: CSSProperties;
}

/** Busca com lupa, botão de limpar e dica de atalho. */
export function SearchField({ value, onChange, placeholder = "Buscar", shortcut, size = "md", style, ...rest }: SearchFieldProps) {
  const [interno, setInterno] = useState(value ?? "");
  const atual = value ?? interno;
  const mudar = (v: string) => {
    setInterno(v);
    onChange?.(v);
  };
  return (
    <div className={cx("gc-input", size !== "md" && `gc-input--${size}`)} style={style} role="search">
      <Icon name="magnifying-glass" />
      <input
        type="search"
        value={atual}
        placeholder={placeholder}
        aria-label={placeholder}
        onChange={(e) => mudar(e.target.value)}
        {...rest}
      />
      {atual ? (
        <button type="button" className="gc-input__clear" aria-label="Limpar busca" onClick={() => mudar("")}>
          <Icon name="x" size={14} />
        </button>
      ) : shortcut ? (
        <kbd className="gc-input__kbd">{shortcut}</kbd>
      ) : null}
    </div>
  );
}
