/**
 * Classes dos primitivos, num lugar só — agora apontando para o design
 * system (`@/design-system`). Botão e cartão SÃO as classes gc-*: mesma
 * altura (44 px), corpo de 15 px, raio de 8 px, hover 600 → 700 e recuo
 * de 1 px no `:active` que já existiam aqui. Campo continua utilitário,
 * mas só com token.
 *
 * Código novo não usa estas constantes: usa os componentes
 * (`<Button size="lg">`, `<Card>`, `<Field>` + `<Input>`).
 */
import { buttonClasses } from "@/design-system";

export const botaoPrimario = buttonClasses({ variant: "primary", size: "lg" });

export const botaoSecundario = buttonClasses({ variant: "secondary", size: "lg" });

export const campo =
  "h-[var(--control-lg)] w-full rounded-[var(--radius-ui)] border border-campo bg-superficie px-3 text-[length:var(--gc-fs-md)] text-texto placeholder:text-secundario transition-colors hover:border-texto aria-[invalid=true]:border-erro";

export const rotulo = "text-sm font-medium text-texto";

export const cartao = "gc-card";
