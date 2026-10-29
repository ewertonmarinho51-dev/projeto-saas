import { expect, test } from "@playwright/test";

/**
 * Site institucional: cada página pública responde, tem um h1, título e
 * descrição próprios, canônica no domínio público, não rola para o lado no
 * celular e não tem link interno quebrado. O mapa do site lista as
 * mesmas páginas e o robots.txt mantém a área do sistema fora do índice.
 * Não precisa de conta.
 */
const PAGINAS = [
  "/",
  "/solucoes",
  "/solucoes/documentos-ia",
  "/solucoes/pesquisa-de-precos",
  "/como-funciona",
  "/sobre",
  "/contato",
  "/privacidade",
];
// Origem canônica: a do ambiente do web (GOVCONECT_SITE_URL; em produção
// https://govconect.com, provado em tests/site.test.ts). A prova lê da home
// e exige que todas as páginas, o sitemap e o JSON-LD usem a mesma.
let SITE = "";
async function origem(page: import("@playwright/test").Page) {
  if (!SITE) {
    await page.goto("/");
    SITE = (await page.locator('link[rel="canonical"]').getAttribute("href")) ?? "";
    expect(SITE).toMatch(/^https?:\/\/[^/]+$/);
  }
  return SITE;
}

test("cada página pública tem h1, título, descrição e canônica próprios", async ({ page }) => {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(`${page.url()}: ${m.text()}`));
  page.on("pageerror", (e) => erros.push(`${page.url()}: ${e.message}`));
  await page.emulateMedia({ reducedMotion: "reduce" });
  await origem(page);

  const titulos = new Set<string>();
  const descricoes = new Set<string>();
  const internos = new Set<string>();
  for (const caminho of PAGINAS) {
    const resposta = await page.goto(caminho);
    expect(resposta?.status(), caminho).toBe(200);
    await expect(page.getByRole("heading", { level: 1 }), caminho).toHaveCount(1);
    await expect(page.locator("main#conteudo"), caminho).toHaveCount(1);

    const titulo = await page.title();
    const descricao = (await page.locator('meta[name="description"]').getAttribute("content")) ?? "";
    expect(titulo, caminho).toContain("Gov Conect");
    expect(descricao.length, `${caminho} sem descrição`).toBeGreaterThan(50);
    titulos.add(titulo);
    descricoes.add(descricao);
    await expect(page.locator('link[rel="canonical"]'), caminho).toHaveAttribute(
      "href",
      `${SITE}${caminho === "/" ? "" : caminho}`,
    );
    await expect(page.locator('meta[property="og:title"]'), caminho).toHaveCount(1);

    for (const href of await page.locator('a[href^="/"]').evaluateAll((as) => as.map((a) => a.getAttribute("href") ?? ""))) {
      internos.add(href.split("#")[0]);
    }

    await page.setViewportSize({ width: 390, height: 844 });
    const { rolagem, janela } = await page.evaluate(() => ({
      rolagem: document.documentElement.scrollWidth,
      janela: window.innerWidth,
    }));
    expect(rolagem, `${caminho} rola para o lado no celular`).toBeLessThanOrEqual(janela);
    await page.screenshot({ path: `e2e/resultados/site/${caminho === "/" ? "inicio" : caminho.slice(1).replace(/\//g, "-")}-390.png`, fullPage: true });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.screenshot({ path: `e2e/resultados/site/${caminho === "/" ? "inicio" : caminho.slice(1).replace(/\//g, "-")}-1440.png`, fullPage: true });
  }
  expect(titulos.size, "títulos repetidos").toBe(PAGINAS.length);
  expect(descricoes.size, "descrições repetidas").toBe(PAGINAS.length);

  // Nenhum link interno quebrado (a área do sistema redireciona para a entrada).
  for (const href of internos) {
    const r = await page.request.get(href, { maxRedirects: 0 });
    expect([200, 307, 308], href).toContain(r.status());
  }
  expect(erros).toEqual([]);
});

test("a navegação marca a página atual e a trilha volta para Soluções", async ({ page }) => {
  await page.goto("/solucoes/pesquisa-de-precos");
  const nav = page.getByRole("navigation", { name: "Navegação pública" });
  await expect(nav.getByRole("link", { name: "Soluções" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("navigation", { name: "Trilha de navegação" }).getByRole("link", { name: "Soluções" }).click();
  await expect(page).toHaveURL(/\/solucoes$/);
});

test("dados estruturados da organização na página inicial", async ({ page }) => {
  await origem(page);
  await page.goto("/");
  const json = await page.locator('script[type="application/ld+json"]').textContent();
  const dados = JSON.parse(json ?? "{}") as { "@graph": { "@type": string; url?: string }[] };
  const organizacao = dados["@graph"].find((n) => n["@type"] === "Organization");
  expect(organizacao?.url).toBe(SITE);
});

test("sitemap lista as páginas públicas e robots deixa o sistema fora", async ({ page, request }) => {
  await origem(page);
  const mapa = await (await request.get("/sitemap.xml")).text();
  for (const caminho of PAGINAS) {
    expect(mapa).toContain(`<loc>${SITE}${caminho === "/" ? "" : caminho}</loc>`);
  }
  expect(mapa).not.toContain("/app");
  const robots = await (await request.get("/robots.txt")).text();
  expect(robots).toContain("Disallow: /app");
  expect(robots).toContain(`Sitemap: ${SITE}/sitemap.xml`);
});
