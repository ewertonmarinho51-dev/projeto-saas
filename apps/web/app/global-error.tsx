"use client";

import { Button, EmptyState } from "@/design-system";

import "./globals.css";

/**
 * Falha no próprio layout raiz. Substitui o `<html>` inteiro, então repete
 * o tema: a página padrão do Next obedeceria ao tema do aparelho.
 */
export default function ErroGlobal({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="pt-BR" data-theme="light">
      <body className="min-h-[100dvh]">
        <main id="conteudo" className="gc-base grid min-h-[100dvh] place-items-center bg-canvas px-[var(--page-padding-x)]">
          <EmptyState
            icon="warning"
            title={
              <span role="heading" aria-level={1}>
                Não foi possível abrir a Gov Conect
              </span>
            }
            description="O serviço pode estar indisponível no momento."
            actions={
              <Button icon="arrow-clockwise" onClick={reset}>
                Tentar de novo
              </Button>
            }
          />
        </main>
      </body>
    </html>
  );
}
