import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { Vitrine } from "@/design-system/vitrine";

export const metadata: Metadata = {
  title: "Design system",
  robots: { index: false, follow: false },
};

/**
 * Vitrine do design system. Em desenvolvimento, sempre; em produção, só
 * com GOVCONECT_VITRINE=1 — é página de bancada, não do produto (e, na
 * convivência, o Caddy nem manda /design-system para o Next).
 */
export default function PaginaDesignSystem() {
  if (process.env.NODE_ENV === "production" && process.env.GOVCONECT_VITRINE !== "1") notFound();
  return <Vitrine />;
}
