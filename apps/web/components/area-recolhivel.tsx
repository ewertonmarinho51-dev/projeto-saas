"use client";

import { useState, type ReactNode } from "react";

/**
 * Área que abre fechada ou aberta ao CARREGAR a página e depois respeita a
 * pessoa (pacote de 14/11/2026, UX-04). Com `<details open>` controlado
 * pelo servidor, incluir o 1º item recolhia a área no refresh e escondia a
 * própria mensagem de sucesso.
 */
export function AreaRecolhivel({
  aberta,
  resumo,
  children,
  testId,
}: {
  aberta: boolean;
  resumo: ReactNode;
  children: ReactNode;
  testId?: string;
}) {
  const [aberto, setAberto] = useState(aberta);
  return (
    <details
      open={aberto}
      onToggle={(e) => setAberto((e.currentTarget as HTMLDetailsElement).open)}
      className="group grid gap-3"
      data-testid={testId}
    >
      <summary className="cursor-pointer text-[length:var(--gc-fs-sm)] font-[number:var(--weight-medium)] text-acento">
        {resumo}
      </summary>
      <div className="mt-3 grid gap-3">{children}</div>
    </details>
  );
}
