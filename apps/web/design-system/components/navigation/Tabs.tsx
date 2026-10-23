"use client";

import { useState, type KeyboardEvent } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface TabItem {
  value: string;
  label: string;
  icon?: IconName;
  count?: number | string;
  disabled?: boolean;
}

export interface TabsProps {
  tabs: TabItem[];
  value?: string;
  defaultValue?: string;
  onChange?: (valor: string) => void;
  /** line = abas de seção; segmented = troca de visão compacta. */
  variant?: "line" | "segmented";
  ariaLabel?: string;
}

/** Abas. As setas do teclado andam entre elas. */
export function Tabs({ tabs, value, defaultValue, onChange, variant = "line", ariaLabel }: TabsProps) {
  const [interno, setInterno] = useState(defaultValue ?? tabs[0]?.value);
  const atual = value ?? interno;
  const escolher = (t: TabItem) => {
    if (t.disabled) return;
    setInterno(t.value);
    onChange?.(t.value);
  };
  const teclado = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    const proxima = tabs[(i + (e.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs.length];
    escolher(proxima);
    const botao = e.currentTarget.parentElement?.children[tabs.indexOf(proxima)];
    if (botao instanceof HTMLElement) botao.focus();
  };
  return (
    <div role="tablist" aria-label={ariaLabel} className={cx("gc-tabs", variant === "segmented" && "gc-tabs--segmented")}>
      {tabs.map((t, i) => (
        <button
          key={t.value}
          role="tab"
          type="button"
          className="gc-tab"
          aria-selected={atual === t.value}
          tabIndex={atual === t.value ? 0 : -1}
          disabled={t.disabled}
          onClick={() => escolher(t)}
          onKeyDown={(e) => teclado(e, i)}
        >
          {t.icon && <Icon name={t.icon} />}
          {t.label}
          {t.count != null && <span className="gc-tab__count">{t.count}</span>}
        </button>
      ))}
    </div>
  );
}
