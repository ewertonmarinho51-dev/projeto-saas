import type { ReactNode } from "react";

import { IconButton } from "../components/actions/IconButton";
import { cx } from "../lib/cx";

export type SaveTone = "neutral" | "progress" | "success" | "warning" | "error";

export interface DocumentWorkspaceProps {
  /** Volta ao processo (link ou botão). */
  back: ReactNode;
  /** Sigla do documento ("DFD", "ETP"). */
  kicker?: ReactNode;
  title: ReactNode;
  /** Selos ao lado do título: situação, revisão. */
  meta?: ReactNode;
  /** Estado de salvamento lido da API. Anunciado por leitor de tela. */
  save?: { tone: SaveTone; label: ReactNode };
  /** Só ações que funcionam. */
  actions?: ReactNode;
  /** Aviso acima do documento (conflito, gravação indisponível). */
  notice?: ReactNode;
  /** Painel lateral aberto, ou nada. */
  panel?: ReactNode;
  panelTitle?: ReactNode;
  onClosePanel?: () => void;
  /** Modo foco: o espaço de trabalho cobre a tela inteira, sem casca nem painel. */
  focus?: boolean;
  /** A área do documento. Continua montada ao abrir painel, entrar em foco ou redimensionar. */
  children: ReactNode;
}

/**
 * Espaço de trabalho de documento: barra do documento (voltar, sigla,
 * título, situação, salvamento, ações) sobre a área do editor, que ocupa o
 * resto da tela, com um painel opcional à direita.
 *
 * Sem cartão em volta da área do documento: o editor nativo desenha a página.
 * Abrir painel, entrar em foco e redimensionar só mudam a grade — a área do
 * documento é o mesmo nó, então o editor dentro dela não é recriado.
 */
export function DocumentWorkspace({
  back,
  kicker,
  title,
  meta,
  save,
  actions,
  notice,
  panel,
  panelTitle,
  onClosePanel,
  focus = false,
  children,
}: DocumentWorkspaceProps) {
  const comPainel = Boolean(panel) && !focus;
  return (
    <div className={cx("gc-workspace", focus && "gc-workspace--focus", comPainel && "gc-workspace--panel")}>
      <header className="gc-workspace__bar">
        <div className="gc-workspace__back">{back}</div>
        <div className="gc-workspace__titles">
          {kicker && <span className="gc-workspace__kicker">{kicker}</span>}
          <h1 className="gc-workspace__title">{title}</h1>
        </div>
        {meta && <div className="gc-workspace__meta">{meta}</div>}
        <span className="gc-workspace__spacer" />
        {save && (
          <span className={cx("gc-workspace__save", `gc-workspace__save--${save.tone}`)} role="status" aria-live="polite">
            {save.label}
          </span>
        )}
        {actions && <div className="gc-workspace__actions">{actions}</div>}
      </header>
      {notice && <div className="gc-workspace__notice">{notice}</div>}
      <div className="gc-workspace__body">
        <div className="gc-workspace__canvas">{children}</div>
        {comPainel && (
          <aside className="gc-workspace__panel" aria-label={typeof panelTitle === "string" ? panelTitle : undefined}>
            <div className="gc-workspace__panel-head">
              <h2 className="gc-workspace__panel-title">{panelTitle}</h2>
              {onClosePanel && <IconButton size="sm" icon="x" label="Fechar painel" onClick={onClosePanel} />}
            </div>
            <div className="gc-workspace__panel-body">{panel}</div>
          </aside>
        )}
      </div>
    </div>
  );
}
