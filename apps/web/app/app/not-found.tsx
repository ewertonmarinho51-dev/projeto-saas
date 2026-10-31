import type { Metadata } from "next";

import { Button, EmptyState } from "@/design-system";

export const metadata: Metadata = { title: "Página não encontrada" };

/**
 * 404 dentro da casca: recurso inexistente ou de outro órgão, sem dizer
 * qual dos dois — confirmar que existe já seria vazamento.
 */
export default function NaoEncontradoNoApp() {
  return (
    <EmptyState
      icon="magnifying-glass"
      title={
        <span role="heading" aria-level={1}>
          Página não encontrada
        </span>
      }
      description="O endereço pode ter mudado, ou este recurso não está disponível para a sua conta."
      actions={
        <Button icon="house" href="/app">
          Voltar ao início
        </Button>
      }
    />
  );
}
