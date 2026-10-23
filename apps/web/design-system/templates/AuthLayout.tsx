import type { ReactNode } from "react";

import { Logo } from "../components/core/Logo";

export interface AuthLayoutProps {
  /** Frase de marca do painel esquerdo. */
  headline?: ReactNode;
  lead?: ReactNode;
  foot?: ReactNode;
  /** Fundo do painel de marca. Padrão: o fundo claro oficial. Só aqui e em hero; nunca atrás de dado. */
  background?: string;
  /** Dentro de outra página (vitrine, prévia): sem `<main id="conteudo">`, que já existe lá. */
  embedded?: boolean;
  children: ReactNode;
}

/**
 * Tela de entrada dividida: painel de marca à esquerda, formulário à
 * direita (até 360 px). Abaixo de 768 px fica só o formulário. Recriada
 * do ui_kit do export (LoginScreen.jsx).
 */
export function AuthLayout({
  headline = "Planejamento público, com método.",
  lead = "Elabore os documentos da fase preparatória em um fluxo seguro, rastreável e alinhado à Lei nº 14.133/2021 — com revisão humana e preços de fonte verificável.",
  foot = "Lei 14.133/2021 · fase preparatória",
  background = "/fundo-hero-claro.png",
  embedded = false,
  children,
}: AuthLayoutProps) {
  const Raiz = embedded ? "div" : "main";
  return (
    <Raiz id={embedded ? undefined : "conteudo"} className="gc-auth gc-base">
      <section className="gc-auth__brand" style={{ backgroundImage: `url(${background})` }}>
        <div className="gc-auth__brand-inner">
          <Logo size={32} />
          <div className="gc-auth__pitch">
            <Logo size={88} withName={false} name="" />
            <p className="gc-auth__headline">{headline}</p>
            <p className="gc-auth__lead">{lead}</p>
          </div>
          <p className="gc-auth__foot">{foot}</p>
        </div>
      </section>
      <section className="gc-auth__panel">
        <div className="gc-auth__form">{children}</div>
      </section>
    </Raiz>
  );
}
