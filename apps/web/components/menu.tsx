"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

export function LinkDoMenu({
  href,
  icone,
  children,
}: {
  href: string;
  icone: React.ReactNode;
  children: React.ReactNode;
}) {
  const caminho = usePathname();
  const ativo = href === "/app" ? caminho === "/app" : caminho === href || caminho.startsWith(`${href}/`);
  return (
    <Link
      href={href}
      aria-current={ativo ? "page" : undefined}
      className={`inline-flex shrink-0 items-center gap-2.5 rounded-[var(--radius-ui)] px-3 py-2 text-sm transition-colors ${
        ativo
          ? "bg-acento-claro font-medium text-acento"
          : "text-secundario hover:bg-canvas hover:text-texto"
      }`}
    >
      {icone}
      {children}
    </Link>
  );
}
