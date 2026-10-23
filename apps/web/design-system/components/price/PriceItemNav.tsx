import { cx } from "../../lib/cx";
import { Icon, type IconName } from "../core/Icon";

export type PriceItemStatus = "done" | "review" | "pending" | "blocked";

export interface PriceItem {
  id: string | number;
  n: string;
  title: string;
  unit?: string;
  refs?: number;
  value?: string;
  status?: PriceItemStatus;
}

export interface PriceItemNavProps {
  items: PriceItem[];
  activeId?: string | number;
  onSelect?: (id: string | number) => void;
  /** Destaca em âmbar o item com menos referências que isto. */
  minRefs?: number;
}

const SITUACAO: Record<PriceItemStatus, { icone: IconName; rotulo: string }> = {
  done: { icone: "check-circle", rotulo: "Concluído" },
  review: { icone: "eye", rotulo: "Em revisão" },
  pending: { icone: "hourglass-medium", rotulo: "Pendente" },
  blocked: { icone: "warning-octagon", rotulo: "Com impedimento" },
};

/** Navegador dos itens de uma pesquisa: número, descrição, nº de referências, estimativa e situação com rótulo. */
export function PriceItemNav({ items, activeId, onSelect, minRefs = 3 }: PriceItemNavProps) {
  return (
    <ul className="gc-itemnav" role="list">
      {items.map((it) => {
        const status = it.status ?? "pending";
        const s = SITUACAO[status];
        const poucas = it.refs != null && it.refs < minRefs;
        return (
          <li key={it.id}>
            <button
              type="button"
              className="gc-itemnav__btn"
              aria-current={it.id === activeId ? "true" : undefined}
              onClick={() => onSelect?.(it.id)}
            >
              <span className="gc-itemnav__n">{it.n}</span>
              <span className="gc-itemnav__body">
                <span className="gc-itemnav__title">{it.title}</span>
                <span className="gc-itemnav__meta">
                  <span className={cx(poucas && "gc-itemnav__refs--low")}>{it.refs ?? 0} ref.</span>
                  {it.unit && <span>· {it.unit}</span>}
                  {it.value && <span className="gc-num">· {it.value}</span>}
                </span>
              </span>
              <span className="gc-itemnav__status" data-status={status} title={s.rotulo}>
                <Icon name={s.icone} weight="fill" label={s.rotulo} />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
