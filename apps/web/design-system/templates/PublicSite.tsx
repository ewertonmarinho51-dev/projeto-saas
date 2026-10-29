import Link from "next/link";
import type { ReactNode } from "react";

import { buttonClasses } from "../components/actions/Button";
import { Icon, type IconName } from "../components/core/Icon";
import { Logo } from "../components/core/Logo";
import { cx } from "../lib/cx";

export interface PublicLink {
  label: string;
  /** Rota do site (`/solucoes`) ou âncora da própria página (`#perguntas`). Nunca âncora sem destino. */
  href: string;
}

export interface PublicHeaderProps {
  /** Links do cabeçalho; viram o menu do celular abaixo de 1180 px. */
  nav?: PublicLink[];
  /** Ação principal (entrar no sistema). */
  signIn: PublicLink;
  /** Ação discreta, some abaixo de 600 px (continua no menu). */
  secondary?: PublicLink;
  /** Caminho da página atual: o link igual (ou pai) ganha `aria-current`. */
  current?: string;
}

function atual(current: string | undefined, href: string): boolean {
  if (!current || href.startsWith("#")) return false;
  return href === "/" ? current === "/" : current === href || current.startsWith(`${href}/`);
}

/**
 * Cabeçalho público de vidro, o mesmo da Hero (`referencia/ui_kits/landing`):
 * marca, navegação, ação discreta e "Acessar sistema". No celular a
 * navegação vira um `<details>` nativo — sem JavaScript.
 */
export function PublicHeader({ nav = [], signIn, secondary, current }: PublicHeaderProps) {
  return (
    <header className="gc-pubhead gc-glass">
      <Logo size={30} href="/" />
      {nav.length > 0 && (
        <nav className="gc-pubhead__nav" aria-label="Navegação pública">
          {nav.map((l) => (
            <Link key={l.href} href={l.href} aria-current={atual(current, l.href) ? "page" : undefined}>
              {l.label}
            </Link>
          ))}
        </nav>
      )}
      <div className="gc-pubhead__actions">
        {secondary && (
          <Link className={buttonClasses({ variant: "subtle", size: "sm" })} href={secondary.href}>
            {secondary.label}
          </Link>
        )}
        <Link className={buttonClasses({ variant: "primary", size: "sm" })} href={signIn.href}>
          {signIn.label}
        </Link>
        {(nav.length > 0 || secondary) && (
          <details className="gc-pubhead__menu">
            <summary className="gc-iconbtn gc-iconbtn--sm" aria-label="Abrir menu" title="Menu">
              <Icon name="list" />
            </summary>
            <div className="gc-pubhead__menu-panel">
              {nav.map((l) => (
                <Link key={l.href} href={l.href} aria-current={atual(current, l.href) ? "page" : undefined}>
                  {l.label}
                </Link>
              ))}
              {secondary && <Link href={secondary.href}>{secondary.label}</Link>}
            </div>
          </details>
        )}
      </div>
    </header>
  );
}

export interface PublicFooterColumn {
  title: string;
  links: PublicLink[];
}

export interface PublicFooterProps {
  columns: PublicFooterColumn[];
  /** Linha final (direitos, base legal). */
  note?: ReactNode;
}

/** Rodapé público: marca, colunas de links e a linha final. */
export function PublicFooter({ columns, note }: PublicFooterProps) {
  return (
    <footer className="gc-pubfoot">
      <div className="gc-pubfoot__inner">
        <div className="gc-pubfoot__brand">
          <Logo size={28} href="/" />
          <p>Planejamento de contratações públicas sob a Lei nº 14.133/2021, com revisão humana.</p>
        </div>
        {columns.map((c) => (
          <nav key={c.title} className="gc-pubfoot__col" aria-label={c.title}>
            <h2>{c.title}</h2>
            <ul>
              {c.links.map((l) => (
                <li key={l.href}>
                  <Link href={l.href}>{l.label}</Link>
                </li>
              ))}
            </ul>
          </nav>
        ))}
      </div>
      {note && <div className="gc-pubfoot__note">{note}</div>}
    </footer>
  );
}

export interface PublicSectionProps {
  id?: string;
  eyebrow?: ReactNode;
  /** h2 da seção. */
  title: ReactNode;
  lead?: ReactNode;
  /** Fundo da superfície (alterna com o fundo da página). */
  muted?: boolean;
  /** Largura de leitura (texto corrido, perguntas). */
  narrow?: boolean;
  children?: ReactNode;
}

/** Seção de conteúdo das páginas públicas: sobretítulo, h2, abertura e corpo. */
export function PublicSection({ id, eyebrow, title, lead, muted, narrow, children }: PublicSectionProps) {
  const tituloId = id ? `${id}-titulo` : undefined;
  return (
    <section id={id} className={cx("gc-pubsec", muted && "gc-pubsec--muted")} aria-labelledby={tituloId}>
      <div className={cx("gc-pubsec__inner", narrow && "gc-pubsec__inner--narrow")}>
        {eyebrow && <span className="gc-pubsec__eyebrow">{eyebrow}</span>}
        <h2 id={tituloId} className="gc-pubsec__title">
          {title}
        </h2>
        {lead && <p className="gc-pubsec__lead">{lead}</p>}
        {children && <div className="gc-pubsec__body">{children}</div>}
      </div>
    </section>
  );
}

export interface PublicFeatureProps {
  icon: IconName;
  /** h3. */
  title: ReactNode;
  children?: ReactNode;
  /** Link "Saiba mais" para a página do tema. */
  href?: string;
  linkLabel?: string;
  /** Destaque (ocupa duas colunas na grade). */
  wide?: boolean;
}

/** Bloco de recurso: ícone, título, texto e link opcional. Use dentro de `PublicGrid`. */
export function PublicFeature({ icon, title, children, href, linkLabel = "Saiba mais", wide }: PublicFeatureProps) {
  return (
    <article className={cx("gc-pubfeat", wide && "gc-pubfeat--wide")}>
      <span className="gc-pubfeat__icon">
        <Icon name={icon} />
      </span>
      <h3 className="gc-pubfeat__title">{title}</h3>
      {children && <div className="gc-pubfeat__text">{children}</div>}
      {href && (
        <Link className="gc-pubfeat__link" href={href}>
          {linkLabel}
          <Icon name="arrow-right" />
        </Link>
      )}
    </article>
  );
}

/** Grade responsiva de `PublicFeature` (3, 2 ou 1 coluna). */
export function PublicGrid({ children, columns = 3 }: { children: ReactNode; columns?: 2 | 3 }) {
  return <div className={cx("gc-pubgrid", columns === 2 && "gc-pubgrid--2")}>{children}</div>;
}

export interface PublicStep {
  title: ReactNode;
  text?: ReactNode;
  /** Sigla em destaque (DFD, ETP…). */
  tag?: string;
}

/** Sequência numerada (lista ordenada) — a ordem é parte do conteúdo. */
export function PublicSteps({ steps }: { steps: PublicStep[] }) {
  return (
    <ol className="gc-pubsteps">
      {steps.map((s, i) => (
        <li key={i} className="gc-pubsteps__item">
          <span className="gc-pubsteps__num gc-mono">{String(i + 1).padStart(2, "0")}</span>
          {s.tag && <span className="gc-pubsteps__tag">{s.tag}</span>}
          <h3 className="gc-pubsteps__title">{s.title}</h3>
          {s.text && <p className="gc-pubsteps__text">{s.text}</p>}
        </li>
      ))}
    </ol>
  );
}

export interface PublicPageProps {
  header: PublicHeaderProps;
  footer: PublicFooterProps;
  /** Trilha curta acima do título (ex.: Soluções). */
  parent?: PublicLink;
  eyebrow?: ReactNode;
  /** h1 da página. */
  title: ReactNode;
  lead?: ReactNode;
  /** Botões do topo. */
  actions?: ReactNode;
  children?: ReactNode;
}

/**
 * Página institucional: cabeçalho de vidro, abertura (sobretítulo, h1,
 * abertura, ações) sobre o mesmo fundo da Hero, conteúdo em seções e rodapé.
 */
export function PublicPage({ header, footer, parent, eyebrow, title, lead, actions, children }: PublicPageProps) {
  return (
    <>
      <div className="gc-pubbar">
        <PublicHeader {...header} />
      </div>
      <main id="conteudo">
        <section className="gc-pubtop" aria-labelledby="gc-pubintro-titulo">
          <div className="gc-pubintro__inner">
            {parent && (
              <nav aria-label="Trilha de navegação" className="gc-pubintro__crumb">
                <Link href={parent.href}>{parent.label}</Link>
                <Icon name="caret-right" />
              </nav>
            )}
            {eyebrow && <span className="gc-pubintro__eyebrow">{eyebrow}</span>}
            <h1 id="gc-pubintro-titulo" className="gc-pubintro__title">
              {title}
            </h1>
            {lead && <p className="gc-pubintro__lead">{lead}</p>}
            {actions && <div className="gc-pubintro__actions">{actions}</div>}
          </div>
        </section>
        {children}
      </main>
      <PublicFooter {...footer} />
    </>
  );
}
