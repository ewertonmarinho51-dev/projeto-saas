import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/**
 * Consulta própria do SINAPI (custo de engenharia), contra a pilha real. A
 * pilha grava uma versão publicada de 10/2026 com três referências REAIS do
 * Pará e liga `referencia_custos_sinapi` (`pilha.semear_sinapi`).
 */
const estado = JSON.parse(readFileSync(process.env.GOVCONECT_E2E_ESTADO ?? "", "utf8")) as {
  contas: Record<string, { email: string; senha: string }>;
};

async function entrar(page: Page) {
  await page.goto("/entrar");
  await page.getByLabel("E-mail institucional").fill(estado.contas.a1_sinapi.email);
  await page.getByLabel("Senha", { exact: true }).fill(estado.contas.a1_sinapi.senha);
  await page.getByRole("button", { name: "Entrar", exact: true }).click();
  await page.waitForURL(/\/app$/);
}

test("servidor consulta custo de insumo e de composição do SINAPI, com a origem oficial", async ({ page }) => {
  await entrar(page);
  await page.goto("/app/precos");
  await page.getByRole("link", { name: "Custos de engenharia (SINAPI)" }).click();
  await expect(page).toHaveURL(/\/app\/precos\/referencias$/);
  await expect(page.getByText("não preço de compra: não entra na cesta")).toBeVisible();

  const busca = page.getByTestId("busca-sinapi");
  await busca.getByLabel("Descrição").fill("cimento portland");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Mês de referência 10/2026 · PA")).toBeVisible();
  const linha = page.locator("tbody tr").filter({ hasText: "CIMENTO PORTLAND COMPOSTO CP II-32" });
  await expect(linha).toHaveCount(1);                       // só o regime pedido
  await expect(linha.getByTestId("custo-sinapi")).toHaveText("R$ 1,08");
  await expect(linha).toContainText("KG");
  await expect(linha).toContainText("Insumo");
  await expect(linha).toContainText("origem coletado");
  await expect(linha).toContainText("aba ISD, linha 1169");
  await expect(linha.getByRole("link", { name: "Relatório oficial 10/2026" })).toHaveAttribute(
    "href",
    "https://www.caixa.gov.br/Downloads/sinapi-relatorios-mensais/SINAPI-2026-10-formato-xlsx.zip",
  );
  await expect(page.getByText("art. 23, § 2º, I")).toBeVisible();

  await busca.getByLabel("Descrição").fill("");
  await busca.getByLabel("Código").fill("104658");
  await busca.getByRole("button", { name: "Consultar" }).click();
  const piso = page.locator("tbody tr").filter({ hasText: "PISO PODOTÁTIL" });
  await expect(piso.getByTestId("custo-sinapi")).toHaveText("R$ 189,32");
  await expect(piso).toContainText("Composição");
  await expect(piso).toContainText("aba CSD, linha 11");

  for (const [nome, width, height] of [["375", 375, 812], ["1440", 1440, 900]] as const) {
    await page.setViewportSize({ width, height });
    await page.screenshot({ path: `e2e/resultados/telas/sinapi-${nome}.png`, fullPage: true });
  }

  // nada encontrado é um estado, não erro
  await busca.getByLabel("Código").fill("999999999");
  await busca.getByRole("button", { name: "Consultar" }).click();
  await expect(page.getByText("Nenhuma referência do SINAPI para esta busca.")).toBeVisible();
});
