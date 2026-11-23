import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta ao SINAPI (custos de engenharia), contra a pilha real. A consulta
 * nasce FECHADA: a licença de reúso da publicação da CAIXA não foi avaliada
 * (`fontes_externas`), então a API responde 404 e a tela diz isso — sem
 * erro, sem tabela vazia que pareça "nada encontrado".
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

async function entrar(page: Page, rotulo: string) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas[rotulo].email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas[rotulo].senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("a consulta ao SINAPI fica separada da pesquisa de preços e nasce fechada", async ({ page }) => {
  await entrar(page, "a1");
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Custos de engenharia (SINAPI)" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/referencias\/sinapi$/);
  await expect(page.getByRole("heading", { name: "Custos de engenharia (SINAPI)" })).toBeVisible();
  await expect(page.getByText("Não é preço de compra e não entra na cesta")).toBeVisible();

  // sem termo nem código, nada é consultado
  await expect(page.getByText("ainda não habilitada")).toHaveCount(0);

  const form = page.getByTestId("consulta-sinapi");
  await form.getByLabel("Descrição").fill("cimento portland");
  await form.getByLabel("Tipo").selectOption("insumo");
  await form.getByRole("button", { name: "Consultar" }).click();
  await expect(page).toHaveURL(/termo=cimento\+portland/);
  await expect(page.getByText("Consulta ao SINAPI ainda não habilitada")).toBeVisible();
  await expect(page.getByRole("table")).toHaveCount(0);
  // o filtro escolhido volta preenchido
  await expect(form.getByLabel("Descrição")).toHaveValue("cimento portland");
  await expect(form.getByLabel("Tipo")).toHaveValue("insumo");
});
