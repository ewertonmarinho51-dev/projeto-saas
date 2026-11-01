"use client";

import Link from "next/link";
import { useState, type ComponentProps } from "react";

/**
 * Link que só faz prefetch quando a pessoa mostra que vai clicar (ponteiro em
 * cima, foco ou toque), nunca por aparecer na tela. O padrão do Next dispararia um
 * pedido por link visível: uma lista de 20 processos mais o menu viraria 30
 * pedidos autenticados por tela, na VPS de 1 vCPU.
 */
export function LinkPorIntencao({ onMouseEnter, onFocus, onTouchStart, ...props }: ComponentProps<typeof Link>) {
  const [intencao, setIntencao] = useState(false);
  return (
    <Link
      {...props}
      prefetch={intencao ? null : false}
      onMouseEnter={(e) => {
        setIntencao(true);
        onMouseEnter?.(e);
      }}
      onFocus={(e) => {
        setIntencao(true);
        onFocus?.(e);
      }}
      onTouchStart={(e) => {
        setIntencao(true);
        onTouchStart?.(e);
      }}
    />
  );
}
