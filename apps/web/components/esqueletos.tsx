import { Card, Skeleton, SkeletonText } from "@/design-system";

/**
 * Formato das telas de lista enquanto os dados vêm. Usados em `<Suspense>`
 * dentro da página, e só em tela que nunca chama `notFound()`: com o corpo já
 * enviado, um 404 sairia como 200.
 */
export function EsqueletoDeLista({ linhas = 5 }: { linhas?: number }) {
  return (
    <Card flush>
      <ul className="divide-y divide-linha" data-testid="esqueleto">
        {Array.from({ length: linhas }, (_, i) => (
          <li key={i} className="px-5 py-3.5">
            <SkeletonText lines={2} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function EsqueletoDoPainel() {
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i}>
            <Skeleton height="var(--space-16)" />
          </Card>
        ))}
      </div>
      <EsqueletoDeLista />
    </>
  );
}
