"use client";

import { useState, type ReactNode } from "react";

import { Sidebar, type SidebarGroup } from "../components/navigation/Sidebar";
import { Topbar } from "../components/navigation/Topbar";

export interface AppShellProps {
  /** Logo. Recolhida, o CSS esconde o nome. */
  brand?: ReactNode;
  groups: SidebarGroup[];
  /** Usuário no rodapé da barra lateral. Recolhida, o CSS esconde o texto. */
  footer?: ReactNode;
  /** Esquerda da barra superior (trilha). */
  topStart?: ReactNode;
  /** Direita da barra superior (salvamento, GovBot, avisos, avatar). */
  topEnd?: ReactNode;
  /** Painel lateral direito (GovBot). */
  aside?: ReactNode;
  /** Ocupa a área inteira, sem a coluna de 1200 px (GovBot em página cheia). */
  bleed?: boolean;
  /** Dentro de outra página (vitrine, prévia): sem `<main id="conteudo">`, que já existe lá. */
  embedded?: boolean;
  children: ReactNode;
}

/**
 * Casca do app: barra lateral de 248 px (68 px recolhida) + barra superior
 * de 64 px com a trilha, e o conteúdo em até 1200 px. Abaixo de 768 px a
 * barra lateral vira navegação horizontal com rolagem (regra do CSS).
 * Recriada do ui_kit do export (Shell.jsx).
 */
export function AppShell({ brand, groups, footer, topStart, topEnd, aside, bleed = false, embedded = false, children }: AppShellProps) {
  const [recolhida, setRecolhida] = useState(false);
  const Conteudo = embedded ? "div" : "main";
  return (
    <div className="gc-shell gc-base">
      <Sidebar collapsed={recolhida} onToggle={() => setRecolhida((r) => !r)} brand={brand} groups={groups} footer={footer} />
      <div className="gc-shell__main">
        <Topbar start={topStart} end={topEnd} />
        <div className="gc-shell__body">
          <Conteudo id={embedded ? undefined : "conteudo"} className="gc-shell__content">
            {bleed ? children : <div className="gc-shell__page">{children}</div>}
          </Conteudo>
          {!bleed && aside}
        </div>
      </div>
    </div>
  );
}
