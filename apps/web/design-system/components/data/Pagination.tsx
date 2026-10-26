import { formatarNumero } from "../../lib/formato";
import { Icon } from "../core/Icon";

export interface PaginationProps {
  page?: number;
  pageSize?: number;
  total: number;
  onChange?: (pagina: number) => void;
}

/** Paginas visíveis: primeira, última e vizinhas da atual; o resto vira "…". */
export function paginasVisiveis(pagina: number, paginas: number): (number | "…")[] {
  const lista: (number | "…")[] = [];
  for (let p = 1; p <= paginas; p++) {
    if (p === 1 || p === paginas || Math.abs(p - pagina) <= 1) lista.push(p);
    else if (lista[lista.length - 1] !== "…") lista.push("…");
  }
  return lista;
}

/** Paginação com o resumo do intervalo ("1–10 de 48") e lista compacta de páginas. */
export function Pagination({ page = 1, pageSize = 10, total, onChange }: PaginationProps) {
  const paginas = Math.max(1, Math.ceil(total / pageSize));
  const de = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const ate = Math.min(total, page * pageSize);
  return (
    <nav className="gc-pagination" aria-label="Paginação">
      <span className="gc-num">
        {formatarNumero(de)}–{formatarNumero(ate)} de {formatarNumero(total)}
      </span>
      <span className="gc-pagination__pages">
        <button type="button" className="gc-page" aria-label="Página anterior" disabled={page <= 1} onClick={() => onChange?.(page - 1)}>
          <Icon name="caret-left" />
        </button>
        {paginasVisiveis(page, paginas).map((p, i) =>
          p === "…" ? (
            <span key={`e${i}`} className="gc-page-ellipsis">
              …
            </span>
          ) : (
            <button
              key={p}
              type="button"
              className="gc-page"
              aria-current={p === page ? "page" : undefined}
              onClick={() => onChange?.(p)}
            >
              {p}
            </button>
          ),
        )}
        <button
          type="button"
          className="gc-page"
          aria-label="Próxima página"
          disabled={page >= paginas}
          onClick={() => onChange?.(page + 1)}
        >
          <Icon name="caret-right" />
        </button>
      </span>
    </nav>
  );
}
