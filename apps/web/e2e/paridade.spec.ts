import { mkdirSync, readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Paridade visual com o Claude Design (entrega 1: Hero, login, casca e
 * painel), na pilha REAL. As capturas saem nos três tamanhos da
 * referência (1440×900, 768×1024, 390×844) em e2e/resultados/paridade/,
 * que o CI publica como artefato — e `scripts/capturar-referencia.mjs`
 * gera as da referência nos mesmos tamanhos, para pôr lado a lado.
 *
 * Captura é evidência, não prova: o que reprova são as afirmações de
 * comportamento (menu por papel, gaveta, recolher, âncora com destino,
 * sem rolagem lateral, movimento reduzido).
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const conta = estado.contas.admin_visual;

const TELAS = [
  { nome: "1440", width: 1440, height: 900 },
  { nome: "768", width: 768, height: 1024 },
  { nome: "390", width: 390, height: 844 },
];
const PASTA = "e2e/resultados/paridade";
mkdirSync(PASTA, { recursive: true });

async function semRolagemLateral(page: Page) {
  const { largura, janela } = await page.evaluate(() => ({
    largura: document.documentElement.scrollWidth,
    janela: window.innerWidth,
  }));
  expect(largura, "rolagem lateral").toBeLessThanOrEqual(janela);
}

async function capturar(page: Page, nome: string) {
  for (const t of TELAS) {
    await page.setViewportSize({ width: t.width, height: t.height });
    await semRolagemLateral(page);
    await page.screenshot({ path: `${PASTA}/${nome}-${t.nome}.png` });
    await page.screenshot({ path: `${PASTA}/${nome}-${t.nome}-inteira.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

function vigiarConsole(page: Page) {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(m.text()));
  page.on("pageerror", (e) => erros.push(e.message));
  return erros;
}

test.describe.configure({ mode: "serial" });

test("Hero: fluxo animado, âncoras com destino, menu do celular", async ({ page }) => {
  const erros = vigiarConsole(page);
  await page.goto("/");
  const hero = page.locator(".gc-hero");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Planejamento público, com método e inteligência.");

  // Anima por padrão (só transform/opacity/stroke)...
  await expect(hero.locator(".gc-hero__node").first()).toHaveCSS("animation-name", "gc-hero-pop");
  await expect(hero.locator(".gc-hero__path").nth(1)).toHaveCSS("animation-name", "gc-hero-draw");
  await expect(page.getByText("Exemplo ilustrativo")).toBeVisible();

  // ...e toda âncora da página aponta para uma seção que existe.
  const ancoras = await page.locator('a[href^="#"]').evaluateAll((as) =>
    as.map((a) => (a.getAttribute("href") ?? "").slice(1)),
  );
  expect(ancoras.length).toBeGreaterThan(0);
  for (const id of new Set(ancoras)) {
    expect(await page.locator(`[id="${id}"]`).count(), `#${id} sem destino`).toBe(1);
  }
  await expect(page.getByRole("link", { name: "Acessar sistema" }).first()).toHaveAttribute("href", "/entrar");

  // Movimento reduzido: tudo visível e parado desde o início.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await expect(hero.locator(".gc-hero__node").first()).toHaveCSS("opacity", "1");
  await expect(hero.locator(".gc-hero__node").first()).toHaveCSS("animation-name", "none");
  await capturar(page, "landing");

  // Celular: a navegação vira menu, e o menu leva à seção.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "Navegação pública" })).toBeHidden();
  await page.getByLabel("Abrir menu").click();
  await page.locator(".gc-hero__menu-panel").getByRole("link", { name: "Plataforma" }).click();
  await expect(page).toHaveURL(/#plataforma$/);
  expect(erros).toEqual([]);
});

test("login no AuthLayout", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/entrar");
  await expect(page.getByRole("heading", { name: "Entrar", level: 1 })).toBeVisible();
  await capturar(page, "entrar");
});

test("casca e painel: menu por papel, trilha, recolher e gaveta", async ({ page }) => {
  const erros = vigiarConsole(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  const menu = page.getByRole("navigation", { name: "Navegação principal" });
  await expect(page.getByRole("heading", { name: "Início", level: 1 })).toBeVisible();
  await expect(menu.getByRole("link", { name: "Início" })).toHaveAttribute("aria-current", "page");
  for (const nome of ["Processos", "Base de Conhecimento", "Instituição", "Usuários", "Senha"]) {
    await expect(menu.getByRole("link", { name: nome, exact: true })).toBeVisible();
  }
  await expect(page.getByTestId("usuario-email")).toHaveText(conta.email);
  await expect(page.getByRole("heading", { name: "Processos recentes" })).toBeVisible();
  // Link com classe do design system mantém a cor dele (a cor de link solto não vaza).
  await expect(page.getByRole("link", { name: "Novo processo" }).first()).toHaveCSS("color", "rgb(255, 255, 255)");
  await expect(menu.getByRole("link", { name: "Processos", exact: true })).toHaveCSS("color", "rgb(91, 104, 124)");
  await capturar(page, "app-inicio");

  // Recolher: a barra vai a 68 px e o rótulo some, o nome acessível fica.
  const barra = page.locator(".gc-sidebar");
  await page.getByRole("button", { name: "Recolher menu" }).click();
  await expect(barra).toHaveCSS("width", "68px");
  await expect(menu.getByRole("link", { name: "Processos", exact: true })).toBeVisible();
  await page.screenshot({ path: `${PASTA}/app-recolhido-1440.png` });
  await page.getByRole("button", { name: "Expandir menu" }).click();
  await expect(barra).toHaveCSS("width", "248px");

  // Celular: a barra vira gaveta; Esc fecha, navegar fecha.
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(menu).toBeHidden();
  const abrir = page.getByRole("button", { name: "Abrir menu" });
  await abrir.click();
  await expect(menu).toBeVisible();
  await page.screenshot({ path: `${PASTA}/app-gaveta-390.png` });
  await page.keyboard.press("Escape");
  await expect(menu).toBeHidden();
  await abrir.click();
  await menu.getByRole("link", { name: "Processos", exact: true }).click();
  await expect(page).toHaveURL(/\/app\/processos$/);
  await expect(menu).toBeHidden();
  await expect(page.getByRole("navigation", { name: "Trilha de navegação" }).getByText("Processos")).toHaveAttribute(
    "aria-current",
    "page",
  );
  await page.setViewportSize({ width: 1440, height: 900 });
  await capturar(page, "app-processos");

  // Tabela: menu de linha só com ações reais, e a linha leva ao processo.
  const tabela = page.getByRole("table", { name: "Processos do órgão" });
  await expect(tabela).toBeVisible();
  await tabela.getByRole("button", { name: /^Mais ações/ }).first().click();
  await expect(page.getByRole("menuitem", { name: "Dados da demanda" })).toBeVisible();
  await expect(page.getByRole("menuitem", { name: /Excluir/ })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await tabela.getByRole("link").first().click();
  await expect(page.getByTestId("titulo-processo")).toBeVisible();
  await expect(page.getByRole("link", { name: "Preencher dados da demanda" })).toBeVisible();
  await capturar(page, "app-processo");
  expect(erros).toEqual([]);
});

test("pesquisa de preços: etapas, itens, triagem que filtra e cesta", async ({ page }) => {
  const erros = vigiarConsole(page);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto("/app/precos");
  await expect(page.getByRole("heading", { name: "Pesquisas de preços", level: 1 })).toBeVisible();
  await capturar(page, "app-precos");
  await page.getByRole("listitem").filter({ hasText: "Luvas E2E" }).first().getByRole("link").click();
  await expect(page.getByTestId("titulo-pesquisa")).toBeVisible();
  await expect(page.getByRole("list", { name: "Etapas da pesquisa de preços" })).toBeVisible();
  await capturar(page, "app-pesquisa");

  await page.locator("section[aria-labelledby=titulo-itens] tbody a").first().click();
  await expect(page.getByTestId("preco-do-item")).toBeVisible();
  const resumo = page.getByRole("group", { name: "Resumo da triagem" });
  await expect(resumo).toBeVisible();
  // O contador filtra de verdade: "Fora do cálculo" esconde o que está na cesta.
  const naCesta = await page.getByTestId("referencia").filter({ hasText: "Na cesta" }).count();
  await resumo.getByRole("button", { name: /Fora do cálculo/ }).click();
  await expect(resumo.getByRole("button", { name: /Fora do cálculo/ })).toHaveAttribute("aria-pressed", "true");
  if (naCesta > 0) await expect(page.getByTestId("referencia").filter({ hasText: "Na cesta" })).toHaveCount(0);
  await resumo.getByRole("button", { name: /Fora do cálculo/ }).click();
  await capturar(page, "app-item");

  // Origem: diálogo com o que a coleta registrou.
  await page.getByTestId("referencia").first().getByRole("button", { name: "Ver origem" }).click();
  await expect(page.getByRole("dialog")).toContainText("Rastreabilidade da referência");
  await page.screenshot({ path: `${PASTA}/app-item-origem-1440.png` });
  await page.getByRole("button", { name: "Fechar", exact: true }).click();
  expect(erros).toEqual([]);
});
