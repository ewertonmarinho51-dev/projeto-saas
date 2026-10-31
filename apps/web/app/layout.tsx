import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import { headers } from "next/headers";

import { FocoDeRota } from "@/components/foco-de-rota";
import { SITE_URL } from "@/components/site";

import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: { default: "Gov Conect", template: "%s | Gov Conect" },
  description:
    "Planejamento de contratações públicas sob a Lei 14.133/2021, com revisão humana e preços de fonte verificável.",
  icons: { icon: "/favicon-32.png" },
};

// Vale antes de o CSS chegar: a tela nunca pinta escura, nem por um instante.
export const viewport: Viewport = { colorScheme: "only light" };

export default async function LayoutRaiz({ children }: { children: React.ReactNode }) {
  // Ler o cabeçalho torna TODA página dinâmica — e é o que se quer: com
  // CSP por nonce, página pré-renderizada sairia sem nonce nos scripts e
  // o navegador os bloquearia. Página pública dinâmica custa pouco aqui.
  await headers();
  // `data-theme` sai do servidor: o tema não depende de JavaScript, então
  // não há flash nem divergência de hidratação.
  return (
    <html lang="pt-BR" data-theme="light" className={`${GeistSans.variable} ${GeistMono.variable}`}>
      <body className="min-h-[100dvh]">
        <FocoDeRota />
        <a
          href="#conteudo"
          className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-[var(--radius-ui)] focus:bg-superficie focus:px-4 focus:py-2"
        >
          Pular para o conteúdo
        </a>
        {children}
      </body>
    </html>
  );
}
