import { Skeleton, SkeletonText } from "../components/feedback/Skeleton";
import { cx } from "../lib/cx";

export interface PageSkeletonProps {
  className?: string;
}

/**
 * Formato genérico de uma página enquanto a próxima não chega: título, resumo e
 * bloco de conteúdo. Não pede nada ao servidor, então serve também às rotas que
 * precisam responder 404 de verdade e por isso não têm `loading.tsx`.
 */
export function PageSkeleton({ className }: PageSkeletonProps) {
  return (
    <div className={cx("gc-pageskeleton", className)} role="status" aria-label="Carregando a página" data-testid="esqueleto-de-pagina">
      <div className="gc-pageskeleton__head">
        <Skeleton width="40%" height="var(--space-8)" />
        <Skeleton width="60%" />
      </div>
      <div className="gc-pageskeleton__body">
        <SkeletonText lines={2} />
        <SkeletonText lines={2} />
        <SkeletonText lines={2} />
      </div>
    </div>
  );
}
