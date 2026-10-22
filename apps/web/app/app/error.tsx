"use client";

import Link from "next/link";

import { botaoSecundario } from "@/components/ui";

/**
 * Falha ao carregar dados da API. Sem detalhe técnico na tela: o
 * identificador da requisição fica no log do servidor.
 */
export default function Erro({ reset }: { error: Error; reset: () => void }) {
  return (
    <div role="alert" className="grid gap-4 rounded-[var(--radius-ui)] border border-linha bg-superficie p-8">
      <h1 className="text-lg font-semibold">Não foi possível carregar esta página</h1>
      <p className="max-w-[56ch] text-sm text-secundario">
        O serviço pode estar indisponível ou sua sessão pode ter expirado.
      </p>
      <div className="flex flex-wrap gap-3">
        <button type="button" onClick={reset} className={botaoSecundario}>
          Tentar de novo
        </button>
        <Link href="/entrar" className={botaoSecundario}>
          Entrar novamente
        </Link>
      </div>
    </div>
  );
}
