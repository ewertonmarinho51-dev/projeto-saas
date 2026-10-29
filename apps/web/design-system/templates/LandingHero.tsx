import Link from "next/link";
import type { ReactNode } from "react";

import { buttonClasses } from "../components/actions/Button";
import { Icon, type IconName } from "../components/core/Icon";
import { cx } from "../lib/cx";
import { PublicHeader, type PublicLink } from "./PublicSite";

/** Mesmo formato do link do site público. */
export type LandingLink = PublicLink;

export interface LandingHeroProps {
  /** Links do cabeçalho; viram o menu do celular abaixo de 1180 px. */
  nav?: LandingLink[];
  /** Ação principal (entrar no sistema): cabeçalho e segundo botão da Hero. */
  signIn: LandingLink;
  /** Ação discreta do cabeçalho. */
  secondary?: LandingLink;
  /** Primeiro botão da Hero (conhecer a plataforma). */
  explore?: LandingLink;
  eyebrow?: ReactNode;
  /** h1. Use `<em>` para a palavra em azul. */
  title?: ReactNode;
  lead?: ReactNode;
  facts?: ReactNode[];
  /** Prefixo dos ids (o h1 é referenciado por aria-labelledby). Troque quando houver duas Heros na página. */
  idPrefix?: string;
  /** Dentro de outra página (vitrine): sem altura de tela cheia. */
  embedded?: boolean;
}

const ETAPAS: { sigla: string; nome: string; icone: IconName; feito?: boolean }[] = [
  { sigla: "DFD", nome: "Formalização da demanda", icone: "check", feito: true },
  { sigla: "ETP", nome: "Estudo técnico preliminar", icone: "file-text" },
  { sigla: "TR", nome: "Termo de referência", icone: "clipboard-text" },
  { sigla: "Preços", nome: "Pesquisa em fontes oficiais", icone: "currency-circle-dollar" },
];

const CURVA = "M110 36 C240 36 240 108 370 108 S500 36 630 36 S760 108 890 108";

/**
 * Hero da landing pública, recriada de `referencia/ui_kits/landing`:
 * cabeçalho flutuante de vidro, texto com entrada escalonada e, à
 * direita, o fluxo DFD → ETP → TR → Preços desenhado em SVG com dois
 * painéis de vidro.
 *
 * A ilustração é EXEMPLO, e diz isso na tela ("Exemplo ilustrativo"):
 * os valores do painel de preços não vêm de pesquisa nenhuma. Por isso
 * ela é `aria-hidden` no conteúdo e não tem link — não é dado.
 *
 * Sem JavaScript: o menu do celular é um `<details>` nativo, e a
 * animação é só CSS (ver styles/landing.css, que respeita
 * prefers-reduced-motion e prefers-reduced-transparency).
 */
export function LandingHero({
  nav = [],
  signIn,
  secondary,
  explore,
  eyebrow = "Fase preparatória · Lei nº 14.133/2021",
  title = (
    <>
      Planejamento público, com método e <em>inteligência</em>.
    </>
  ),
  lead = "Elabore DFD, ETP, Mapa de Riscos e Termo de Referência com apoio de IA e revisão humana, e pesquise preços em fontes oficiais com a origem de cada valor registrada.",
  facts = ["Revisão humana em cada documento", "PNCP, Compras.gov.br e Painel de Preços"],
  idPrefix = "gc-hero",
  embedded = false,
}: LandingHeroProps) {
  const titulo = `${idPrefix}-titulo`;
  return (
    <section className={cx("gc-hero", embedded && "gc-hero--embedded")} aria-labelledby={titulo}>
      <PublicHeader nav={nav} signIn={signIn} secondary={secondary} current="/" />

      <div className="gc-hero__grid">
        <div className="gc-hero__copy">
          {eyebrow && (
            <span className="gc-hero__eyebrow gc-hero__rv" data-d="0">
              <Icon name="seal-check" weight="fill" />
              {eyebrow}
            </span>
          )}
          <h1 id={titulo} className="gc-hero__title gc-hero__rv" data-d="1">
            {title}
          </h1>
          {lead && (
            <p className="gc-hero__lead gc-hero__rv" data-d="2">
              {lead}
            </p>
          )}
          <div className="gc-hero__ctas gc-hero__rv" data-d="3">
            {explore && (
              <Link className={buttonClasses({ variant: "primary", size: "lg" })} href={explore.href}>
                {explore.label}
                <Icon name="arrow-right" className="gc-hero__arrow" />
              </Link>
            )}
            <Link
              className={buttonClasses({ variant: explore ? "secondary" : "primary", size: "lg" })}
              href={signIn.href}
            >
              <Icon name="sign-in" />
              {signIn.label}
            </Link>
          </div>
          {facts.length > 0 && (
            <div className="gc-hero__facts gc-hero__rv" data-d="4">
              {facts.map((f, i) => (
                <span key={i}>
                  <Icon name="check-circle" weight="fill" />
                  {f}
                </span>
              ))}
            </div>
          )}
        </div>

        <div className="gc-hero__viz" role="img" aria-label="Exemplo ilustrativo do fluxo da fase preparatória: DFD, ETP, TR e pesquisa de preços.">
          <span className="gc-hero__note gc-hero__rv" data-d="2" aria-hidden="true">
            Exemplo ilustrativo
          </span>
          <div className="gc-hero__flow" aria-hidden="true">
            <svg viewBox="0 0 1000 150" preserveAspectRatio="none">
              <path className="gc-hero__path gc-hero__path--track" vectorEffect="non-scaling-stroke" d={CURVA} />
              <path className="gc-hero__path" pathLength={1} vectorEffect="non-scaling-stroke" d={CURVA} />
            </svg>
            {ETAPAS.map((e) => (
              <div key={e.sigla} className={cx("gc-hero__node", e.feito && "gc-hero__node--done")}>
                <span className="gc-hero__node-icon">
                  <Icon name={e.icone} />
                </span>
                <span className="gc-hero__node-text">
                  <b>{e.sigla}</b>
                  <span>{e.nome}</span>
                </span>
              </div>
            ))}
          </div>
          <div className="gc-hero__panels" aria-hidden="true">
            <article className="gc-hero__panel gc-glass">
              <div className="gc-hero__panel-head">
                <div>
                  <div className="gc-hero__panel-eyebrow">Documento</div>
                  <div className="gc-hero__panel-title">Estudo Técnico Preliminar</div>
                </div>
                <span className="gc-badge gc-badge--warning gc-badge--sm">
                  <Icon name="eye" />
                  Em revisão
                </span>
              </div>
              <div className="gc-hero__lines">
                <i style={{ width: "92%" }} />
                <i className="gc-hero__ai" style={{ width: "100%" }} />
                <i className="gc-hero__ai" style={{ width: "78%" }} />
                <i style={{ width: "86%" }} />
                <i style={{ width: "54%" }} />
              </div>
              <div className="gc-progress">
                <div className="gc-progress__row">
                  <span>Seções revisadas</span>
                  <span className="gc-progress__value">4 de 6</span>
                </div>
                <div className="gc-progress__track">
                  <div className="gc-progress__fill" style={{ width: "66%" }} />
                </div>
              </div>
            </article>
            <article className="gc-hero__panel gc-hero__panel--b gc-glass">
              <div className="gc-hero__float">
                <div className="gc-hero__panel-head">
                  <div>
                    <div className="gc-hero__panel-eyebrow">Pesquisa de preços</div>
                    <div className="gc-hero__panel-title">Papel A4 75 g/m² · resma</div>
                  </div>
                  <span className="gc-badge gc-badge--brand gc-badge--sm">3 fontes</span>
                </div>
                <div className="gc-hero__price">
                  <Icon name="check-circle" weight="fill" />
                  <span>PNCP</span>
                  <b>R$ 22,00</b>
                </div>
                <div className="gc-hero__price">
                  <Icon name="check-circle" weight="fill" />
                  <span>Compras.gov.br</span>
                  <b>R$ 21,50</b>
                </div>
                <div className="gc-hero__price gc-hero__price--warn">
                  <Icon name="warning-circle" weight="fill" />
                  <span>Painel de Preços</span>
                  <b>R$ 19,03</b>
                </div>
                <div className="gc-hero__median">
                  <span>Mediana</span>
                  <b>R$ 21,50</b>
                </div>
              </div>
            </article>
          </div>
        </div>
      </div>
    </section>
  );
}
