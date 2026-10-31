import type { Metadata } from "next";

import { Button, EmptyState } from "@/design-system";

export const metadata: Metadata = { title: "Página não encontrada", robots: { index: false, follow: false } };

/**
 * 404 fora da área autenticada. Existe também por causa do tema: a página
 * padrão do Next obedece ao `prefers-color-scheme` e sairia preta em
 * aparelho configurado no escuro.
 */
export default function PaginaNaoEncontrada() {
  return (
    <main id="conteudo" className="gc-base grid min-h-[100dvh] place-items-center bg-canvas px-[var(--page-padding-x)]">
      <EmptyState
        icon="magnifying-glass"
        title={
          <span role="heading" aria-level={1}>
            Página não encontrada
          </span>
        }
        description="O endereço pode ter mudado ou não existir mais."
        actions={
          <Button icon="house" href="/">
            Ir para o início
          </Button>
        }
      />
    </main>
  );
}
