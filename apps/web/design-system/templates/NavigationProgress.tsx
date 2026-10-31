import { cx } from "../lib/cx";

export interface NavigationProgressProps {
  /** Dentro de outra página (vitrine): sem `position: fixed`. */
  embedded?: boolean;
}

/**
 * Barra fina no topo da tela enquanto a próxima página não chega: a resposta
 * ao clique, antes de qualquer dado. Só aparece depois de um instante, para não
 * piscar em navegação rápida. Quem decide quando mostrar é o app.
 */
export function NavigationProgress({ embedded = false }: NavigationProgressProps) {
  return <div className={cx("gc-navprogress", embedded && "gc-navprogress--embedded")} role="progressbar" aria-label="Carregando a página" />;
}
