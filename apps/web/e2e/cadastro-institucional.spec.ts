import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Prefeitura, Secretarias e Identidade visual (M7b) contra a pilha real,
 * como administrador. O RLS da 0035 é quem deixa cada escrita passar.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("administrador edita a prefeitura, cria secretaria e identidade visual", async ({ page }) => {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.admin_a.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.admin_a.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.getByRole("link", { name: "Instituição" }).click();
  // Espera a página: sem isto, o clique seguinte pega o link de um processo
  // "Prefeitura — ..." ainda na tela inicial.
  await expect(page.getByRole("heading", { name: "Instituição", level: 1 })).toBeVisible();
  await page.getByRole("link", { name: "Prefeitura", exact: true }).click();
  await page.waitForURL(/secao=prefeitura/);
  await expect(page.getByRole("button", { name: "Salvar dados institucionais" })).toBeVisible();
  const cidade = `Cidade E2E ${Date.now()}`;
  await page.getByLabel("Cidade").fill(cidade);
  await page.getByRole("button", { name: "Salvar dados institucionais" }).click();
  await expect(page.getByText("Dados institucionais salvos.")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Cidade")).toHaveValue(cidade);

  await page.getByRole("link", { name: "Secretarias", exact: true }).click();
  await page.waitForURL(/secao=secretarias/);
  await expect(page.getByRole("heading", { name: "Nova secretaria" })).toBeVisible();
  const secretaria = `Secretaria E2E ${Date.now()}`;
  await page.getByLabel("Nome", { exact: true }).fill(secretaria);
  await page.getByLabel("Sigla").fill("SE2E");
  await page.getByRole("button", { name: "Criar secretaria" }).click();
  await expect(page.getByText(`Secretaria ${secretaria} criada.`)).toBeVisible();
  await expect(page.getByTestId("lista-secretarias")).toContainText(secretaria);

  await page.getByRole("link", { name: "Identidade visual", exact: true }).click();
  await page.waitForURL(/secao=identidade/);
  await expect(page.getByRole("heading", { name: "Nova identidade" })).toBeVisible();
  await page.getByRole("tab", { name: "Definir por texto" }).click();
  const orgao = `Órgão E2E ${Date.now()}`;
  await page.getByTestId("identidade-texto").getByLabel("Órgão").fill(orgao);
  await page.getByLabel("Cabeçalho").fill("PREFEITURA DE TESTE · SECRETARIA E2E");
  await page.getByRole("button", { name: "Salvar identidade (texto)" }).click();
  await expect(page.getByText("Identidade (texto) salva.")).toBeVisible();
  await expect(page.getByTestId("lista-identidades")).toContainText(orgao);
  await page.screenshot({ path: "e2e/resultados/telas/identidade-visual-1440.png", fullPage: true });

  // A identidade salva é espelhada em Secretarias (o resolvedor do timbrado lê de lá).
  await page.getByRole("link", { name: "Secretarias", exact: true }).click();
  await page.waitForURL(/secao=secretarias/);
  await expect(page.getByRole("heading", { name: "Nova secretaria" })).toBeVisible();
  await expect(page.getByTestId("lista-secretarias")).toContainText(orgao);

  await page.getByRole("link", { name: "Identidade visual", exact: true }).click();
  await page.waitForURL(/secao=identidade/);
  await expect(page.getByRole("heading", { name: "Nova identidade" })).toBeVisible();
  const linha = page.getByTestId("lista-identidades").getByRole("listitem").filter({ hasText: orgao });
  await linha.getByRole("button", { name: "Excluir" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Excluir", exact: true }).click();
  await expect(page.getByText("Identidade excluída.")).toBeVisible();
  await expect(page.getByTestId("lista-identidades")).not.toContainText(orgao);
});
