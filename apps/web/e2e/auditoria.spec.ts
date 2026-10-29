import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Auditoria global da interface nova (entrega 5 da paridade visual): cada
 * tela autenticada, na pilha REAL, no desktop e no celular, tem de
 *   - responder 200 e ficar dentro da casca (menu, trilha, `main#conteudo`);
 *   - ter exatamente um h1;
 *   - não rolar para o lado;
 *   - não ter imagem sem `alt` nem botão sem nome acessível;
 *   - não registrar erro no console.
 * As capturas vão para e2e/resultados/auditoria/ (artefato web-e2e-telas).
 */
type Conta = { email: string; senha: string };
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, Conta>;
};
const conta = estado.contas.admin_auditoria;

const ROTAS = [
  ["inicio", "/app"],
  ["processos", "/app/processos"],
  ["precos", "/app/precos"],
  ["precos-nova", "/app/precos/nova"],
  ["instituicao", "/app/admin/instituicao"],
  ["usuarios", "/app/admin/usuarios"],
  ["base-conhecimento", "/app/admin/base-conhecimento"],
  ["senha", "/app/conta/senha"],
] as const;

async function conferir(page: Page, nome: string) {
  await expect(page.locator("main#conteudo")).toHaveCount(1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveCount(1);
  await expect(page.getByRole("navigation", { name: "Trilha de navegação" })).toBeVisible();
  for (const [largura, altura] of [
    [1440, 900],
    [390, 844],
  ]) {
    await page.setViewportSize({ width: largura, height: altura });
    const { rolagem, janela } = await page.evaluate(() => ({
      rolagem: document.documentElement.scrollWidth,
      janela: window.innerWidth,
    }));
    expect(rolagem, `${nome} rola para o lado em ${largura}px`).toBeLessThanOrEqual(janela);
    await page.screenshot({ path: `e2e/resultados/auditoria/${nome}-${largura}.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  const problemas = await page.evaluate(() => {
    const semAlt = [...document.querySelectorAll("img:not([alt])")].length;
    const botoesMudos = [...document.querySelectorAll("button")].filter(
      (b) => !(b.textContent ?? "").trim() && !b.getAttribute("aria-label") && !b.getAttribute("title"),
    ).length;
    return { semAlt, botoesMudos };
  });
  expect(problemas, nome).toEqual({ semAlt: 0, botoesMudos: 0 });
}

test("todas as telas autenticadas passam na auditoria de casca, layout e acessibilidade", async ({ page }) => {
  const erros: string[] = [];
  page.on("console", (m) => m.type() === "error" && erros.push(`${page.url()}: ${m.text()}`));
  page.on("pageerror", (e) => erros.push(`${page.url()}: ${e.message}`));
  await page.emulateMedia({ reducedMotion: "reduce" });

  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(conta.email);
  await page.getByLabel("Senha", { exact: true }).fill(conta.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  // O primeiro Tab cai no "Pular para o conteúdo".
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Pular para o conteúdo" })).toBeFocused();

  for (const [nome, rota] of ROTAS) {
    const resposta = await page.goto(rota);
    expect(resposta?.status(), rota).toBe(200);
    await conferir(page, nome);
  }

  // Telas com id: a primeira pesquisa e o primeiro item dela, e o primeiro processo.
  await page.goto("/app/precos");
  await page.locator("main#conteudo ul a").first().click();
  await expect(page.getByTestId("titulo-pesquisa")).toBeVisible();
  await conferir(page, "pesquisa");
  const item = page.locator("section[aria-labelledby=titulo-itens] tbody a").first();
  if (await item.count()) {
    await item.click();
    await expect(page.getByTestId("preco-do-item")).toBeVisible();
    await conferir(page, "item");
  }
  await page.goto("/app/processos");
  await page.getByRole("table", { name: "Processos do órgão" }).getByRole("link").first().click();
  await expect(page.getByTestId("titulo-processo")).toBeVisible();
  await conferir(page, "processo");

  expect(erros).toEqual([]);
});
