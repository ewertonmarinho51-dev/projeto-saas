import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { etapasDaPesquisa, SECAO } from "../components/etapas-da-pesquisa";
import { Stepper, type StepItem } from "../design-system/components/navigation/Stepper";

const html = (steps: StepItem[], extra: Record<string, unknown> = {}) =>
  renderToStaticMarkup(createElement(Stepper, { steps, ariaLabel: "Etapas", ...extra }));

/** Os <li> do fluxo, na ordem. */
const itens = (markup: string) => [...markup.matchAll(/<li\b[\s\S]*?<\/li>/g)].map((m) => m[0]);

describe("Stepper: etapa passada leva de volta", () => {
  const passos: StepItem[] = [
    { label: "Definir itens", state: "done", href: "#importar-itens" },
    { label: "Triagem", state: "current", href: "#itens" },
    { label: "Relatório final", state: "todo", href: "#relatorios" },
  ];

  it("só a concluída vira link, com o rótulo e o estado no nome acessível", () => {
    const [feita, atual, futura] = itens(html(passos));
    expect(feita).toMatch(/<a class="gc-step__btn" href="#importar-itens">[\s\S]*Definir itens[\s\S]*\(concluída\)[\s\S]*<\/a>/);
    expect(atual).not.toContain("<a ");
    expect(futura).not.toContain("<a ");
    expect(atual).not.toContain("<button");
  });

  it("a atual leva aria-current=step, e só ela", () => {
    const markup = html(passos);
    expect(markup.match(/aria-current="step"/g)).toHaveLength(1);
    expect(itens(markup)[1]).toContain('aria-current="step"');
  });

  it("sem href, onStepClick faz da concluída um botão de verdade", () => {
    const markup = html([{ label: "DFD" }, { label: "ETP" }], { current: 1, onStepClick: () => {} });
    const [feita, atual] = itens(markup);
    expect(feita).toMatch(/<button type="button" class="gc-step__btn">[\s\S]*DFD[\s\S]*<\/button>/);
    expect(atual).not.toContain("<button");
  });

  it("sem href nem onStepClick, nada é clicável", () => {
    const markup = html([{ label: "DFD", state: "done" }, { label: "ETP", state: "current" }]);
    expect(markup).not.toMatch(/<a |<button/);
  });

  it("o alvo do clique é caixa de verdade: display:contents esconderia o anel de foco", () => {
    const css = readFileSync(join(__dirname, "../design-system/styles/components.css"), "utf8");
    const regra = css.match(/\.gc-step__btn\{[^}]*\}/)?.[0] ?? "";
    expect(regra).not.toBe("");
    expect(regra).not.toContain("display:contents");
    expect(css).toMatch(/\.gc-step__btn:focus-visible\{[^}]*outline:[^}]*var\(--focus-ring-color\)/);
  });
});

describe("etapas da pesquisa de preços", () => {
  const links = (e: StepItem[]) => e.map((s) => s.href ?? null);

  it("sem itens, nada passou: nenhum link", () => {
    expect(links(etapasDaPesquisa("draft", 0, 0, true))).toEqual([null, null, null, null, null]);
  });

  it("em triagem, definir e coletar levam às seções delas", () => {
    const e = etapasDaPesquisa("review", 7, 3, true);
    expect(e.map((s) => s.state)).toEqual(["done", "done", "current", "todo", "todo"]);
    expect(links(e)).toEqual([`#${SECAO.importar}`, `#${SECAO.coleta}`, null, null, null]);
  });

  it("concluída: triagem e mapa voltam à tabela de itens", () => {
    const e = etapasDaPesquisa("completed", 7, 7, true);
    expect(links(e)).toEqual([`#${SECAO.importar}`, `#${SECAO.coleta}`, `#${SECAO.itens}`, `#${SECAO.itens}`, null]);
  });

  it("aplicada: importação e coleta somem da página, e o link cai na tabela", () => {
    const e = etapasDaPesquisa("applied", 7, 7, false);
    expect(e.every((s) => s.state === "done")).toBe(true);
    expect(links(e)).toEqual([
      `#${SECAO.itens}`,
      `#${SECAO.itens}`,
      `#${SECAO.itens}`,
      `#${SECAO.itens}`,
      `#${SECAO.relatorios}`,
    ]);
  });

  it("coleta que falhou não vira link de volta", () => {
    const e = etapasDaPesquisa("failed", 7, 0, true);
    expect(e[1].state).toBe("error");
    const markup = renderToStaticMarkup(createElement(Stepper, { steps: e }));
    expect(itens(markup)[1]).not.toContain("<a ");
  });

  it("cada destino é uma seção que a página declara", () => {
    const pagina = readFileSync(join(__dirname, "../app/app/precos/[id]/page.tsx"), "utf8");
    for (const chave of Object.keys(SECAO)) expect(pagina).toContain(`id={SECAO.${chave}}`);
  });
});
