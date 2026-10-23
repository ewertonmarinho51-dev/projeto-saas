import type { CSSProperties } from "react";

import { cx } from "../../lib/cx";

export interface SkeletonProps {
  width?: number | string;
  height?: number | string;
  circle?: boolean;
  radius?: number | string;
  style?: CSSProperties;
}

/** Marcador de carregamento no formato do conteúdo final; o brilho para com movimento reduzido. */
export function Skeleton({ width = "100%", height = 12, circle, radius, style }: SkeletonProps) {
  return (
    <span
      className={cx("gc-skeleton", circle && "gc-skeleton--circle")}
      aria-hidden="true"
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

export function SkeletonText({ lines = 3 }: { lines?: number }) {
  return (
    <span className="gc-skeleton-text" aria-busy="true" aria-label="Carregando">
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} width={i === lines - 1 ? "60%" : "100%"} />
      ))}
    </span>
  );
}
