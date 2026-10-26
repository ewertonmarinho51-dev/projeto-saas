import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Consolidar Demandas (M4) contra a pilha real: dois DFDs em PDF de texto
 * (gerados pela pilha), a soma por secretaria, a prova de que a conta
 * fecha e a aplicação à planilha do processo.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
  demandas: string[];
};

test("consolidar dois DFDs e aplicar à planilha do processo", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.b1.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.b1.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto("/app/processos");
  await page.getByLabel("Órgão ou secretaria").fill("Secretaria de Administração");
  await page.getByLabel("Objeto da contratação").fill(`Material de expediente E2E ${Date.now()}`);
  await page.getByRole("button", { name: "Criar processo" }).click();
  await expect(page.getByText("Processo criado.")).toBeVisible();

  await page.getByRole("link", { name: "Consolidar demandas" }).click();
  await expect(page).toHaveURL(/\/demandas$/);
  await page.locator('input[type=file][accept=".pdf,application/pdf"]').setInputFiles(estado.demandas);

  const tabela = page.getByTestId("tabela-consolidada");
  await expect(tabela).toBeVisible();
  const envelope = tabela.locator("tr", { hasText: "370614" });
  await expect(envelope).toContainText("70");
  await expect(page.getByText("A conta fecha")).toBeVisible();
  await page.screenshot({ path: "e2e/resultados/telas/demandas-1440.png", fullPage: true });

  await page.getByRole("button", { name: "Aplicar ao processo" }).click();
  await expect(page).toHaveURL(/\/formulario\?demanda=2$/);
  await expect(page.getByText(/Demanda consolidada aplicada: 2 itens/)).toBeVisible();
  await expect(page.getByTestId("planilha-itens").locator("tbody tr")).toHaveCount(2);
});
