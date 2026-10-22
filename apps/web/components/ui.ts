/**
 * Classes dos primitivos, num lugar só. Um raio (8px), uma borda (1px),
 * um acento. Hover real e `:active` com recuo de 1px; foco vem do CSS
 * global (`:focus-visible`).
 */
export const botaoPrimario =
  "inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-ui)] bg-acento px-5 text-[15px] font-medium text-sobre-acento transition-colors duration-150 hover:bg-acento-forte active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60";

export const botaoSecundario =
  "inline-flex h-11 items-center justify-center gap-2 whitespace-nowrap rounded-[var(--radius-ui)] border border-linha bg-superficie px-5 text-[15px] font-medium text-texto transition-colors duration-150 hover:border-campo hover:bg-canvas active:translate-y-px";

export const campo =
  "h-11 w-full rounded-[var(--radius-ui)] border border-campo bg-superficie px-3 text-[15px] text-texto placeholder:text-secundario transition-colors hover:border-texto aria-[invalid=true]:border-erro";

export const rotulo = "text-sm font-medium text-texto";

export const cartao = "rounded-[var(--radius-ui)] border border-linha bg-superficie";
