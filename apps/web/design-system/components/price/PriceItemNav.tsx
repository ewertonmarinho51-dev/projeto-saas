"use client";

import { useEffect, useRef } from "react";

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
  /**
   * Lista longa (centenas de itens): a lista rola dentro do cartão, até a
   * altura de `--gc-itemnav-max`, e abre com o item atual à vista.
   */
  scroll?: boolean;
}

const SITUACAO: Record<PriceItemStatus, { icone: IconName; rotulo: string }> = {
  done: { icone: "check-circle", rotulo: "Concluído" },
  review: { icone: "eye", rotulo: "Em revisão" },
  pending: { icone: "hourglass-medium", rotulo: "Pendente" },
  blocked: { icone: "warning-octagon", rotulo: "Com impedimento" },
};

/** Navegador dos itens de uma pesquisa: número, descrição, nº de referências, estimativa e situação com rótulo. */
export function PriceItemNav({ items, activeId, onSelect, minRefs = 3, scroll = false }: PriceItemNavProps) {
  const lista = useRef<HTMLUListElement>(null);

  // Só a própria lista rola (scrollTop), nunca a página: `scrollIntoView`
  // arrastaria a janela junto quando a lista está fora da tela. Uma vez por
  // item atual: se a lista ainda não tem altura (estilo chegando, painel
  // oculto), espera o primeiro tamanho de verdade e para de observar.
  useEffect(() => {
    const ul = lista.current;
    if (!scroll || !ul) return;
    const centralizar = () => {
      if (ul.clientHeight === 0 || ul.scrollHeight <= ul.clientHeight) return false;
      const atual = ul.querySelector<HTMLElement>('[aria-current="true"]');
      if (!atual) return true;
      const topo = atual.offsetTop; // a lista com rolagem é `position: relative`
      if (topo < ul.scrollTop || topo + atual.offsetHeight > ul.scrollTop + ul.clientHeight) {
        ul.scrollTop = Math.max(0, topo - (ul.clientHeight - atual.offsetHeight) / 2);
      }
      return true;
    };
    if (centralizar() || typeof ResizeObserver === "undefined") return;
    const observador = new ResizeObserver(() => centralizar() && observador.disconnect());
    observador.observe(ul);
    return () => observador.disconnect();
  }, [scroll, activeId]);

  return (
    <ul ref={lista} className={cx("gc-itemnav", scroll && "gc-itemnav--scroll")} role="list">
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
                  {it.refs != null && <span className={cx(poucas && "gc-itemnav__refs--low")}>{it.refs} ref.</span>}
                  {it.unit && <span>{it.refs != null && "· "}{it.unit}</span>}
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
