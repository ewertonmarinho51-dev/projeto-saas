import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Base de Conhecimento (M6) contra a pilha real, como administrador:
 * indexar um arquivo, vê-lo na lista e excluí-lo. Na pilha não há chave de
 * embeddings, então o material entra PENDENTE de vetor — e a tela precisa
 * dizer isso. O RLS da 0020 + 0034 é quem deixa a escrita passar.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("administrador indexa, lista e exclui uma referência", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.getByRole("link", { name: "Base de Conhecimento" }).click();
  const titulo = `Norma E2E ${Date.now()}`;
  const texto = Array.from({ length: 40 }, (_, i) => `Art. ${i + 1}º A contratação observará o planejamento.`).join("\n");
  await page
    .getByTestId("envio-base")
    .locator('input[type="file"]')
    .setInputFiles({ name: "norma-e2e.txt", mimeType: "text/plain", buffer: Buffer.from(texto, "utf8") });
  await page.getByLabel("Categoria").selectOption("lei");
  await page.getByLabel("Título").fill(titulo);
  await page.getByRole("button", { name: "Indexar na Base de Conhecimento" }).click();

  await expect(page.getByText(/\d+ trechos/).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("lista-referencias")).toContainText(titulo);
  await page.screenshot({ path: "e2e/resultados/telas/base-conhecimento-1440.png", fullPage: true });

  await page.getByRole("button", { name: `Excluir ${titulo}` }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Excluir", exact: true }).click();
  await expect(page.getByText(titulo)).toHaveCount(0);
});
