"use client";

import { Alert, Button } from "@/design-system";

/**
 * Falha ao carregar dados da API. Sem detalhe técnico na tela: o
 * identificador da requisição fica no log do servidor.
 */
export default function Erro({ reset }: { error: Error; reset: () => void }) {
  return (
    <Alert
      variant="error"
      title="Não foi possível carregar esta página"
      actions={
        <>
          <Button size="sm" variant="secondary" icon="arrow-clockwise" onClick={reset}>
            Tentar de novo
          </Button>
          <Button size="sm" variant="ghost" icon="sign-in" href="/entrar">
            Entrar novamente
          </Button>
        </>
      }
    >
      O serviço pode estar indisponível ou sua sessão pode ter expirado.
    </Alert>
  );
}
