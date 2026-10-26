import type { ReactNode } from "react";

export interface PriceMapCell {
  value: ReactNode;
  /** Fora do cálculo: riscado, com texto para leitor de tela. */
  excluded?: boolean;
}

export interface PriceMapRow {
  id: string | number;
  n: string;
  desc: ReactNode;
  unit?: string;
  qty?: ReactNode;
  cells?: Record<string, PriceMapCell>;
  estimate: ReactNode;
  total?: ReactNode;
}

export interface PriceMapSource {
  key: string;
  label: string;
  sub?: string;
}

export interface PriceMapTableProps {
  sources: PriceMapSource[];
  rows: PriceMapRow[];
  total?: ReactNode;
  totalLabel?: string;
  method?: string;
}

/** Largura mínima: colunas fixas + uma coluna por referência (rola na horizontal, não espreme). */
const LARGURA_FIXA = 640;
const LARGURA_REFERENCIA = 110;

/**
 * Mapa de preços: itens × referências. Valor fora do cálculo riscado, a
 * coluna da estimativa adotada em azul e o total global no rodapé.
 */
export function PriceMapTable({ sources, rows, total, totalLabel = "Valor global estimado", method = "Média" }: PriceMapTableProps) {
  return (
    <div className="gc-table-wrap">
      <table className="gc-table gc-table--compact gc-pmap" style={{ minWidth: LARGURA_FIXA + sources.length * LARGURA_REFERENCIA }}>
        <caption className="gc-sr-only">Mapa de preços por item e referência</caption>
        <thead>
          <tr>
            <th scope="col">Nº</th>
            <th scope="col">Item</th>
            <th scope="col" data-align="right">
              Qtd.
            </th>
            {sources.map((s) => (
              <th key={s.key} scope="col" data-align="right">
                {s.label}
                {s.sub && <span className="gc-table__sub">{s.sub}</span>}
              </th>
            ))}
            <th scope="col" data-align="right" className="gc-pmap__est">
              {method}
            </th>
            <th scope="col" data-align="right">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id}>
              <td className="gc-mono gc-pmap__n">{r.n}</td>
              <td>
                {r.desc}
                {r.unit && <span className="gc-table__sub">{r.unit}</span>}
              </td>
              <td data-align="right">{r.qty}</td>
              {sources.map((s) => {
                const c = r.cells?.[s.key];
                return (
                  <td key={s.key} data-align="right" className={c?.excluded ? "gc-pmap__out" : undefined}>
                    {c ? (
                      <>
                        {c.value}
                        {c.excluded && <span className="gc-sr-only"> (fora do cálculo)</span>}
                      </>
                    ) : (
                      <span className="gc-pmap__empty">—</span>
                    )}
                  </td>
                );
              })}
              <td data-align="right" className="gc-pmap__est">
                <b>{r.estimate}</b>
              </td>
              <td data-align="right">{r.total}</td>
            </tr>
          ))}
        </tbody>
        {total && (
          <tfoot>
            <tr>
              <td colSpan={4 + sources.length} data-align="right">
                {totalLabel}
              </td>
              <td colSpan={1} />
              <td data-align="right">
                <b>{total}</b>
              </td>
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}
