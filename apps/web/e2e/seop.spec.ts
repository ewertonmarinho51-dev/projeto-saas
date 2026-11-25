import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta própria da SEOP-PA (Planilha Padrão), contra a pilha real. A
 * consulta nasce DESLIGADA (`referencia_custos_seop_pa`) e a importação do
 * PDF só publica depois de uma pessoa aprovar: aqui se prova o caminho até a
 * tela, a separação da cesta e o estado desligado dito com clareza.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

async function entrar(page: Page) {
  // conta própria: o limite de 5 entradas por e-mail em 15 min
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_seop.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_seop.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("a consulta da SEOP-PA fica ao lado da do SINAPI, fora da cesta, e nasce desligada", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/precos/referencias");
  await page.getByRole("link", { name: "Planilha da SEOP-PA" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/referencias\/seop$/);
  await expect(page.getByRole("heading", { name: "Custos de engenharia (SEOP-PA)" })).toBeVisible();
  await expect(page.getByText("não preço de compra: não entra na cesta")).toBeVisible();

  const busca = page.getByTestId("busca-seop");
  await busca.getByLabel("Descrição").fill("andaime metálico");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page).toHaveURL(/termo=andaime/);
  await expect(page.getByText("A consulta à SEOP-PA está desligada neste ambiente.")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  await expect(busca.getByLabel("Descrição")).toHaveValue("andaime metálico");
});
