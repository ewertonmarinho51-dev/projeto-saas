import { readFileSync } from "node:fs";
import { join } from "node:path";

import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import * as ds from "../design-system";
import { paginasVisiveis } from "../design-system/components/data/Pagination";
import { iniciais } from "../design-system/components/core/Avatar";
import { Vitrine } from "../design-system/vitrine";

const WEB = join(__dirname, "..");
const RAIZ = join(WEB, "..", "..");

/**
 * Os 71 nomes do `_ds_manifest.json` do export do Claude Design
 * (23/10/2026). Se o export tem N componentes, o projeto termina com N.
 */
const DO_EXPORT = [
  "Button", "IconButton", "Menu", "Toolbar", "ToolbarSeparator", "ToolbarSpacer",
  "AiDraftBlock", "AiProcessing", "ChatComposer", "ChatMessage", "Cite", "ContextBar", "ConversationList",
  "MessageFeedback", "PromptSuggestions", "SourceList",
  "Accordion", "Card", "DataList", "Dialog", "DocumentViewer",
  "Avatar", "Icon", "Logo", "Tooltip",
  "BarChart", "DataTable", "TableContainer", "KpiCard", "Pagination",
  "Alert", "Badge", "EmptyState", "ProgressBar", "Skeleton", "SkeletonText", "Spinner", "PROCESS_STATUS",
  "StatusBadge", "Tag", "Toast", "ToastStack",
  "Checkbox", "DateField", "Field", "FileUpload", "Input", "Radio", "RadioGroup", "SearchField", "Select",
  "Switch", "Textarea",
  "Breadcrumbs", "NavItem", "Sidebar", "UserCard", "Stepper", "Tabs", "Topbar",
  "ExclusionDialog", "PriceBasket", "PriceDispersion", "PriceItemNav", "PriceMapTable", "PriceReferenceRow",
  "PriceStats", "ScreeningSummary", "SourcePicker", "TraceabilityPanel", "ValidationSummary",
];
const TEMPLATES = [
  "AppShell",
  "AuthLayout",
  "DocumentWorkspace",
  "LandingHero",
  "PageHead",
  "PublicFeature",
  "PublicFooter",
  "PublicGrid",
  "PublicHeader",
  "PublicPage",
  "PublicSection",
  "PublicSteps",
];

describe("inventário do design system", () => {
  it("o export tem 71 nomes", () => {
    expect(new Set(DO_EXPORT).size).toBe(71);
  });

  it("o índice exporta exatamente os 71 do export + 12 templates", () => {
    // Componente e constante (PascalCase ou CAIXA_ALTA); helper em camelCase fica de fora.
    const publicos = Object.keys(ds).filter((n) => /^[A-Z]/.test(n));
    expect(publicos.sort()).toEqual([...DO_EXPORT, ...TEMPLATES].sort());
  });
});

/** `--nome: valor;` de um bloco de CSS. */
function variaveis(css: string): Map<string, string> {
  const mapa = new Map<string, string>();
  for (const m of css.matchAll(/--([\w-]+):([^;]+);/g)) mapa.set(m[1], m[2].trim());
  return mapa;
}

function bloco(css: string, seletor: string): string {
  const i = css.indexOf(seletor);
  if (i < 0) throw new Error(`seletor ausente: ${seletor}`);
  return css.slice(i, css.indexOf("}", i));
}

/** Seção `chave:` do front matter: pares `  nome: valor` até a próxima seção. */
function secao(frente: string, nome: string): Map<string, string> {
  const linhas = frente.split("\n");
  const inicio = linhas.indexOf(`${nome}:`);
  if (inicio < 0) throw new Error(`seção ausente no DESIGN.md: ${nome}`);
  const mapa = new Map<string, string>();
  for (const linha of linhas.slice(inicio + 1)) {
    if (!linha.startsWith("  ")) break;
    const m = linha.match(/^ {2}([\w-]+): (.+)$/);
    if (m) mapa.set(m[1], m[2].replace(/^"|"$/g, ""));
  }
  return mapa;
}

describe("DESIGN.md é a fonte da verdade dos tokens", () => {
  // Checkout no Windows pode trazer CRLF.
  const design = readFileSync(join(RAIZ, "DESIGN.md"), "utf8").replace(/\r\n/g, "\n");
  const frente = design.split("\n---\n")[0];
  const tokens = (arquivo: string) => readFileSync(join(WEB, "design-system", "tokens", arquivo), "utf8");
  const cores = tokens("colors.css");
  const claro = variaveis(bloco(cores, ':root,\n[data-theme="light"] {'));
  const escuro = variaveis(bloco(cores, '[data-theme="dark"] {'));
  const sistemaEscuro = variaveis(bloco(cores, ':root:not([data-theme="light"]) {'));
  const espaco = variaveis(tokens("spacing.css"));
  const tipo = variaveis(tokens("typography.css"));

  it("toda cor do DESIGN.md tem o mesmo valor no CSS, nos dois temas", () => {
    const doDesign = secao(frente, "colors");
    expect(doDesign.size).toBeGreaterThan(80);
    for (const [nome, valor] of doDesign) {
      if (nome.startsWith("dark-")) {
        expect(escuro.get(nome.slice(5)), nome).toBe(valor);
      } else {
        const ref = valor.match(/^\{colors\.([\w-]+)\}$/);
        expect(claro.get(nome), nome).toBe(ref ? `var(--${ref[1]})` : valor);
      }
    }
    // E nenhuma cor do CSS fica fora do DESIGN.md.
    for (const nome of claro.keys()) expect(doDesign.has(nome), `--${nome} sem entrada no DESIGN.md`).toBe(true);
    for (const nome of escuro.keys()) expect(doDesign.has(`dark-${nome}`), `--${nome} escuro sem entrada`).toBe(true);
  });

  it("o escuro por prefers-color-scheme é o mesmo do [data-theme=dark]", () => {
    expect([...sistemaEscuro]).toEqual([...escuro]);
  });

  it("raios e espaçamento batem", () => {
    for (const [nome, valor] of secao(frente, "rounded")) expect(espaco.get(`gc-radius-${nome}`), nome).toBe(valor);
    for (const [nome, valor] of secao(frente, "spacing")) {
      const css = nome.startsWith("control-") ? espaco.get(nome) : espaco.get(`space-${nome}`);
      expect(css === "0" ? "0px" : css, nome).toBe(valor);
    }
  });

  it("os tamanhos de fonte dos papéis existem na escala do CSS", () => {
    const tamanhos = new Set([...tipo].filter(([n]) => n.startsWith("gc-fs-")).map(([, v]) => v));
    const papeis = [...design.matchAll(/^ {4}fontSize: (\S+)$/gm)].map((m) => m[1]);
    expect(papeis.length).toBe(10);
    for (const t of papeis) expect(tamanhos.has(t), t).toBe(true);
  });
});

describe("nada que colida com o tema do Tailwind", () => {
  // `--text-sm`, `--radius-md`, `--shadow-sm`... são nomes do tema do
  // Tailwind v4: redefinir qualquer um muda cada utilitário do app.
  const COLIDE = /--(text-(2xs|xs|sm|base|md|lg|xl|[2-9]xl)|radius-(xs|sm|md|lg|xl)|shadow-(xs|sm|md|lg)|leading-\w+|tracking-\w+|ease-\w+|font-(sans|mono)):/;
  it.each(["colors.css", "typography.css", "spacing.css", "elevation.css", "motion.css", "layout.css"])("%s", (arquivo) => {
    const css = readFileSync(join(WEB, "design-system", "tokens", arquivo), "utf8");
    expect(css).not.toMatch(COLIDE);
  });
});

describe("regras pequenas dos componentes", () => {
  it("iniciais: primeiro e último nome", () => {
    expect(iniciais("Ana Maria Souza")).toBe("AS");
    expect(iniciais("Ana")).toBe("A");
    expect(iniciais("")).toBe("");
  });

  it("paginação: primeira, última e vizinhas; o resto vira reticências", () => {
    expect(paginasVisiveis(1, 1)).toEqual([1]);
    expect(paginasVisiveis(5, 10)).toEqual([1, "…", 4, 5, 6, "…", 10]);
    expect(paginasVisiveis(2, 5)).toEqual([1, 2, 3, "…", 5]);
  });

  it("StatusBadge cobre todo o vocabulário com ícone e rótulo", () => {
    for (const [status, s] of Object.entries(ds.PROCESS_STATUS)) {
      const html = renderToStaticMarkup(createElement(ds.StatusBadge, { status: status as ds.ProcessStatus }));
      expect(html).toContain(s.label);
      expect(html).toContain("<svg");
    }
  });
});

describe("vitrine", () => {
  const html = renderToStaticMarkup(createElement(Vitrine));

  it("renderiza os dois temas", () => {
    expect(html).toContain('data-theme="light"');
    expect(html).toContain('data-theme="dark"');
  });

  it("não repete id entre os painéis", () => {
    const ids = [...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
    const repetidos = ids.filter((id, i) => ids.indexOf(id) !== i);
    expect(repetidos).toEqual([]);
  });

  it("mostra cada grupo e os templates", () => {
    for (const secaoId of ["cores", "core", "actions", "forms", "navigation", "content", "feedback", "data", "ai", "price", "templates"]) {
      expect(html).toContain(`id="claro-${secaoId}"`);
      expect(html).toContain(`id="escuro-${secaoId}"`);
    }
  });
});
