import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Cadastro institucional (M7a) contra a pilha real, como administrador:
 * cadastrar servidor, registrar portaria, ativá-la e designar o membro.
 * O RLS da 0025 (`e_admin()`) é quem deixa a escrita passar.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("administrador cadastra servidor e portaria com membro", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.getByRole("link", { name: "Instituição" }).click();
  await page.getByRole("link", { name: "Servidores" }).click();
  const nome = `Servidora E2E ${Date.now()}`;
  await page.getByLabel("Nome").fill(nome);
  await page.getByLabel("Cargo").fill("Agente de Contratação");
  await page.getByRole("button", { name: "Cadastrar servidor" }).click();
  await expect(page.getByText(`${nome} cadastrado.`)).toBeVisible();
  await expect(page.getByTestId("lista-servidores")).toContainText(nome);

  await page.getByRole("link", { name: "Portarias" }).click();
  const numero = String(Date.now()).slice(-4);
  await page.getByLabel("Número").fill(numero);
  await page.getByRole("button", { name: "Registrar portaria" }).click();
  await expect(page.getByText(new RegExp(`Portaria ${numero}/\\d{4} registrada como RASCUNHO`))).toBeVisible();

  const cartao = page.locator("section", { hasText: `Portaria ${numero}/` });
  await cartao.getByLabel("Situação declarada").selectOption("ATIVA");
  await expect(cartao.getByText("Situação atualizada.")).toBeVisible();
  await cartao.getByLabel("Servidor").selectOption({ label: nome });
  await cartao.getByRole("button", { name: "Adicionar" }).click();
  await expect(cartao.getByText("Membro designado.")).toBeVisible();
  await expect(cartao).toContainText(nome);
  await page.screenshot({ path: "e2e/resultados/telas/instituicao-1440.png", fullPage: true });
});
