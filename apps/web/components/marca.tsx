import { Logo as LogoDoSistema } from "@/design-system";

/**
 * Marca oficial, pelo design system: PNG transparente do logo
 * vetorizado, sem placa branca (o cliente confirmou em 23/10/2026 que a
 * marca nunca vai num quadrado branco). Estes dois nomes ficam para não
 * mexer nas páginas que já os usam; código novo usa `<Logo>` de
 * `@/design-system`.
 */
export function Logo({ tamanho = 32, prioridade = false }: { tamanho?: number; prioridade?: boolean }) {
  return <LogoDoSistema size={tamanho} withName={false} name="" priority={prioridade} />;
}

export function MarcaComNome({ href = "/" }: { href?: string }) {
  return <LogoDoSistema size={32} href={href} />;
}
