import { Fragment, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import { LinkPorIntencao } from "../../lib/LinkPorIntencao";
import { Icon, type IconName } from "../core/Icon";

export interface NavItemProps {
  id?: string;
  icon?: IconName;
  label: string;
  href?: string;
  active?: boolean;
  badge?: ReactNode;
  onClick?: (e: MouseEvent<HTMLAnchorElement>) => void;
}

/** Link de módulo. Ativo: ícone fill, fundo azul-50 e barra de 3 px à esquerda. */
export function NavItem({ icon, label, href = "#", active, badge, onClick }: NavItemProps) {
  return (
    <LinkPorIntencao href={href} className="gc-navitem" aria-current={active ? "page" : undefined} title={label} onClick={onClick}>
      {icon && <Icon name={icon} weight={active ? "fill" : "bold"} />}
      <span className="gc-navitem__label">{label}</span>
      {badge != null && <span className="gc-navitem__badge">{badge}</span>}
    </LinkPorIntencao>
  );
}

export interface SidebarGroup {
  label?: string;
  items: NavItemProps[];
}

export interface SidebarProps {
  brand?: ReactNode;
  groups: SidebarGroup[];
  footer?: ReactNode;
  /** 68 px, só ícones (o rótulo fica no title). */
  collapsed?: boolean;
  onToggle?: () => void;
  ariaLabel?: string;
  style?: CSSProperties;
}

/** Barra lateral do app (248 px; 68 px recolhida), com módulos em grupos e o usuário no rodapé. */
export function Sidebar({
  brand,
  groups,
  footer,
  collapsed = false,
  onToggle,
  ariaLabel = "Navegação principal",
  style,
}: SidebarProps) {
  return (
    <aside className={cx("gc-sidebar", collapsed && "gc-sidebar--collapsed")} style={style}>
      <div className="gc-sidebar__head">
        {brand}
        {onToggle && !collapsed && (
          <button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Recolher menu" onClick={onToggle}>
            <Icon name="caret-double-left" />
          </button>
        )}
      </div>
      {collapsed && onToggle && (
        <div className="gc-sidebar__expand">
          <button type="button" className="gc-iconbtn gc-iconbtn--sm" aria-label="Expandir menu" onClick={onToggle}>
            <Icon name="caret-double-right" />
          </button>
        </div>
      )}
      <nav className="gc-sidebar__nav" aria-label={ariaLabel}>
        {groups.map((g, gi) => (
          <Fragment key={gi}>
            {g.label && <div className="gc-sidebar__group">{g.label}</div>}
            {g.items.map((it) => (
              <NavItem key={it.id ?? it.label} {...it} />
            ))}
          </Fragment>
        ))}
      </nav>
      {footer && <div className="gc-sidebar__foot">{footer}</div>}
    </aside>
  );
}

export interface UserCardProps {
  name: ReactNode;
  role?: string;
  avatar?: ReactNode;
  action?: ReactNode;
}

/** Usuário no rodapé da barra lateral. */
export function UserCard({ name, role, avatar, action }: UserCardProps) {
  return (
    <div className="gc-usercard">
      {avatar}
      <span className="gc-usercard__text">
        <span className="gc-usercard__name">{name}</span>
        <span className="gc-usercard__role">{role}</span>
      </span>
      {action}
    </div>
  );
}
