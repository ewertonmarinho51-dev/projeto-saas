"use client";

import { usePathname } from "next/navigation";
import { useEffect, useId, useState, type ReactNode } from "react";

import { Icon } from "../components/core/Icon";
import { Sidebar, type SidebarGroup } from "../components/navigation/Sidebar";
import { Topbar } from "../components/navigation/Topbar";
import { cx } from "../lib/cx";

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
  /**
   * Modo de trabalho (editor de documento): área inteira na altura da tela,
   * sem rolagem da página, e a barra lateral recolhida ao entrar (a pessoa
   * pode abrir de novo). Implica `bleed`.
   */
  workspace?: boolean;
  /** Dentro de outra página (vitrine, prévia): sem `<main id="conteudo">`, que já existe lá. */
  embedded?: boolean;
  children: ReactNode;
}

/**
 * Casca do app: barra lateral de 248 px (68 px recolhida) + barra superior
 * de 64 px com a trilha, e o conteúdo em até 1200 px. Recriada do ui_kit
 * do export (Shell.jsx).
 *
 * Até 768 px a barra lateral sai da grade e vira gaveta: o botão de menu
 * da barra superior abre, e fecham o fundo escuro, o Esc e a troca de
 * página. Recolher é só da tela larga — na gaveta o menu aparece inteiro.
 */
export function AppShell({ brand, groups, footer, topStart, topEnd, aside, bleed = false, workspace = false, embedded = false, children }: AppShellProps) {
  const [recolhida, setRecolhida] = useState(false);
  // No modo de trabalho a barra nasce recolhida; abrir vale só enquanto durar o modo.
  const [abertaNoTrabalho, setAbertaNoTrabalho] = useState(false);
  const fechada = workspace ? !abertaNoTrabalho : recolhida;
  const cheio = bleed || workspace;
  // A gaveta lembra em que página abriu: navegou, ela fecha sozinha (o
  // link já levou aonde a pessoa queria), sem efeito para sincronizar.
  const caminho = usePathname() ?? "";
  const [abertaEm, setAbertaEm] = useState<string | null>(null);
  const gaveta = abertaEm === caminho;
  const setGaveta = (aberta: boolean) => setAbertaEm(aberta ? caminho : null);
  const navId = useId();
  const Conteudo = embedded ? "div" : "main";

  useEffect(() => {
    if (!gaveta) return;
    const aoTeclar = (e: KeyboardEvent) => e.key === "Escape" && setAbertaEm(null);
    document.addEventListener("keydown", aoTeclar);
    return () => document.removeEventListener("keydown", aoTeclar);
  }, [gaveta]);

  return (
    <div className={cx("gc-shell gc-base", gaveta && "gc-shell--drawer-open", workspace && "gc-shell--workspace")}>
      <div className="gc-shell__nav" id={navId}>
        <Sidebar
          collapsed={fechada && !gaveta}
          onToggle={gaveta ? undefined : () => (workspace ? setAbertaNoTrabalho((a) => !a) : setRecolhida((r) => !r))}
          brand={brand}
          groups={groups}
          footer={footer}
        />
      </div>
      {gaveta && <div className="gc-shell__scrim" aria-hidden="true" onClick={() => setGaveta(false)} />}
      <div className="gc-shell__main">
        <Topbar
          start={
            <>
              <button
                type="button"
                className="gc-iconbtn gc-iconbtn--sm gc-shell__menu"
                aria-label={gaveta ? "Fechar menu" : "Abrir menu"}
                aria-expanded={gaveta}
                aria-controls={navId}
                onClick={() => setGaveta(!gaveta)}
              >
                <Icon name={gaveta ? "x" : "list"} />
              </button>
              {topStart}
            </>
          }
          end={topEnd}
        />
        <div className="gc-shell__body">
          <Conteudo id={embedded ? undefined : "conteudo"} className="gc-shell__content">
            {cheio ? children : <div className="gc-shell__page">{children}</div>}
          </Conteudo>
          {!cheio && aside}
        </div>
      </div>
    </div>
  );
}
