"use client";

import { useEffect, useRef, type CSSProperties, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Icon } from "../core/Icon";

export type RowKey = string | number;

export interface DataTableColumn<T> {
  key: string;
  label: ReactNode;
  align?: "left" | "right" | "center";
  sortable?: boolean;
  width?: number | string;
  /** Sem render, mostra `row[key]`. */
  render?: (row: T) => ReactNode;
}

export interface SortState {
  key: string;
  dir: "asc" | "desc";
}

export interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  /** Campo que identifica a linha. Padrão: "id". */
  rowKey?: keyof T & string;
  selectable?: boolean;
  selected?: RowKey[];
  onSelect?: (chaves: RowKey[]) => void;
  sort?: SortState;
  onSort?: (s: SortState) => void;
  compact?: boolean;
  caption?: string;
  empty?: ReactNode;
  onRowClick?: (row: T) => void;
  minWidth?: number | string;
}

/**
 * Tabela densa, ordenável e selecionável. Dentro de TableContainer (borda
 * e rolagem horizontal no celular) ou de Card flush. Número à direita,
 * tabular. Linha com `_muted: true` fica apagada (referência fora do
 * cálculo). Tabela de preço não vira cartão no celular: rola.
 *
 * Cliente: `render` é função, então a tabela é montada dentro de um
 * componente cliente.
 */
export function DataTable<T extends object>({
  columns,
  rows,
  rowKey,
  selectable = false,
  selected = [],
  onSelect,
  sort,
  onSort,
  compact = false,
  caption,
  empty = "Nenhum registro encontrado.",
  onRowClick,
  minWidth,
}: DataTableProps<T>) {
  const chaveDe = (r: T): RowKey => (r as Record<string, unknown>)[rowKey ?? "id"] as RowKey;
  const todas = rows.length > 0 && selected.length === rows.length;
  const algumas = selected.length > 0 && !todas;
  const cabecalho = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (cabecalho.current) cabecalho.current.indeterminate = algumas;
  }, [algumas]);
  const alternar = (k: RowKey) => onSelect?.(selected.includes(k) ? selected.filter((x) => x !== k) : [...selected, k]);
  const estilo: CSSProperties | undefined = minWidth ? { minWidth } : undefined;

  return (
    <table className={cx("gc-table", compact && "gc-table--compact")} style={estilo}>
      {caption && <caption className="gc-sr-only">{caption}</caption>}
      <thead>
        <tr>
          {selectable && (
            <th className="gc-table__check">
              <span className="gc-check">
                <input
                  ref={cabecalho}
                  type="checkbox"
                  aria-label="Selecionar todos"
                  checked={todas}
                  onChange={() => onSelect?.(todas ? [] : rows.map(chaveDe))}
                />
              </span>
            </th>
          )}
          {columns.map((c) => {
            const ativa = sort?.key === c.key;
            return (
              <th
                key={c.key}
                scope="col"
                data-align={c.align}
                style={c.width ? { width: c.width } : undefined}
                aria-sort={ativa ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                {c.sortable ? (
                  <button
                    type="button"
                    className="gc-table__sort"
                    data-active={ativa || undefined}
                    onClick={() => onSort?.({ key: c.key, dir: ativa && sort?.dir === "asc" ? "desc" : "asc" })}
                  >
                    {c.label}
                    <Icon name={ativa ? (sort?.dir === "asc" ? "caret-up" : "caret-down") : "caret-up-down"} />
                  </button>
                ) : (
                  c.label
                )}
              </th>
            );
          })}
        </tr>
      </thead>
      <tbody>
        {rows.length === 0 && (
          <tr>
            <td className="gc-table__empty" colSpan={columns.length + (selectable ? 1 : 0)}>
              {empty}
            </td>
          </tr>
        )}
        {rows.map((r) => {
          const k = chaveDe(r);
          const marcada = selected.includes(k);
          const apagada = (r as { _muted?: boolean })._muted;
          return (
            <tr
              key={k}
              aria-selected={selectable ? marcada : undefined}
              data-muted={apagada || undefined}
              data-clickable={onRowClick ? true : undefined}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
            >
              {selectable && (
                <td className="gc-table__check" onClick={(e) => e.stopPropagation()}>
                  <span className="gc-check">
                    <input type="checkbox" aria-label={`Selecionar linha ${k}`} checked={marcada} onChange={() => alternar(k)} />
                  </span>
                </td>
              )}
              {columns.map((c) => (
                <td key={c.key} data-align={c.align}>
                  {c.render ? c.render(r) : ((r as Record<string, unknown>)[c.key] as ReactNode)}
                </td>
              ))}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function TableContainer({ children, style }: { children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="gc-table-wrap" style={style}>
      {children}
    </div>
  );
}
