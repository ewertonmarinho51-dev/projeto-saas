import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export interface ConversationItem {
  id: string;
  title: string;
  /** Processo vinculado. */
  meta?: string;
  icon?: IconName;
}

export interface ConversationListProps {
  groups: { label: string; items: ConversationItem[] }[];
  activeId?: string;
  onSelect?: (id: string) => void;
  onNew?: () => void;
  search?: ReactNode;
}

/** Histórico de conversas do GovBot por recência ("Hoje", "Esta semana"), com "Nova conversa". */
export function ConversationList({ groups, activeId, onSelect, onNew, search }: ConversationListProps) {
  return (
    <nav className="gc-convlist" aria-label="Conversas">
      {onNew && (
        <button type="button" className="gc-btn gc-btn--secondary gc-btn--sm gc-btn--block" onClick={onNew}>
          <Icon name="plus" />
          Nova conversa
        </button>
      )}
      {search}
      {groups.map((g, gi) => (
        <div key={gi} className="gc-convlist__group">
          <div className="gc-convlist__label">{g.label}</div>
          {g.items.map((it) => (
            <button
              key={it.id}
              type="button"
              className="gc-convlist__item"
              aria-current={it.id === activeId ? "true" : undefined}
              onClick={() => onSelect?.(it.id)}
            >
              <Icon name={it.icon ?? "chat-centered-text"} />
              <span className="gc-convlist__text">
                <span className="gc-convlist__title">{it.title}</span>
                {it.meta && <span className="gc-convlist__meta">{it.meta}</span>}
              </span>
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}
