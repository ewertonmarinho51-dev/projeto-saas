import { useId, type ReactNode } from "react";

import { IconButton } from "../components/actions/IconButton";
import { Icon, type IconName } from "../components/core/Icon";
import { cx } from "../lib/cx";

export type SaveTone = "neutral" | "progress" | "success" | "warning" | "error";

/** Uma ferramenta do trilho lateral: abre e fecha o painel de mesmo `id`. */
export interface WorkspaceTool {
  id: string;
  icon: IconName;
  label: string;
}

export interface DocumentWorkspaceProps {
  /** Volta ao processo (link ou botão). */
  back: ReactNode;
  /** Sigla do documento ("DFD", "ETP"). */
  kicker?: ReactNode;
  title: ReactNode;
  /** Selos ao lado do título: situação. A revisão vai no salvamento, não aqui. */
  meta?: ReactNode;
  /** Estado de salvamento lido da API. Anunciado por leitor de tela. */
  save?: { tone: SaveTone; label: ReactNode };
  /** Só ações que funcionam (Exportar, Modo foco). */
  actions?: ReactNode;
  /** Aviso acima do documento (conflito, gravação indisponível). */
  notice?: ReactNode;
  /**
   * Trilho lateral à direita, na ordem dada. Um painel por vez: clicar na
   * ferramenta aberta fecha o painel. Sem `tools`, não há trilho.
   */
  tools?: WorkspaceTool[];
  /** Ferramenta aberta (o painel ao lado do trilho), ou nada. */
  activeTool?: string | null;
  onToolChange?: (id: string | null) => void;
  /** Conteúdo do painel aberto, ou nada. */
  panel?: ReactNode;
  panelTitle?: ReactNode;
  onClosePanel?: () => void;
  /** Modo foco: o espaço de trabalho cobre a tela inteira, sem casca, trilho nem painel. */
  focus?: boolean;
  /** A área do documento. Continua montada ao abrir painel, entrar em foco ou redimensionar. */
  children: ReactNode;
}

/**
 * Espaço de trabalho de documento: uma faixa compacta (voltar, sigla e
 * título, situação, salvamento, ações) sobre a área do editor, que ocupa o
 * resto da altura; à direita, o trilho de ferramentas e, quando aberto, o
 * painel dela entre a área e o trilho.
 *
 * Sem cartão em volta da área do documento: o editor nativo desenha a página.
 * Abrir painel, entrar em foco e redimensionar só mudam a grade — a área do
 * documento é o mesmo nó (primeiro filho, sempre), então o editor dentro dela
 * não é recriado e o texto, a seleção e a rolagem continuam onde estavam.
 */
export function DocumentWorkspace({
  back,
  kicker,
  title,
  meta,
  save,
  actions,
  notice,
  tools,
  activeTool = null,
  onToolChange,
  panel,
  panelTitle,
  onClosePanel,
  focus = false,
  children,
}: DocumentWorkspaceProps) {
  const painelId = useId();
  const comPainel = Boolean(panel) && !focus;
  const comTrilho = Boolean(tools?.length) && !focus;
  const fechar = onClosePanel ?? (onToolChange ? () => onToolChange(null) : undefined);
  return (
    <div
      className={cx(
        "gc-workspace",
        focus && "gc-workspace--focus",
        comPainel && "gc-workspace--panel",
        comTrilho && "gc-workspace--rail",
      )}
    >
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
          <aside id={painelId} className="gc-workspace__panel" aria-label={typeof panelTitle === "string" ? panelTitle : undefined}>
            <div className="gc-workspace__panel-head">
              <h2 className="gc-workspace__panel-title">{panelTitle}</h2>
              {fechar && <IconButton size="sm" icon="x" label="Fechar painel" onClick={fechar} />}
            </div>
            <div className="gc-workspace__panel-body">{panel}</div>
          </aside>
        )}
        {comTrilho && (
          <nav className="gc-workspace__rail" aria-label="Painéis do documento">
            {tools!.map((t) => {
              const aberta = activeTool === t.id;
              return (
                <button
                  key={t.id}
                  type="button"
                  className="gc-workspace__tool"
                  aria-pressed={aberta}
                  aria-controls={aberta && comPainel ? painelId : undefined}
                  onClick={() => onToolChange?.(aberta ? null : t.id)}
                >
                  <Icon name={t.icon} weight={aberta ? "fill" : "bold"} />
                  <span className="gc-workspace__tool-label">{t.label}</span>
                </button>
              );
            })}
          </nav>
        )}
      </div>
    </div>
  );
}
