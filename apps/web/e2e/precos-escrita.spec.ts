import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Pesquisa de preços sem sair da interface nova (P04e), contra a pilha
 * real: criar a pesquisa, importar a planilha XLSX (conferir antes, gravar
 * só na confirmação) e concluir/reabrir um item em revisão.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  escrita: string;
  planilha: string;
};

test.describe.configure({ mode: "serial" });

async function entrar(page: Page) {
  // admin_a: o limite de login conta 5 entradas por e-mail em 15 min, e
  // a1 já entra em vários specs.
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("criar pesquisa, importar planilha e concluir/reabrir item", async ({ page }) => {
  await entrar(page);

  // Criar.
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Nova pesquisa" }).click();
  await page.getByLabel("Nome da pesquisa").fill("Material de expediente (E2E)");
  await page.getByLabel("Objeto").fill("Canetas e papel para as secretarias.");
  await page.getByRole("button", { name: "Criar pesquisa" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/[0-9a-f-]{36}\?criada=1$/);
  await expect(page.getByTestId("titulo-pesquisa")).toHaveText("Material de expediente (E2E)");

  // Importar: conferir não grava; confirmar grava.
  await page.getByLabel("Planilha de itens (XLSX)").setInputFiles(estado.planilha);
  await page.getByRole("button", { name: "Conferir planilha" }).click();
  const plano = page.getByTestId("plano-importacao");
  await expect(plano).toContainText("2 item(ns) novo(s)");
  await expect(plano).toContainText("12,5");
  await expect(page.locator("tbody tr")).toHaveCount(2); // a tabela do plano, nada gravado
  await page.screenshot({ path: "e2e/resultados/telas/importacao-1440.png", fullPage: true });
  await page.getByRole("button", { name: "Confirmar importação" }).click();
  await expect(page).toHaveURL(/\?importada=1$/);
  await expect(page.getByText("Planilha importada.")).toBeVisible();
  await expect(page.locator("section[aria-labelledby=titulo-itens] tbody tr")).toHaveCount(2);
  await expect(page.locator("section[aria-labelledby=titulo-itens] tbody")).toContainText("Pendente");

  // Concluir e reabrir um item em revisão (pesquisa semeada própria).
  await page.goto(`/app/precos/${estado.escrita}`);
  await page.locator("section[aria-labelledby=titulo-itens] tbody a").first().click();
  const ato = page.getByTestId("ato-item");
  await ato.getByLabel(/Justificativa/).fill("Conferido na fonte oficial (E2E).");
  await ato.getByRole("button", { name: "Concluir item" }).click();
  await expect(page.getByText("Item concluído.")).toBeVisible();
  await ato.getByLabel("Motivo da reabertura").fill("Faltou conferir um preço (E2E).");
  await ato.getByRole("button", { name: "Reabrir item" }).click();
  await expect(page.getByText("Item reaberto para revisão.")).toBeVisible();
  await page.screenshot({ path: "e2e/resultados/telas/item-reaberto-1440.png", fullPage: true });
});
