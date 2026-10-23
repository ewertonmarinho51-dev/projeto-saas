import Link from "next/link";
import type { MouseEvent } from "react";

import { Icon } from "../core/Icon";

export interface BreadcrumbItem {
  label: string;
  href?: string;
  onClick?: (e: MouseEvent<HTMLAnchorElement>) => void;
}

export interface BreadcrumbsProps {
  items: BreadcrumbItem[];
}

/** Trilha de navegação; o último item é a página atual e não é link. */
export function Breadcrumbs({ items }: BreadcrumbsProps) {
  return (
    <nav className="gc-breadcrumbs" aria-label="Trilha de navegação">
      <ol>
        {items.map((it, i) => {
          const ultimo = i === items.length - 1;
          return (
            <li key={i}>
              {ultimo ? (
                <span aria-current="page">{it.label}</span>
              ) : (
                <Link href={it.href ?? "#"} onClick={it.onClick}>
                  {it.label}
                </Link>
              )}
              {!ultimo && <Icon name="caret-right" />}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
