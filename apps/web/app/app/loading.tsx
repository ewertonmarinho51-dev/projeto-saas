import { Card, Skeleton, SkeletonText } from "@/design-system";

/**
 * Enquanto a página da área autenticada busca os dados na API: marcadores
 * no formato do cabeçalho e dos cartões, dentro da casca (que já está
 * montada). Nada de número de mentira no lugar do real.
 */
export default function Carregando() {
  return (
    <div className="grid gap-6" aria-busy="true" aria-live="polite">
      <span className="gc-sr-only">Carregando</span>
      <div className="grid gap-2">
        <Skeleton width="30%" height="var(--space-6)" />
        <Skeleton width="55%" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Card key={i}>
            <SkeletonText lines={3} />
          </Card>
        ))}
      </div>
      <Card>
        <SkeletonText lines={5} />
      </Card>
    </div>
  );
}
