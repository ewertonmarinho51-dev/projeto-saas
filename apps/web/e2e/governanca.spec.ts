import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Centro de Governança (M8a leitura, M8b escrita por RPC) contra a pilha real. As flags do
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

test("admin cria uma cláusula em rascunho e a envia para revisão (RPCs da 0036)", async ({ page }) => {
  await entrar(page, "admin_base");
  await page.getByRole("link", { name: "Governança", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Centro de Governança", level: 1 })).toBeVisible();
  await expect(page.getByText("admin municipal")).toBeVisible();
  await expect(page.getByRole("link", { name: "Catálogo de cláusulas" })).toHaveAttribute("aria-current", "page");

  const chave = `clausula.e2e.${Date.now()}`;
  const form = page.getByTestId("nova-clausula");
  await form.getByRole("textbox", { name: "Chave estável", exact: true }).fill(chave);
  await form.getByRole("textbox", { name: "Título", exact: true }).fill("Garantia contratual (e2e)");
  await form.getByRole("textbox", { name: "Texto", exact: true }).fill("A contratada prestará garantia contratual nos termos do edital.");
  await form.getByRole("button", { name: "Criar rascunho" }).click();
  await expect(form.getByText(`Rascunho ${chave} criado.`)).toBeVisible();

  const cartao = page.getByRole("listitem").filter({ hasText: chave });
  await expect(cartao.getByText("v1 · rascunho")).toBeVisible();
  await cartao.getByRole("button", { name: "Enviar para revisão" }).click();
  await expect(cartao.getByText("v1 · em revisão")).toBeVisible();
  await expect(cartao.getByRole("button", { name: "Aprovar para simulação" })).toBeVisible();
  await page.screenshot({ path: "e2e/resultados/telas/governanca-1440.png", fullPage: true });
});

test("servidor comum não vê o Centro", async ({ page }) => {
  await entrar(page, "a1_gestao");
  await expect(page.getByRole("link", { name: "Governança", exact: true })).toHaveCount(0);
  const resposta = await page.goto("/app/governanca");
  expect(resposta?.status()).toBe(404);
});
