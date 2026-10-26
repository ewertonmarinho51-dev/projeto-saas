import type { ReactNode } from "react";

import { Icon, type IconName } from "../core/Icon";

export interface EmptyStateProps {
  icon?: IconName;
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}

/** Lista vazia ou primeiro uso: o que falta e como começar. */
export function EmptyState({ icon = "folder-open", title, description, actions }: EmptyStateProps) {
  return (
    <div className="gc-empty">
      <span className="gc-empty__icon">
        <Icon name={icon} />
      </span>
      <p className="gc-empty__title">{title}</p>
      {description && <p className="gc-empty__desc">{description}</p>}
      {actions && <div className="gc-empty__actions">{actions}</div>}
    </div>
  );
}
