import type { ReactNode } from "react";

import { Icon } from "../core/Icon";

export interface ChatMessageProps {
  role?: "assistant" | "user";
  name?: string;
  time?: string;
  children?: ReactNode;
  /** Aviso de revisão sob a resposta da IA. */
  notice?: ReactNode;
  sources?: ReactNode;
  actions?: ReactNode;
  loading?: boolean;
}

/**
 * Turno da conversa com o GovBot. Assistente: brilho num quadrado (nunca
 * robô ou mascote), resposta, aviso de revisão, fontes e ações. Usuário:
 * balão azul-claro à direita. Referência em linha com `<Cite n={1} />`.
 */
export function ChatMessage({ role = "assistant", name = "GovBot", time, children, notice, sources, actions, loading }: ChatMessageProps) {
  if (role === "user") {
    return (
      <div className="gc-msg gc-msg--user">
        <div className="gc-msg__bubble">{children}</div>
      </div>
    );
  }
  return (
    <div className="gc-msg">
      <span className="gc-msg__avatar">
        <Icon name="sparkle" weight="fill" />
      </span>
      <div className="gc-msg__main">
        <div className="gc-msg__head">
          {name}
          {time && <span className="gc-msg__time">{time}</span>}
        </div>
        {loading ? (
          <div className="gc-msg__content gc-msg__typing" aria-label="Escrevendo">
            <span className="gc-msg__dot" />
            <span className="gc-msg__dot" />
            <span className="gc-msg__dot" />
          </div>
        ) : (
          <div className="gc-msg__content">{children}</div>
        )}
        {notice && (
          <div className="gc-alert gc-alert--info gc-alert--compact" role="note">
            <Icon name="info" weight="fill" />
            <div className="gc-alert__body">
              <div className="gc-alert__desc">{notice}</div>
            </div>
          </div>
        )}
        {sources}
        {actions && <div className="gc-msg__actions">{actions}</div>}
      </div>
    </div>
  );
}

/** Citação numerada em linha, ligada ao item da SourceList. */
export function Cite({ n, href = "#" }: { n: number | string; href?: string }) {
  return (
    <a className="gc-cite" href={href} aria-label={`Fonte ${n}`}>
      {n}
    </a>
  );
}
