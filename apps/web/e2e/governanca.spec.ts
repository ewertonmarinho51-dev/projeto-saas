import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Centro de Governança em leitura (M8a) contra a pilha real. As flags do
 * Centro estão ligadas SÓ na pilha (em produção, desligadas). O admin entra
 * como admin municipal; o servidor comum não vê o item no menu nem a página.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

async function entrar(page: import("@playwright/test").Page, conta: string) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas[conta].email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas[conta].senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("admin vê o Centro de Governança em modo leitura", async ({ page }) => {
  await entrar(page, "admin_base");
  await page.getByRole("link", { name: "Governança", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Centro de Governança", level: 1 })).toBeVisible();
  await expect(page.getByText("admin municipal")).toBeVisible();
  await expect(page.getByText("Modo leitura")).toBeVisible();
  await expect(page.getByRole("link", { name: "Catálogo de cláusulas" })).toHaveAttribute("aria-current", "page");
  await page.screenshot({ path: "e2e/resultados/telas/governanca-1440.png", fullPage: true });
});

test("servidor comum não vê o Centro", async ({ page }) => {
  await entrar(page, "a1_gestao");
  await expect(page.getByRole("link", { name: "Governança", exact: true })).toHaveCount(0);
  const resposta = await page.goto("/app/governanca");
  expect(resposta?.status()).toBe(404);
});
