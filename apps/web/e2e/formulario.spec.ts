import { readFileSync } from "node:fs";

import { expect, test } from "@playwright/test";

/**
 * Formulário Matriz (M1) contra a pilha real: criar o processo, abrir os
 * dados da demanda, importar a planilha (o próprio modelo baixado pelo
 * web), anexar o memorando, salvar rascunho e iniciar a elaboração.
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

test("preencher o Formulário Matriz e iniciar a elaboração", async ({ page }) => {
  // b1: o limite de login conta 5 entradas por e-mail em 15 min, e as
  // outras contas já entram em vários specs.
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.b1.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.b1.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);

  await page.goto("/app/processos");
  await page.getByLabel("Órgão ou secretaria").fill("Secretaria de Educação");
  await page.getByLabel("Objeto da contratação").fill(`Equipamentos de informática E2E ${Date.now()}`);
  await page.getByRole("button", { name: "Criar processo" }).click();
  await expect(page.getByText("Processo criado.")).toBeVisible();

  await page.getByRole("link", { name: "Preencher dados da demanda" }).click();
  await expect(page).toHaveURL(/\/formulario$/);
  const form = page.getByTestId("formulario-matriz");
  // O órgão e o objeto do cadastro já vêm preenchidos.
  await expect(form.getByLabel(/Quem está pedindo/)).toHaveValue("Secretaria de Educação");

  // Planilha: o modelo baixado pelo web, importado de volta. O servidor
  // lê e calcula; nada é gravado até salvar.
  const modelo = await page.request.get("/app/processos/modelo-planilha");
  expect(modelo.ok()).toBeTruthy();
  await page.locator('input[type=file][accept=".xlsx"]').setInputFiles({
    name: "modelo.xlsx",
    mimeType: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    buffer: await modelo.body(),
  });
  await expect(page.getByText(/2 item\(ns\) importado\(s\)/)).toBeVisible();
  await expect(page.getByTestId("planilha-itens").locator("tbody tr")).toHaveCount(2);

  // Memorando por arquivo: o texto vai para o campo.
  await page.locator('input[type=file][accept=".pdf,.docx,.txt,.md"]').setInputFiles({
    name: "memorando.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Memorando nº 12/2026 — solicita equipamentos de informática para as escolas da rede municipal."),
  });
  await expect(page.getByText(/Memorando importado/)).toBeVisible();

  await page.getByRole("button", { name: "Salvar rascunho" }).click();
  await expect(page).toHaveURL(/\/formulario\?salvo=1$/);
  await expect(page.getByText("Rascunho salvo.")).toBeVisible();
  await expect(page.getByTestId("valor-estimado")).toContainText("R$ 540.000,00");

  // Iniciar sem os obrigatórios: a regra do wizard, dita pela API.
  await page.getByRole("button", { name: "Iniciar elaboração dos documentos" }).click();
  await expect(page.getByText(/Preencha os campos obrigatórios/)).toBeVisible();

  const campos = page.getByTestId("formulario-matriz");
  await campos.getByLabel(/Por que isso é necessário/).fill("Laboratórios das escolas estão sem equipamentos.");
  await campos.getByLabel(/Como a entrega vai acontecer/).selectOption({ index: 2 });
  await page.screenshot({ path: "e2e/resultados/telas/formulario-1440.png", fullPage: true });
  await page.getByRole("button", { name: "Iniciar elaboração dos documentos" }).click();
  await expect(page).toHaveURL(/\/app\/processos\/[0-9a-f-]{36}\?iniciado=1$/);
  await expect(page.getByText(/Dados da demanda completos/)).toBeVisible();
});
