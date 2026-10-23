"use client";

import { Fragment, useEffect, useRef, useState, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export interface MenuItem {
  label?: string;
  icon?: IconName;
  shortcut?: string;
  danger?: boolean;
  disabled?: boolean;
  onSelect?: () => void;
  separator?: boolean;
  group?: string;
}

export interface MenuProps {
  trigger?: (estado: { open: boolean; toggle: () => void }) => ReactNode;
  items: MenuItem[];
  align?: "start" | "end";
  defaultOpen?: boolean;
  /** Lista estática, sem gatilho nem camada flutuante. */
  inline?: boolean;
}

/**
 * Menu de ações ("Mais ações" da linha, transbordo). Fecha no clique fora
 * e no Esc.
 */
export function Menu({ trigger, items, align = "start", defaultOpen = false, inline = false }: MenuProps) {
  const [open, setOpen] = useState(defaultOpen);
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!open || inline) return;
    const fora = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", fora);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", fora);
      document.removeEventListener("keydown", esc);
    };
  }, [open, inline]);

  const lista = (
    <div role="menu" className={cx("gc-menu", !inline && "gc-menu--floating", align === "end" && "gc-menu--end")}>
      {items.map((it, i) => (
        <Fragment key={i}>
          {it.separator ? (
            <div className="gc-menu__sep" role="separator" />
          ) : it.group ? (
            <div className="gc-menu__label">{it.group}</div>
          ) : (
            <button
              role="menuitem"
              type="button"
              aria-disabled={it.disabled || undefined}
              className={cx("gc-menu__item", it.danger && "gc-menu__item--danger")}
              onClick={() => {
                if (it.disabled) return;
                it.onSelect?.();
                if (!inline) setOpen(false);
              }}
            >
              {it.icon && <Icon name={it.icon} />}
              <span>{it.label}</span>
              {it.shortcut && <span className="gc-menu__shortcut">{it.shortcut}</span>}
            </button>
          )}
        </Fragment>
      ))}
    </div>
  );

  if (inline) return lista;
  return (
    <span className="gc-menu-anchor" ref={ref}>
      {trigger?.({ open, toggle: () => setOpen((o) => !o) })}
      {open && lista}
    </span>
  );
}
